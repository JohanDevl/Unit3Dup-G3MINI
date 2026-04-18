# -*- coding: utf-8 -*-
"""
encoding_validator.py — Validation des règles d'encodage (encodage.md)
"""

import re
from typing import Optional

from unit3dup.validators import BaseValidator, ValidationResult

_X264_PRESET_ORDER = [
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow", "placebo",
]
_X265_PRESET_ORDER = [
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow", "placebo",
]

_CRF_RANGES = {
    "x264": {"720p": (16, 20), "1080p": (17, 21)},
    "x265": {"720p": (18, 22), "1080p": (20, 24), "2160p": (22, 26)},
    "AV1":  {"720p": (24, 28), "1080p": (26, 30), "2160p": (28, 32)},
}


def _parse_encoding_settings(text: str) -> dict[str, str]:
    """Parse x264/x265 encoding_settings strings (key=value / key=value)."""
    if not text:
        return {}
    result = {}
    parts = text.split(" / ")
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _detect_source_type(release_name: str) -> str:
    name_upper = release_name.upper()
    if any(p in name_upper for p in ("BDRIP", "WEBRIP", "TVRIP", "HDLIGHT", "4KLIGHT", "HDRIP")):
        return "encode"
    # Encoder-library tags (lowercase x264/x265, AV1) are scene convention
    # for a re-encode. REMUX releases use HEVC/H.265/H.264 — never x264/x265.
    # Match on word boundaries so "X265" in "X265-GROUP" or ".x265." matches
    # but e.g. "HEVC" or "H265" does not trigger.
    if re.search(r'(?:^|[\W_])(?:[xX]26[45]|AV1)(?:$|[\W_])', release_name):
        return "encode"
    if "REMUX" in name_upper:
        return "remux"
    if "WEB" in name_upper and "WEBRIP" not in name_upper:
        return "web"
    if "BLURAY" in name_upper:
        return "bluray"
    if "HDTV" in name_upper:
        return "hdtv"
    return "unknown"


def _detect_codec(release_name: str) -> str:
    name_upper = release_name.upper()
    if "X264" in name_upper:
        return "x264"
    if "X265" in name_upper:
        return "x265"
    if "AV1" in name_upper:
        return "AV1"
    return ""


def _detect_resolution(release_name: str) -> str:
    for r in ("2160p", "1080p", "1080i", "720p"):
        if r in release_name:
            return r
    return ""


class EncodingValidator(BaseValidator):
    """Validator pour les règles d'encodage G3MINI."""

    def validate(
        self,
        media,
        mediafile,
        release_name: str,
        mediainfo_text: Optional[str] = None,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        # Upscale tag check — runs for ALL source types
        results.extend(self._check_upscale_tag(release_name))

        try:
            source_type = _detect_source_type(release_name)
            codec = _detect_codec(release_name)
            resolution = _detect_resolution(release_name)

            if source_type == "encode":
                results.extend(self._check_crf_range(mediafile, codec, resolution))
                results.extend(self._check_preset_minimum(mediafile, codec))
                results.extend(self._check_x264_2160p(codec, resolution))
                results.extend(self._check_pgs_vobsub(mediafile))
                results.extend(self._check_hdr_metadata(release_name, mediafile))
                results.extend(self._check_abr_cbr(mediafile))
                results.extend(self._check_upscale(mediafile, resolution))
                results.extend(self._check_crop(mediafile))

            if source_type in ("encode", "remux"):
                results.extend(self._check_container(mediafile))

            results.extend(self._check_forbidden_audio(mediafile))

            # Source-vs-writing-library consistency (encodage.md §1:
            # "Interdiction d'encoder depuis une source deja reencodee")
            results.extend(self._check_source_library_mismatch(source_type, mediafile))

        except Exception:
            pass

        return results

    # ── Check 1: CRF range ─────────────────────────────────────────────────

    def _check_crf_range(self, mediafile, codec: str, resolution: str) -> list[ValidationResult]:
        if not mediafile or not getattr(mediafile, 'encoding_settings', None):
            return []
        if not codec or not resolution:
            return []

        settings = _parse_encoding_settings(mediafile.encoding_settings)
        if "crf" not in settings:
            return []

        # 1080i uses same CRF ranges as 1080p
        lookup_res = "1080p" if resolution == "1080i" else resolution
        crf_range = _CRF_RANGES.get(codec, {}).get(lookup_res)
        if not crf_range:
            return []

        try:
            crf_value = float(settings["crf"])
            lo, hi = crf_range
            if crf_value < lo or crf_value > hi:
                return [ValidationResult(
                    rule="encoding.crf_range",
                    severity="WARNING",
                    message=f"CRF {crf_value} hors plage recommandee ({lo}-{hi}) pour {codec} en {resolution}",
                    source_doc="encodage",
                )]
        except (ValueError, KeyError):
            pass
        return []

    # ── Check 2: Preset minimum ────────────────────────────────────────────

    def _check_preset_minimum(self, mediafile, codec: str) -> list[ValidationResult]:
        if not mediafile or not getattr(mediafile, 'encoding_settings', None):
            return []

        settings = _parse_encoding_settings(mediafile.encoding_settings)
        preset = settings.get("preset", "").lower()
        if not preset:
            return []

        if codec == "x264":
            order = _X264_PRESET_ORDER
            min_idx = 6  # "slow"
            min_name = "slow"
        elif codec == "x265":
            order = _X265_PRESET_ORDER
            min_idx = 5  # "medium"
            min_name = "medium"
        elif codec == "AV1":
            # SVT-AV1 uses numeric presets: lower = slower = better
            # Minimum preset 4 (Slower) — higher number = faster = worse
            try:
                preset_num = int(preset)
                if preset_num > 4:
                    return [ValidationResult(
                        rule="encoding.preset_minimum",
                        severity="WARNING",
                        message=f"AV1 preset {preset_num} trop rapide (minimum: 4/Slower)",
                        source_doc="encodage",
                    )]
            except ValueError:
                pass
            return []
        else:
            return []

        try:
            idx = order.index(preset)
            if idx < min_idx:
                return [ValidationResult(
                    rule="encoding.preset_minimum",
                    severity="WARNING",
                    message=f"Preset '{preset}' trop rapide pour {codec} (minimum: {min_name})",
                    source_doc="encodage",
                )]
        except ValueError:
            pass
        return []

    # ── Check 3: x264 at 2160p ─────────────────────────────────────────────

    @staticmethod
    def _check_x264_2160p(codec: str, resolution: str) -> list[ValidationResult]:
        if codec == "x264" and resolution == "2160p":
            return [ValidationResult(
                rule="encoding.x264_2160p",
                severity="WARNING",
                message="x264 deconseille en 2160p",
                source_doc="encodage",
            )]
        return []

    # ── Check 4: Container .mkv ────────────────────────────────────────────

    @staticmethod
    def _check_container(mediafile) -> list[ValidationResult]:
        if not mediafile or not getattr(mediafile, 'container_format', None):
            return []
        if mediafile.container_format != ".mkv":
            return [ValidationResult(
                rule="encoding.container_mkv",
                severity="ERROR",
                message=f"Container doit etre .mkv, detecte: {mediafile.container_format}",
                source_doc="encodage",
            )]
        return []

    # ── Check 5: Forbidden audio codecs ────────────────────────────────────

    @staticmethod
    def _check_forbidden_audio(mediafile) -> list[ValidationResult]:
        if not mediafile or not getattr(mediafile, 'audio_formats', None):
            return []

        results = []
        for track in mediafile.audio_formats:
            fmt = track.get("format", "").upper()
            channels = track.get("channels", 0)
            try:
                channels = int(channels)
            except (ValueError, TypeError):
                channels = 0

            if fmt in ("MPEG AUDIO", "MP3"):
                results.append(ValidationResult(
                    rule="encoding.forbidden_audio",
                    severity="ERROR",
                    message="MP3 interdit",
                    source_doc="encodage",
                ))
                break

            if fmt == "FLAC" and channels > 2:
                results.append(ValidationResult(
                    rule="encoding.forbidden_audio",
                    severity="ERROR",
                    message=f"FLAC interdit pour surround ({channels} canaux)",
                    source_doc="encodage",
                ))
                break

        return results

    # ── Check 6: PGS/VOBSUB subtitles ─────────────────────────────────────

    @staticmethod
    def _check_pgs_vobsub(mediafile) -> list[ValidationResult]:
        if not mediafile or not getattr(mediafile, 'subtitle_formats', None):
            return []

        has_pgs_vobsub = False
        has_text = False
        for track in mediafile.subtitle_formats:
            fmt = track.get("format", "").upper()
            if fmt in ("PGS", "VOBSUB"):
                has_pgs_vobsub = True
            if fmt in ("UTF-8", "ASS", "SSA", "SUBRIP"):
                has_text = True

        if has_pgs_vobsub and not has_text:
            return [ValidationResult(
                rule="encoding.pgs_vobsub_encode",
                severity="WARNING",
                message="PGS/VobSub sans sous-titres texte (SRT/ASS) — interdit pour les encodes",
                source_doc="encodage",
            )]
        return []

    # ── Check 7: HDR metadata ──────────────────────────────────────────────

    @staticmethod
    def _check_hdr_metadata(release_name: str, mediafile) -> list[ValidationResult]:
        hdr_tokens = ("HDR", "HDR10", "HDR10P", "DV", "HLG", "HYBRID")
        if not any(t in release_name.upper() for t in hdr_tokens):
            return []
        if not mediafile:
            return []

        issues = []

        bit_depth = getattr(mediafile, 'video_bit_depth', None)
        if bit_depth and bit_depth != "Unknown":
            try:
                if int(str(bit_depth).split()[0]) < 10:
                    issues.append("bit depth < 10")
            except (ValueError, AttributeError):
                pass

        color = getattr(mediafile, 'color_primaries', None)
        if color and "BT.2020" not in str(color):
            issues.append("color primaries != BT.2020")

        transfer = getattr(mediafile, 'transfer_characteristics', None)
        if transfer:
            t_upper = str(transfer).upper()
            if "PQ" not in t_upper and "2084" not in t_upper and "HLG" not in t_upper:
                issues.append("transfer characteristics manquantes (PQ/2084/HLG)")

        if issues:
            return [ValidationResult(
                rule="encoding.hdr_metadata",
                severity="WARNING",
                message=f"HDR metadata: {'; '.join(issues)}",
                source_doc="encodage",
            )]
        return []

    # ── Check 8: ABR 1-pass / CBR ──────────────────────────────────────────

    @staticmethod
    def _check_abr_cbr(mediafile) -> list[ValidationResult]:
        if not mediafile or not getattr(mediafile, 'encoding_settings', None):
            return []

        settings = _parse_encoding_settings(mediafile.encoding_settings)

        # CRF mode is fine
        if "crf" in settings:
            return []

        # 2-pass ABR is fine
        if "pass" in settings:
            return []

        # If we have bitrate/rc settings but no CRF and no 2-pass → likely ABR 1-pass or CBR
        rc = settings.get("rc", "").lower()
        if rc == "cbr":
            return [ValidationResult(
                rule="encoding.abr_cbr",
                severity="ERROR",
                message="Encodage CBR interdit — utiliser CRF",
                source_doc="encodage",
            )]

        # Only flag if we see explicit bitrate evidence without CRF
        if "bitrate" in settings or "vbv-maxrate" in settings:
            return [ValidationResult(
                rule="encoding.abr_cbr",
                severity="ERROR",
                message="ABR 1-pass detecte — utiliser CRF ou ABR 2-pass",
                source_doc="encodage",
            )]

        return []

    # ── Check 9: Upscale tag in release name ────────────────────────────────

    @staticmethod
    def _check_upscale_tag(release_name: str) -> list[ValidationResult]:
        if re.search(r'UpScal', release_name, re.IGNORECASE):
            return [ValidationResult(
                rule="encoding.upscale_forbidden",
                severity="ERROR",
                message="Contenu upscale interdit — aucun upscale autorise",
                source_doc="encodage",
            )]
        return []

    # ── Check 12: Crop (no black borders) ──────────────────────────────────
    # encodage.md §1: "Les videos doivent etre crop (aucune bordure noire)".
    # Reliable detection from MediaInfo alone is limited. Heuristic:
    # encode stored as full 16:9 (1920×1080 / 3840×2160 / 1280×720) for a
    # movie with typical cinema aspect (>= 1.85:1) strongly suggests bars.
    # We only flag the most obvious cases as INFO (manual review required).
    @staticmethod
    def _check_crop(mediafile) -> list[ValidationResult]:
        if not mediafile:
            return []
        try:
            w = int(str(getattr(mediafile, 'video_width', '') or '').split()[0])
            h = int(str(getattr(mediafile, 'video_height', '') or '').split()[0])
        except (ValueError, AttributeError, IndexError):
            return []
        if not w or not h:
            return []
        # Only flag strict 16:9 standard resolutions — bars can't be detected
        # reliably without content analysis, so we just alert on suspicious
        # exact 16:9 when aspect ratio metadata hints at wider content.
        ratio = w / h
        if abs(ratio - (16 / 9)) > 0.02:
            return []  # Not 16:9, already likely cropped
        dar = str(getattr(mediafile, 'video_aspect_ratio', '') or '').lower()
        # If DAR explicitly reports >= 1.85 cinematic ratios, bars are likely.
        if any(hint in dar for hint in ("2.35", "2.39", "2.40", "21:9", "1.85", "1.90")):
            return [ValidationResult(
                rule="encoding.crop_suspected",
                severity="INFO",
                message=f"Video stored 16:9 ({w}x{h}) but DAR={dar} — possible black borders, verify crop",
                source_doc="encodage",
            )]
        return []

    # ── Check 11: Source tag vs writing library mismatch ───────────────────
    # encodage.md §1: untouched sources (REMUX, FULL, BluRay, WEB-DL, HDTV)
    # must NOT come from an already re-encoded file. If the file carries an
    # x264/x265 writing library but the release is tagged as untouched, the
    # source is effectively a re-encode — which is forbidden.
    @staticmethod
    def _check_source_library_mismatch(source_type: str, mediafile) -> list[ValidationResult]:
        if source_type not in ("remux", "web", "bluray", "hdtv"):
            return []
        if not mediafile:
            return []
        lib = getattr(mediafile, 'writing_library', None)
        if not lib:
            return []
        lib_upper = str(lib).upper()
        if lib_upper.startswith("X264") or lib_upper.startswith("X265"):
            return [ValidationResult(
                rule="encoding.source_reencoded",
                severity="ERROR",
                message=f"Source taguee untouched ({source_type}) mais writing library = {lib} — encodage depuis une source deja reencodee est interdit",
                source_doc="encodage",
            )]
        return []

    # ── Check 10: Upscale detection (height-based) ──────────────────────────

    @staticmethod
    def _check_upscale(mediafile, resolution: str) -> list[ValidationResult]:
        if not mediafile or not resolution:
            return []

        # Map tagged resolution to expected max height
        res_map = {"2160p": 2160, "1080p": 1080, "1080i": 1080, "720p": 720}
        expected_height = res_map.get(resolution)
        if not expected_height:
            return []

        actual_height = getattr(mediafile, 'video_height', None)
        if actual_height is None:
            return []

        try:
            actual_height = int(actual_height)
        except (ValueError, TypeError):
            return []

        # If actual height significantly exceeds what the source type would normally provide,
        # and actual height matches the tagged resolution, we can't detect upscale from height alone.
        # But if actual height is LESS than tagged → possible wrong tag (not upscale).
        # If actual height matches but source is suspicious (e.g., WEB at 2160p for x264), that's
        # already covered by x264_2160p check.
        # Real upscale detection: if stored_height < height (rare in MediaInfo)
        # For now: warn if actual height doesn't match tagged resolution
        if actual_height < expected_height * 0.9:
            return [ValidationResult(
                rule="encoding.upscale",
                severity="WARNING",
                message=f"Resolution reelle ({actual_height}p) inferieure a la resolution taguee ({resolution}) — possible upscale",
                source_doc="encodage",
            )]

        return []
