# -*- coding: utf-8 -*-

import json
import os
from datetime import datetime

# Legacy delimiter used in old composite keys (folder_path||basename).
_KEY_SEP = "||"


class WatcherState:
    """Persistent state for the watcher to track processed entries and avoid reprocessing.

    Stores two categories in a JSON file:
      - uploaded: entries successfully uploaded to at least one tracker
      - skipped: entries that could not be uploaded (validation, encoding, etc.)

    The JSON file is stored in the config directory so it persists across
    Docker restarts (mounted volume).

    Keys are the source basename. The folder_path is stored inside each entry.
    """

    def __init__(self, state_dir: str, filename: str = "watcher_state.json"):
        self.state_file = os.path.join(state_dir, filename)
        self._state = self._load()
        self._migrate_legacy_keys()

    def _load(self) -> dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "uploaded" in data and "skipped" in data:
                        return data
            except (json.JSONDecodeError, IOError):
                pass
        return {"uploaded": {}, "skipped": {}}

    def _save(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self._state, f, indent=4, ensure_ascii=False)

    def _migrate_legacy_keys(self):
        """Migrate old composite keys (folder_path||basename) to basename-only keys."""
        changed = False
        for section in ("uploaded", "skipped"):
            migrated = {}
            for key, value in self._state[section].items():
                if _KEY_SEP in key:
                    new_key = key.split(_KEY_SEP, 1)[1]
                    migrated[new_key] = value
                    changed = True
                else:
                    migrated[key] = value
            self._state[section] = migrated
        if changed:
            self._save()

    @staticmethod
    def _make_key(source_path: str, folder_path: str | None = None) -> str:
        return os.path.basename(source_path)

    def is_known(self, source_path: str, folder_path: str | None = None) -> str | None:
        """Check if a source entry is already tracked.

        Returns:
            "uploaded", "skipped", or None if unknown.
        """
        key = self._make_key(source_path)

        if key in self._state["uploaded"]:
            return "uploaded"
        if key in self._state["skipped"]:
            return "skipped"
        return None


    def mark_uploaded(self, source_path: str, torrent_name: str, trackers: list[str],
                      folder_path: str | None = None, category: str | None = None,
                      content_category: str | None = None):
        """Record a successfully uploaded entry."""
        key = self._make_key(source_path)
        # Promote from skipped to uploaded if previously skipped
        self._state["skipped"].pop(key, None)
        self._state["uploaded"][key] = {
            "torrent_name": torrent_name,
            "source_name": key,
            "folder_path": folder_path,
            "category": category,
            "content_category": content_category,
            "type": "folder" if os.path.isdir(source_path) else "file",
            "trackers": trackers,
            "timestamp": datetime.now().isoformat(),
        }
        self._save()

    def mark_skipped(self, source_path: str, torrent_name: str, reason: str,
                     folder_path: str | None = None, category: str | None = None,
                     content_category: str | None = None):
        """Record a skipped entry with the reason it was not uploaded."""
        key = self._make_key(source_path)
        # Never downgrade an uploaded entry to skipped
        if key in self._state["uploaded"]:
            return
        self._state["skipped"][key] = {
            "torrent_name": torrent_name,
            "source_name": key,
            "folder_path": folder_path,
            "category": category,
            "content_category": content_category,
            "type": "folder" if os.path.isdir(source_path) else "file",
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        self._save()

    def remove(self, source_name: str, folder_path: str | None = None):
        """Remove an entry from the state to allow reprocessing."""
        key = self._make_key(source_name)
        self._state["uploaded"].pop(key, None)
        self._state["skipped"].pop(key, None)
        self._save()

    @property
    def uploaded(self) -> dict:
        return self._state["uploaded"]

    @property
    def skipped(self) -> dict:
        return self._state["skipped"]
