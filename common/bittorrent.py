# -*- coding: utf-8 -*-

from dataclasses import dataclass
from unit3dup.pvtTorrent import Mytorrent
from unit3dup.media import Media


@dataclass
class BittorrentData:
    tracker_response: str | None
    torrent_response: Mytorrent | None
    content: Media
    tracker_message: dict | str
    archive_path: str
