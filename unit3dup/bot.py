# -*- coding: utf-8 -*-

from pathlib import Path
import argparse
import os
import time

from unit3dup.media import Media
from unit3dup.media_manager.ContentManager import ContentManager
from unit3dup.media_manager.TorrentManager import TorrentManager

from common.external_services.ftpx.core.models.list import FTPDirectory
from common.external_services.ftpx.core.menu import Menu
from common.external_services.ftpx.client import Client
from common.extractor import Extractor
from common.utility import ManageTitles

from view import custom_console


class Bot:
    """
    A Bot class that manages media files, including processing, torrent management,TMDB ,FTP

    Methods:
        run(): Starts the media processing and torrent handling tasks
        watcher(duration: int, watcher_folders: list): Monitors multiple folders for changes and processes files
        ftp(): Connects to a remote FTP server and processes files
    """

    # Bot Manager
    def __init__(self, path: str, cli: argparse.Namespace, trackers_name_list: list, mode="man",
                 torrent_archive_path=None, qbit_category: str | None = None):
        """
        Initializes the Bot instance with path, command-line interface object, and mode

        Args:
            path (str): The path to the directory or file to be managed
            cli (argparse.Namespace): The command-line arguments object
            mode (str): The mode of operation, default is 'man'
        """
        self.trackers_name_list = trackers_name_list
        self.torrent_archive_path = torrent_archive_path
        self.qbit_category = qbit_category
        self.content_manager = None
        self.path = path.strip()
        self.cli = cli
        self.mode = mode
        self.upload_count = 0
        self.skip_reasons: list[dict] = []
        self.release_names: list[str] = []
        self.release_sources: list[str] = []
        self.content_categories: list[str] = []
        self.validation_reports: dict[str, list[dict]] = {}


    def contents(self) -> bool | list[Media]:
        """
        Start the process of analyzing and processing media files
        This method retrieves media files
        """
        custom_console.panel_message("Analyzing your media files... Please wait")

        if not os.path.exists(self.path):
            custom_console.bot_error_log("Path doesn't exist")
            return False

        # Get a Files list with basic attributes and create a content object for each
        self.content_manager: ContentManager = ContentManager(path=self.path, mode=self.mode, cli=self.cli)
        contents = self.content_manager.process()

        # -u requires a single file
        if not contents:
            custom_console.bot_error_log("There are no Media to process")
            return False

        # we got a handled exception
        if contents is None:
            exit(1)

        # -f requires at least one file
        if not contents:
            custom_console.bot_error_log(f"There are no Files to process. Try using -scan")
            exit(1)

        # Print the list of files being processed
        custom_console.bot_process_table_log(contents)

        return contents


    def run(self) -> bool:
        """
        processes the files using the TorrentManager and SeedManager
        """

        # Get the user content
        contents = self.contents()
        if not contents:
            return False

        # Instance a new run
        torrent_manager = TorrentManager(cli=self.cli, tracker_archive=self.torrent_archive_path, qbit_category=self.qbit_category)
        # Process the torrents content (files)
        torrent_manager.process(contents=contents)

        # We want to reseed
        if self.cli.reseed:
            torrent_manager.reseed(trackers_name_list=self.trackers_name_list)
        else:
            # otherwise run the torrents creations and the upload process
            torrent_manager.run(trackers_name_list=self.trackers_name_list)

        self.upload_count = torrent_manager.upload_count
        self.skip_reasons = torrent_manager.skip_reasons
        self.release_names = torrent_manager.release_names
        self.release_sources = torrent_manager.release_sources
        self.content_categories = torrent_manager.content_categories
        self.validation_reports = torrent_manager.validation_reports
        return True

    def prepare(self) -> list:
        """Prepare contents without uploading. Returns list of PreparedItem objects."""
        from unit3dup.prepared_item import PreparedItem

        contents = self.contents()
        if not contents:
            return []

        torrent_manager = TorrentManager(
            cli=self.cli,
            tracker_archive=self.torrent_archive_path,
            qbit_category=self.qbit_category,
        )
        torrent_manager.process(contents=contents)
        prepared_items = torrent_manager.prepare_all(trackers_name_list=self.trackers_name_list)

        self.skip_reasons = torrent_manager.skip_reasons
        self.validation_reports = torrent_manager.validation_reports

        return prepared_items

    def watcher(self, duration: int, watcher_folders: list, state_dir: str) -> bool:
        """
        Monitors multiple watcher folders for new files/folders, uploads them one-by-one.
        Each folder can have its own qBittorrent category.
        Uses a persistent JSON state file to skip already-processed entries.

        Args:
            duration (int): The time duration in seconds for the watchdog to wait before checking again
            watcher_folders (list[WatcherFolder]): List of folder configs to monitor
            state_dir (str): Directory where the watcher_state.json is stored (config dir)
        """
        from unit3dup.watcher_state import WatcherState

        try:
            # Validate folders at startup
            valid_folders = []
            for wf in watcher_folders:
                if os.path.exists(wf.path):
                    cat_info = f" (category: {wf.category})" if wf.category else ""
                    custom_console.bot_log(f"[Watcher] Monitoring: {wf.path}{cat_info}")
                    valid_folders.append(wf)
                else:
                    custom_console.bot_warning_log(f"[Watcher] Path does not exist, skipping: {wf.path}")

            if not valid_folders:
                custom_console.bot_error_log("[Watcher] No valid watcher folders found\n")
                return False

            dry_run = self.cli.noup or self.cli.noseed
            watcher_state = WatcherState(state_dir=state_dir)
            # In dry-run mode, write to a separate preview file
            dryrun_state = WatcherState(state_dir=state_dir, filename="watcher_dryrun.json") if dry_run else None

            state_db = None
            if getattr(self.cli, 'web', False):
                from unit3dup.state_db import StateDB
                db_path = os.path.join(state_dir, "unit3dup.db")
                state_db = StateDB(db_path=db_path)
                # Migrate existing JSON state if DB is fresh
                if not state_db.count_by_status():
                    migrated = state_db.migrate_from_json(watcher_state.state_file)
                    if migrated:
                        custom_console.bot_log(f"[Watcher] Migrated {migrated} entries from JSON to SQLite")

            if dry_run:
                custom_console.bot_log("[Watcher] DRY-RUN mode: results written to watcher_dryrun.json only")
            custom_console.bot_log(
                f"[Watcher] State file: {watcher_state.state_file} "
                f"({len(watcher_state.uploaded)} uploaded, {len(watcher_state.skipped)} skipped)"
            )

            # Watchdog loop
            while True:
                for watcher_folder in valid_folders:
                    watcher_path = watcher_folder.path
                    folder_category = watcher_folder.category

                    if not os.path.exists(watcher_path):
                        continue

                    watcher_root = Path(watcher_path)

                    # Skip if there are no files in this watcher folder
                    if not os.listdir(watcher_path):
                        continue

                    entries = sorted(
                        [p for p in watcher_root.iterdir()
                         if p.name and not p.name.startswith(".")
                         and (p.is_dir() or ManageTitles.filter_ext(p.name))],
                        key=lambda p: p.name.lower(),
                    )

                    for src in entries:
                        if not src.exists():
                            continue

                        # Check state BEFORE any heavy processing
                        if state_db:
                            status = state_db.is_known(src.name)
                        else:
                            status = watcher_state.is_known(str(src), folder_path=watcher_path)
                        if status:
                            continue

                        # Upload this single item (folder or file)
                        mode = "folder" if src.is_dir() else "man"
                        custom_console.bot_log(f"\n[Watcher] Processing -> {src}")

                        single_bot = Bot(
                            path=str(src),
                            cli=self.cli,
                            trackers_name_list=self.trackers_name_list,
                            mode=mode,
                            torrent_archive_path=self.torrent_archive_path,
                            qbit_category=folder_category,
                        )

                        if state_db:
                            # Web mode: prepare only, don't upload
                            import json
                            from datetime import datetime
                            prepared_items = single_bot.prepare()

                            # Handle stale already_in_archive: if torrent files exist
                            # but the DB has no confirmed upload, remove stale files
                            # so the item gets fully prepared on the next cycle.
                            if prepared_items and all(
                                getattr(p, 'skip_reason', None) == "already_in_archive"
                                for p in prepared_items
                            ):
                                existing = state_db.get_item_by_basename(src.name)
                                if not existing or existing.get("status") != "uploaded":
                                    for p in prepared_items:
                                        archive_path = getattr(p, 'torrent_filepath', None)
                                        if archive_path and os.path.exists(archive_path):
                                            os.remove(archive_path)
                                            custom_console.bot_log(
                                                f"[Watcher/Web] Removed stale archive: {os.path.basename(archive_path)}"
                                            )
                                    custom_console.bot_log(f"[Watcher/Web] Will re-process {src.name} next cycle")
                                    continue  # Skip to next entry; next cycle will fully prepare it

                            for item in prepared_items:
                                if item.skip_reason:
                                    state_db.add_item(
                                        source_basename=src.name,
                                        source_path=str(src),
                                        folder_path=watcher_path,
                                        source_type="folder" if src.is_dir() else "file",
                                        status="skipped",
                                        content_category=item.content_category,
                                        qbit_category=item.qbit_category,
                                        display_name=item.display_name,
                                        torrent_name=item.content.torrent_name if item.content else "",
                                        release_name=item.release_name,
                                        source_tag=item.source_tag,
                                        file_size=item.content.size if item.content else 0,
                                        resolution=item.resolution,
                                        tmdb_id=item.tmdb_id,
                                        imdb_id=item.imdb_id,
                                        igdb_id=item.igdb_id,
                                        tmdb_title=item.tmdb_title,
                                        tmdb_year=item.tmdb_year,
                                        description=item.description,
                                        mediainfo=item.mediainfo,
                                        nfo_content=item.nfo_content,
                                        tracker_payload=item.tracker_data,
                                        tracker_name=item.tracker_name,
                                        trackers_list=item.trackers_list,
                                        torrent_archive_path=item.torrent_filepath,
                                        validation_report=item.validation_report,
                                        has_errors=int(item.has_errors),
                                        has_warnings=int(item.has_warnings),
                                        skip_reason=item.skip_reason,
                                        discovered_at=datetime.now().isoformat(),
                                        prepared_at=None,
                                    )
                                    custom_console.bot_warning_log(f"[Watcher/Web] Skipped → {src.name} ({item.skip_reason})")
                                else:
                                    state_db.add_item(
                                        source_basename=src.name,
                                        source_path=str(src),
                                        folder_path=watcher_path,
                                        source_type="folder" if src.is_dir() else "file",
                                        status="pending",
                                        content_category=item.content_category,
                                        qbit_category=item.qbit_category,
                                        display_name=item.display_name,
                                        torrent_name=item.content.torrent_name if item.content else "",
                                        release_name=item.release_name,
                                        source_tag=item.source_tag,
                                        file_size=item.content.size if item.content else 0,
                                        resolution=item.resolution,
                                        tmdb_id=item.tmdb_id,
                                        imdb_id=item.imdb_id,
                                        igdb_id=item.igdb_id,
                                        tmdb_title=item.tmdb_title,
                                        tmdb_year=item.tmdb_year,
                                        description=item.description,
                                        mediainfo=item.mediainfo,
                                        nfo_content=item.nfo_content,
                                        tracker_payload=item.tracker_data,
                                        tracker_name=item.tracker_name,
                                        trackers_list=item.trackers_list,
                                        torrent_archive_path=item.torrent_filepath,
                                        validation_report=item.validation_report,
                                        has_errors=int(item.has_errors),
                                        has_warnings=int(item.has_warnings),
                                        discovered_at=datetime.now().isoformat(),
                                        prepared_at=datetime.now().isoformat(),
                                    )
                                    custom_console.bot_log(f"[Watcher/Web] Pending → {item.release_name or src.name}")

                            if not prepared_items:
                                state_db.add_item(
                                    source_basename=src.name,
                                    source_path=str(src),
                                    folder_path=watcher_path,
                                    source_type="folder" if src.is_dir() else "file",
                                    status="skipped",
                                    skip_reason="no_processable_media",
                                    discovered_at=datetime.now().isoformat(),
                                )
                                custom_console.bot_warning_log(f"[Watcher/Web] Skipped → {src.name} (no_processable_media)")

                            continue  # Skip the normal (non-web) processing below

                        ok = single_bot.run()

                        # In dry-run, only write to the preview file (not the main state)
                        target_state = dryrun_state if dry_run else watcher_state

                        content_cat = single_bot.content_categories[0] if single_bot.content_categories else None

                        if ok and single_bot.upload_count > 0:
                            # Use the normalized release name if available
                            release_name = single_bot.release_names[0] if single_bot.release_names else src.name
                            upload_report = single_bot.validation_reports.get(release_name)
                            release_source = single_bot.release_sources[0] if single_bot.release_sources else None
                            target_state.mark_uploaded(
                                source_path=str(src),
                                torrent_name=release_name,
                                trackers=self.trackers_name_list,
                                folder_path=watcher_path,
                                category=folder_category,
                                content_category=content_cat,
                                validation_report=upload_report,
                                source=release_source,
                            )
                            label = "[Watcher] DRY-RUN uploaded" if dry_run else "[Watcher] Uploaded"
                            custom_console.bot_log(f"{label} -> {release_name}")
                        elif single_bot.skip_reasons:
                            unique_reasons = sorted(set(s["reason"] for s in single_bot.skip_reasons))

                            if unique_reasons == ["already_in_archive"]:
                                # Torrent exists in archive = content was uploaded before
                                archive_name = single_bot.skip_reasons[0].get("torrent_name", src.name)
                                archive_source = next(
                                    (s.get("source") for s in single_bot.skip_reasons if s.get("source")), None
                                )
                                target_state.mark_uploaded(
                                    source_path=str(src),
                                    torrent_name=archive_name,
                                    trackers=self.trackers_name_list,
                                    folder_path=watcher_path,
                                    category=folder_category,
                                    content_category=content_cat,
                                    source=archive_source,
                                )
                                label = "[Watcher] DRY-RUN already uploaded" if dry_run else "[Watcher] Already uploaded"
                                custom_console.bot_log(f"{label} -> {archive_name}")
                            else:
                                reasons = ", ".join(unique_reasons)
                                skip_report = []
                                skip_source = None
                                for s in single_bot.skip_reasons:
                                    if "validation_report" in s:
                                        skip_report.extend(s["validation_report"])
                                    if not skip_source and s.get("source"):
                                        skip_source = s["source"]
                                target_state.mark_skipped(
                                    source_path=str(src),
                                    torrent_name=src.name,
                                    reason=reasons,
                                    folder_path=watcher_path,
                                    category=folder_category,
                                    content_category=content_cat,
                                    validation_report=skip_report or None,
                                    source=skip_source,
                                )
                                custom_console.bot_warning_log(
                                    f"[Watcher] Skipped -> {src.name} ({reasons})"
                                )
                        else:
                            target_state.mark_skipped(
                                source_path=str(src),
                                torrent_name=src.name,
                                reason="no_processable_media",
                                folder_path=watcher_path,
                                category=folder_category,
                                content_category=content_cat,
                            )
                            custom_console.bot_warning_log(
                                f"[Watcher] Skipped -> {src.name} (no_processable_media)"
                            )

                    # Clean orphaned NFO files for this folder
                    self._cleanup_orphaned_nfo_files(watcher_path)

                # Wait before next cycle
                print()
                start_time = time.perf_counter()
                end_time = start_time + duration
                # Counter
                while time.perf_counter() < end_time:
                    remaining_time = end_time - time.perf_counter()
                    custom_console.bot_counter_log(
                        f"WATCHDOG: {remaining_time:.1f} seconds Ctrl-c to Exit "
                    )
                    time.sleep(1)
                print()

        except KeyboardInterrupt:
            custom_console.bot_log("Exiting...")
        return True

    def _cleanup_orphaned_nfo_files(self, watcher_path: str) -> None:
        """
        Supprime uniquement les fichiers .nfo isolés à la RACINE du dossier watcher.
        Ces fichiers sont ceux générés par le script lors de l'upload.
        NE supprime PAS les fichiers .nfo dans les sous-dossiers (ceux qui étaient là avant).
        """
        try:
            if not os.path.exists(watcher_path) or not os.path.isdir(watcher_path):
                return
            
            # Vérifier UNIQUEMENT à la racine du watcher_path, pas récursivement
            files = os.listdir(watcher_path)
            
            # Chercher les fichiers .nfo à la racine
            nfo_files = [f for f in files if f.lower().endswith('.nfo') and os.path.isfile(os.path.join(watcher_path, f))]
            
            if not nfo_files:
                return
            
            # Vérifier s'il y a des fichiers vidéo à la racine
            video_files = [f for f in files if ManageTitles.filter_ext(f) and os.path.isfile(os.path.join(watcher_path, f))]
            
            # Si pas de fichiers vidéo à la racine mais des fichiers .nfo, supprimer les .nfo
            # (ce sont ceux générés par le script)
            if not video_files and nfo_files:
                for nfo_file in nfo_files:
                    nfo_path = os.path.join(watcher_path, nfo_file)
                    try:
                        os.remove(nfo_path)
                        custom_console.bot_log(
                            f"[Watcher] Deleted orphaned NFO file at root: {nfo_path}"
                        )
                    except Exception as e:
                        custom_console.bot_warning_log(
                            f"[Watcher] Failed to delete orphaned NFO '{nfo_path}': {e}"
                        )
        
        except Exception as e:
            custom_console.bot_warning_log(f"[Watcher] Error cleaning up orphaned NFO files: {e}")

    def ftp(self)-> None:
        """
        Connects to a remote FTP server and interacts with files.

        This method handles FTP connection, navigation, and file download from the remote server
        """
        custom_console.bot_question_log("\nConnecting to the remote FTP...\n")

        # FTP service
        ftp_client = Client()
        custom_console.bot_question_log(f"Connected to {ftp_client.sys_info()}\n\n")

        menu = Menu()

        page = ftp_client.home_page()
        menu.show(table=page)

        while True:
            user_option = ftp_client.user_input()
            page = ftp_client.input_manager(user_option)
            if page == 0:
                ftp_client.quit()
                break
            if not page:
                continue

            # Display selected folder or file
            if isinstance(page, FTPDirectory):
                ftp_directory_name = page.name
                if page.type == "Folder":
                    page = ftp_client.change_path(selected_folder=ftp_directory_name)
                    menu.show(table=page)
                else:
                    ftp_client.select_file(one_file_selected=page)
                continue

            # Show page as table
            menu.show(table=page)

        if ftp_client.download_to_local_path:
            self.path = os.path.dirname(ftp_client.download_to_local_path)
            self.mode = 'folder'
            # Upload -f process
            # Decompress .rar files if the flags are set
            extractor = Extractor(compressed_media__path=self.path)
            result = extractor.unrar()
            if result is False:
                custom_console.bot_error_log("Unrar Exit")
                exit(1)

            self.run()
        return None