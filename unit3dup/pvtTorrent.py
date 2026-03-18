# -*- coding: utf-8 -*-

import json
import os
import torf
from tqdm import tqdm

from common.trackers.data import trackers_api_data
from unit3dup.media import Media
from unit3dup import config_settings

from view import custom_console

class HashProgressBar(tqdm):
    def callback(self, mytorr, path, current_num_hashed, total_pieces):
        progress_percentage = (current_num_hashed / total_pieces) * 100
        self.total = 100
        self.update(int(progress_percentage) - self.n)

class Mytorrent:

    def __init__(self, contents: Media, meta: str, trackers_list = None):

        self.torrent_path = contents.torrent_path
        self.trackers_list = trackers_list

        announces = []
        # one tracker at time
        for tracker_name in trackers_list:
            announce = trackers_api_data[tracker_name.upper()]['announce'] if tracker_name else None
            announces.append([announce])

        self.metainfo = json.loads(meta)
        self.mytorr = torf.Torrent(path=contents.torrent_path, trackers=announces)
        self.mytorr.comment = config_settings.user_preferences.TORRENT_COMMENT
        self.mytorr.name = contents.torrent_name
        self.mytorr.created_by = "https://github.com/31December99/Unit3Dup"
        self.mytorr.private = True
        self.mytorr.source= trackers_api_data[trackers_list[0]]['source']
        # Piece size set dynamically in hash() based on content size

    @staticmethod
    def _compute_piece_size(size_bytes: int) -> int:
        """Compute optimal piece size based on total content size (upload.md rules)."""
        size_mb = size_bytes / (1024 * 1024)
        size_gb = size_bytes / (1024 ** 3)
        if size_gb > 20:    return 16 * 1024 * 1024   # 16 MB
        if size_gb > 8:     return  8 * 1024 * 1024   #  8 MB
        if size_gb > 4:     return  4 * 1024 * 1024   #  4 MB
        if size_gb > 2:     return  2 * 1024 * 1024   #  2 MB
        if size_gb > 1:     return  1 * 1024 * 1024   #  1 MB
        if size_mb > 500:   return    512 * 1024       # 512 KB
        return 256 * 1024                              # 256 KB

    def hash(self):
        self.mytorr.segments = self._compute_piece_size(self.mytorr.size)
        # Calculate the torrent size
        size = round(self.mytorr.size / (1024 ** 3), 2)
        # Print a message for the user
        custom_console.print(f"\n{self.trackers_list} {self.mytorr.name} - {size} GB")
        # Hashing
        with HashProgressBar() as progress:
            try:
                self.mytorr.generate(threads=4, callback=progress.callback, interval=0)
            except torf.TorfError as e:
                custom_console.bot_error_log(e)
                exit(1)

    def write(self, overwrite: bool, full_path: str) -> bool:
        try:
            if overwrite:
                os.remove(full_path)
            self.mytorr.write(full_path)
            return True
        except torf.TorfError as e:
            if "File exists" in str(e):
                custom_console.bot_error_log(f"This torrent file already exists: {full_path}")
            return False
        except FileNotFoundError as e:
            custom_console.bot_error_log(f"Trying to update torrent but it does not exist: {full_path}")
            return False
