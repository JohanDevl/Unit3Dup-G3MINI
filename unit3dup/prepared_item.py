# -*- coding: utf-8 -*-
"""Data class holding all information gathered during the 'prepare' phase.

A PreparedItem is the output of VideoManager.prepare() / GameManager.prepare() /
DocuManager.prepare(). It contains everything needed to either display a preview
in the web dashboard or execute the actual upload to the tracker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from unit3dup.media import Media


@dataclass
class PreparedItem:
    """Snapshot of a fully-analysed media item, ready for review or upload."""

    # ── Source identity ──────────────────────────────────────────────
    content: Media
    source_path: str                          # full path to the source file/folder
    source_type: str = ""                     # 'file' | 'folder'

    # ── Torrent ──────────────────────────────────────────────────────
    torrent_response: Any = None              # Mytorrent | None
    torrent_filepath: str = ""                # path to the .torrent file in archive

    # ── Tracker payload ──────────────────────────────────────────────
    tracker_data: dict = field(default_factory=dict)   # complete tracker upload dict
    tracker_name: str = ""
    trackers_list: list[str] = field(default_factory=list)

    # ── Release info ─────────────────────────────────────────────────
    release_name: str = ""
    display_name: str = ""
    source_tag: str = ""                      # WEB-DL, BluRay, etc.
    resolution: str = ""
    content_category: str = ""                # movie, tv, game, documentary...
    qbit_category: str | None = None

    # ── Rich content ─────────────────────────────────────────────────
    description: str = ""                     # BBCode prez
    mediainfo: str = ""                       # raw mediainfo text
    nfo_content: str | None = None            # NFO file contents (read at prepare time)
    audio_tracks: list[dict] = field(default_factory=list)
    subtitle_tracks: list[dict] = field(default_factory=list)

    # ── External IDs ─────────────────────────────────────────────────
    tmdb_id: int = 0
    imdb_id: int = 0
    igdb_id: int = 0
    tmdb_title: str | None = None
    tmdb_year: int | None = None

    # ── Validation ───────────────────────────────────────────────────
    validation_report: list[dict] = field(default_factory=list)
    has_errors: bool = False
    has_warnings: bool = False

    # ── Skip / error ─────────────────────────────────────────────────
    skip_reason: str | None = None            # if set, item was not uploadable
    duplicate_match: dict | None = None       # tracker torrent matched as duplicate
