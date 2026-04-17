# -*- coding: utf-8 -*-
"""Compliance background service: runs scans in a daemon thread, hooks into
successful uploads to check each newly-uploaded torrent."""

from __future__ import annotations

import queue
import re
import threading
from datetime import datetime
from typing import Any, Optional

from unit3dup.compliance.scanner import ComplianceScanner
from unit3dup.state_db import StateDB

try:
    from view import custom_console
except Exception:  # pragma: no cover
    class _Noop:
        def bot_log(self, *a, **k): pass
        def bot_warning_log(self, *a, **k): pass
        def bot_error_log(self, *a, **k): pass
    custom_console = _Noop()


# Matches UnIT3D torrent URLs, with or without the /download/ segment:
#   /torrents/12345
#   /torrents/12345.ext
#   /torrents/download/12345.rsskey
_TORRENT_ID_RE = re.compile(r"/torrents/(?:download/)?(\d+)(?:[./?#]|$)")


def extract_torrent_id_from_url(url: str) -> Optional[int]:
    """Best-effort parse of the torrent id from a tracker response URL.

    UnIT3D typically returns `{base}/torrents/download/{id}.{rss_key}` or a
    similar URL that contains the id. Returns None on no match.
    """
    if not url or not isinstance(url, str):
        return None
    m = _TORRENT_ID_RE.search(url)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


class ComplianceService:
    """Daemon-thread wrapper around ComplianceScanner. One job at a time."""

    _PLACEHOLDER_USERNAMES = {"", "no_key", "no_user", "none"}

    def __init__(
        self,
        db: StateDB,
        scanner: ComplianceScanner,
        uploader: Optional[str],
        tracker_name: str = "GEMINI",
    ):
        self.db = db
        self.scanner = scanner
        self.uploader = self._clean_uploader(uploader)
        self.tracker_name = tracker_name.upper()

        # Bounded to provide backpressure. In practice the scan consumes jobs
        # much faster than they arrive (post-upload hooks are rare); a cap at
        # 5000 just guards against runaway enqueue bugs.
        self._queue: queue.Queue = queue.Queue(maxsize=5000)
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "current_job": None,       # "full" | "one" | "by_name" | None
            "current_label": None,
            "started_at": None,
            "processed": 0,
            "last_error": None,
            "last_finished_at": None,
            "last_summary": None,
        }

    # ── public configuration ─────────────────────────────────────────

    def set_uploader(self, uploader: Optional[str]) -> None:
        self.uploader = self._clean_uploader(uploader)

    def is_configured(self) -> bool:
        return bool(self.uploader)

    @classmethod
    def _clean_uploader(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.lower() in cls._PLACEHOLDER_USERNAMES:
            return None
        return stripped

    # ── lifecycle ────────────────────────────────────────────────────

    def start_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._shutdown.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="ComplianceWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def stop_worker(self) -> None:
        self._shutdown.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)

    # ── enqueue helpers ──────────────────────────────────────────────

    def enqueue_full_scan(self) -> dict:
        if not self.is_configured():
            return {
                "success": False,
                "message": "Uploader username is not configured (Gemini_USERNAME)",
            }
        try:
            self._queue.put(("full", None), timeout=1)
        except queue.Full:
            return {"success": False, "message": "Compliance queue is full"}
        custom_console.bot_log(f"[Compliance] Full scan queued for uploader={self.uploader}")
        return {"success": True, "message": "Full scan queued"}

    def enqueue_check_one(self, torrent_id: int) -> dict:
        try:
            tid = int(torrent_id)
        except (TypeError, ValueError):
            return {"success": False, "message": "Invalid torrent_id"}
        try:
            self._queue.put(("one", {"torrent_id": tid}), timeout=1)
        except queue.Full:
            return {"success": False, "message": "Compliance queue is full"}
        return {"success": True, "message": f"Check queued for torrent #{tid}"}

    def enqueue_after_upload(self, item: dict, tracker_response: str) -> None:
        """Called by the upload worker after a successful mark_uploaded.

        Best-effort: we never raise, never block the upload path.
        """
        try:
            tid = extract_torrent_id_from_url(tracker_response)
            linked_id = item.get("id") if isinstance(item, dict) else None

            if tid:
                try:
                    self._queue.put_nowait(("one", {"torrent_id": tid, "linked_item_id": linked_id}))
                except queue.Full:
                    custom_console.bot_warning_log("[Compliance] queue full; post-upload check dropped")
                return

            basename = None
            if isinstance(item, dict):
                basename = (
                    item.get("release_name")
                    or item.get("torrent_name")
                    or item.get("source_basename")
                )
            if basename:
                try:
                    self._queue.put_nowait(("by_name", {"name": basename, "linked_item_id": linked_id}))
                except queue.Full:
                    custom_console.bot_warning_log("[Compliance] queue full; post-upload by-name check dropped")
        except Exception as exc:
            custom_console.bot_warning_log(f"[Compliance] enqueue_after_upload failed: {exc}")

    # ── worker loop ──────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                job_type, payload = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                self._begin(job_type)
                if job_type == "full":
                    self._run_full_scan()
                elif job_type == "one":
                    self._run_one(payload or {})
                elif job_type == "by_name":
                    self._run_by_name(payload or {})
            except Exception as exc:
                custom_console.bot_error_log(f"[Compliance] Worker error on {job_type}: {exc}")
                with self._state_lock:
                    self._state["last_error"] = str(exc)
            finally:
                self._end()
                self._queue.task_done()

    def _begin(self, job_type: str) -> None:
        with self._state_lock:
            self._state.update(
                running=True,
                current_job=job_type,
                current_label=None,
                started_at=datetime.now().isoformat(),
                processed=0,
                last_error=None,
            )

    def _end(self) -> None:
        with self._state_lock:
            self._state.update(
                running=False,
                current_job=None,
                current_label=None,
                last_finished_at=datetime.now().isoformat(),
            )

    def _run_full_scan(self) -> None:
        if not self.is_configured():
            with self._state_lock:
                self._state["last_error"] = "Uploader username is not configured"
            return

        def _progress(info: dict) -> None:
            with self._state_lock:
                self._state["processed"] = int(info.get("processed", 0) or 0)
                self._state["current_label"] = info.get("current")

        summary = self.scanner.scan_all(
            uploader=self.uploader or "",
            stop_event=self._shutdown,
            progress_cb=_progress,
        )
        with self._state_lock:
            self._state["last_summary"] = summary

    def _run_one(self, payload: dict) -> None:
        torrent_id = payload.get("torrent_id")
        if torrent_id is None:
            return
        linked_item_id = payload.get("linked_item_id")
        row = self.scanner.scan_one(int(torrent_id), uploader=self.uploader)
        if row is None:
            custom_console.bot_warning_log(
                f"[Compliance] scan_one: torrent #{torrent_id} not found"
            )
            return
        # Attach the linked item id (if any) without touching scan metadata.
        if linked_item_id is not None and not row.get("linked_item_id"):
            try:
                self.db.attach_compliance_linked_item(int(torrent_id), int(linked_item_id))
            except Exception as exc:
                custom_console.bot_warning_log(
                    f"[Compliance] failed to attach linked_item_id: {exc}"
                )
        with self._state_lock:
            self._state["processed"] = 1
            self._state["current_label"] = row.get("current_name")

    def _run_by_name(self, payload: dict) -> None:
        name = payload.get("name")
        if not name:
            return
        linked_item_id = payload.get("linked_item_id")
        row = self.scanner.scan_by_name(
            name=name,
            uploader=self.uploader,
            linked_item_id=linked_item_id,
        )
        if row is None:
            custom_console.bot_warning_log(
                f"[Compliance] scan_by_name: no match for '{name}'"
            )
            return
        with self._state_lock:
            self._state["processed"] = 1
            self._state["current_label"] = row.get("current_name")

    # ── status ───────────────────────────────────────────────────────

    def scan_status(self) -> dict:
        with self._state_lock:
            state = dict(self._state)
        state["queue_size"] = self._queue.qsize()
        state["configured"] = self.is_configured()
        state["uploader"] = self.uploader
        return state
