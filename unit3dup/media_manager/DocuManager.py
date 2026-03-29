# -*- coding: utf-8 -*-
import argparse
import os

from common.bittorrent import BittorrentData

from unit3dup.media_manager.common import UserContent
from unit3dup.pvtDocu import PdfImages
from unit3dup.upload import UploadBot
from unit3dup import config_settings
from unit3dup.media import Media
from unit3dup.prepared_item import PreparedItem

from view import custom_console

class DocuManager:

    def __init__(self, contents: list[Media], cli: argparse.Namespace, qbit_category: str | None = None):
        self._my_tmdb = None
        self.contents: list['Media'] = contents
        self.cli: argparse = cli
        self.qbit_category = qbit_category

    def prepare(self, selected_tracker: str, tracker_name_list: list, tracker_archive: str) -> tuple[list[PreparedItem], list[dict]]:
        """Prepare all items for upload without sending them to trackers."""

        # -multi : no announce_list . One announce for multi tracker
        if self.cli.mt:
            tracker_name_list = [selected_tracker.upper()]

        prepared_items = []
        skip_reasons = []

        for content in self.contents:
            # get the archive path
            archive = os.path.join(tracker_archive, selected_tracker)
            os.makedirs(archive, exist_ok=True)
            torrent_filepath = os.path.join(tracker_archive, selected_tracker, f"{content.torrent_name}.torrent")

            if self.cli.watcher:
                if os.path.exists(torrent_filepath):
                    custom_console.bot_log(f"Watcher Active.. skip the old upload '{content.file_name}'")
                    skip_reasons.append({"torrent_name": content.torrent_name, "reason": "already_in_archive",
                                         "source": content.source or ""})
                    prepared_items.append(
                        PreparedItem(
                            content=content,
                            source_path=content.torrent_path or content.file_name,
                            source_type="folder" if os.path.isdir(content.torrent_path) else "file",
                            skip_reason="already_in_archive",
                        )
                    )
                    continue

            torrent_response = UserContent.torrent(content=content, tracker_name_list=tracker_name_list,
                                                   selected_tracker=selected_tracker, this_path=torrent_filepath)

            # Skip if it is a duplicate
            if ((self.cli.duplicate or config_settings.user_preferences.DUPLICATE_ON)
                    and UserContent.is_duplicate(content=content, tracker_name=selected_tracker, cli=self.cli)):
                skip_reasons.append({"torrent_name": content.torrent_name, "reason": "duplicate_on_tracker",
                                     "source": content.source or ""})
                prepared_items.append(
                    PreparedItem(
                        content=content,
                        source_path=content.torrent_path or content.file_name,
                        source_type="folder" if os.path.isdir(content.torrent_path) else "file",
                        skip_reason="duplicate_on_tracker",
                    )
                )
                continue

            # print the title will be shown on the torrent page
            custom_console.bot_log(f"'DISPLAYNAME'...{{{content.display_name}}}\n")

            # Get the cover image and description
            docu_info = PdfImages(content.file_name)
            docu_info.build_info()

            # Tracker payload
            unit3d_up = UploadBot(content=content, tracker_name=selected_tracker, cli=self.cli)

            # Build tracker data
            unit3d_up.data_docu(document_info=docu_info)

            # Exclusion par tag d'équipe
            release_name_check = unit3d_up.tracker.data.get("name", "")
            if UploadBot.is_excluded_tag(release_name_check):
                tag = release_name_check.rsplit('-', 1)[-1] if '-' in release_name_check else "?"
                custom_console.bot_warning_log(f"Tag '{tag}' exclu (EXCLUDED_TAGS). Skip: {release_name_check}")
                skip_reasons.append({"torrent_name": content.torrent_name, "reason": "excluded_tag",
                                     "source": content.source or ""})
                prepared_items.append(
                    PreparedItem(
                        content=content,
                        source_path=content.torrent_path or content.file_name,
                        source_type="folder" if os.path.isdir(content.torrent_path) else "file",
                        skip_reason="excluded_tag",
                    )
                )
                continue

            # Create PreparedItem
            prepared = PreparedItem(
                content=content,
                source_path=content.torrent_path or content.file_name,
                source_type="folder" if os.path.isdir(content.torrent_path) else "file",
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
            )
            prepared_items.append(prepared)

        return prepared_items, skip_reasons

    @staticmethod
    def upload_item(prepared: PreparedItem, cli: argparse.Namespace) -> BittorrentData | None:
        """Upload a single prepared item to the tracker."""
        # Create UploadBot
        unit3d_up = UploadBot(content=prepared.content, tracker_name=prepared.tracker_name, cli=cli)

        # Set tracker data from prepared
        unit3d_up.tracker.data = prepared.tracker_data

        # Send to tracker
        tracker_response, tracker_message = unit3d_up.send(torrent_archive=prepared.torrent_filepath)

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
        """Process and upload all items to tracker. Backward-compatible wrapper around prepare() + upload_item()."""
        prepared_items, skip_reasons = self.prepare(selected_tracker, tracker_name_list, tracker_archive)

        bittorrent_list = []

        for prepared in prepared_items:
            # Skip items that have skip_reason set
            if prepared.skip_reason:
                continue

            # Handle -noup (dry-run)
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
                continue

            # Upload the item
            bittorrent_data = self.upload_item(prepared, self.cli)
            if bittorrent_data:
                bittorrent_list.append(bittorrent_data)

        return bittorrent_list, skip_reasons