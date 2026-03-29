# -*- coding: utf-8 -*-
"""SQLite-backed state database for tracking media items through the
prepare → review → upload lifecycle.

Replaces the JSON-based WatcherState for web-mode operation.
Uses WAL journal mode for concurrent read/write access (watcher thread + web server).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any


_ALLOWED_COLUMNS = {
    "source_basename", "source_path", "folder_path", "source_type",
    "status", "content_category", "qbit_category", "display_name",
    "torrent_name", "release_name", "source_tag", "file_size", "resolution",
    "tmdb_id", "imdb_id", "igdb_id", "tmdb_title", "tmdb_year",
    "description", "mediainfo", "nfo_content",
    "tracker_payload", "tracker_name", "trackers_list", "torrent_archive_path",
    "validation_report", "has_errors", "has_warnings",
    "rejection_reason", "user_edited_name", "user_edited_desc",
    "discovered_at", "prepared_at", "decided_at", "uploaded_at",
    "tracker_response", "upload_error", "skip_reason",
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_basename     TEXT NOT NULL UNIQUE,
    source_path         TEXT NOT NULL,
    folder_path         TEXT,
    source_type         TEXT,

    status              TEXT NOT NULL DEFAULT 'pending',

    content_category    TEXT,
    qbit_category       TEXT,
    display_name        TEXT,
    torrent_name        TEXT,
    release_name        TEXT,
    source_tag          TEXT,
    file_size           INTEGER,
    resolution          TEXT,

    tmdb_id             INTEGER,
    imdb_id             INTEGER,
    igdb_id             INTEGER,
    tmdb_title          TEXT,
    tmdb_year           INTEGER,

    description         TEXT,
    mediainfo           TEXT,
    nfo_content         TEXT,

    tracker_payload     TEXT,
    tracker_name        TEXT,
    trackers_list       TEXT,
    torrent_archive_path TEXT,

    validation_report   TEXT,
    has_errors          INTEGER DEFAULT 0,
    has_warnings        INTEGER DEFAULT 0,

    rejection_reason    TEXT,
    user_edited_name    TEXT,
    user_edited_desc    TEXT,

    discovered_at       TEXT DEFAULT (datetime('now', 'localtime')),
    prepared_at         TEXT,
    decided_at          TEXT,
    uploaded_at         TEXT,

    tracker_response    TEXT,
    upload_error        TEXT,
    skip_reason         TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_discovered ON items(discovered_at);
CREATE INDEX IF NOT EXISTS idx_items_source_basename ON items(source_basename);
"""


class StateDB:
    """Thread-safe SQLite state database."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._ensure_schema()

    # ── Connection helpers ────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

    # ── Query helpers ─────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        # Deserialize JSON fields
        for field in ("tracker_payload", "trackers_list", "validation_report"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    # ── Public API: queries ───────────────────────────────────────────

    def is_known(self, source_basename: str) -> str | None:
        """Check if a source entry is already tracked.

        Returns the status string or None if unknown.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT status FROM items WHERE source_basename = ?",
                (source_basename,),
            ).fetchone()
            return row["status"] if row else None
        finally:
            conn.close()

    def get_item(self, item_id: int) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            return self._row_to_dict(row)
        finally:
            conn.close()

    def get_item_by_basename(self, source_basename: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM items WHERE source_basename = ?", (source_basename,)
            ).fetchone()
            return self._row_to_dict(row)
        finally:
            conn.close()

    def list_items(
        self,
        status: str | None = None,
        category: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict]:
        """List items with optional filtering and pagination.

        Returns dicts WITHOUT the large text fields (description, mediainfo, nfo_content)
        for performance. Use get_item() for full detail.
        """
        conditions = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if category:
            conditions.append("content_category = ?")
            params.append(category)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * per_page
        params.extend([per_page, offset])

        conn = self._connect()
        try:
            rows = conn.execute(
                f"""SELECT id, source_basename, source_path, folder_path, source_type,
                       status, content_category, qbit_category, display_name,
                       torrent_name, release_name, source_tag, file_size, resolution,
                       tmdb_id, imdb_id, igdb_id, tmdb_title, tmdb_year,
                       tracker_name, trackers_list, torrent_archive_path,
                       has_errors, has_warnings, validation_report,
                       rejection_reason, user_edited_name, user_edited_desc,
                       discovered_at, prepared_at, decided_at, uploaded_at,
                       upload_error, skip_reason
                FROM items {where}
                ORDER BY discovered_at DESC
                LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def count_by_status(self) -> dict[str, int]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM items GROUP BY status"
            ).fetchall()
            return {r["status"]: r["cnt"] for r in rows}
        finally:
            conn.close()

    # ── Public API: writes ────────────────────────────────────────────

    def add_item(self, **kwargs) -> int:
        """Insert a new item. Serializes JSON fields automatically.

        Returns the new item ID.
        """
        invalid = set(kwargs.keys()) - _ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column names: {invalid}")

        for field in ("tracker_payload", "trackers_list", "validation_report"):
            if field in kwargs and not isinstance(kwargs[field], str):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)

        columns = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))

        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    f"INSERT OR IGNORE INTO items ({columns}) VALUES ({placeholders})",
                    list(kwargs.values()),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def update_item(self, item_id: int, **kwargs) -> bool:
        """Update specific fields on an item."""
        invalid = set(kwargs.keys()) - _ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column names: {invalid}")

        for field in ("tracker_payload", "trackers_list", "validation_report"):
            if field in kwargs and not isinstance(kwargs[field], str):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)

        if not kwargs:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [item_id]

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(f"UPDATE items SET {set_clause} WHERE id = ?", values)
                conn.commit()
                return True
            finally:
                conn.close()

    def mark_uploaded(self, item_id: int, tracker_response: str = "") -> bool:
        return self.update_item(
            item_id,
            status="uploaded",
            uploaded_at=datetime.now().isoformat(),
            decided_at=datetime.now().isoformat(),
            tracker_response=tracker_response,
        )

    def mark_rejected(self, item_id: int, reason: str) -> bool:
        return self.update_item(
            item_id,
            status="rejected",
            decided_at=datetime.now().isoformat(),
            rejection_reason=reason,
        )

    def mark_error(self, item_id: int, error: str) -> bool:
        return self.update_item(
            item_id,
            status="error",
            upload_error=error,
        )

    def retry_item(self, item_id: int) -> bool:
        """Move a rejected/error/skipped item back to pending for reprocessing."""
        return self.update_item(
            item_id,
            status="pending",
            decided_at=None,
            uploaded_at=None,
            rejection_reason=None,
            upload_error=None,
            skip_reason=None,
            tracker_response=None,
        )

    def delete_item(self, item_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
                conn.commit()
                return True
            finally:
                conn.close()

    def atomic_transition(self, item_id: int, from_statuses: tuple[str, ...], to_status: str, **extra_fields) -> bool:
        """Atomically transition an item's status. Returns True if the transition was applied."""
        invalid = set(extra_fields.keys()) - _ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column names: {invalid}")

        for field in ("tracker_payload", "trackers_list", "validation_report"):
            if field in extra_fields and not isinstance(extra_fields[field], str):
                extra_fields[field] = json.dumps(extra_fields[field], ensure_ascii=False)

        placeholders_str = ", ".join(f"{k} = ?" for k in extra_fields)
        set_clause = f"status = ?"
        if placeholders_str:
            set_clause += f", {placeholders_str}"

        where_in = ", ".join("?" for _ in from_statuses)

        values = [to_status] + list(extra_fields.values()) + [item_id] + list(from_statuses)

        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    f"UPDATE items SET {set_clause} WHERE id = ? AND status IN ({where_in})",
                    values,
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    # ── Migration from WatcherState JSON ──────────────────────────────

    def migrate_from_json(self, json_path: str) -> int:
        """Import entries from a watcher_state.json file.

        Returns the number of entries migrated.
        """
        if not os.path.exists(json_path):
            return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return 0

        count = 0
        now = datetime.now().isoformat()

        for basename, entry in data.get("uploaded", {}).items():
            if self.is_known(basename):
                continue
            self.add_item(
                source_basename=basename,
                source_path=entry.get("folder_path", "") or basename,
                folder_path=entry.get("folder_path"),
                source_type=entry.get("type", ""),
                status="uploaded",
                content_category=entry.get("content_category", ""),
                torrent_name=entry.get("torrent_name", ""),
                release_name=entry.get("torrent_name", ""),
                source_tag=entry.get("source", ""),
                tracker_name="",
                trackers_list=entry.get("trackers", []),
                validation_report=entry.get("validation_report", []),
                discovered_at=entry.get("timestamp", now),
                uploaded_at=entry.get("timestamp", now),
            )
            count += 1

        for basename, entry in data.get("skipped", {}).items():
            if self.is_known(basename):
                continue
            self.add_item(
                source_basename=basename,
                source_path=entry.get("folder_path", "") or basename,
                folder_path=entry.get("folder_path"),
                source_type=entry.get("type", ""),
                status="skipped",
                content_category=entry.get("content_category", ""),
                torrent_name=entry.get("torrent_name", ""),
                release_name=entry.get("torrent_name", ""),
                source_tag=entry.get("source", ""),
                skip_reason=entry.get("reason", ""),
                validation_report=entry.get("validation_report", []),
                discovered_at=entry.get("timestamp", now),
            )
            count += 1

        return count
