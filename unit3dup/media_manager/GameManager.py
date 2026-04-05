# -*- coding: utf-8 -*-
import argparse
import os

from common.external_services.igdb.client import IGDBClient
from common.bittorrent import BittorrentData

from unit3dup.media_manager.common import UserContent
from unit3dup.upload import UploadBot
from unit3dup import config_settings
from unit3dup.media import Media
from unit3dup.prepared_item import PreparedItem

from view import custom_console

class GameManager:

    def __init__(self, contents: list["Media"], cli: argparse.Namespace, qbit_category: str | None = None):
        """
        Initialize the GameManager with the given contents

        Args:
            contents (list): List of content media objects
            cli (argparse.Namespace): user flag Command line
            qbit_category (str | None): qBittorrent category to assign to uploaded torrents
        """
        self.contents: list[Media] = contents
        self.cli: argparse = cli
        self.qbit_category = qbit_category
        self.igdb = IGDBClient()

    def prepare(self, selected_tracker: str, tracker_name_list: list, tracker_archive: str) -> tuple[list[PreparedItem], list[dict]]:
        """
        Prepare game contents for upload without sending them.

        Returns:
            tuple: (list of PreparedItem objects, list of skip reason dicts)
        """

        login = self.igdb.connect()
        if not login:
            exit(1)

        # -multi : no announce_list . One announce for multi tracker
        if self.cli.mt:
            tracker_name_list = [selected_tracker.upper()]

        if self.cli.upload:
            custom_console.bot_error_log("Game upload works only with the '-f' flag.You need to specify a folder name.")
            return [], []

        prepared_items = []
        skip_reasons = []

        for content in self.contents:
            # get the archive path
            archive = os.path.join(tracker_archive, selected_tracker)
            os.makedirs(archive, exist_ok=True)
            torrent_filepath = os.path.join(tracker_archive, selected_tracker, f"{content.torrent_name}.torrent")

            # Filter contents based on existing torrents or duplicates
            if self.cli.watcher:
                if os.path.exists(torrent_filepath):
                    custom_console.bot_log(f"Watcher Active.. skip the old upload '{content.file_name}'")
                    skip_reasons.append({"torrent_name": content.torrent_name, "reason": "already_in_archive",
                                         "source": content.source or ""})
                    prepared_items.append(PreparedItem(
                        content=content,
                        source_path=content.torrent_path or content.file_name or "",
                        source_type="folder" if os.path.isdir(content.torrent_path or "") else "file",
                        display_name=content.display_name,
                        content_category=content.category,
                        qbit_category=self.qbit_category,
                        source_tag=content.source or "",
                        skip_reason="already_in_archive",
                    ))
                    continue

            torrent_response = UserContent.torrent(content=content, tracker_name_list=tracker_name_list,
                                                       selected_tracker=selected_tracker, this_path=torrent_filepath)

            # Skip if it is a duplicate
            if ((self.cli.duplicate or config_settings.user_preferences.DUPLICATE_ON)
                    and UserContent.is_duplicate(content=content, tracker_name=selected_tracker, cli=self.cli)):
                skip_reasons.append({"torrent_name": content.torrent_name, "reason": "duplicate_on_tracker",
                                     "source": content.source or ""})
                prepared_items.append(PreparedItem(
                    content=content,
                    source_path=content.torrent_path or content.file_name or "",
                    source_type="folder" if os.path.isdir(content.torrent_path or "") else "file",
                    display_name=content.display_name,
                    content_category=content.category,
                    qbit_category=self.qbit_category,
                    source_tag=content.source or "",
                    skip_reason="duplicate_on_tracker",
                ))
                continue

            # Search for the game on IGDB using the content's title and platform tags
            game_data_results = self.igdb.game(content=content)
            # print the title will be shown on the torrent page
            custom_console.bot_log(f"'DISPLAYNAME'...{{{content.display_name}}}\n")

            # Skip the upload if there is no valid IGDB
            if not game_data_results:
                skip_reasons.append({"torrent_name": content.torrent_name, "reason": "no_igdb_result",
                                     "source": content.source or ""})
                prepared_items.append(PreparedItem(
                    content=content,
                    source_path=content.torrent_path or content.file_name or "",
                    source_type="folder" if os.path.isdir(content.torrent_path or "") else "file",
                    display_name=content.display_name,
                    content_category=content.category,
                    qbit_category=self.qbit_category,
                    source_tag=content.source or "",
                    skip_reason="no_igdb_result",
                ))
                continue

            # Tracker instance
            unit3d_up = UploadBot(content=content, tracker_name=selected_tracker, cli=self.cli)

            # Get the data
            unit3d_up.data_game(igdb=game_data_results)

            # Exclusion par tag d'équipe
            release_name_check = unit3d_up.tracker.data.get("name", "")
            if UploadBot.is_excluded_tag(release_name_check):
                tag = release_name_check.rsplit('-', 1)[-1] if '-' in release_name_check else "?"
                custom_console.bot_warning_log(f"Tag '{tag}' exclu (EXCLUDED_TAGS). Skip: {release_name_check}")
                skip_reasons.append({"torrent_name": content.torrent_name, "reason": "excluded_tag",
                                     "source": content.source or ""})
                prepared_items.append(PreparedItem(
                    content=content,
                    source_path=content.torrent_path or content.file_name or "",
                    source_type="folder" if os.path.isdir(content.torrent_path or "") else "file",
                    display_name=content.display_name,
                    content_category=content.category,
                    qbit_category=self.qbit_category,
                    source_tag=content.source or "",
                    skip_reason="excluded_tag",
                ))
                continue

            # Read NFO content if it exists
            nfo_content = None
            if os.path.exists(content.game_nfo):
                try:
                    with open(content.game_nfo, 'r', encoding='utf-8') as f:
                        nfo_content = f.read()
                except Exception:
                    nfo_content = None

            # Determine source type
            source_path = content.torrent_path or content.file_name
            source_type = "folder" if os.path.isdir(source_path) else "file"

            # Create PreparedItem
            prepared = PreparedItem(
                content=content,
                source_path=source_path,
                source_type=source_type,
                torrent_response=torrent_response,
                torrent_filepath=torrent_filepath,
                tracker_data=dict(unit3d_up.tracker.data),
                tracker_name=selected_tracker,
                trackers_list=tracker_name_list,
                release_name=unit3d_up.tracker.data.get("name", content.display_name),
                display_name=content.display_name,
                source_tag=content.source or "",
                content_category=content.category,
                qbit_category=self.qbit_category,
                description=unit3d_up.tracker.data.get("description", ""),
                igdb_id=game_data_results.id if game_data_results else 0,
                nfo_content=nfo_content,
            )
            prepared_items.append(prepared)

        return prepared_items, skip_reasons

    @staticmethod
    def upload_item(prepared: PreparedItem, cli: argparse.Namespace) -> BittorrentData | None:
        """
        Upload a prepared game item to the tracker.

        Args:
            prepared: PreparedItem with all required data
            cli: Command line arguments

        Returns:
            BittorrentData with upload results, or None on failure
        """
        # Create UploadBot and restore tracker data
        unit3d_up = UploadBot(content=prepared.content, tracker_name=prepared.tracker_name, cli=cli)
        unit3d_up.tracker.data = prepared.tracker_data

        # Send to the tracker
        tracker_response, tracker_message = unit3d_up.send(torrent_archive=prepared.torrent_filepath, nfo_path=prepared.content.game_nfo)

        return BittorrentData(
            tracker_response=tracker_response,
            torrent_response=prepared.torrent_response,
            content=prepared.content,
            tracker_message=tracker_message,
            archive_path=prepared.torrent_filepath,
            release_name=prepared.release_name,
            qbit_category=prepared.qbit_category,
        )

    def process(self, selected_tracker: str, tracker_name_list: list, tracker_archive: str) -> tuple[list[BittorrentData], list[dict]]:
        """
        Process the game contents to filter duplicates and create torrents.
        Backward-compatible wrapper around prepare() and upload_item().

        Returns:
            tuple: (list of Bittorrent objects, list of skip reasons dicts)
        """
        # Prepare all items
        prepared_items, skip_reasons = self.prepare(selected_tracker, tracker_name_list, tracker_archive)

        # Upload prepared items
        bittorrent_list = []
        for prepared in prepared_items:
            # Don't upload if -noup is set to True
            if self.cli.noup:
                custom_console.bot_warning_log(f"[DRY-RUN] No upload → {prepared.release_name}")
                bittorrent_list.append(
                    BittorrentData(
                        tracker_response=None,
                        torrent_response=prepared.torrent_response,
                        content=prepared.content,
                        tracker_message="dry-run",
                        archive_path=prepared.torrent_filepath,
                        release_name=prepared.release_name,
                        qbit_category=prepared.qbit_category,
                    ))
            else:
                result = self.upload_item(prepared, self.cli)
                if result:
                    bittorrent_list.append(result)

        return bittorrent_list, skip_reasons

