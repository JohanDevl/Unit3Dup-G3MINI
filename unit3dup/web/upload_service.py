# -*- coding: utf-8 -*-
"""Upload service: executes tracker uploads for approved items."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from unit3dup.state_db import StateDB
from unit3dup.pvtTracker import Unit3d
from unit3dup.upload import UploadBot

from view import custom_console


class UploadService:
    """Handles upload execution for web-approved items."""

    def __init__(self, state_db: StateDB):
        self.state_db = state_db
        self._upload_lock = threading.Lock()

    def approve_and_upload(
        self,
        item_id: int,
        release_name_override: str | None = None,
        description_override: str | None = None,
    ) -> dict:
        """Approve an item and upload it to the tracker.

        Args:
            item_id: Database item ID
            release_name_override: Optional new release name
            description_override: Optional new description

        Returns:
            dict with keys: success (bool), message (str), tracker_response (str|None)
        """
        with self._upload_lock:
            return self._do_upload(item_id, release_name_override, description_override)

    def _do_upload(
        self,
        item_id: int,
        release_name_override: str | None = None,
        description_override: str | None = None,
    ) -> dict:
        """Execute upload logic (must be called with lock held).

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
        transitioned = self.state_db.atomic_transition(
            item_id,
            from_statuses=("pending", "error"),
            to_status="approved",
            decided_at=datetime.now().isoformat(),
        )
        if not transitioned:
            return {"success": False, "message": f"Item cannot be approved (current status: {item['status']})"}

        try:
            # Save user edits
            if release_name_override:
                self.state_db.update_item(item_id, user_edited_name=release_name_override)
            if description_override:
                self.state_db.update_item(item_id, user_edited_desc=description_override)

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
        if item["status"] == "uploaded":
            return {"success": False, "message": "Cannot reject an already uploaded item"}

        self.state_db.mark_rejected(item_id, reason)
        return {"success": True, "message": "Item rejected"}

    def retry_item(self, item_id: int) -> dict:
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}
        if item["status"] not in ("rejected", "error", "skipped"):
            return {"success": False, "message": f"Cannot retry item with status '{item['status']}'"}

        self.state_db.retry_item(item_id)
        return {"success": True, "message": "Item moved back to pending"}

    def bulk_approve(self, ids: list[int]) -> dict:
        results = []
        with self._upload_lock:
            for item_id in ids:
                result = self._do_upload(item_id)
                results.append({"id": item_id, **result})
        successes = sum(1 for r in results if r["success"])
        return {"success": True, "message": f"{successes}/{len(ids)} uploaded", "results": results}

    def rescan_tmdb(self, item_id: int, new_tmdb_id: int) -> dict:
        """Re-fetch TMDB data for an item with a corrected TMDB ID.

        Updates: tmdb_id, tmdb_title, tmdb_year, imdb_id, keywords,
        and the corresponding fields in tracker_payload.
        """
        item = self.state_db.get_item(item_id)
        if not item:
            return {"success": False, "message": "Item not found"}
        if item["status"] not in ("pending", "error", "skipped", "rejected"):
            return {"success": False, "message": f"Cannot rescan item with status '{item['status']}'"}

        try:
            from common.external_services.theMovieDB.core.api import TmdbAPI

            api = TmdbAPI()
            category = item.get("content_category", "movie")
            # Map to TMDB category
            tmdb_category = "tv" if category in ("tv", "tv_show", "tv_animation") else "movie"

            # Fetch details
            details = api.details(video_id=new_tmdb_id, category=tmdb_category)
            if not details:
                return {"success": False, "message": f"TMDB ID {new_tmdb_id} not found for category '{tmdb_category}'"}

            result = details  # MovieDetails or TVShowDetails object
            title = result.get_title() if hasattr(result, 'get_title') else str(result)
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

            # Update tracker payload
            tracker_payload = item.get("tracker_payload")
            if isinstance(tracker_payload, str):
                tracker_payload = json.loads(tracker_payload)
            if tracker_payload:
                tracker_payload["tmdb"] = new_tmdb_id
                tracker_payload["imdb"] = imdb_id
                if keywords_list:
                    tracker_payload["keywords"] = keywords_list

            # Update DB
            self.state_db.update_item(
                item_id,
                tmdb_id=new_tmdb_id,
                tmdb_title=title,
                tmdb_year=year,
                imdb_id=imdb_id,
                tracker_payload=tracker_payload,
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
