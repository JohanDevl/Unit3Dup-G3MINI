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
        self.audio_tracks: list[dict] = []
        self.subtitle_tracks: list[dict] = []

    @staticmethod
    def hash_key(key: str) -> str:
        """ Generate a hashkey for the cache index """
        return hashlib.md5(key.encode('utf-8')).hexdigest()

    @staticmethod
    def _strip_mediainfo_path(mediainfo_text: str) -> str:
        """Replace the full file path with just the filename in the 'Complete name' field."""
        pattern = r'(Complete name\s+:\s+)(.+[/\\])([^/\\]+\.\w+)'
        return re.sub(pattern, lambda m: m.group(1) + m.group(3), mediainfo_text)

    @staticmethod
    def generate_nfo_file(media_info: MediaFile, output_path: str) -> bool:
        """Génère un fichier NFO avec la sortie brute de Mediainfo.

        - Utilise `media_info.info` (texte brut de Mediainfo)
        - Remplace le chemin complet par juste le nom du fichier dans "Complete name"
        """
        try:
            mediainfo_output = Video._strip_mediainfo_path(media_info.info)

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
        self.mediainfo = self._strip_mediainfo_path(media_info.info)
        self.audio_tracks = media_info.audio_track
        self.subtitle_tracks = media_info.subtitle_track

        # Generate prez BBCode description
        self.description = generate_prez(media_info)

        # Determine SD flag: 0 = HD (>=720p), 1 = SD
        try:
            height = int(media_info.video_height) if media_info.video_height else 0
        except (ValueError, TypeError):
            height = 0
        self.is_hd = 0 if height >= 720 else 1