# -*- coding: utf-8 -*-
import re
import os

from pymediainfo import MediaInfo
from common.utility import ManageTitles

class MediaFile:
    """
    Get attributes from mediainfo
    """
    def __init__(self, file_path: str):
        self.file_path = file_path

        self._video_info: list = []
        self._general_track: dict = {}
        self._audio_info: list = []

        try:
            self.media_info = MediaInfo.parse(self.file_path)
        except OSError as e:
            if os.name != 'nt':
                print(f"{e} Try to install: sudo apt-get install -y libmediainfo-dev")
            exit(1)


    @property
    def general_track(self)-> dict:
        """Returns general information"""
        if not self._general_track:
            for track in self.media_info.to_data().get("tracks", []):
                if track.get("track_type") == "General":
                    self._general_track = track
                    return self._general_track
            self._general_track = {}
        return self._general_track

    @property
    def video_track(self) -> list:
        """Returns video information"""
        if not self._video_info:
            for track in self.media_info.tracks:
                if track.track_type == "Video":
                    self._video_info.append(track.to_data())

        return self._video_info

    @property
    def audio_track(self) -> list:
        """Returns audio information"""
        if not self._audio_info:
            for track in self.media_info.tracks:
                if track.track_type == "Audio":
                    self._audio_info.append(track.to_data())
        return self._audio_info

    @property
    def codec_id(self) -> str:
        """Returns the codec_id of the first video track"""
        video = self.video_track
        if video:
            return video[0].get("codec_id", "Unknown")
        return "Unknown"

    @property
    def video_width(self) -> str:
        """Returns the width of the video"""
        video = self.video_track
        if video:
            return video[0].get("width", "Unknown")
        return "Unknown"

    @property
    def video_height(self) -> str | None:
        """Returns the height of the video"""
        video = self.video_track
        if video:
            return video[0].get("height", None)
        return None

    @property
    def video_scan_type(self) -> str | None:
        """Returns the scan type"""
        video = self.video_track
        if video:
            return video[0].get("scan_type", None)
        return None

    @property
    def video_aspect_ratio(self) -> str:
        """Returns the aspect ratio of the video"""
        video = self.video_track
        if video:
            return video[0].get("display_aspect_ratio", "Unknown")
        return "Unknown"

    @property
    def video_frame_rate(self) -> str:
        """Returns the frame rate of the video"""
        video = self.video_track
        if video:
            return video[0].get("frame_rate", "Unknown")
        return "Unknown"

    @property
    def video_bit_depth(self) -> str:
        """Returns the bit depth of the video"""
        video = self.video_track
        if video:
            return video[0].get("bit_depth", "Unknown")
        return "Unknown"

    @property
    def audio_codec_id(self) -> str:
        """Returns the codec_id of the first audio track"""
        audio = self.audio_track
        if audio:
            return audio[0].get("codec_id", "Unknown")
        return "Unknown"

    @property
    def audio_bit_rate(self) -> str:
        """Returns the bit rate of the audio"""
        audio = self.audio_track
        if audio:
            return audio[0].get("bit_rate", "Unknown")
        return "Unknown"

    @property
    def audio_channels(self) -> str:
        """Returns the number of audio channels"""
        audio = self.audio_track
        if audio:
            return audio[0].get("channels", "Unknown")
        return "Unknown"

    @property
    def audio_sampling_rate(self) -> str:
        """Returns the sampling rate of the audio"""
        audio = self.audio_track
        if audio:
            return audio[0].get("sampling_rate", "Unknown")
        return "Unknown"

    @property
    def subtitle_track(self) -> list:
        """Get subtitle track"""
        subtitle_info = []
        for track in self.media_info.tracks:
            if track.track_type == "Text":
                subtitle_info.append(track.to_data())
        return subtitle_info

    @property
    def available_languages(self) -> list:
        """Get available languages from audio and subtitle tracks"""
        languages = set()

        for track in self.audio_track:
            lang = track.get("language", "Unknown")
            # zxx = "No linguistic content" (film muet) → on skip
            if lang in ("Unknown", "zxx"):
                continue
            converted = ManageTitles.convert_iso(lang)
            # convert_iso peut retourner une str ou une list
            if isinstance(converted, list):
                languages.update(converted)
            else:
                languages.add(converted)

        return list(languages) if languages else ["not found"]

    @property
    def file_size(self) -> str:
        """Get the file size"""
        general = self.general_track
        if general:
            return general.get("file_size", "Unknown")
        return "Unknown"

    @property
    def info(self):
        return MediaInfo.parse(self.file_path, output="STRING", full=False)

    @property
    def is_interlaced(self) -> int | None:
        video = self.video_track
        if video:
            encoding_settings = video[0].get("encoding_settings", None)
            if encoding_settings:
                match = re.search(r"interlaced=(\d)", encoding_settings)
                if match:
                    return int(match.group(1))

        return None

    def generate(self, guess_title: str, resolution: str)-> str | None:
        if self.video_track:
            video_format = self.video_track[0].get("format", "")
            audio_format = self.audio_track[0].get("format", "")
            _, file_ext =os.path.splitext(self.file_path)

            return f"{guess_title}.web-dl.{video_format}.{resolution}.{audio_format}.{file_ext}"
        return None
        
    @property
    def is_silent(self) -> bool:
        """True si toutes les pistes audio sont zxx (film muet)."""
        audio = self.audio_track
        if not audio:
            return False
        langs = [t.get("language", "") for t in audio]
        return bool(langs) and all(l == "zxx" for l in langs)

    # ── Propriétés ajoutées pour les validators ────────────────────────────

    @property
    def encoding_settings(self) -> str | None:
        """Chaîne encoding_settings du premier track vidéo (options x264/x265)."""
        video = self.video_track
        if video:
            return video[0].get("encoding_settings", None)
        return None

    @property
    def writing_library(self) -> str | None:
        """Writing library du premier track vidéo."""
        video = self.video_track
        if video:
            return video[0].get("writing_library", None)
        return None

    @property
    def video_format(self) -> str | None:
        """Format vidéo (AVC, HEVC, AV1, etc.)."""
        video = self.video_track
        if video:
            return video[0].get("format", None)
        return None

    @property
    def color_primaries(self) -> str | None:
        """Color primaries (BT.601, BT.709, BT.2020, etc.)."""
        video = self.video_track
        if video:
            return video[0].get("color_primaries", None)
        return None

    @property
    def transfer_characteristics(self) -> str | None:
        """Transfer characteristics (PQ / SMPTE ST 2084, HLG, etc.)."""
        video = self.video_track
        if video:
            return video[0].get("transfer_characteristics", None)
        return None

    @property
    def hdr_format(self) -> str | None:
        """HDR format string (Dolby Vision, HDR10, HDR10+, etc.)."""
        video = self.video_track
        if video:
            return video[0].get("hdr_format", None)
        return None

    @property
    def container_format(self) -> str:
        """Extension du fichier (container)."""
        _, ext = os.path.splitext(self.file_path)
        return ext.lower()

    @property
    def multiview_count(self) -> int | None:
        """Nombre de vues pour contenu 3D."""
        video = self.video_track
        if video:
            val = video[0].get("multiview_count", None)
            return int(val) if val else None
        return None

    @property
    def audio_formats(self) -> list[dict]:
        """Liste des formats et canaux de chaque piste audio."""
        result = []
        for track in self.audio_track:
            result.append({
                "format": track.get("format", ""),
                "channels": track.get("channel_s", 0),
                "service_kind": track.get("service_kind", ""),
                "delay": track.get("delay_relative_to_video", None),
                "language": track.get("language", ""),
            })
        return result

    @property
    def subtitle_formats(self) -> list[dict]:
        """Liste des formats de chaque piste sous-titre."""
        result = []
        for track in self.subtitle_track:
            result.append({
                "format": track.get("format", ""),
                "language": track.get("language", ""),
            })
        return result