# -*- coding: utf-8 -*-
import os
import bencode2
import argparse
import requests
import tempfile


from concurrent.futures import ThreadPoolExecutor

from common.torrent_clients import TransmissionClient, QbittorrentClient, RTorrentClient
from common.trackers.data import trackers_api_data
from common.bittorrent import BittorrentData
from common.utility import ManageTitles
from common import config_settings
from unit3dup.pvtTorrent import Mytorrent
from unit3dup.duplicate import Duplicate
from unit3dup.media import Media

from view import custom_console

class UserContent:
    """
    Manage user media Files
    """

    @staticmethod
    def tracker_key(tracker_data: dict, value)-> str | None:
        """
        read the string Key from tracker data dictionary
        Args:
            tracker_data: tracker data dictionary in trackers folder
            value: key of tracker data

        Returns: value of tracker key
        """

        for key, val in tracker_data.items():
            if val == value:
                return key
        return None

    @staticmethod
    def is_preferred_language(content: Media) -> bool:
        """
           Compare preferred language with the audio language

           Args:
               content (Contents): The content object media

           Returns:
               return boolean
           """
        preferred_lang = config_settings.user_preferences.PREFERRED_LANG.upper()
        preferred_lang_to_iso = ManageTitles.convert_iso(preferred_lang)

        if not content.audio_languages:
            return True

        if preferred_lang == 'ALL':
            return True

        # If an audio lang exists in the preferred list
        if any(item in content.audio_languages for item in preferred_lang_to_iso):
            return True


        custom_console.bot_log(f"'{content.file_name}'")
        custom_console.bot_warning_log(
            "[UserContent] ** Your preferred lang is not in your media being uploaded, skipping ! **\n"
        )
        custom_console.rule()
        return False



    @staticmethod
    def torrent_announces(torrent_path: str, tracker_name_list: list,selected_tracker: str) -> bool:
        """ Add announces to a torrent file"""

        if not tracker_name_list:
           tracker_name_list = [selected_tracker]
        custom_console.bot_log(f"UPLOAD TO {tracker_name_list}")

        # // Read the existing torrent file
        with open(torrent_path, 'rb') as f:
            # It decodes it
            torrent_data = bencode2.bdecode(f.read())

        announce_list_encoded = []
        # a single tracker in the tracker_list corresponds to the '-tracker' flag from the user's CLI
        for tracker in tracker_name_list:
            # Get data for each tracker
            api_data = trackers_api_data[tracker.upper()]
            # Add to the list and encode it
            announce_list_encoded.append([api_data['announce'].encode()])

        create_torrent = False
        if b'announce-list' in torrent_data:
            if torrent_data[b'announce-list'] != announce_list_encoded:
                create_torrent = True


        if b'announce' in torrent_data:
            if torrent_data[b'announce'] != announce_list_encoded[0][0]:
                create_torrent = True

        return create_torrent

    @staticmethod
    def torrent(content: Media, tracker_name_list: list, selected_tracker: str, this_path: str) -> Mytorrent | None:
        """
        Check if a torrent file for the given content already exists

        Args:
            trackers:
            content:
            path: The torrent's path
            tracker_name_list: the trackers name
            selected_tracker: current tracker for the upload process (default tracker or -tracker )

        Returns:
            bool: True if the torrent file exists otherwise False
        """

        if os.path.exists(this_path):
            custom_console.bot_warning_log(f"\n<> Reusing the existing torrent file..'{content.torrent_path}'\n")

            # Compare the exists announces and return True if it's/they are different from the request -tracker flags
            different = UserContent.torrent_announces(torrent_path=this_path,
                                          tracker_name_list=tracker_name_list,
                                          selected_tracker=selected_tracker)
            # False if we need Update the torrent file
            if different:
                my_torrent = Mytorrent(contents=content, meta=content.metainfo, trackers_list=tracker_name_list)
                my_torrent.hash()
                return my_torrent if my_torrent.write(overwrite=True, full_path=this_path) else None
        else:
            # Crea a new torrent file
            my_torrent = Mytorrent(contents=content, meta=content.metainfo, trackers_list=tracker_name_list)
            my_torrent.hash()
            return my_torrent if my_torrent.write(overwrite=False, full_path=this_path) else None

        # if it exists but no update is needed
        return None

    @staticmethod
    def check_duplicate(content: Media, tracker_name: str,  cli: argparse.Namespace) -> dict | None:
        """
           Search for a duplicate. Delta = config.SIZE_TH

           Args:
               cli: cli flags from the user
               content (Contents): The content object media
               tracker_name: The name of the tracker
           Returns:
               match data dict (id, name, size, resolution, info_hash, ...) when a
               duplicate is detected and the user chose to skip; None otherwise.
        """
        duplicate = Duplicate(content=content, tracker_name=tracker_name, cli=cli)
        if duplicate.process():
            custom_console.bot_error_log(
                f"\n*** User chose to skip '{content.display_name}' ***\n"
            )
            custom_console.rule()
            return duplicate.match_data or {}
        return None

    @staticmethod
    def can_ressed(content: Media, tracker_name: str,  cli: argparse.Namespace, tmdb_id :int) -> list[requests.Response]:
        """
           Search for a duplicate and compare with the user content. Delta = config.SIZE_TH

           Args:
               tmdb_id: user content tmdb ID
               cli: cli flags from the user
               content (Contents): The content object media
               tracker_name: The name of the tracker
           Returns:
               list of requests ( torrents)
        """
        duplicate = Duplicate(content=content, tracker_name=tracker_name, cli=cli)
        return duplicate.process_dead_torrents(tmdb_id=tmdb_id)



    @staticmethod
    def send_to_bittorrent_worker(bittorrent_file: BittorrentData, client: QbittorrentClient | TransmissionClient):
        """
        worker: This function will handle sending a single torrent to torrent clients

        Args:
            bittorrent_file: The object containing the torrent and other necessary info
            client: qbittorrent client | transmission_rpc
        """
        try:
            # Check if we have a valid response from the tracker
            if bittorrent_file.tracker_response:
                if client:
                    # Télécharger le torrent depuis le tracker
                    downloaded_torrent_path = None
                    try:
                        # Créer un fichier temporaire pour le torrent téléchargé
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.torrent') as tmp_file:
                            downloaded_torrent_path = tmp_file.name
                        
                        # Télécharger le torrent depuis le tracker
                        if UserContent.download_file(bittorrent_file.tracker_response, downloaded_torrent_path):
                            custom_console.bot_log(
                                f"[Torrent] Downloaded torrent from tracker: {bittorrent_file.tracker_response}"
                            )
                            # Utiliser le torrent téléchargé au lieu du fichier local
                            archive_path_to_use = downloaded_torrent_path
                        else:
                            custom_console.bot_warning_log(
                                f"[Torrent] Failed to download torrent from tracker, using local file"
                            )
                            # Fallback sur le fichier local si le téléchargement échoue
                            archive_path_to_use = bittorrent_file.archive_path
                    except Exception as e:
                        custom_console.bot_warning_log(
                            f"[Torrent] Error downloading torrent from tracker: {e}, using local file"
                        )
                        # Fallback sur le fichier local en cas d'erreur
                        archive_path_to_use = bittorrent_file.archive_path
                    
                    client.send_to_client(
                        tracker_data_response=bittorrent_file.tracker_response,
                        torrent=bittorrent_file.torrent_response,
                        content=bittorrent_file.content,
                        archive_path=archive_path_to_use,
                        category=bittorrent_file.qbit_category,
                    )
                    
                    # Nettoyer le fichier temporaire après utilisation
                    if downloaded_torrent_path and os.path.exists(downloaded_torrent_path):
                        try:
                            os.remove(downloaded_torrent_path)
                        except Exception as e:
                            custom_console.bot_warning_log(
                                f"[Torrent] Failed to remove temporary torrent file: {e}"
                            )
            else:
                # invalid response
                custom_console.rule()

        except Exception as e:
            custom_console.bot_error_log(f"Error sending torrent {bittorrent_file.content.file_name}: {str(e)}")


    @staticmethod
    def get_client() -> QbittorrentClient | TransmissionClient:

        client = QbittorrentClient()

        if config_settings.torrent_client_config.TORRENT_CLIENT.lower()=='qbittorrent':
            client = QbittorrentClient()
            client.connect()

        elif config_settings.torrent_client_config.TORRENT_CLIENT.lower()=='transmission':
            client = TransmissionClient()
            client.connect()

        elif config_settings.torrent_client_config.TORRENT_CLIENT.lower()=='rtorrent':
            client = RTorrentClient()
            client.connect()
        else:
            custom_console.bot_error_log(f"{UserContent.__class__.__name__} - "
                                         f" Invalid torrent client '{config_settings.torrent_client_config.TORRENT_CLIENT}'" )
            exit(1)

        return client

    @staticmethod
    def send_to_bittorrent(bittorrent_list: list[BittorrentData], message: str, cli: argparse.Namespace = None) -> None:
        """
        Sends a list of torrents to Bittorrent using threads

        Args:
            bittorrent_list (list[Bittorrent]): A list of Bittorrent objects to be sent to the client
            message: printed message
            cli: command line arguments (optional, for watcher mode)
        """

        if not bittorrent_list:
            return None

        custom_console.bot_warning_log(f"\nSending {message} torrents to the "
                                       f"{config_settings.torrent_client_config.TORRENT_CLIENT.upper()} client "
                                       f"... Please wait")

        client = UserContent.get_client()

        with ThreadPoolExecutor(max_workers=20) as executor:
            # Submit the torrents
            futures = [executor.submit(UserContent.send_to_bittorrent_worker, bittor, client)
                       for bittor in bittorrent_list]
            # Wait for all threads to complete
            for future in futures:
                future.result()
        
        # Si on est en mode watcher et que c'est qBittorrent, modifier les chemins de destination
        if cli and cli.watcher and config_settings.torrent_client_config.TORRENT_CLIENT.lower() == 'qbittorrent':
            UserContent._update_qbittorrent_paths_for_watcher(bittorrent_list, client)

    @staticmethod
    def _update_qbittorrent_paths_for_watcher(bittorrent_list: list[BittorrentData], client: QbittorrentClient) -> None:
        """
        Met à jour les chemins de destination dans qBittorrent pour les torrents uploadés via le watcher.
        Cherche les torrents par nom de dossier et modifie leur savepath vers /storage/Upload_Auto/Deja_Upload
        """
        if not client or not client.client:
            return
        
        import time
        
        new_savepath = "/storage/Upload_Auto/Deja_Upload"
        
        # Attendre un peu pour que les torrents soient bien ajoutés dans qBittorrent
        time.sleep(2)
        
        # Grouper par nom de dossier (torrent_name) pour éviter les doublons
        processed_folders = set()
        
        for bittorrent_file in bittorrent_list:
            if not bittorrent_file.content or not bittorrent_file.content.torrent_name:
                continue
            
            folder_name = bittorrent_file.content.torrent_name
            if folder_name in processed_folders:
                continue
            
            processed_folders.add(folder_name)
            
            try:
                # Récupérer tous les torrents de qBittorrent
                all_torrents = client.client.torrents()
                
                # Chercher les torrents qui correspondent au nom du dossier
                # Normalement on devrait en trouver 2 : un pour Gemini et un autre du tracker source
                matching_torrents = []
                for torrent in all_torrents:
                    torrent_name = torrent.get('name', '')
                    # Le nom du torrent dans qBittorrent correspond généralement au nom du dossier
                    # Vérifier si le nom du torrent commence par le nom du dossier ou est exactement le même
                    if torrent_name == folder_name or torrent_name.startswith(folder_name + '.'):
                        matching_torrents.append(torrent)
                
                # Modifier le savepath pour chaque torrent trouvé
                if matching_torrents:
                    custom_console.bot_log(
                        f"[Watcher] Found {len(matching_torrents)} torrent(s) for folder '{folder_name}'"
                    )
                    for torrent in matching_torrents:
                        torrent_hash = torrent.get('hash', '')
                        torrent_name = torrent.get('name', 'unknown')
                        if torrent_hash:
                            try:
                                # Utiliser l'API qBittorrent pour changer le savepath
                                client.client._post(
                                    "torrents/setLocation",
                                    data={
                                        "hashes": torrent_hash,
                                        "location": new_savepath
                                    }
                                )
                                custom_console.bot_log(
                                    f"[Watcher] Updated qBittorrent savepath for '{torrent_name}' "
                                    f"-> {new_savepath}"
                                )
                            except Exception as e:
                                custom_console.bot_warning_log(
                                    f"[Watcher] Failed to update savepath for '{torrent_name}': {e}"
                                )
                else:
                    custom_console.bot_warning_log(
                        f"[Watcher] No matching torrents found for folder '{folder_name}'"
                    )
                
            except Exception as e:
                custom_console.bot_warning_log(
                    f"[Watcher] Error updating qBittorrent paths for '{folder_name}': {e}"
                )

    @staticmethod
    def download_file(url: str, destination_path: str) -> bool:
        download = requests.get(url)
        if download.status_code == 200:
            # File archived
            with open(destination_path, "wb") as file:
                file.write(download.content)
            return True
        return False
