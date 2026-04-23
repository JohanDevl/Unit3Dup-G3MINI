# -*- coding: utf-8 -*-
"""
Generate BBCode presentation (prez style 3) for torrent descriptions.
Matches the format used in mediatorr's prezStyle3.
"""

import re

from common.mediainfo import MediaFile


# ── Language mappings ──────────────────────────────────────────────────

ISO_TO_LANG_NAME = {
    "fr": "Français", "fr-CA": "Français (Canada)", "fr-BE": "Français (Belgique)",
    "en": "Anglais", "de": "Allemand", "es": "Espagnol",
    "it": "Italien", "ja": "Japonais", "ko": "Coréen", "pt": "Portugais",
    "ru": "Russe", "zh": "Chinois", "ar": "Arabe", "nl": "Néerlandais",
    "pl": "Polonais", "tr": "Turc", "hi": "Hindi", "sv": "Suédois",
    "no": "Norvégien", "da": "Danois", "fi": "Finnois", "el": "Grec",
    "hu": "Hongrois", "ro": "Roumain", "cs": "Tchèque", "he": "Hébreu",
    "th": "Thaï", "vi": "Vietnamien", "id": "Indonésien", "ms": "Malais",
    "bg": "Bulgare", "hr": "Croate", "sr": "Serbe", "sk": "Slovaque",
    "sl": "Slovène", "uk": "Ukrainien", "ca": "Catalan", "eu": "Basque",
    "et": "Estonien", "lv": "Letton", "lt": "Lituanien", "is": "Islandais",
    "ka": "Géorgien", "hy": "Arménien", "fa": "Persan", "bn": "Bengali",
    "ta": "Tamoul", "te": "Télougou", "ur": "Ourdou", "tl": "Tagalog",
}

LANG_TO_COUNTRY = {
    "Français": "FR", "Français (Canada)": "CA", "Français (Belgique)": "BE",
    "Anglais": "GB", "Allemand": "DE", "Espagnol": "ES",
    "Italien": "IT", "Japonais": "JP", "Coréen": "KR", "Portugais": "PT",
    "Russe": "RU", "Chinois": "CN", "Arabe": "SA", "Néerlandais": "NL",
    "Polonais": "PL", "Turc": "TR", "Hindi": "IN", "Suédois": "SE",
    "Norvégien": "NO", "Danois": "DK", "Finnois": "FI", "Grec": "GR",
    "Hongrois": "HU", "Roumain": "RO", "Tchèque": "CZ", "Hébreu": "IL",
    "Thaï": "TH", "Vietnamien": "VN", "Indonésien": "ID", "Malais": "MY",
    "Bulgare": "BG", "Croate": "HR", "Serbe": "RS", "Slovaque": "SK",
    "Slovène": "SI", "Ukrainien": "UA", "Catalan": "ES", "Basque": "ES",
    "Estonien": "EE", "Letton": "LV", "Lituanien": "LT", "Islandais": "IS",
    "Géorgien": "GE", "Arménien": "AM", "Persan": "IR", "Bengali": "BD",
    "Tamoul": "LK", "Télougou": "IN", "Ourdou": "PK", "Tagalog": "PH",
}

VARIANT_COUNTRY = {"VFQ": "CA", "VFB": "BE"}

_LANG_NAME_TO_ISO: dict[str, str] = {v.lower(): k for k, v in ISO_TO_LANG_NAME.items()}
_LANG_NAME_TO_ISO.update({
    "english": "en", "french": "fr", "german": "de", "spanish": "es",
    "italian": "it", "japanese": "ja", "korean": "ko", "portuguese": "pt",
    "russian": "ru", "chinese": "zh", "arabic": "ar", "dutch": "nl",
    "polish": "pl", "turkish": "tr", "hindi": "hi", "swedish": "sv",
    "norwegian": "no", "danish": "da", "finnish": "fi", "greek": "el",
    "hungarian": "hu", "romanian": "ro", "czech": "cs", "hebrew": "he",
    "thai": "th", "vietnamese": "vi", "indonesian": "id", "malay": "ms",
    "bulgarian": "bg", "croatian": "hr", "serbian": "sr", "slovak": "sk",
    "slovenian": "sl", "ukrainian": "uk", "catalan": "ca", "basque": "eu",
    "estonian": "et", "latvian": "lv", "lithuanian": "lt", "icelandic": "is",
    "georgian": "ka", "armenian": "hy", "persian": "fa", "bengali": "bn",
    "tamil": "ta", "telugu": "te", "urdu": "ur", "tagalog": "tl",
})

# ── Codec normalization ───────────────────────────────────────────────

CODEC_SHORT = {
    "E-AC-3": "EAC3", "E-AC-3 JOC": "EAC3 Atmos", "AC-3": "AC3",
    "TrueHD": "TrueHD", "MLP FBA": "TrueHD", "MLP FBA 16-ch": "TrueHD Atmos",
    "DTS-HD MA": "DTS-HD MA", "DTS-HD": "DTS-HD", "DTS": "DTS",
    "DTS:X": "DTS:X", "AAC": "AAC", "HE-AAC": "HE-AAC",
    "FLAC": "FLAC", "Opus": "Opus", "Vorbis": "Vorbis",
    "PCM": "PCM", "LPCM": "LPCM",
}

VIDEO_CODEC_LABEL = {
    "AVC": "x264", "HEVC": "x265", "AV1": "AV1",
    "VP9": "VP9", "MPEG-4 Visual": "XviD",
}

SUB_FORMAT_NORMALIZE = {
    "UTF-8": "SRT", "SUBRIP": "SRT", "ASS": "ASS", "SSA": "SSA",
    "PGS": "PGS", "VOBSUB": "VobSub", "HDMV_PGS": "PGS",
    "S_TEXT/UTF8": "SRT", "S_TEXT/ASS": "ASS", "S_TEXT/SSA": "SSA",
    "S_HDMV/PGS": "PGS", "S_VOBSUB": "VobSub",
}


# ── Language normalization ────────────────────────────────────────────

# ISO 639-2 (3-letter) → ISO 639-1 (2-letter). Only common audio/sub
# languages pymediainfo emits in the wild.
_ISO3_TO_ISO1 = {
    "fra": "fr", "fre": "fr", "eng": "en", "deu": "de", "ger": "de",
    "spa": "es", "ita": "it", "jpn": "ja", "kor": "ko", "por": "pt",
    "rus": "ru", "zho": "zh", "chi": "zh", "ara": "ar", "nld": "nl",
    "dut": "nl", "pol": "pl", "tur": "tr", "hin": "hi", "swe": "sv",
    "nor": "no", "dan": "da", "fin": "fi", "ell": "el", "gre": "el",
    "hun": "hu", "ron": "ro", "rum": "ro", "ces": "cs", "cze": "cs",
    "heb": "he", "tha": "th", "vie": "vi", "ind": "id", "msa": "ms",
    "may": "ms", "bul": "bg", "hrv": "hr", "srp": "sr", "slk": "sk",
    "slo": "sk", "slv": "sl", "ukr": "uk", "cat": "ca", "eus": "eu",
    "baq": "eu", "est": "et", "lav": "lv", "lit": "lt", "isl": "is",
    "ice": "is", "kat": "ka", "geo": "ka", "hye": "hy", "arm": "hy",
    "fas": "fa", "per": "fa", "ben": "bn", "tam": "ta", "tel": "te",
    "urd": "ur", "tgl": "tl",
}

# Region word/code → ISO country code, used to resolve regional variants
# of the same base language (e.g. fr-CA, fr-BE).
_REGION_TO_COUNTRY = {
    "ca": "CA", "can": "CA", "canada": "CA", "fq": "CA", "quebec": "CA",
    "québec": "CA", "qc": "CA",
    "be": "BE", "bel": "BE", "belgium": "BE", "belgique": "BE",
}


def normalize_lang_code(raw: str) -> str:
    """Convert a raw mediainfo language value to a canonical ISO_TO_LANG_NAME key.

    Handles 2-letter ISO 639-1, 3-letter ISO 639-2, English names, hyphen/
    underscore separated regional variants ("fr-CA", "fr_CA"), and
    parenthesised region names ("French (Canada)"). Returns "" when no
    confident mapping is found.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""

    # Pull out a region token from "French (Canada)" → region_word="canada".
    region_word = ""
    m = re.match(r'^\s*([^()]+?)\s*\(\s*([^()]+)\s*\)\s*$', s)
    if m:
        s = m.group(1).strip()
        region_word = m.group(2).strip().lower()

    s_norm = s.replace("_", "-").lower()
    parts = s_norm.split("-", 1)
    base = parts[0].strip()
    suffix = parts[1].strip() if len(parts) == 2 else ""

    if base in ISO_TO_LANG_NAME and "-" not in base:
        base_iso = base
    elif base in _LANG_NAME_TO_ISO:
        base_iso = _LANG_NAME_TO_ISO[base]
    elif base in _ISO3_TO_ISO1:
        base_iso = _ISO3_TO_ISO1[base]
    else:
        return ""

    region_code = _REGION_TO_COUNTRY.get(suffix) or _REGION_TO_COUNTRY.get(region_word)
    if region_code:
        regional_key = f"{base_iso}-{region_code}"
        if regional_key in ISO_TO_LANG_NAME:
            return regional_key
    return base_iso


# ── Helpers ───────────────────────────────────────────────────────────

def _country_to_flag(country_code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country_code.upper())


def _lang_name(iso_code: str) -> str:
    if not iso_code:
        return "Inconnu"
    canonical = normalize_lang_code(iso_code)
    if canonical and canonical in ISO_TO_LANG_NAME:
        return ISO_TO_LANG_NAME[canonical]
    cleaned = re.sub(r'\s*\([^)]*\)', '', iso_code).strip()
    return cleaned.capitalize() if cleaned else "Inconnu"


def _infer_lang_from_title(title: str) -> str:
    """Try to extract an ISO language code from a track title."""
    if not title:
        return ""
    # Try exact match first
    key = title.strip().lower()
    if key in _LANG_NAME_TO_ISO:
        return _LANG_NAME_TO_ISO[key]
    # Split on common delimiters and check each token
    import re
    for token in re.split(r'[\s(),/\-]+', key):
        iso = _LANG_NAME_TO_ISO.get(token)
        if iso:
            return iso
    return ""


def _lang_flag(lang_name: str, variant: str | None = None) -> str:
    if variant:
        vc = VARIANT_COUNTRY.get(variant)
        if vc:
            return _country_to_flag(vc)
    cc = LANG_TO_COUNTRY.get(lang_name)
    return _country_to_flag(cc) if cc else "\U0001f3f3\ufe0f"


def _format_channels(channel_count) -> str:
    try:
        ch = int(channel_count)
    except (ValueError, TypeError):
        return ""
    if ch > 2:
        return f"{ch - 1}.1"
    return "2.0" if ch == 2 else "1.0"


def _format_bitrate(bps) -> str:
    try:
        bps_int = int(bps)
    except (ValueError, TypeError):
        return str(bps) if bps else ""
    if bps_int >= 1_000_000:
        return f"{bps_int / 1_000_000:.1f} Mb/s"
    return f"{bps_int // 1_000} kb/s"


def _detect_audio_type(title: str | None) -> str | None:
    if not title:
        return None
    upper = title.upper()
    for variant in ("VFF", "VFQ", "VFI", "VF2", "VOF", "VOST", "VFB", "VF", "VO"):
        if variant in upper.split() or variant in upper.replace(",", " ").split():
            return variant
    return None


def _detect_sub_qualifier(title: str | None, forced: str | None) -> str:
    if title:
        t = title.lower()
        if "forced" in t or "forcé" in t:
            return " forcés"
        if "full" in t or "complet" in t:
            return " complets"
        if "sdh" in t or "cc" in t:
            return " SDH"
    if forced and forced.lower() == "yes":
        return " forcés"
    return ""


def _normalize_sub_format(fmt: str | None) -> str:
    if not fmt:
        return ""
    return SUB_FORMAT_NORMALIZE.get(fmt.upper().strip(), fmt.upper().strip())


def _quality_label(width, height) -> str:
    """Determine quality label from video dimensions, preferring width."""
    try:
        w = int(width) if width else 0
    except (ValueError, TypeError):
        w = 0
    try:
        h = int(height) if height else 0
    except (ValueError, TypeError):
        h = 0

    if not w and not h:
        return ""

    # Width-based (primary) — matches Mediatorr logic
    if w >= 3800:
        return "UHD 2160p"
    if w >= 1900:
        return "HD 1080p"
    if w >= 1200:
        return "HD 720p"

    # Height-based fallback (if width unavailable)
    if h >= 2160:
        return "UHD 2160p"
    if h >= 1080:
        return "HD 1080p"
    if h >= 720:
        return "HD 720p"
    if h >= 480:
        return "SD 480p"
    return f"SD {h}p"


def _codec_label(video_format: str | None) -> str:
    if not video_format:
        return ""
    return VIDEO_CODEC_LABEL.get(video_format, video_format)


# ── Main generator ────────────────────────────────────────────────────

def generate_prez(media_file: MediaFile, *, audio_tracks=None, sub_tracks=None) -> str:
    """Generate prez style 3 BBCode from a MediaFile instance."""
    bb = ""

    # ── Technique card ──
    codec = _codec_label(media_file.video_format)
    bit_depth_raw = media_file.video_bit_depth
    bit_depth = f"{bit_depth_raw} bits" if bit_depth_raw and bit_depth_raw != "Unknown" else ""
    quality = _quality_label(media_file.video_width, media_file.video_height)

    badges = []
    if codec:
        badges.append(f"[badge=red][size=13]{codec}[/size][/badge]")
    if bit_depth:
        badges.append(f"[badge=gray][size=13]{bit_depth}[/size][/badge]")
    if quality:
        badges.append(f"[badge=blue][size=13]{quality}[/size][/badge]")

    if badges:
        bb += "[card]\n"
        bb += "[card-title][color=#e74c3c][size=18][b]Technique[/b][/size][/color][/card-title]\n"
        bb += "[card-body]\n"
        bb += " ".join(badges) + "\n"
        bb += "[/card-body]\n[/card]\n\n"

    # ── Audio + Subtitles grid ──
    audio_tracks = audio_tracks if audio_tracks is not None else media_file.audio_track
    sub_tracks = sub_tracks if sub_tracks is not None else media_file.subtitle_track

    if not audio_tracks and not sub_tracks:
        return bb

    bb += "[grid]\n"

    # ── Audio column ──
    if audio_tracks:
        bb += "[col]\n[card]\n"
        bb += "[card-title][color=#2ecc71][size=18][b]\U0001f50a Audio[/b][/size][/color][/card-title]\n"
        bb += "[card-body]\n"

        audio_entries = []
        for track in audio_tracks:
            lang = track.get("language", "")
            title = track.get("title", "")
            fmt = track.get("format", "")
            channels = track.get("channel_s", "")
            bitrate = track.get("bit_rate", "")

            if not lang and title:
                lang = _infer_lang_from_title(title)
            name = _lang_name(lang)
            audio_type = _detect_audio_type(title)
            flag = _lang_flag(name, audio_type)
            type_str = f" ({audio_type})" if audio_type else ""

            codec_name = CODEC_SHORT.get(fmt, fmt) if fmt else ""
            ch_str = _format_channels(channels)
            br_str = _format_bitrate(bitrate)

            details = " \u2022 ".join(filter(None, [codec_name, ch_str, br_str]))
            entry = f"{flag} {name}{type_str}"
            if details:
                entry += f"\n[size=11][color=#7f8c8d]{details}[/color][/size]"
            audio_entries.append(entry)

        bb += "\n\n".join(audio_entries) + "\n"
        bb += "[/card-body]\n[/card]\n[/col]\n"

    # ── Subtitles column ──
    if sub_tracks:
        bb += "\n[col]\n[card]\n"
        bb += "[card-title][color=#f39c12][size=18][b]\U0001f4dd Sous-titres[/b][/size][/color][/card-title]\n"
        bb += "[card-body]\n"

        sub_entries = []
        for track in sub_tracks:
            lang = track.get("language", "")
            title = track.get("title", "")
            forced = track.get("forced", "")
            fmt = track.get("format", "")

            if not lang and title:
                lang = _infer_lang_from_title(title)
            name = _lang_name(lang)
            flag = _lang_flag(name)
            qualifier = _detect_sub_qualifier(title, forced)
            sub_format = _normalize_sub_format(fmt)

            entry = f"{flag} {name}{qualifier}"
            if sub_format:
                entry += f"\n[size=11][color=#7f8c8d]{sub_format}[/color][/size]"
            sub_entries.append(entry)

        bb += "\n\n".join(sub_entries) + "\n"
        bb += "[/card-body]\n[/card]\n[/col]\n"

    bb += "[/grid]\n"
    return bb
