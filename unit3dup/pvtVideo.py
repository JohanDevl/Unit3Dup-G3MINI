# -*- coding: utf-8 -*-
import hashlib
import os.path
import re

import diskcache

from common.mediainfo import MediaFile

from view import custom_console
from unit3dup import config_settings
from unit3dup.media import Media


class Video:
    """ Build a description for the torrent page: technical information only """

    def __init__(self, media: Media,  tmdb_id: int, trailer_key=None):
        self.file_name: str = media.file_name
        self.display_name: str = media.display_name
        self.torrent_name: str = media.torrent_name

        self.tmdb_id: int = tmdb_id
        self.trailer_key: int = trailer_key
        self.cache = diskcache.Cache(str(config_settings.user_preferences.CACHE_PATH))

        # Create a cache key for tmdb_id
        self.key = f"{self.tmdb_id}.{self.display_name}"
        self.cache_key = self.hash_key(self.key)

        # Init
        self.is_hd: int = 0
        self.description: str = ''
        self.mediainfo: str = ''

    @staticmethod
    def hash_key(key: str) -> str:
        """ Generate a hashkey for the cache index """
        return hashlib.md5(key.encode('utf-8')).hexdigest()

    @staticmethod
    def extract_quality_from_title(title: str) -> str:
        """Extrait la qualité (WEBRip, BluRay, etc.) depuis le titre"""
        title_upper = title.upper()
        
        patterns = [
            (r'\bREMUX\b', 'REMUX'),
            (r'\bWEB-DL\b', 'WEB-DL'),
            (r'\bWEBRIP\b', 'WEBRip'),
            (r'\bWEB\b', 'WEB-DL'),
            (r'\bBLURAY\b', 'BluRay'),
            (r'\bBDRIP\b', 'BDRip'),
            (r'\bDVDRIP\b', 'DVDRip'),
            (r'\bHDTV\b', 'HDTV'),
            (r'\bPDTV\b', 'PDTV'),
        ]
        
        for pattern, quality in patterns:
            if re.search(pattern, title_upper):
                return quality
        
        return ""

    @staticmethod
    def extract_resolution_from_title(title: str) -> str:
        """Extrait la résolution depuis le titre"""
        resolution_match = re.search(r'\b(\d{3,4})[pP]\b', title)
        if resolution_match:
            return resolution_match.group(1) + "p"
        return ""

    @staticmethod
    def extract_codec_from_title(title: str) -> str:
        """Extrait le codec (x265, x264, etc.) depuis le titre"""
        title_upper = title.upper()
        
        # Cherche x265, h265, h.265
        if re.search(r'\b(X265|H265|H\.265)\b', title_upper):
            return "x265"
        # Cherche x264, h264, h.264
        if re.search(r'\b(X264|H264|H\.264)\b', title_upper):
            return "x264"
        
        return ""

    @staticmethod
    def map_codec_id(codec: str, codec_id: str) -> str:
        """Mappe le codec_id vers une version plus lisible"""
        codec_upper = codec.upper()
        codec_id_upper = codec_id.upper()
        
        # Mapping pour HEVC
        if "HEVC" in codec_upper or "HEVC" in codec_id_upper:
            return "x265"
        
        # Mapping pour AVC/H.264
        if "AVC" in codec_upper or "H264" in codec_upper or "H.264" in codec_upper:
            return "x264"
        
        # Si le codec_id contient des slashes, on prend juste le dernier élément
        if "/" in codec_id:
            parts = codec_id.split("/")
            # Cherche un élément qui ressemble à un codec (x265, x264, etc.)
            for part in reversed(parts):
                part_upper = part.upper()
                if "X265" in part_upper or "H265" in part_upper:
                    return "x265"
                if "X264" in part_upper or "H264" in part_upper:
                    return "x264"
        
        return ""

    @staticmethod
    def find_nfo_file(media_file_path: str) -> str | None:
        """Cherche un fichier NFO dans le même répertoire que le fichier média"""
        if not media_file_path:
            return None
        
        media_dir = os.path.dirname(media_file_path)
        if not os.path.isdir(media_dir):
            return None
        
        # Cherche un fichier .nfo dans le même répertoire
        for file in os.listdir(media_dir):
            if file.lower().endswith('.nfo'):
                nfo_path = os.path.join(media_dir, file)
                if os.path.isfile(nfo_path):
                    return nfo_path
        
        return None

    @staticmethod
    def generate_nfo_file(media_info: MediaFile, output_path: str) -> bool:
        """Génère un fichier NFO avec la sortie brute de Mediainfo"""
        try:
            # Utiliser la sortie brute de Mediainfo (comme video_info.mediainfo)
            mediainfo_output = media_info.info
            
            # Remplacer le chemin complet par juste le nom du fichier dans "Complete name"
            # Pattern pour trouver "Complete name" suivi du chemin complet
            pattern = r'(Complete name\s+:\s+)(.+[/\\])([^/\\]+\.\w+)'
            
            def replace_path(match):
                # Remplacer par juste le nom du fichier
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

    @staticmethod
    def parse_nfo_for_tech_info(nfo_content: str) -> dict:
        """Parse le contenu d'un NFO pour extraire les informations techniques"""
        nfo_tech_info = {
            "format": "",
            "codec_video": "",
            "audio_tracks": [],
            "subtitle_tracks": []
        }
        
        # Patterns pour extraire le format
        format_patterns = [
            r"Format\s*[:=]\s*([^\n]+)",
            r"Container\s*[:=]\s*([^\n]+)",
            r"File\s+extension\s*[:=]\s*([^\n]+)",
        ]
        for pattern in format_patterns:
            match = re.search(pattern, nfo_content, re.IGNORECASE)
            if match:
                nfo_tech_info["format"] = match.group(1).strip().upper()
                break
        
        # Patterns pour extraire le codec vidéo
        codec_patterns = [
            r"Codec\s+Vid[ée]o\s*[:=]\s*([^\n]+)",
            r"Video\s+Codec\s*[:=]\s*([^\n]+)",
            r"Video\s+Format\s*[:=]\s*([^\n]+)",
        ]
        for pattern in codec_patterns:
            match = re.search(pattern, nfo_content, re.IGNORECASE)
            if match:
                codec_str = match.group(1).strip()
                # Essayer d'extraire x265, x264, etc.
                if re.search(r'\b(x265|h265|h\.265)\b', codec_str, re.IGNORECASE):
                    nfo_tech_info["codec_video"] = "x265"
                elif re.search(r'\b(x264|h264|h\.264)\b', codec_str, re.IGNORECASE):
                    nfo_tech_info["codec_video"] = "x264"
                else:
                    nfo_tech_info["codec_video"] = codec_str
                break
        
        # Patterns pour extraire les pistes audio (format simplifié)
        # Cherche des lignes avec langue, canaux, codec, bitrate
        audio_patterns = [
            r"([A-Za-z]+(?:\s*\([^)]+\))?)\s*\[([\d.]+)\]\s*\|\s*([^\n]+)",
            r"Audio\s+(\d+)\s*[:=]\s*([^\n]+)",
        ]
        for pattern in audio_patterns:
            matches = re.finditer(pattern, nfo_content, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 3:
                    lang = match.group(1).strip()
                    channels = match.group(2).strip()
                    codec_info = match.group(3).strip()
                    nfo_tech_info["audio_tracks"].append(f"{lang} [{channels}] | {codec_info}")
        
        # Patterns pour extraire les sous-titres
        subtitle_patterns = [
            r"([A-Za-z]+(?:\s*\([^)]+\))?)\s*\|\s*Text/([^\n]+)\s*\(([^)]+)\)",
            r"Subtitle\s+(\d+)\s*[:=]\s*([^\n]+)",
        ]
        for pattern in subtitle_patterns:
            matches = re.finditer(pattern, nfo_content, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 3:
                    lang = match.group(1).strip()
                    format_sub = match.group(2).strip()
                    forced = match.group(3).strip()
                    forced_str = "Forcés" if "forced" in forced.lower() or "forcé" in forced.lower() else "Complets"
                    nfo_tech_info["subtitle_tracks"].append(f"{lang} | Text/{format_sub} ({forced_str})")
        
        return nfo_tech_info

    @staticmethod
    def format_audio_track(audio_track: dict) -> str:
        """Formate une piste audio selon le format demandé"""
        language = audio_track.get("language", "")
        channels = audio_track.get("channels", "")
        format_name = audio_track.get("format", "")
        codec_id = audio_track.get("codec_id", "")
        bit_rate = audio_track.get("bit_rate", "")
        
        lang_map = {
            "fr": "Français (VFF)",
            "en": "Anglais (VO)",
            "es": "Espagnol",
            "de": "Allemand",
            "it": "Italien",
        }
        
        lang_display = lang_map.get(language.lower(), language.upper())
        
        channels_str = ""
        if channels:
            try:
                ch = int(channels)
                if ch == 1:
                    channels_str = "[Mono]"
                elif ch == 2:
                    channels_str = "[Stereo]"
                elif ch == 6:
                    channels_str = "[5.1]"
                elif ch == 8:
                    channels_str = "[7.1]"
                else:
                    channels_str = f"[{ch} channels]"
            except (ValueError, TypeError):
                channels_str = f"[{channels}]"
        
        codec_str = format_name
        if codec_id and codec_id != format_name:
            codec_str = f"{format_name} / {codec_id}"
        
        bitrate_str = ""
        if bit_rate:
            try:
                br = int(bit_rate)
                if br >= 1000:
                    bitrate_str = f" à {br / 1000:.0f} kb/s"
                else:
                    bitrate_str = f" à {br} b/s"
            except (ValueError, TypeError):
                pass
        
        return f"{lang_display} {channels_str} | {codec_str}{bitrate_str}"

    @staticmethod
    def format_subtitle_track(subtitle_track: dict) -> str:
        """Formate une piste de sous-titre selon le format demandé"""
        language = subtitle_track.get("language", "")
        format_name = subtitle_track.get("format", "")
        
        lang_map = {
            "fr": "Français (VFF)",
            "en": "Anglais (VO)",
            "es": "Espagnol",
            "de": "Allemand",
            "it": "Italien",
        }
        
        lang_display = lang_map.get(language.lower(), language.upper())
        
        title = subtitle_track.get("title", "").upper()
        forced = "Forcés" if "FORCED" in title or "FORCÉ" in title else "Complets"
        
        format_str = format_name if format_name else "Text"
        
        return f"{lang_display} | {format_str}/SRT ({forced})"

    def build_info(self):
        """Build the information to send to the tracker"""

        # media_info
        media_info = MediaFile(self.file_name)
        self.mediainfo = media_info.info

        if config_settings.user_preferences.CACHE_SCR:
            description = self.cache.get(self.cache_key)
            if description:
                custom_console.bot_warning_log(f"\n<> Using cached description for '{self.key}'")
                self.description = description.get('description', '')
                self.is_hd = description.get('is_hd', 0)

        if not self.description:
            # Generate new description with technical info only
            custom_console.bot_log(f"\n[GENERATING DESCRIPTION..]")
            
            # Chercher le NFO si disponible
            nfo_path = self.find_nfo_file(self.file_name)
            nfo_data = {}
            if nfo_path:
                try:
                    with open(nfo_path, 'r', encoding='utf-8', errors='ignore') as f:
                        nfo_content = f.read()
                    nfo_data = self.parse_nfo_for_tech_info(nfo_content)
                    custom_console.bot_log(f"[NFO] Fichier NFO trouvé: {nfo_path}")
                except Exception as e:
                    custom_console.bot_warning_log(f"[NFO] Erreur lors de la lecture du NFO: {e}")
            
            # 1. Qualité
            quality = ""
            source = self.extract_quality_from_title(self.torrent_name)
            resolution = self.extract_resolution_from_title(self.torrent_name)
            if source and resolution:
                quality = f"{source} {resolution}"
            elif resolution:
                quality = resolution
            elif source:
                height = media_info.video_height
                if height:
                    quality = f"{source} {height}p"
            else:
                height = media_info.video_height
                if height:
                    quality = f"{height}p"

            # 2. Format (priorité au NFO, sinon Mediainfo, sinon extension)
            format_name = ""
            if nfo_data.get("format"):
                format_name = nfo_data["format"]
            else:
                general_track = media_info.general_track
                if general_track:
                    format_name = general_track.get("format", "")
                if not format_name:
                    _, ext = os.path.splitext(self.file_name)
                    format_name = ext.upper().replace(".", "")

            # 3. Codec Vidéo
            codec_video = ""
            video_track = media_info.video_track
            if video_track and len(video_track) > 0:
                codec = video_track[0].get("format", "")
                codec_id = video_track[0].get("codec_id", "")
                if codec:
                    # Essaie d'extraire le codec depuis le titre de la release
                    codec_from_title = self.extract_codec_from_title(self.torrent_name)
                    
                    if codec_from_title:
                        # Utilise le codec extrait du titre
                        codec_video = f"{codec} / {codec_from_title}"
                    elif codec_id and codec_id != codec:
                        # Essaie de mapper le codec_id vers une version lisible
                        mapped_codec = self.map_codec_id(codec, codec_id)
                        if mapped_codec:
                            codec_video = f"{codec} / {mapped_codec}"
                        else:
                            codec_video = codec
                    else:
                        codec_video = codec

            # 4. Audio tracks (priorité au NFO, sinon Mediainfo)
            audio_lines = []
            if nfo_data.get("audio_tracks"):
                audio_lines = nfo_data["audio_tracks"]
            else:
                audio_tracks = media_info.audio_track
                for audio in audio_tracks:
                    audio_line = self.format_audio_track(audio)
                    audio_lines.append(audio_line)

            # 5. Subtitle tracks (priorité au NFO, sinon Mediainfo)
            subtitle_lines = []
            if nfo_data.get("subtitle_tracks"):
                subtitle_lines = nfo_data["subtitle_tracks"]
            else:
                subtitle_tracks = media_info.subtitle_track
                for sub in subtitle_tracks:
                    sub_line = self.format_subtitle_track(sub)
                    subtitle_lines.append(sub_line)

            # Build description
            self.description = f"""Qualité : {quality}
Format : {format_name}
Codec Vidéo : {codec_video}
"""
            
            if audio_lines:
                self.description += "\n"
                self.description += "\n".join(audio_lines)
            
            if audio_lines and subtitle_lines:
                self.description += "\n---------------------------\n"
            
            if subtitle_lines:
                self.description += "\n".join(subtitle_lines)
            
            # Determine HD status (for compatibility)
            height = media_info.video_height
            if height:
                try:
                    self.is_hd = 0 if int(height) >= 720 else 1
                except (ValueError, TypeError):
                    self.is_hd = 0

        # Caching
        if config_settings.user_preferences.CACHE_SCR:
            self.cache[self.cache_key] = {'tmdb_id': self.tmdb_id, 'description': self.description, 'is_hd': self.is_hd}