# -*- coding: utf-8 -*-

import json
import os
from datetime import datetime

# Delimiter for composite keys (folder_path||basename).
# Using || to avoid collision with Windows drive letter colons (C:\path).
_KEY_SEP = "||"


class WatcherState:
    """Persistent state for the watcher to track processed entries and avoid reprocessing.

    Stores two categories in a JSON file:
      - uploaded: entries successfully uploaded to at least one tracker
      - skipped: entries that could not be uploaded (validation, encoding, etc.)

    The JSON file is stored in the config directory so it persists across
    Docker restarts (mounted volume).

    Keys use composite format "folder_path||basename" for multi-folder support,
    with backward compatibility for legacy basename-only keys.
    """

    def __init__(self, state_dir: str, filename: str = "watcher_state.json"):
        self.state_file = os.path.join(state_dir, filename)
        self._state = self._load()

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

    @staticmethod
    def _make_key(source_path: str, folder_path: str | None = None) -> str:
        name = os.path.basename(source_path)
        if folder_path:
            return f"{folder_path}{_KEY_SEP}{name}"
        return name

    def _migrate_legacy_key(self, name: str, key: str):
        """Migrate a legacy basename-only entry to the new composite key format."""
        for section in ("uploaded", "skipped"):
            if name in self._state[section] and name != key:
                self._state[section].pop(name, None)

    def is_known(self, source_path: str, folder_path: str | None = None) -> str | None:
        """Check if a source entry is already tracked.

        Checks composite key first, then falls back to legacy basename-only key
        for backward compatibility with existing state files.

        Returns:
            "uploaded", "skipped", or None if unknown.
        """
        key = self._make_key(source_path, folder_path)
        name = os.path.basename(source_path)

        # Check composite key first, then legacy key
        if key in self._state["uploaded"] or name in self._state["uploaded"]:
            return "uploaded"
        if key in self._state["skipped"] or name in self._state["skipped"]:
            return "skipped"
        return None


    def mark_uploaded(self, source_path: str, torrent_name: str, trackers: list[str],
                      folder_path: str | None = None, category: str | None = None):
        """Record a successfully uploaded entry."""
        key = self._make_key(source_path, folder_path)
        name = os.path.basename(source_path)
        # Remove legacy basename-only key to migrate to composite format
        self._migrate_legacy_key(name, key)
        # Promote from skipped to uploaded if previously skipped (check both keys)
        self._state["skipped"].pop(key, None)
        self._state["skipped"].pop(name, None)
        self._state["uploaded"][key] = {
            "torrent_name": torrent_name,
            "source_name": name,
            "folder_path": folder_path,
            "category": category,
            "type": "folder" if os.path.isdir(source_path) else "file",
            "trackers": trackers,
            "timestamp": datetime.now().isoformat(),
        }
        self._save()

    def mark_skipped(self, source_path: str, torrent_name: str, reason: str,
                     folder_path: str | None = None, category: str | None = None):
        """Record a skipped entry with the reason it was not uploaded."""
        key = self._make_key(source_path, folder_path)
        name = os.path.basename(source_path)
        # Never downgrade an uploaded entry to skipped (check both keys)
        if key in self._state["uploaded"] or name in self._state["uploaded"]:
            return
        # Remove legacy basename-only key to migrate to composite format
        self._migrate_legacy_key(name, key)
        self._state["skipped"][key] = {
            "torrent_name": torrent_name,
            "source_name": name,
            "folder_path": folder_path,
            "category": category,
            "type": "folder" if os.path.isdir(source_path) else "file",
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        self._save()

    def remove(self, source_name: str, folder_path: str | None = None):
        """Remove an entry from the state to allow reprocessing."""
        key = self._make_key(source_name, folder_path)
        # Remove both composite and legacy keys
        for k in (key, os.path.basename(source_name)):
            self._state["uploaded"].pop(k, None)
            self._state["skipped"].pop(k, None)
        self._save()

    @property
    def uploaded(self) -> dict:
        return self._state["uploaded"]

    @property
    def skipped(self) -> dict:
        return self._state["skipped"]
