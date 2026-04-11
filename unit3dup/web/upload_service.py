# -*- coding: utf-8 -*-
"""Upload service: executes tracker uploads for approved items."""

from __future__ import annotations

import json
import os
import queue
import re
import threading
from datetime import datetime

from unit3dup.state_db import StateDB
from unit3dup.pvtTracker import Unit3d
from unit3dup.upload import UploadBot
from unit3dup.prez import generate_prez
from common.mediainfo import MediaFile

from view import custom_console


class UploadService:
    """Handles upload execution for web-approved items."""

    def __init__(self, state_db: StateDB):
        self.state_db = state_db
        self._queue: queue.Queue = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._rescan_queue: queue.Queue = queue.Queue()
        self._rescan_worker_thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._current_item_id: int | None = None
        self._current_rescan_item_id: int | None = None

    def start_worker(self):
        """Start the background upload and rescan workers. Re-enqueues items left in queued/approved/rescanning status from a previous crash."""
        for status in ("queued", "approved"):
            items = self.state_db.list_items(status=status)
            for item in items:
                self._queue.put((item["id"], None, None))
                custom_console.bot_log(f"[Web] Re-enqueued {status} item #{item['id']}: {item.get('release_name', '?')}")
        for item in self.state_db.list_items(status="rescanning"):
            self._rescan_queue.put(item["id"])
            custom_console.bot_log(f"[Web] Re-enqueued rescanning item #{item['id']}: {item.get('release_name', '?')}")
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        self._rescan_worker_thread = threading.Thread(target=self._rescan_worker_loop, daemon=True)
        self._rescan_worker_thread.start()

    def stop_worker(self):
        """Signal the workers to stop and wait for them."""
        self._shutdown.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        if self._rescan_worker_thread and self._rescan_worker_thread.is_alive():
            self._rescan_worker_thread.join(timeout=5)

    def _worker_loop(self):
        """Background loop: pick items from queue and upload one at a time."""
        while not self._shutdown.is_set():
            try:
                item_id, name_override, desc_override = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._current_item_id = item_id
                self._do_upload(item_id, name_override, desc_override)
            except Exception as e:
                custom_console.bot_error_log(f"[Web] Worker error for item #{item_id}: {e}")
                try:
                    self.state_db.mark_error(item_id, f"Worker error: {e}")
                except Exception:
                    custom_console.bot_error_log(f"[Web] Failed to mark error for item #{item_id}")
            finally:
                self._current_item_id = None
                self._queue.task_done()

    def _rescan_worker_loop(self):
        """Background loop: pick items from rescan queue and re-prepare one at a time."""
        while not self._shutdown.is_set():
            try:
                item_id = self._rescan_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._current_rescan_item_id = item_id
                self._do_rescan(item_id)
            except Exception as e:
                custom_console.bot_error_log(f"[Web] Rescan worker error for item #{item_id}: {e}")
                try:
                    self.state_db.mark_error(item_id, f"Rescan worker error: {e}")
                except Exception:
                    custom_console.bot_error_log(f"[Web] Failed to mark error for item #{item_id}")
            finally:
                self._current_rescan_item_id = None
                self._rescan_queue.task_done()

    def approve_and_upload(
        self,
        item_id: int,
        release_name_override: str | None = None,
        description_override: str | None = None,
    ) -> dict:
        """Queue an item for upload. Returns immediately."""
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}

        transitioned = self.state_db.atomic_transition(
            item_id,
            from_statuses=("pending", "error"),
            to_status="queued",
            decided_at=datetime.now().isoformat(),
        )
        if not transitioned:
            return {"success": False, "message": f"Item cannot be queued (current status: {item['status']})"}

        # Save user edits immediately
        if release_name_override:
            self.state_db.update_item(item_id, user_edited_name=release_name_override)
        if description_override:
            self.state_db.update_item(item_id, user_edited_desc=description_override)

        self._queue.put((item_id, release_name_override, description_override))
        custom_console.bot_log(f"[Web] Queued → {item.get('release_name', 'unknown')}")
        return {"success": True, "message": "Queued for upload"}

    def _do_upload(
        self,
        item_id: int,
        release_name_override: str | None = None,
        description_override: str | None = None,
    ) -> dict:
        """Execute upload logic. Called by the background worker thread.

        Args:
            item_id: Database item ID
            release_name_override: Optional new release name
            description_override: Optional new description

        Returns:
            dict with keys: success (bool), message (str), tracker_response (str|None)
        """
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}

        # Use atomic transition to prevent TOCTOU race
        # Accept both "queued" (normal) and "approved" (crash recovery re-enqueue)
        transitioned = self.state_db.atomic_transition(
            item_id,
            from_statuses=("queued", "approved"),
            to_status="approved",
            decided_at=datetime.now().isoformat(),
        )
        if not transitioned:
            return {"success": False, "message": f"Item cannot be approved (current status: {item['status']})"}

        try:
            # Resolve user overrides: prefer passed values, fall back to DB columns
            # (important for crash recovery where overrides are None)
            release_name_override = release_name_override or item.get("user_edited_name")
            description_override = description_override or item.get("user_edited_desc")

            # Build tracker payload
            tracker_payload = item.get("tracker_payload")
            if isinstance(tracker_payload, str):
                tracker_payload = json.loads(tracker_payload)
            if not tracker_payload:
                self.state_db.mark_error(item_id, "No tracker payload found")
                return {"success": False, "message": "No tracker payload stored for this item"}

            # Apply user overrides
            if release_name_override:
                tracker_payload["name"] = release_name_override
            if description_override:
                tracker_payload["description"] = description_override

            tracker_name = item.get("tracker_name", "")
            torrent_archive_path = item.get("torrent_archive_path", "")

            if not torrent_archive_path or not os.path.exists(torrent_archive_path):
                self.state_db.mark_error(item_id, f"Torrent file not found: {torrent_archive_path}")
                return {"success": False, "message": f"Torrent file not found: {torrent_archive_path}"}

            # Execute upload
            try:
                tracker = Unit3d(tracker_name=tracker_name)
                tracker.data = tracker_payload

                # Search for NFO file
                nfo_path = self._find_nfo(item)

                response = tracker.upload_t(
                    data=tracker_payload,
                    torrent_archive_path=torrent_archive_path,
                    nfo_path=nfo_path,
                )

                if response.status_code == 200:
                    response_body = response.json()
                    tracker_url = response_body.get("data", "")

                    # Download the new torrent file from tracker (with new info_hash)
                    if tracker_url:
                        UploadBot.download_file(url=tracker_url, destination_path=torrent_archive_path)

                    self.state_db.mark_uploaded(item_id, tracker_response=tracker_url)
                    custom_console.bot_log(f"[Web] Uploaded → {tracker_payload.get('name', 'unknown')}")

                    # Optionally send to bittorrent client
                    self._send_to_client(item, torrent_archive_path, tracker_url)

                    return {
                        "success": True,
                        "message": f"Upload successful: {response_body.get('message', 'OK')}",
                        "tracker_response": tracker_url,
                    }
                else:
                    error_msg = f"Tracker returned {response.status_code}: {response.text[:500]}"
                    self.state_db.mark_error(item_id, error_msg)
                    return {"success": False, "message": error_msg}

            except Exception as e:
                error_msg = f"Upload failed: {str(e)}"
                self.state_db.mark_error(item_id, error_msg)
                custom_console.bot_error_log(f"[Web] {error_msg}")
                return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"Upload preparation failed: {str(e)}"
            self.state_db.mark_error(item_id, error_msg)
            custom_console.bot_error_log(f"[Web] {error_msg}")
            return {"success": False, "message": error_msg}

    def reject_item(self, item_id: int, reason: str) -> dict:
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}
        if item["status"] in ("uploaded", "queued", "approved", "rescanning"):
            return {"success": False, "message": f"Cannot reject item with status '{item['status']}'"}

        self.state_db.mark_rejected(item_id, reason)
        return {"success": True, "message": "Item rejected"}

    def cancel_item(self, item_id: int) -> dict:
        """Cancel a queued item, moving it back to pending."""
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}

        transitioned = self.state_db.atomic_transition(
            item_id,
            from_statuses=("queued",),
            to_status="pending",
            decided_at=None,
        )
        if not transitioned:
            return {"success": False, "message": f"Cannot cancel item with status '{item['status']}'"}

        custom_console.bot_log(f"[Web] Cancelled → {item.get('release_name', 'unknown')}")
        return {"success": True, "message": "Item removed from queue"}

    def reset_uploaded_item(self, item_id: int) -> dict:
        """Reset an uploaded item back to pending for re-review."""
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}

        transitioned = self.state_db.atomic_transition(
            item_id,
            from_statuses=("uploaded",),
            to_status="pending",
            decided_at=None,
            uploaded_at=None,
            tracker_response=None,
            upload_error=None,
        )
        if not transitioned:
            return {"success": False, "message": f"Cannot reset item with status '{item['status']}'"}

        custom_console.bot_log(f"[Web] Reset → {item.get('release_name', 'unknown')}")
        return {"success": True, "message": "Item moved back to pending"}

    def retry_item(self, item_id: int) -> dict:
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}

        transitioned = self.state_db.atomic_transition(
            item_id,
            from_statuses=("rejected", "error", "skipped"),
            to_status="pending",
            decided_at=None,
            uploaded_at=None,
            rejection_reason=None,
            upload_error=None,
            skip_reason=None,
            tracker_response=None,
        )
        if not transitioned:
            return {"success": False, "message": f"Cannot retry item with status '{item['status']}'"}

        return {"success": True, "message": "Item moved back to pending"}

    def rescan_item(self, item_id: int) -> dict:
        """Queue an item for rescan. Returns immediately."""
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}
        if item["status"] not in ("pending", "error", "skipped", "rejected"):
            return {"success": False, "message": f"Cannot rescan item with status '{item['status']}'"}

        source_path = item.get("source_path", "")
        if not source_path or not os.path.exists(source_path):
            return {"success": False, "message": f"Source file not found: {source_path}"}

        transitioned = self.state_db.atomic_transition(
            item_id,
            from_statuses=("pending", "error", "skipped", "rejected"),
            to_status="rescanning",
        )
        if not transitioned:
            return {"success": False, "message": f"Cannot rescan item with status '{item['status']}'"}

        self._rescan_queue.put(item_id)
        custom_console.bot_log(f"[Web] Rescan queued → {item.get('release_name', 'unknown')}")
        return {"success": True, "message": "Queued for rescan"}

    def _do_rescan(self, item_id: int):
        """Execute rescan logic. Called by the background rescan worker thread."""
        item = self.state_db.get_item(item_id)
        if not item:
            return

        source_path = item.get("source_path", "")
        if not source_path or not os.path.exists(source_path):
            self.state_db.mark_error(item_id, f"Source file not found: {source_path}")
            return

        try:
            import argparse
            from unit3dup.bot import Bot
            from unit3dup import config_settings
            from common.trackers.data import trackers_api_data

            cli = argparse.Namespace(
                mt=False, duplicate=False, watcher=False, noup=False, noseed=True,
                reseed=False, personal=False, confirm=False, skip_validation=False,
                notitle=None, gentitle=False, force=None, upload=None, folder=None,
                scan=None, web=True, ftp=False, tracker=None,
            )

            trackers = item.get("trackers_list", [])
            if isinstance(trackers, str):
                trackers = json.loads(trackers)
            if not trackers:
                trackers = list(trackers_api_data.keys())[:1]

            tracker_archive = config_settings.user_preferences.TORRENT_ARCHIVE_PATH or "."
            mode = "folder" if os.path.isdir(source_path) else "man"

            bot = Bot(
                path=source_path,
                cli=cli,
                trackers_name_list=trackers,
                mode=mode,
                torrent_archive_path=tracker_archive,
                qbit_category=item.get("qbit_category"),
            )

            prepared_items = bot.prepare()

            if not prepared_items:
                self.state_db.mark_error(item_id, "Rescan produced no results")
                return

            p = prepared_items[0]
            new_status = "pending" if not p.skip_reason else "skipped"

            transitioned = self.state_db.atomic_transition(
                item_id,
                from_statuses=("rescanning",),
                to_status=new_status,
                release_name=p.release_name,
                display_name=p.display_name,
                source_tag=p.source_tag,
                resolution=p.resolution,
                content_category=p.content_category,
                tmdb_id=p.tmdb_id,
                imdb_id=p.imdb_id,
                igdb_id=p.igdb_id,
                tmdb_title=p.tmdb_title,
                tmdb_year=p.tmdb_year,
                description=p.description,
                mediainfo=p.mediainfo,
                tracker_payload=p.tracker_data,
                tracker_name=p.tracker_name,
                trackers_list=p.trackers_list,
                torrent_archive_path=p.torrent_filepath,
                audio_tracks=p.audio_tracks,
                subtitle_tracks=p.subtitle_tracks,
                validation_report=p.validation_report,
                has_errors=int(p.has_errors),
                has_warnings=int(p.has_warnings),
                skip_reason=p.skip_reason,
                prepared_at=datetime.now().isoformat(),
                upload_error=None,
                rejection_reason=None,
                user_edited_name=None,
                user_edited_desc=None,
            )

            if not transitioned:
                custom_console.bot_warning_log(f"[Web] Rescan skipped — item #{item_id} status changed during rescan")
                return

            if p.skip_reason:
                custom_console.bot_warning_log(f"[Web] Rescan → {p.skip_reason}: {source_path}")
            else:
                custom_console.bot_log(f"[Web] Rescan → {p.release_name}")

        except Exception as e:
            custom_console.bot_error_log(f"[Web] Rescan failed: {e}")
            self.state_db.mark_error(item_id, f"Rescan failed: {str(e)}")

    def regenerate_prez(self, item_id: int, audio_tracks: list[dict], subtitle_tracks: list[dict]) -> dict:
        """Regenerate the prez description with modified track data."""
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}
        source_path = item.get("source_path", "")
        if not source_path or not os.path.exists(source_path):
            return {"success": False, "message": f"Source file not found: {source_path}"}
        try:
            # For folder-based items, find the actual video file
            file_path = source_path
            if os.path.isdir(source_path):
                from common.utility import ManageTitles
                video_exts = {".mkv", ".mp4", ".avi", ".ts", ".m2ts"}
                for entry in sorted(os.listdir(source_path)):
                    if os.path.splitext(entry)[1].lower() in video_exts:
                        file_path = os.path.join(source_path, entry)
                        break
                else:
                    return {"success": False, "message": "No video file found in folder"}
            media_file = MediaFile(file_path)
            new_desc = generate_prez(media_file, audio_tracks=audio_tracks, sub_tracks=subtitle_tracks)
            self.state_db.update_item(
                item_id,
                description=new_desc,
                audio_tracks=audio_tracks,
                subtitle_tracks=subtitle_tracks,
                user_edited_desc=None,
            )
            return {"success": True, "message": "Description regenerated", "description": new_desc}
        except Exception as e:
            return {"success": False, "message": f"Regeneration failed: {str(e)}"}

    def bulk_approve(self, ids: list[int]) -> dict:
        count = 0
        for item_id in ids:
            result = self.approve_and_upload(item_id)
            if result["success"]:
                count += 1
        return {"success": True, "message": f"{count}/{len(ids)} queued"}

    def bulk_rescan(self, ids: list[int]) -> dict:
        """Transition all valid items to 'rescanning' first, then enqueue them all at once."""
        valid_ids = []
        for item_id in ids:
            item = self.state_db.get_item(item_id)
            if not item:
                continue
            if item["status"] not in ("pending", "error", "skipped", "rejected"):
                continue
            source_path = item.get("source_path", "")
            if not source_path or not os.path.exists(source_path):
                continue
            transitioned = self.state_db.atomic_transition(
                item_id,
                from_statuses=("pending", "error", "skipped", "rejected"),
                to_status="rescanning",
            )
            if transitioned:
                valid_ids.append(item_id)

        for item_id in valid_ids:
            self._rescan_queue.put(item_id)

        if valid_ids:
            custom_console.bot_log(f"[Web] Bulk rescan queued → {len(valid_ids)} item(s)")
        return {"success": True, "message": f"{len(valid_ids)}/{len(ids)} queued for rescan"}

    def queue_status(self) -> dict:
        """Return current queue state."""
        return {
            "queue_size": self._queue.qsize(),
            "uploading_item_id": self._current_item_id,
            "rescan_queue_size": self._rescan_queue.qsize(),
            "rescanning_item_id": self._current_rescan_item_id,
        }

    def rescan_tmdb(self, item_id: int, new_tmdb_id: int) -> dict:
        """Re-fetch TMDB data for an item with a corrected TMDB ID.

        Updates: tmdb_id, tmdb_title, tmdb_year, imdb_id, keywords,
        release_name, display_name, tracker_payload (including name),
        and clears user_edited_name.
        """
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}
        if item["status"] not in ("pending", "error", "skipped", "rejected"):
            return {"success": False, "message": f"Cannot rescan item with status '{item['status']}'"}

        try:
            from common.external_services.theMovieDB.core.api import TmdbAPI

            api = TmdbAPI()
            # Override language to French, fallback English
            original_lang = api.params.get("language")
            api.params["language"] = "fr-FR"

            category = item.get("content_category", "movie")
            # Map to TMDB category
            tmdb_category = "tv" if category in ("tv", "tv_show", "tv_animation", "tv_documentary") else "movie"

            # Fetch details in French
            details = api.details(video_id=new_tmdb_id, category=tmdb_category)
            if not details:
                return {"success": False, "message": f"TMDB ID {new_tmdb_id} not found for category '{tmdb_category}'"}

            result = details[0]  # MovieDetails or TVShowDetails object
            title = result.get_title()

            # If French title is empty, fallback to English
            if not title or title == str(new_tmdb_id):
                api.params["language"] = "en-US"
                details_en = api.details(video_id=new_tmdb_id, category=tmdb_category)
                if details_en:
                    title = details_en[0].get_title()

            # Restore original language
            api.params["language"] = original_lang
            year = None
            if hasattr(result, 'get_date') and result.get_date():
                try:
                    from datetime import datetime as dt
                    year = dt.strptime(result.get_date(), '%Y-%m-%d').year
                except (ValueError, TypeError):
                    pass

            # Fetch keywords
            keywords_list = ""
            try:
                keywords_result = api.keywords(video_id=new_tmdb_id, category=tmdb_category)
                if keywords_result:
                    keywords_list = keywords_result
            except Exception:
                pass

            # Fetch IMDB ID from details
            imdb_id = 0
            if hasattr(result, 'imdb_id') and result.imdb_id:
                try:
                    imdb_id = int(str(result.imdb_id).replace('tt', ''))
                except (ValueError, TypeError):
                    pass

            # --- Update release_name and display_name ---
            old_release = item.get("release_name") or ""
            old_display = item.get("display_name") or ""
            old_title = item.get("tmdb_title") or ""
            old_year = item.get("tmdb_year")

            new_release = old_release
            new_display = old_display

            if old_title and title:
                old_title_dotted = old_title.replace(" ", ".")
                new_title_dotted = title.replace(" ", ".")
                if old_title_dotted in new_release:
                    new_release = new_release.replace(old_title_dotted, new_title_dotted, 1)
                if old_title in new_display:
                    new_display = new_display.replace(old_title, title, 1)

            if old_year and year and str(old_year) != str(year):
                year_pattern = re.compile(r'\b' + re.escape(str(old_year)) + r'\b')
                new_year_str = str(year)
                new_release = year_pattern.sub(new_year_str, new_release, count=1)
                new_display = year_pattern.sub(new_year_str, new_display, count=1)

            # Update tracker payload
            tracker_payload = item.get("tracker_payload")
            if isinstance(tracker_payload, str):
                tracker_payload = json.loads(tracker_payload)
            if tracker_payload:
                tracker_payload["tmdb"] = new_tmdb_id
                tracker_payload["imdb"] = imdb_id
                if keywords_list:
                    tracker_payload["keywords"] = keywords_list
                if new_release != old_release:
                    tracker_payload["name"] = new_release

            # Update DB
            self.state_db.update_item(
                item_id,
                tmdb_id=new_tmdb_id,
                tmdb_title=title,
                tmdb_year=year,
                imdb_id=imdb_id,
                tracker_payload=tracker_payload,
                release_name=new_release,
                display_name=new_display,
                user_edited_name=None,
                status="pending",  # Reset to pending for re-review
            )

            custom_console.bot_log(f"[Web] TMDB rescan → {title} ({year}) ID:{new_tmdb_id}")
            return {
                "success": True,
                "message": f"TMDB updated: {title} ({year})",
                "tmdb_id": new_tmdb_id,
                "tmdb_title": title,
                "tmdb_year": year,
                "imdb_id": imdb_id,
                "release_name": new_release,
            }

        except Exception as e:
            return {"success": False, "message": f"TMDB rescan failed: {str(e)}"}

    def bulk_reject(self, ids: list[int], reason: str) -> dict:
        count = 0
        for item_id in ids:
            result = self.reject_item(item_id, reason)
            if result["success"]:
                count += 1
        return {"success": True, "message": f"{count}/{len(ids)} rejected"}

    @staticmethod
    def _find_nfo(item: dict) -> str | None:
        """Search for an NFO file based on the item's source path."""
        source_path = item.get("source_path", "")
        if not source_path or not os.path.exists(source_path):
            return None

        if os.path.isdir(source_path):
            nfo_files = [f for f in os.listdir(source_path) if f.lower().endswith(".nfo")]
            if nfo_files:
                return os.path.join(source_path, nfo_files[0])
        elif os.path.isfile(source_path):
            base = os.path.splitext(source_path)[0]
            nfo_candidate = base + ".nfo"
            if os.path.isfile(nfo_candidate):
                return nfo_candidate

        return None

    @staticmethod
    def _send_to_client(item: dict, torrent_archive_path: str, tracker_url: str) -> None:
        """Optionally send the uploaded torrent to the configured bittorrent client."""
        try:
            from unit3dup import config_settings
            from common.torrent_clients import QbittorrentClient, TransmissionClient, RTorrentClient

            client_name = config_settings.torrent_client_config.TORRENT_CLIENT.lower()
            if client_name == "qbittorrent":
                client = QbittorrentClient()
            elif client_name == "transmission":
                client = TransmissionClient()
            elif client_name == "rtorrent":
                client = RTorrentClient()
            else:
                return

            client.connect()

            # Download the torrent from tracker and add to client
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".torrent") as tmp:
                tmp_path = tmp.name

            if UploadBot.download_file(url=tracker_url, destination_path=tmp_path):
                client.send_to_client(
                    tracker_data_response=tracker_url,
                    torrent=None,
                    content=None,
                    archive_path=tmp_path,
                    category=item.get("qbit_category"),
                )

            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        except Exception as e:
            custom_console.bot_warning_log(f"[Web] Failed to send to bittorrent client: {e}")
