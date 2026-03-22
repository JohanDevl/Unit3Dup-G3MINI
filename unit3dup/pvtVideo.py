# -*- coding: utf-8 -*-
import hashlib
import re

from common.mediainfo import MediaFile
from unit3dup.prez import generate_prez

from view import custom_console
from unit3dup.media import Media


class Video:
    """ Build a description for the torrent page: prez BBCode, mediainfo, metadata """

    def __init__(self, media: Media,  tmdb_id: int, trailer_key=None):
        self.file_name: str = media.file_name
        self.display_name: str = media.display_name

        self.tmdb_id: int = tmdb_id
        self.trailer_key: int = trailer_key

        # Init
        self.is_hd: int = 0
        self.description: str = ''
        self.mediainfo: str = ''

    @staticmethod
    def hash_key(key: str) -> str:
        """ Generate a hashkey for the cache index """
        return hashlib.md5(key.encode('utf-8')).hexdigest()

    @staticmethod
    def generate_nfo_file(media_info: MediaFile, output_path: str) -> bool:
        """Génère un fichier NFO avec la sortie brute de Mediainfo.

        - Utilise `media_info.info` (texte brut de Mediainfo)
        - Remplace le chemin complet par juste le nom du fichier dans "Complete name"
        """
        try:
            mediainfo_output = media_info.info

            # Pattern pour trouver "Complete name" suivi du chemin complet
            pattern = r'(Complete name\s+:\s+)(.+[/\\])([^/\\]+\.\w+)'

            def replace_path(match: re.Match) -> str:
                # Garder seulement le nom de fichier
                return match.group(1) + match.group(3)

            # Appliquer le remplacement
            mediainfo_output = re.sub(pattern, replace_path, mediainfo_output)

            # Écrire le fichier NFO avec la sortie modifiée
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(mediainfo_output)

            return True
        except Exception as e:
            custom_console.bot_warning_log(f"[NFO] Erreur lors de la génération du NFO: {e}")
            return False

    def build_info(self):
        """Build the information to send to the tracker"""

        # media_info
        media_info = MediaFile(self.file_name)
        self.mediainfo = media_info.info

        # Generate prez BBCode description
        self.description = generate_prez(media_info)

        # Determine SD flag: 0 = HD (>=720p), 1 = SD
        try:
            height = int(media_info.video_height) if media_info.video_height else 0
        except (ValueError, TypeError):
            height = 0
        self.is_hd = 0 if height >= 720 else 1