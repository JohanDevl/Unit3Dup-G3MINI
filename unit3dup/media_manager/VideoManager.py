# -*- coding: utf-8 -*-
import argparse
import os

from common.external_services.theMovieDB.core.api import DbOnline
from common.bittorrent import BittorrentData
from common.utility import ManageTitles, System

from unit3dup.media_manager.common import UserContent
from unit3dup.upload import UploadBot
from unit3dup import config_settings
from unit3dup.pvtVideo import Video
from unit3dup.media import Media
from unit3dup.prepared_item import PreparedItem

from view import custom_console

class VideoManager:

    def __init__(self, contents: list[Media], cli: argparse.Namespace, qbit_category: str | None = None):
        """
        Initialize the VideoManager with the given contents

        Args:
            contents (list): List of content media objects
            cli (argparse.Namespace): user flag Command line
            qbit_category (str | None): qBittorrent category to assign to uploaded torrents
        """

        self.torrent_found:bool = False
        self.contents: list[Media] = contents
        self.cli: argparse = cli
        self.qbit_category = qbit_category
        self.validation_reports: dict[str, list[dict]] = {}

    def prepare(self, selected_tracker: str, tracker_name_list: list, tracker_archive: str) -> tuple[list[PreparedItem], list[dict]]:
        """
        Prepare video contents without uploading. Returns PreparedItem objects and skip reasons.

        Returns:
            tuple: (list of PreparedItem objects, list of skip reasons dicts)
        """

        # -multi : no announce_list . One announce for multi tracker
        if self.cli.mt:
            tracker_name_list = [selected_tracker.upper()]

        # Init the lists
        prepared_items = []
        skip_reasons = []

        for content in self.contents:
            # get the archive path
            archive = os.path.join(tracker_archive, selected_tracker)
            os.makedirs(archive, exist_ok=True)
            torrent_filepath = os.path.join(tracker_archive, selected_tracker, f"{content.torrent_name}.torrent")

            # Filter contents based on existing torrents or duplicates
            if UserContent.is_preferred_language(content=content):

                if self.cli.watcher and not self.cli.noup:
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

                # Skip(S) if it is a duplicate or let the user choose to continue (C)
                if ((self.cli.duplicate or config_settings.user_preferences.DUPLICATE_ON)
                        and UserContent.is_duplicate(content=content, tracker_name=selected_tracker,
                                                     cli=self.cli)):
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

                # Search for VIDEO ID
                db_online = DbOnline(media=content, category=content.category, no_title=self.cli.notitle)
                db = db_online.media_result

                # If it is 'None' we skipped the imdb search (-notitle)
                if not db:
                    skip_reasons.append({"torrent_name": content.torrent_name, "reason": "no_tmdb_result",
                                         "source": content.source or ""})
                    prepared_items.append(PreparedItem(
                        content=content,
                        source_path=content.torrent_path or content.file_name or "",
                        source_type="folder" if os.path.isdir(content.torrent_path or "") else "file",
                        display_name=content.display_name,
                        content_category=content.category,
                        qbit_category=self.qbit_category,
                        source_tag=content.source or "",
                        skip_reason="no_tmdb_result",
                    ))
                    continue

                # Override category for animated content based on TMDB genre
                if db.is_animation():
                    if content.category == System.category_list[System.MOVIE]:
                        content.category = System.category_list[System.ANIMATION]
                        custom_console.bot_log("Category → 'animation' (TMDB genre)")
                    elif content.category == System.category_list[System.TV_SHOW]:
                        content.category = System.category_list[System.TV_ANIMATION]
                        custom_console.bot_log("Category → 'tv_animation' (TMDB genre)")

                # Update display name with Serie Title when requested by the user (-notitle)
                if self.cli.notitle:
                    # Add generated metadata to the display_title
                    if self.cli.gentitle:
                        content.display_name = (f"{db_online.media_result.result.get_title()} "
                                                f"{db_online.media_result.year} ")
                        content.display_name += " " + content.generate_title
                    else:
                        # otherwise keep the old meta_data and add the new display_title to it
                        print()
                        content.display_name = (f"{db_online.media_result.result.get_title()}"
                                                f" {db_online.media_result.year} {content.guess_title}")

                # Get meta from the media video
                video_info = Video(media=content, tmdb_id=db.video_id, trailer_key=db.trailer_key)
                video_info.build_info()
                # print the title will be shown on the torrent page
                custom_console.bot_log(f"'DISPLAYNAME'...{{{content.display_name}}}\n")

                # Tracker instance
                unit3d_up = UploadBot(content=content, tracker_name=selected_tracker, cli=self.cli)

                # Get the data
                unit3d_up.data(show_id=db.video_id, imdb_id=db.imdb_id, show_keywords_list=db.keywords_list,
                               video_info=video_info)

                # ── Exclusion par tag d'équipe ────────────────────────────────
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

                # ── Validation des règles tracker ─────────────────────────────
                val_results = None
                runner = None
                if not getattr(self.cli, 'skip_validation', False):
                    from unit3dup.validators import ValidationRunner, create_default_validators
                    runner = ValidationRunner(create_default_validators())
                    val_results = runner.validate(
                        media=content,
                        mediafile=getattr(content, 'mediafile', None),
                        release_name=unit3d_up.tracker.data.get("name", ""),
                        mediainfo_text=content.mediafile.info if getattr(content, 'mediafile', None) else None,
                    )
                    if val_results:
                        runner.print_report(custom_console)
                        # Store warnings/infos even if there are errors (web UI will show them)
                        self.validation_reports[release_name_check] = runner.to_dicts()

                # ── Create PreparedItem ──────────────────────────────────────────
                source_type = "folder" if os.path.isdir(content.torrent_path) else "file"

                prepared_item = PreparedItem(
                    content=content,
                    source_path=content.torrent_path or content.file_name,
                    source_type=source_type,
                    torrent_response=torrent_response,
                    torrent_filepath=torrent_filepath,
                    tracker_data=dict(unit3d_up.tracker.data),  # Make a copy!
                    tracker_name=selected_tracker,
                    trackers_list=tracker_name_list,
                    release_name=unit3d_up.tracker.data.get("name", content.display_name),
                    display_name=content.display_name,
                    source_tag=content.source or "",
                    resolution=content.screen_size or content.resolution or "",
                    content_category=content.category,
                    qbit_category=self.qbit_category,
                    description=video_info.description,
                    mediainfo=video_info.mediainfo,
                    nfo_content=None,
                    tmdb_id=db.video_id if db else 0,
                    imdb_id=db.imdb_id if db else 0,
                    tmdb_title=db.result.get_title() if db and db.result else None,
                    tmdb_year=db.year if db else None,
                    validation_report=runner.to_dicts() if val_results else [],
                    has_errors=runner.has_errors() if val_results else False,
                    has_warnings=bool(val_results) and not runner.has_errors() if val_results else False,
                )

                prepared_items.append(prepared_item)

        # // end content
        return prepared_items, skip_reasons

    @staticmethod
    def upload_item(prepared: PreparedItem, cli: argparse.Namespace) -> BittorrentData | None:
        """
        Execute the upload for a PreparedItem.

        Args:
            prepared: PreparedItem containing all prepared data
            cli: Command line arguments

        Returns:
            BittorrentData object or None if upload failed
        """

        # Reconstruct UploadBot with the tracker data from prepared
        unit3d_up = UploadBot(content=prepared.content, tracker_name=prepared.tracker_name, cli=cli)
        # Restore the tracker payload
        unit3d_up.tracker.data = prepared.tracker_data

        # ── Search / generate NFO ────────────────────────────
        nfo_path = None
        nfo_generated = False

        media_file_path = prepared.content.file_name if prepared.content.file_name else prepared.content.torrent_path

        if media_file_path:
            media_file_path = os.path.abspath(media_file_path)

            if os.path.isdir(media_file_path):
                # Cas d'un dossier (release pack)
                media_dir = media_file_path

                # Chercher un fichier .nfo dans le dossier (n'importe quel .nfo)
                nfo_files = [f for f in os.listdir(media_dir) if f.lower().endswith('.nfo')]

                if nfo_files:
                    # Utiliser le premier .nfo trouvé dans le dossier
                    nfo_path = os.path.join(media_dir, nfo_files[0])
                    custom_console.bot_log(f"[NFO] Fichier NFO existant trouvé et utilisé: {nfo_path}")
                    # nfo_generated reste False → on ne supprimera pas ce fichier
                else:
                    # Aucun NFO trouvé → en générer un temporaire
                    nfo_filename = f"{prepared.content.torrent_name}.nfo"
                    nfo_path = os.path.join(media_dir, nfo_filename)
                    custom_console.bot_log(f"[NFO] Aucun NFO trouvé, génération du fichier NFO temporaire: {nfo_path}")
                    from common.mediainfo import MediaFile
                    try:
                        # Chercher le premier fichier vidéo dans le dossier
                        video_files = [f for f in os.listdir(media_dir)
                                     if ManageTitles.filter_ext(f)]
                        if video_files:
                            video_file_path = os.path.join(media_dir, video_files[0])
                            media_file = MediaFile(video_file_path)
                            if Video.generate_nfo_file(media_file, nfo_path):
                                custom_console.bot_log(f"[NFO] Fichier NFO temporaire généré avec succès")
                                nfo_generated = True  # Marquer comme temporaire → à supprimer après
                            else:
                                custom_console.bot_warning_log(f"[NFO] Échec de la génération du NFO")
                                nfo_path = None
                        else:
                            custom_console.bot_warning_log(f"[NFO] Aucun fichier vidéo trouvé dans le dossier pour générer le NFO")
                            nfo_path = None
                    except Exception as e:
                        custom_console.bot_warning_log(f"[NFO] Erreur lors de la génération du NFO: {e}")
                        nfo_path = None
            elif os.path.isfile(media_file_path):
                # Cas d'un fichier unique
                file_dir = os.path.dirname(media_file_path)
                file_base = os.path.splitext(os.path.basename(media_file_path))[0]
                nfo_candidate = os.path.join(file_dir, f"{file_base}.nfo")

                if os.path.isfile(nfo_candidate):
                    nfo_path = nfo_candidate
                    custom_console.bot_log(f"[NFO] Fichier NFO existant trouvé et utilisé: {nfo_path}")
                else:
                    # Générer un NFO temporaire
                    nfo_path = nfo_candidate
                    custom_console.bot_log(f"[NFO] Aucun NFO trouvé, génération du fichier NFO temporaire: {nfo_path}")
                    from common.mediainfo import MediaFile
                    try:
                        media_file = MediaFile(media_file_path)
                        if Video.generate_nfo_file(media_file, nfo_path):
                            custom_console.bot_log(f"[NFO] Fichier NFO temporaire généré avec succès")
                            nfo_generated = True
                        else:
                            custom_console.bot_warning_log(f"[NFO] Échec de la génération du NFO")
                            nfo_path = None
                    except Exception as e:
                        custom_console.bot_warning_log(f"[NFO] Erreur lors de la génération du NFO: {e}")
                        nfo_path = None
            else:
                custom_console.bot_warning_log(f"[NFO] Chemin média invalide (ni fichier ni dossier): {media_file_path}")

        # Send to the tracker
        # Vérifier que le NFO existe avant l'envoi
        if nfo_path:
            if os.path.isfile(nfo_path):
                custom_console.bot_log(f"[NFO] Envoi du fichier NFO au tracker: {nfo_path}")
            else:
                custom_console.bot_warning_log(f"[NFO] Fichier NFO introuvable avant l'envoi: {nfo_path}")
                nfo_path = None
        else:
            custom_console.bot_warning_log(f"[NFO] Aucun fichier NFO à envoyer")

        tracker_response, tracker_message = unit3d_up.send(torrent_archive=prepared.torrent_filepath, nfo_path=nfo_path)

        # Supprimer UNIQUEMENT le NFO temporaire généré par le script (ne pas supprimer les .nfo existants)
        if nfo_generated and nfo_path and os.path.isfile(nfo_path):
            try:
                os.remove(nfo_path)
                custom_console.bot_log(f"[NFO] Fichier NFO temporaire supprimé: {nfo_path}")
            except Exception as e:
                custom_console.bot_warning_log(f"[NFO] Impossible de supprimer le NFO temporaire: {e}")

        # Store response for the torrent clients
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
           Process the video contents to filter duplicates and create torrents

           Returns:
               tuple: (list of Bittorrent objects, list of skip reasons dicts)
        """

        # Call prepare() to get all prepared items and skip reasons
        prepared_items, skip_reasons = self.prepare(selected_tracker, tracker_name_list, tracker_archive)

        # Init the torrent list
        bittorrent_list = []

        for prepared in prepared_items:
            # ── Handle validation errors ─────────────────────────────
            if prepared.has_errors:
                custom_console.bot_error_log("Validation errors found. Skipping upload. Use -skipval to bypass.")
                skip_reasons.append({"torrent_name": prepared.content.torrent_name, "reason": "validation_error",
                                     "validation_report": prepared.validation_report,
                                     "source": prepared.source_tag})
                continue

            # ── Confirmation interactive (-confirm) ───────────────────────
            if getattr(self.cli, 'confirm', False):
                custom_console.rule("[bold cyan]Validation release[/bold cyan]")
                custom_console.bot_log(f"  Fichier      : {prepared.display_name}")
                if prepared.tmdb_id:
                    custom_console.bot_log(f"  TMDB         : {prepared.tmdb_id}")
                if prepared.imdb_id:
                    custom_console.bot_log(f"  IMDb         : tt{prepared.imdb_id:07d}")
                custom_console.bot_question_log(
                    f"\n  Release name : {prepared.release_name}\n\n"
                    f"  Confirmer l'upload ? [o/N] : "
                )
                try:
                    answer = input().strip().lower()
                except EOFError:
                    custom_console.bot_warning_log("No interactive input available, skipping confirmation")
                    continue
                except KeyboardInterrupt:
                    custom_console.bot_error_log("\nOpération annulée par l'utilisateur.")
                    break
                if answer not in ("o", "oui", "y", "yes"):
                    custom_console.bot_warning_log(f"  ✗ Upload annulé → {prepared.release_name}\n")
                    custom_console.rule()
                    continue
                custom_console.bot_log(f"  ✓ Upload confirmé → {prepared.release_name}\n")
                custom_console.rule()

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
                continue

            # Upload the item
            bittorrent_data = self.upload_item(prepared, self.cli)
            if bittorrent_data:
                bittorrent_list.append(bittorrent_data)

        # // end content
        return bittorrent_list, skip_reasons
