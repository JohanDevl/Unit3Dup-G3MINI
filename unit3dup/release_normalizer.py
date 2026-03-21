# -*- coding: utf-8 -*-
"""
release_normalizer.py — Normalisation des noms de release pour G3MINI Tracker

Portage Python du script g3mini_rename.sh
Ne renomme aucun fichier — agit uniquement sur le champ release_name.
"""

import re
import unicodedata
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_lang(raw: str) -> str:
    r = raw.upper()
    if r == "TRUEFRENCH":                   return "VFF"
    if re.match(r'^VFF-', r):               return "MULTi.VFF"
    if re.match(r'^VFQ-', r):               return "MULTi.VFQ"
    if re.match(r'^VF2-', r):               return "MULTi.VF2"
    if re.match(r'^VFB-', r):               return "MULTi.VFB"
    if r in ("MULTI.VFF", "MULTI-VFF"):     return "MULTi.VFF"
    if r in ("MULTI.VFQ", "MULTI-VFQ"):     return "MULTi.VFQ"
    if r in ("MULTI.VF2", "MULTI-VF2"):     return "MULTi.VF2"
    if r in ("MULTI.VFB", "MULTI-VFB"):     return "MULTi.VFB"
    if r in ("MULTI", "MULTIC"):            return "MULTi"
    if r in ("FRENCH", "VFF", "VFI"):       return "VFF"
    if r == "VFQ":                          return "VFQ"
    if r == "VF2":                          return "VF2"
    if r == "VFB":                          return "VFB"
    if r == "VOF":                          return "VOF"
    if r == "VOQ":                          return "VOQ"
    if r == "VOB":                          return "VOB"
    if r == "VOSTFR":                       return "VOSTFR"
    if r == "SUBFRENCH":                    return "SUBFRENCH"
    return raw


def _normalize_source(raw: str) -> str:
    r = raw.upper()
    if r in ("BLURAY", "BLU-RAY"):          return "BluRay"
    if r == "BDRIP":                        return "BDRip"
    if r == "BRRIP":                        return "BRRip"
    if r == "4KLIGHT":                      return "4KLight"
    if r in ("HDLIGHT", "MHD"):             return "HDLight"
    if r == "WEBRIP":                       return "WEBRip"
    if r in ("WEB-DL", "WEBDL", "WEB"):     return "WEB"
    if r == "HDRIP":                        return "HDRip"
    if r == "HDTV":                         return "HDTV"
    if r in ("TVRIP", "TVHDRIP"):           return "TVRip"
    if r in ("DVDRIP", "DVD"):              return "DVDRip"
    if r == "REMUX":                        return "REMUX"
    return raw


def _clean_title(t: str) -> str:
    t = t.strip()
    t = t.replace(" ", ".")
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-zA-Z0-9._-]', '', t)
    # Remove isolated dashes: ".-." or leading/trailing dashes
    t = re.sub(r'\.?-\.?', '.', t)
    t = re.sub(r'\.{2,}', '.', t)
    t = t.strip('.')
    return t


def _remove_token(s: str, tok: str) -> str:
    """Supprime toutes les occurrences d'un token (insensible à la casse).
    Gère début, milieu et fin de chaîne. Compacte les espaces résiduels."""
    tok_esc = re.escape(tok)
    result = re.sub(r'(^|\s)' + tok_esc + r'(\s|$)', ' ', s, flags=re.IGNORECASE)
    return re.sub(r' {2,}', ' ', result).strip()


def _ws(s: str) -> str:
    """Compactage simple des espaces."""
    return re.sub(r' {2,}', ' ', s).strip()


# ══════════════════════════════════════════════════════════════════════════════
#  MEDIAINFO PARSERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_codec_from_mediainfo(mi: str) -> str:
    """Détecte le codec vidéo depuis le texte brut MediaInfo."""
    if not mi:
        return ""
    # Isoler le bloc Video (jusqu'au prochain bloc ou fin)
    m = re.search(r'^Video.*?(?=\n(?:Audio|Text|Menu|General)|\Z)', mi,
                  re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    block = m.group(0)

    # Encoded_Library_Name (underscore ou espace selon version MediaInfo)
    lib_m = re.search(r'Encoded[\s_]library[\s_]name\s*:\s*(.+)', block, re.IGNORECASE)
    if lib_m:
        lib = lib_m.group(1).strip().upper()
        if lib.startswith("X264"):  return "x264"
        if lib.startswith("X265"):  return "x265"

    # Format (première ligne du bloc)
    fmt_m = re.search(r'^Format\s*:\s*(.+)', block, re.MULTILINE | re.IGNORECASE)
    if fmt_m:
        fmt = fmt_m.group(1).strip().upper()
        return {
            "AVC":    "x264",
            "HEVC":   "x265",
            "AV1":    "AV1",
            "VP9":    "VP9",
            "MPEG-2": "MPEG-2",
            "MPEG2":  "MPEG-2",
            "MPEG":   "MPEG-2",
            "VC-1":   "VC-1",
            "VC1":    "VC-1",
        }.get(fmt, "")
    return ""


def _has_encode_library(mi: str) -> bool:
    """Retourne True uniquement si la writing library confirme un encode x264/x265.
    Ne se base PAS sur le champ Format — réservé aux vrais encodes (pas untouched)."""
    if not mi:
        return False
    m = re.search(r'^Video.*?(?=\n(?:Audio|Text|Menu|General)|\Z)', mi,
                  re.MULTILINE | re.DOTALL)
    if not m:
        return False
    block = m.group(0)
    # Writing library (ligne "Writing library" ou "Encoded library name")
    for pattern in (
        r'Writing\s+library\s*:\s*(.+)',
        r'Encoded[\s_]library[\s_]name\s*:\s*(.+)',
    ):
        lib_m = re.search(pattern, block, re.IGNORECASE)
        if lib_m:
            lib = lib_m.group(1).strip().upper()
            if lib.startswith("X264") or lib.startswith("X265"):
                return True
    return False


def _get_lang_from_mediainfo(mi: str) -> str:
    """Retourne le tag de langue dominant (sans préfixe MULTi) :
    VFF, VFQ, VF2, VFB, VOF, VOQ, VOB ou '' """
    if not mi:
        return ""
    vff = vfq = vfb = vof = voq = vob = False
    for line in mi.splitlines():
        if   re.search(r'Language\s*:\s*French\s*\(FR\)', line, re.IGNORECASE):                             vff = True
        elif re.search(r'Language\s*:\s*French\s*\(CA\)', line, re.IGNORECASE):                             vfq = True
        elif re.search(r'Title\s*:.*\b(VFF|VFI|TrueFrench|French\s*\(France\))\b', line, re.IGNORECASE):   vff = True
        elif re.search(r'Title\s*:.*\b(VFB|French\s*\(Belgique\))\b', line, re.IGNORECASE):                vfb = True
        elif re.search(r'Title\s*:.*\b(VOF)\b', line, re.IGNORECASE):                                      vof = True
        elif re.search(r'Title\s*:.*\b(VFQ|French\s*\(Canadien\))\b', line, re.IGNORECASE):                vfq = True
        elif re.search(r'Title\s*:.*\b(VOQ|French\s*\(Québec\))\b', line, re.IGNORECASE):                  voq = True
        elif re.search(r'Title\s*:.*\b(VOB|French\s*\(Belgique\s*VO\))\b', line, re.IGNORECASE):           vob = True

    if vff and vfq: return "VF2"
    if vff:         return "VFF"
    if vfq:         return "VFQ"
    if vfb:         return "VFB"
    if vof:         return "VOF"
    if voq:         return "VOQ"
    if vob:         return "VOB"
    return ""


def _get_subfr_from_mediainfo(mi: str) -> str:
    """Retourne 'yes', 'no' ou 'unknown' selon la présence de ST français."""
    if not mi:
        return "unknown"
    in_text = False
    for line in mi.splitlines():
        if re.match(r'^Text\s*$|^Text #', line):
            in_text = True
        elif re.match(r'^(Video|Audio|General|Menu)', line):
            in_text = False
        if in_text and re.search(r'Language\s*:\s*(French|fr)\b', line, re.IGNORECASE):
            return "yes"
    return "no"

def _is_silent_from_mediainfo(mi: str) -> bool:
    """Retourne True si toutes les pistes audio ont Language: zxx (film muet).
    zxx est le code ISO 639-2 pour 'No linguistic content'."""
    if not mi:
        return False
    in_audio = False
    audio_langs = []
    for line in mi.splitlines():
        if re.match(r'^Audio\s*$|^Audio #', line):
            in_audio = True
        elif re.match(r'^(Video|Text|Menu|General)', line):
            in_audio = False
        if in_audio:
            m = re.search(r'Language\s*:\s*(\S+)', line, re.IGNORECASE)
            if m:
                audio_langs.append(m.group(1).strip().lower())
    return bool(audio_langs) and all(l == 'zxx' for l in audio_langs)    


# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTES DE PARSING
# ══════════════════════════════════════════════════════════════════════════════

# Séparateurs utilisés en step 5b pour décoller les tokens collés.
# Ordre important : plus long avant plus court dans chaque famille.
_TAGS = (
    r'BluRay|BDRip|BRRip|WEBRip|WEB|4KLight|HDLight|HDRip|TVRip|DVDRip|HDTV|REMUX|CAM'
    r'|2160p|1080p|1080i|720p|576p|480p|4K|UHD'
    r'|HDR10P|HDR10|SDR|DV|HLG|PQ10|HDR'
    r'|x265|x264|H265|H264|HEVC|AVC|AV1|VP9|VC1'
    r'|DTS-HDMA|DTS-HDHRA|DTS-HD|DTS|AC3|DDP|TrueHD|Atmos|AAC|OPUS'
    r'|MULTi|VFF|VFQ|VF2|VFB|VOSTFR|SUBFRENCH|VOF|VOQ|VOB|FRENCH'
    r'|EXTENDED|PROPER|REPACK|UNRATED|UNCUT|REMASTERED|INTERNAL|NoTAG|iNTEGRALE'
    r'|8bit|10bit|12bit'
    r'|3D|SBS|HSBS|TAB|HTAB|MVC|CUSTOM|NoGRP'
)

# Du plus spécifique au moins spécifique
_LANG_PATTERNS = [
    r'VFF-[A-Za-z]+(?:-[A-Za-z]+)*',
    r'VFQ-[A-Za-z]+(?:-[A-Za-z]+)*',
    r'VFB-[A-Za-z]+(?:-[A-Za-z]+)*',
    r'VF2-[A-Za-z]+(?:-[A-Za-z]+)*',
    r'MULTi\.VFF', r'MULTi\.VFQ', r'MULTi\.VF2', r'MULTi\.VFB',
    r'MULTi',
    r'FRENCH', r'VFF', r'VFQ', r'VF2', r'VFB',
    r'VOF', r'VOQ', r'VOB',
    r'VOSTFR', r'SUBFRENCH',
]

_EXTRAS_MAP = {
    'EXTENDED':      'EXTENDED',
    'THEATRICAL':    'THEATRICAL',
    'PROPER':        'PROPER',
    'REPACK':        'REPACK',
    'UNRATED':       'UNRATED',
    'UNCUT':         'UNCUT',
    'REMASTERED':    'REMASTERED',
    'INTERNAL':      'INTERNAL',
    'INTEGRALE':     'iNTEGRALE',
    'LIMITED':       'LIMITED',
    'IMAX EDITION':  'IMAX.EDITION',
    'IMAX':          'IMAX',
    'CUSTOM':         'CUSTOM',
    'UPSCALED':       'UpScaled',
}

_CODEC_LIST = [
    ("x265",   "x265"),
    ("x264",   "x264"),
    ("H\\.265", "H.265"),
    ("H\\.264", "H.264"),
    ("H265",   "H.265"),
    ("H264",   "H.264"),
    ("HEVC",   "HEVC"),
    ("AVC",    "AVC"),
    ("AV1",    "AV1"),
    ("VP9",    "VP9"),
    ("MPEG-2", "MPEG-2"),
    ("VC-1",   "VC-1"),
]

# Sources testées du plus spécifique au moins spécifique.
# "UHD BluRay" (espace) car les points ont été convertis en step 3.
# NOTE: 4KLight et HDLight sont gérés SÉPARÉMENT (source_qual) avant cette liste.
_SOURCE_LIST = [
    "UHD BluRay",
    "BluRay", "Blu-Ray",
    "BDRip", "BRRip",
    "WEB-DL", "WEBRip",
    "HDTV", "HDRip", "TVRip",
    "WEB", "DVDRip", "DVD",
]

# Codecs connus — utilisés pour exclure les faux positifs team tag
_CODEC_NAMES = frozenset({
    "X264", "X265", "H264", "H265", "HEVC", "AVC", "AV1", "VP9", "VC1",
    "MPEG2", "MPEG-2",
})

# Qualificatifs de source : peuvent coexister avec une source principale.
# Ex: "4KLight BluRay" → source = "4KLight.BluRay"
_SOURCE_QUAL_LIST = ["4KLight", "HDLight", "mHD"]


# ══════════════════════════════════════════════════════════════════════════════
#  PARSER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def _parse_release(original: str, mi: Optional[str] = None, is_silent: bool = False) -> str:
    name = original

    # ── 1. Extension ─────────────────────────────────────────────────────────
    ext = ""
    m = re.search(r'\.(mkv|mp4|avi|ts|m2ts|iso)$', name, re.IGNORECASE)
    if m:
        ext = "." + m.group(1)
        name = name[:-len(ext)]

    # ── 1b. Pré-nettoyage : séparateurs et bruit ────────────────────────────
    # " - " ou ".-." → espace (évite les artefacts .-.-. dans le titre)
    name = re.sub(r'[.\s]+-[.\s]+', ' ', name)
    # @bitrate (ex: AC3@640Kbps) → supprimer le suffixe @bitrate
    name = re.sub(r'@\d+[kKmM]bps', '', name, flags=re.IGNORECASE)
    # Bitrates standalone (384kbps, 2Mbps…) : bruit sans valeur pour le nommage
    name = re.sub(r'-?\d+[kKmM]bps', '', name, flags=re.IGNORECASE)
    name = name.strip()

    # ── 2. Team ───────────────────────────────────────────────────────────────
    # Extrait avant la normalisation des séparateurs.
    # name_team = nom sans les parens de fin (ex: "(58 minutes pour vivre)")
    team = ""
    name_team = re.sub(r'\s*\([^)]*\)\s*$', '', name)
    # Supporte les teams composées : -Tsundere-Raws, -PSA-BATGirl, -Team1&Team2
    m = re.search(r'-([A-Za-z0-9@_&]+(?:-[A-Za-z0-9@_&]+)*)$', name_team)
    if m:
        raw_team = m.group(1)
        team = re.sub(r'[^a-zA-Z0-9&-]', '', raw_team)  # préserve la casse, & et -
        # Suppression globale via replace (couvre le cas avec parens après le tag)
        name = name.replace(f'-{raw_team}', '')
    else:
        m = re.search(r'\.([A-Za-z0-9]{2,12})$', name_team)
        if m:
            suffix = m.group(1)
            # Exclure les codecs connus et extensions courantes des faux team tags
            if not re.match(r'^(COM|NET|ORG|IO|FR|MKV|MP4|AVI|MP3|AAC)$', suffix, re.IGNORECASE) \
               and suffix.upper() not in _CODEC_NAMES:
                team = suffix
                # Coupe au niveau de name_team (avant les éventuelles parens de fin)
                cut_pos = name_team.rfind(f'.{suffix}')
                if cut_pos >= 0:
                    name = name[:cut_pos] + name[cut_pos + len(suffix) + 1:]

    if not team:
        team = "NoTag"

    # ── 3. Normalisation séparateurs : points & underscores → espaces ─────────
    name = name.replace('.', ' ').replace('_', ' ')
    name = _ws(name)

    # 3b. Recoller les channel tokens détruits (ex: "7 1" → "7.1")
    name = re.sub(r'(?<!\d)(7) (1)(?!\d)', '7.1', name)
    name = re.sub(r'(?<!\d)(5) (1)(?!\d)', '5.1', name)
    name = re.sub(r'(?<!\d)(2) (0)(?!\d)', '2.0', name)
    name = re.sub(r'(?<!\d)(1) (0)(?!\d)', '1.0', name)
    name = re.sub(r'(?<!\d)(4) (0)(?!\d)', '4.0', name)
    name = re.sub(r'(?<!\d)(6) (1)(?!\d)', '6.1', name)

    # ── 4. [Crochets] → contenu conservé ────────────────────────────────────────
    name = re.sub(r'\[([^\]]*)\]', r'\1', name)
    # Parenthèses non-année : supprimer tôt pour éviter que leur contenu pollue
    # les étapes suivantes. On garde uniquement les parens contenant une année.
    name = re.sub(r'\((?![12][0-9]{3}\))[^)]*\)', '', name)
    name = _ws(name)

    # ── 5. Pré-normalisation : aliases symboliques et textuels ────────────────
    name = re.sub(r'HDR10\+',                               'HDR10P',   name, flags=re.IGNORECASE)
    name = re.sub(r'HDR10PLUS',                             'HDR10P',   name, flags=re.IGNORECASE)
    name = re.sub(r'DOLBY[\s._-]*VISION',                   'DV',       name, flags=re.IGNORECASE)
    name = re.sub(r'DD\+',                                  'DDP',      name, flags=re.IGNORECASE)
    # EAC3/E-AC3 avec canaux → DDP + canaux préservés
    name = re.sub(r'E-?AC-?3\s*(\d[.]\d)',                   r'DDP \1',  name, flags=re.IGNORECASE)
    name = re.sub(r'E-?AC-?3',                               'DDP',      name, flags=re.IGNORECASE)
    # HE-AAC → AAC (variante haute efficacité, normalisée à AAC)
    name = re.sub(r'HE-AAC',                                 'AAC',      name, flags=re.IGNORECASE)
    # AC3@640Kbps et similaires → AC3 (supprimer le bitrate)
    name = re.sub(r'AC3@\d+[Kk]bps',                        'AC3',      name, flags=re.IGNORECASE)
    # DD avec canal (DD5.1, DD7.1) → AC3 + canal
    name = re.sub(r'(?<!\w)DD(\d[.]\d)',                    r'AC3 \1',  name, flags=re.IGNORECASE)
    # DD seul → AC3 (mais pas DD+, DDP, DTS)
    name = re.sub(r'(?<!\w)DD(?=\s|$)',                     'AC3',      name, flags=re.IGNORECASE)
    name = re.sub(r'TRUE[\s._-]*HD',                        'TrueHD',   name, flags=re.IGNORECASE)
    name = re.sub(r'TRUEFRENCH',                            'VFF',      name, flags=re.IGNORECASE)
    name = re.sub(r'DTS[\s_-]*HD[\s_-]*MA',                'DTS-HDMA', name, flags=re.IGNORECASE)
    name = re.sub(r'DTS[\s_-]*HD[\s_-]*(?:H?RA)',           'DTS-HDHRA', name, flags=re.IGNORECASE)
    name = re.sub(r'WEB-Rip',                               'WEBRip',   name, flags=re.IGNORECASE)
    # 4KLight (variable separators) → 4KLight
    name = re.sub(r'4K[\s._-]*LIGHT',                       '4KLight',  name, flags=re.IGNORECASE)
    # MULTi-VFF/VFQ/VF2/VFB (tiret) → MULTi.VFF etc.
    name = re.sub(r'MULTi-(VFF|VFQ|VF2|VFB)',
                  lambda mo: f'MULTi.{mo.group(1).upper()}',            name, flags=re.IGNORECASE)
    # VFI → VFF (case-insensitive, word-boundary)
    name = re.sub(r'(?<!\w)VFI(?!\w)',                      'VFF',      name, flags=re.IGNORECASE)
    # FR-EN, FR-ENG-JAP, ... → MULTi.VFF (un ou plusieurs segments après FR-)
    name = re.sub(r'(^|\s)FR-[A-Za-z]+(?:-[A-Za-z]+)*(\s|$)',
                  r'\1MULTi.VFF\2',                                     name, flags=re.IGNORECASE)
    # FR seul → FRENCH
    name = re.sub(r'(^|\s)FR(\s|$)',                        r'\1FRENCH\2', name, flags=re.IGNORECASE)
    name = _ws(name)

    # ── 5b. Séparation des tokens collés (boucle jusqu'à stabilité) ───────────
    prev = None
    while name != prev:
        prev = name
        name = re.sub(f'({_TAGS})({_TAGS})', r'\1 \2', name, flags=re.IGNORECASE)
    name = _ws(name)

    # ── 5d. Bit depth : 8bit retiré (défaut), 10bit/12bit conservés ──────────
    # 8bit est le défaut et n'apporte pas d'information → retiré
    name = re.sub(r'(?:^|\s)8[- ]?bits?(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    name = _ws(name)
    # 10bit/12bit extraits pour reconstruction (entre résolution et HDR)
    # Supporte 10bit, 10Bit, 10bits, 10 bit etc.
    bit_depth = ""
    m_bd = re.search(r'(?:^|\s)(10|12)[- ]?bits?(?:\s|$)', name, re.IGNORECASE)
    if m_bd:
        bit_depth = f"{m_bd.group(1)}bit"
        name = re.sub(r'(?:^|\s)(?:10|12)[- ]?bits?(?:\s|$)', ' ', name, flags=re.IGNORECASE)
        name = _ws(name)

    # ── 5c. SAISON N → S0N ────────────────────────────────────────────────────
    while True:
        m = re.search(r'(?:^|\s)[Ss][Aa][Ii][Ss][Oo][Nn]\s*([0-9]+)(?:\s|$)', name)
        if not m:
            break
        snum = m.group(1)
        padded = f'S{int(snum):02d}'
        name = re.sub(rf'[Ss][Aa][Ii][Ss][Oo][Nn]\s*{re.escape(snum)}', padded, name, flags=re.IGNORECASE)

    # ── 6. Année ──────────────────────────────────────────────────────────────
    year = ""
    m = re.search(r'\(([12][0-9]{3})\)', name)
    if m:
        year = m.group(1)
        name = name.replace(f'({year})', '')
    else:
        m = re.search(r'(?:^|\s)([12][0-9]{3})(?:\s|$)', name)
        if m:
            year = m.group(1)
            name = re.sub(rf'(?:^|\s){re.escape(year)}(?:\s|$)', ' ', name)
    name = _ws(name)

    # ── 7. Extras ─────────────────────────────────────────────────────────────
    extras = ""
    for kw, display in _EXTRAS_MAP.items():
        if re.search(rf'(?:^|\s){kw}(?:\s|$)', name, re.IGNORECASE):
            extras += f'.{display}'
            name = _remove_token(name, kw)
    if re.search(r'(?:^|\s)VL(?:\s|$)', name):
        extras += '.EXTENDED'
        name = _remove_token(name, 'VL')
    # DC EXTREME → DIRECTORS.CUT.EXTREME (avant DC seul)
    if re.search(r'(?:^|\s)DC\s+EXTREME(?:\s|$)', name, re.IGNORECASE):
        extras += '.DIRECTORS.CUT.EXTREME'
        name = re.sub(r'(?:^|\s)DC\s+EXTREME(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)DC(?:\s|$)', name):
        extras += '.DIRECTORS.CUT'
        name = _remove_token(name, 'DC')
    # AD (audio-description) : extraire seulement si l'année a été trouvée
    # (indique que AD est en position extras, pas en début de titre comme "Ad Vitam")
    if year and re.search(r'(?:^|\s)AD(?:\s|$)', name):
        extras += '.AD'
        name = _remove_token(name, 'AD')

    # NoTAG/NoGRP : gérés comme team suffix, pas extras — nettoyer les résidus
    for _notag in ('NoTAG', 'NoGRP'):
        name = _remove_token(name, _notag)

    # ── 8a. Normalisation casse MULTi ─────────────────────────────────────────
    name = re.sub(
        r'(?:^|\s)[Mm][Uu][Ll][Tt][Ii][Cc]?(?:\s|$)',
        lambda mo: mo.group(0)[0] + 'MULTi' + mo.group(0)[-1],
        name,
    )

    # ── 8b. Compound "MULTi VFF" → "MULTi.VFF" etc. ──────────────────────────
    name = re.sub(r'MULTi\s+FRENCH',                        'MULTi.VFF', name, flags=re.IGNORECASE)
    name = re.sub(r'MULTi\s+VFF-[A-Za-z]+(?:-[A-Za-z]+)*', 'MULTi.VFF', name)
    name = re.sub(r'MULTi\s+VFQ-[A-Za-z]+(?:-[A-Za-z]+)*', 'MULTi.VFQ', name)
    name = re.sub(r'MULTi\s+VF2-[A-Za-z]+(?:-[A-Za-z]+)*', 'MULTi.VF2', name)
    name = re.sub(r'MULTi\s+VFB-[A-Za-z]+(?:-[A-Za-z]+)*', 'MULTi.VFB', name)
    name = re.sub(r'MULTi\s+(VFF)(\s|$)',                   r'MULTi.VFF\2', name)
    name = re.sub(r'MULTi\s+(VFQ)(\s|$)',                   r'MULTi.VFQ\2', name)
    name = re.sub(r'MULTi\s+(VF2)(\s|$)',                   r'MULTi.VF2\2', name)
    name = re.sub(r'MULTi\s+(VFB)(\s|$)',                   r'MULTi.VFB\2', name)

    # ── 9. Langue ─────────────────────────────────────────────────────────────
    lang = ""
    lang_compound = False
    lang_from_french = False  # True si le token source était "FRENCH" (pas VFF/VFI explicite)
    for p in _LANG_PATTERNS:
        m = re.search(r'(?:^|\s)(' + p + r')(?:\s|$)', name, re.IGNORECASE)
        if m:
            matched = m.group(1)
            lang = _normalize_lang(matched)
            name = _remove_token(name, matched)
            if '-' in matched:
                lang_compound = True
            if matched.upper() == "FRENCH":
                lang_from_french = True
            break

    # Nettoyer les tokens de langue restants pour éviter les doublons (ex: VOF + FRENCH)
    for p in _LANG_PATTERNS:
        while True:
            m2 = re.search(r'(?:^|\s)(' + p + r')(?:\s|$)', name, re.IGNORECASE)
            if not m2:
                break
            name = _remove_token(name, m2.group(1))

    # ── 9b. VFF-ENG composé : MULTi.VFF seulement si ST français présents ─────
    if lang == "MULTi.VFF" and lang_compound and mi:
        subfr = _get_subfr_from_mediainfo(mi)
        if subfr == "no":
            orig_upper = original.upper().replace('.', ' ')
            mo = re.search(r'VFF-[A-Z]+(?:-[A-Z]+)*', orig_upper)
            lang = mo.group(0) if mo else "VFF"
        # yes ou unknown → on garde MULTi.VFF

    # ── 9b2. FRENCH + MediaInfo : VFF (FR) ou VFQ (CA) ───────────────────────
    # Quand le token source est "FRENCH" (ambigu), on consulte le MI pour
    # distinguer French (FR) → VFF et French (CA) → VFQ.
    if lang_from_french and mi:
        mi_lang = _get_lang_from_mediainfo(mi)
        if mi_lang:
            lang = mi_lang  # VFF, VFQ, VF2, VFB...

    # ── 9c. Fallback mediainfo : lang vide ou MULTi plain ─────────────────────
    if (not lang or lang == "MULTi") and (is_silent or (mi and _is_silent_from_mediainfo(mi))):
        lang = "MUET"
    elif (not lang or lang == "MULTi") and mi:
        mi_lang = _get_lang_from_mediainfo(mi)
        lang = f"MULTi.{mi_lang}" if mi_lang else "MULTi.VFF"

    # ── 10. HDR / SDR — tous les tokens collectés ─────────────────────────────
    hdr_parts = []
    hybrid = ""
    if re.search(r'(?:^|\s)Hybrid(?:\s|$)', name, re.IGNORECASE):
        hybrid = "Hybrid"
        name = _remove_token(name, "Hybrid")
    for h in ("HDR10P", "HDR10", "SDR", "DV", "HLG", "PQ10", "HDR"):
        if re.search(rf'(?:^|\s){re.escape(h)}(?:\s|$)', name, re.IGNORECASE):
            hdr_parts.append(h)
            name = _remove_token(name, h)
    hdr = '.'.join(hdr_parts)
    if hybrid and hdr:
        hdr = f"Hybrid.{hdr}"
    elif hybrid:
        hdr = "Hybrid"

    # ── 10b. 3D type ──────────────────────────────────────────────────────
    type_3d = ""
    is_3d = False
    if re.search(r'(?:^|\s)3D(?:\s|$)', name, re.IGNORECASE):
        is_3d = True
        name = _remove_token(name, "3D")
    for t3d in ("HSBS", "HTAB", "SBS", "TAB", "MVC"):
        if re.search(rf'(?:^|\s){t3d}(?:\s|$)', name, re.IGNORECASE):
            type_3d = t3d
            is_3d = True
            name = _remove_token(name, t3d)
            break

    # ── 11. Résolution ────────────────────────────────────────────────────────
    res = ""
    for r in ("2160p", "4K", "1080p", "1080i", "720p", "576p", "480p"):
        if re.search(rf'(?:^|\s){re.escape(r)}(?:\s|$)', name, re.IGNORECASE):
            res = r
            name = _remove_token(name, r)
            break
    # UHD est redondant si 2160p/4K déjà capturé
    if res in ("2160p", "4K"):
        name = _remove_token(name, "UHD")

    # ── 12. Source ────────────────────────────────────────────────────────────
    source = ""
    source_qual = ""   # qualificatif de source : 4KLight, HDLight (peut coexister avec BluRay)
    remux = ""
    full_disc = ""

    if re.search(r'(?:^|\s)FULL\s+DISC(?:\s|$)', name, re.IGNORECASE):
        full_disc = "FULL"
        name = re.sub(r'(?:^|\s)FULL\s+DISC(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)FULL(?:\s|$)', name, re.IGNORECASE):
        full_disc = "FULL"
        name = _remove_token(name, "FULL")

    # Qualificatifs de source extraits en priorité : peuvent coexister avec
    # une source principale (ex: "4KLight BluRay" → "4KLight.BluRay").
    for q in _SOURCE_QUAL_LIST:
        if re.search(rf'(?:^|\s){re.escape(q)}(?:\s|$)', name, re.IGNORECASE):
            source_qual = _normalize_source(q)
            name = _remove_token(name, q)
            name = _ws(name)
            break

    # "UHD BluRay" avec espace car les points ont été convertis en step 3
    for s in _SOURCE_LIST:
        pat = re.escape(s).replace(r'\ ', r'\s+')  # espace → \s+ pour robustesse
        if re.search(rf'(?:^|\s){pat}(?:\s|$)', name, re.IGNORECASE):
            if s.upper() in ("UHD BLURAY", "UHD.BLURAY"):
                source = "BluRay"
            else:
                source = _normalize_source(s)
            name = re.sub(rf'(?:^|\s){pat}(?:\s|$)', ' ', name, flags=re.IGNORECASE)
            name = _ws(name)
            break

    # Combine qualificatif + source principale : ex. "4KLight.BluRay"
    if source_qual and source:
        source = f"{source_qual}.{source}"
    elif source_qual:
        source = source_qual

    if re.search(r'(?:^|\s)REMUX(?:\s|$)', name, re.IGNORECASE):
        remux = "REMUX"
        name = _remove_token(name, "REMUX")

    for leftover in ("Netflix", "hdlight", "mHD", "NF", "AMZN", "DSNP", "HULU", "ATVP", "PCOK",
                     "Disney", "AppleTV", "Paramount", "HMAX", "HBO",
                     "READNFO", "DUAL", "CR", "Sub", "DOC"):
        name = _remove_token(name, leftover)

    # Langues étrangères non-FR orphelines (mHDgz style: "FR EN" → FR traité, EN reste)
    # Note: pas DE (conflit avec "de" français), ni IT (conflit avec titres)
    for foreign_lang in ("EN", "KO", "JA", "ES", "PT", "RU", "ZH", "NL"):
        name = _remove_token(name, foreign_lang)

    # NCH (2CH, 6CH, 8CH) → extraire comme info audio si pas encore de codec audio
    # Les règles G3MINI les listent comme formats de canaux valides
    nch_match = re.search(r'(?:^|\s)(\d+CH)(?:\s|$)', name, re.IGNORECASE)
    if nch_match:
        nch_val = nch_match.group(1).upper()
        name = _remove_token(name, nch_match.group(1))
        # Stocké temporairement, sera ajouté à l'audio en step 13 si pas de codec audio
        _nch_token = nch_val
    else:
        _nch_token = ""

    # ── 13. Audio — par famille indépendante (multi-codec possible) ───────────
    audio_parts = []

    # Famille DTS
    if re.search(r'DTS-HDMA|DTS[-. ]?HD[-. ]?MA', name, re.IGNORECASE):
        name = re.sub(r'DTS-HDMA|DTS[-. ]?HD[-. ]?MA', ' ', name, flags=re.IGNORECASE)
        name = _ws(name)
        mo = re.search(r'(?:^|\s)([0-9][.][0-9])(?:\s|$)', name)
        dts_ch = f".{mo.group(1)}" if mo else ""
        if mo:
            name = re.sub(r'(?:^|\s)[0-9][.][0-9](?:\s|$)', ' ', name)
        audio_parts.append(f"DTS-HDMA{dts_ch}")

    elif re.search(r'DTS-HDHRA|DTS[-. ]?HD[-. ]?HRA', name, re.IGNORECASE):
        name = re.sub(r'DTS-HDHRA|DTS[-. ]?HD[-. ]?HRA', ' ', name, flags=re.IGNORECASE)
        name = _ws(name)
        mo = re.search(r'(?:^|\s)([0-9][.][0-9])(?:\s|$)', name)
        dts_ch = f".{mo.group(1)}" if mo else ""
        if mo:
            name = re.sub(r'(?:^|\s)[0-9][.][0-9](?:\s|$)', ' ', name)
        audio_parts.append(f"DTS-HD.HRA{dts_ch}")

    elif re.search(r'(?:^|\s)DTS-HD(?:\s|$)', name, re.IGNORECASE):
        name = _remove_token(name, "DTS-HD")
        mo = re.search(r'(?:^|\s)([0-9][.][0-9])(?:\s|$)', name)
        dts_ch = f".{mo.group(1)}" if mo else ""
        if mo:
            name = re.sub(r'(?:^|\s)[0-9][.][0-9](?:\s|$)', ' ', name)
        audio_parts.append(f"DTS-HD{dts_ch}")

    elif re.search(r'(?:^|\s)(?:AC3-DTS|DTS-AC3)(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("DTS")
        name = re.sub(r'(?:^|\s)(?:AC3-DTS|DTS-AC3)(?:\s|$)', ' ', name, flags=re.IGNORECASE)

    elif re.search(r'(?:^|\s)DTS(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("DTS")
        name = _remove_token(name, "DTS")

    # Famille TrueHD / Atmos
    if re.search(r'(?:^|\s)TrueHD\s+Atmos(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("TrueHD.Atmos")
        name = re.sub(r'(?:^|\s)TrueHD\s+Atmos(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)TrueHD(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("TrueHD")
        name = _remove_token(name, "TrueHD")
        if re.search(r'(?:^|\s)Atmos(?:\s|$)', name, re.IGNORECASE):
            audio_parts[-1] = "TrueHD.Atmos"
            name = _remove_token(name, "Atmos")
    elif re.search(r'(?:^|\s)Atmos(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("Atmos")
        name = _remove_token(name, "Atmos")

    # Famille DDP
    if re.search(r'(?:^|\s)DDP\s*7\.1(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("DDP7.1")
        name = re.sub(r'(?:^|\s)DDP\s*7\.1(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)DDP\s*5\.1(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("DDP5.1")
        name = re.sub(r'(?:^|\s)DDP\s*5\.1(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)DDP\s*2\.0(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("DDP2.0")
        name = re.sub(r'(?:^|\s)DDP\s*2\.0(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)DDP(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("DDP")
        name = _remove_token(name, "DDP")

    # Famille AC3
    if re.search(r'(?:^|\s)AC3[-. ][0-9]', name, re.IGNORECASE):
        audio_parts.append("AC3")
        name = re.sub(r'(?:^|\s)AC3[-. ][0-9](?:[. ][0-9])?(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)AC3(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("AC3")
        name = _remove_token(name, "AC3")

    # Famille AAC
    if re.search(r'(?:^|\s)AAC\s*5\.1(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("AAC5.1")
        name = re.sub(r'(?:^|\s)AAC\s*5\.1(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)AAC\s*2\.0(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("AAC2.0")
        name = re.sub(r'(?:^|\s)AAC\s*2\.0(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)AAC(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("AAC")
        name = _remove_token(name, "AAC")

    # Famille OPUS
    if re.search(r'(?:^|\s)OPUS\s*7\.1(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("OPUS7.1")
        name = re.sub(r'(?:^|\s)OPUS\s*7\.1(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)OPUS\s*5\.1(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("OPUS5.1")
        name = re.sub(r'(?:^|\s)OPUS\s*5\.1(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)OPUS\s*2\.0(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("OPUS2.0")
        name = re.sub(r'(?:^|\s)OPUS\s*2\.0(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    elif re.search(r'(?:^|\s)OPUS(?:\s|$)', name, re.IGNORECASE):
        audio_parts.append("OPUS")
        name = _remove_token(name, "OPUS")

    # Channel tokens orphelins résiduels
    name = re.sub(r'(?:^|\s)[0-9][.][0-9](?:\s|$)', ' ', name)

    # Film muet : on vide le codec audio
    if lang == "MUET":
        audio_parts = []

    # Si NCH détecté et pas de codec audio, l'ajouter comme info canal
    if _nch_token and not audio_parts:
        audio_parts.append(_nch_token)

    audio = '.'.join(audio_parts)

    # ── 14. Codec vidéo ───────────────────────────────────────────────────────
    codec = ""
    for c_pat, c_norm in _CODEC_LIST:
        if re.search(rf'(?:^|\s){c_pat}(?:\s|$)', name, re.IGNORECASE):
            codec = c_norm
            # Suppression via le pattern (c_pat peut contenir des chars regex)
            name = re.sub(rf'(?:^|\s){c_pat}(?:\s|$)', ' ', name, flags=re.IGNORECASE)
            name = _ws(name)
            break

    # Nettoyage codecs redondants (ex: x265 + HEVC dans le même nom)
    for c_pat, _ in _CODEC_LIST:
        name = re.sub(rf'(?:^|\s){c_pat}(?:\s|$)', ' ', name, flags=re.IGNORECASE)
    name = _ws(name)

    # ── 15. Fallback mediainfo si codec manquant ──────────────────────────────
    if not codec and mi:
        codec = _get_codec_from_mediainfo(mi)

    # ── 16. Adaptation codec selon source (convention G3MINI) ─────────────────
    #   REMUX              → HEVC / AVC
    #   WEB / HDTV         → H.265 / H.264  (sauf si MI confirme un vrai encode)
    #   WEBRip/BDRip/TVRip → x265 / x264
    #   BluRay/DVDRip      → inchangé
    if codec:
        is265 = bool(re.fullmatch(r'x265|HEVC|H\.?265', codec, re.IGNORECASE))
        is264 = bool(re.fullmatch(r'x264|AVC|H\.?264',  codec, re.IGNORECASE))
        # Détermine la source "nue" pour la logique de codec (sans le qualificatif)
        base_source = source.split('.')[-1] if source else ""
        # HDLight/4KLight sont des encodes (variantes BDRip) → convention encode
        if source_qual in ("4KLight", "HDLight", "mHD") and base_source in ("BluRay", "", "4KLight", "HDLight", "mHD"):
            base_source = "BDRip"
        # Si le MI confirme un encode via writing library (x264/x265), on ne
        # remplace pas par H.264/H.265 même sur source WEB/HDTV.
        mi_is_encode = _has_encode_library(mi) if mi else False
        if is265:
            if remux == "REMUX":                                     codec = "HEVC"
            elif base_source in ("WEB", "HDTV") and not mi_is_encode: codec = "H.265"
            elif base_source in ("WEBRip", "BDRip", "TVRip"):       codec = "x265"
        elif is264:
            if remux == "REMUX":                                     codec = "AVC"
            elif base_source in ("WEB", "HDTV") and not mi_is_encode: codec = "H.264"
            elif base_source in ("WEBRip", "BDRip", "TVRip"):       codec = "x264"

    # ── 17. Titre = résidu ────────────────────────────────────────────────────
    name = re.sub(r'\([^)]*\)', '', name)
    title = _clean_title(name)

    # ── Reconstruction ────────────────────────────────────────────────────────
    new = title
    if year:        new += f".{year}"
    if is_3d:       new += ".3D"
    if type_3d:     new += f".{type_3d}"
    if extras:      new += extras        # commence déjà par '.'
    if lang:        new += f".{lang}"
    if res:         new += f".{res}"
    if bit_depth:   new += f".{bit_depth}"
    if hdr:         new += f".{hdr}"
    if source:      new += f".{source}"
    if full_disc:   new += f".{full_disc}"
    if remux:       new += f".{remux}"
    if audio:       new += f".{audio}"
    if codec:       new += f".{codec}"
    if team:        new += f"-{team}"
    new += ext

    new = re.sub(r'\.{2,}', '.', new)
    return new


# ══════════════════════════════════════════════════════════════════════════════
#  POINT D'ENTRÉE PUBLIC
# ══════════════════════════════════════════════════════════════════════════════

def normalize_release_name(
    release_name: str,
    mediainfo_text: Optional[str] = None,
    is_silent: bool = False,
) -> str:
    return _parse_release(release_name, mediainfo_text, is_silent)