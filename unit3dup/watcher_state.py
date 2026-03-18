# -*- coding: utf-8 -*-

import json
import os
from datetime import datetime


class WatcherState:
    """Persistent state for the watcher to track processed entries and avoid reprocessing.

    Stores two categories in a JSON file:
      - uploaded: entries successfully uploaded to at least one tracker
      - skipped: entries that could not be uploaded (validation, encoding, etc.)

    The JSON file is stored in the config directory so it persists across
    Docker restarts (mounted volume).
    """

    def __init__(self, state_dir: str):
        self.state_file = os.path.join(state_dir, "watcher_state.json")
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

    def is_known(self, source_path: str) -> str | None:
        """Check if a source entry is already tracked.

        Returns:
            "uploaded", "skipped", or None if unknown.
        """
        name = os.path.basename(source_path)
        if name in self._state["uploaded"]:
            return "uploaded"
        if name in self._state["skipped"]:
            return "skipped"
        return None

    def mark_uploaded(self, source_path: str, torrent_name: str, trackers: list[str]):
        """Record a successfully uploaded entry."""
        name = os.path.basename(source_path)
        # Promote from skipped to uploaded if previously skipped
        self._state["skipped"].pop(name, None)
        self._state["uploaded"][name] = {
            "torrent_name": torrent_name,
            "source_name": name,
            "type": "folder" if os.path.isdir(source_path) else "file",
            "trackers": trackers,
            "timestamp": datetime.now().isoformat(),
        }
        self._save()

    def mark_skipped(self, source_path: str, torrent_name: str, reason: str):
        """Record a skipped entry with the reason it was not uploaded."""
        name = os.path.basename(source_path)
        # Never downgrade an uploaded entry to skipped
        if name in self._state["uploaded"]:
            return
        self._state["skipped"][name] = {
            "torrent_name": torrent_name,
            "source_name": name,
            "type": "folder" if os.path.isdir(source_path) else "file",
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        self._save()

    def remove(self, source_name: str):
        """Remove an entry from the state to allow reprocessing."""
        self._state["uploaded"].pop(source_name, None)
        self._state["skipped"].pop(source_name, None)
        self._save()

    @property
    def uploaded(self) -> dict:
        return self._state["uploaded"]

    @property
    def skipped(self) -> dict:
        return self._state["skipped"]
