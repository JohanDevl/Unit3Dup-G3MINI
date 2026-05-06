# -*- coding: utf-8 -*-
"""
naming_validator.py — Validation des règles de nommage (nommage.md)
"""

from typing import Optional
import re

from unit3dup.validators import BaseValidator, ValidationResult


class NamingValidator(BaseValidator):
    """Validator pour les règles de nommage G3MINI."""

    def validate(
        self,
        media,
        mediafile,
        release_name: str,
        mediainfo_text: Optional[str] = None,
    ) -> list[ValidationResult]:
        """
        Valide le nommage selon les règles :
        - Check 1: 3D content detection
        - Check 2: Audio Description detection
        - Check 3: CUSTOM tag suggestion
        - Check 4: NoGRP/NoTAG for unknown teams
        """
        results: list[ValidationResult] = []

        try:
            # Check 1: 3D content detection
            results.extend(self._check_3d_tag(mediafile, release_name))

            # Check 2: Audio Description detection
            results.extend(self._check_ad_tag(mediafile, release_name))

            # Check 3: CUSTOM tag suggestion
            results.extend(self._check_custom_tag(mediafile, release_name))

            # Check 4: NoGRP/NoTAG for unknown teams
            results.extend(self._check_nogrp_tag(release_name))

            # Check 5: Reject releases with invalid team (NoTag, NoGRP, or year)
            results.extend(self._check_invalid_team(release_name))

            # Check 6: HARDSUB content requires SUBFRENCH tag (upload.md §3)
            results.extend(self._check_hardsub_tag(release_name))

            # Check 7: MULTi invariant — VO + VF + ST FR (encodage.md §1)
            results.extend(self._check_multi_invariant(mediafile, release_name))

        except Exception:
            # Wrap all checks in try/except to be safe
            pass

        return results

    def _check_3d_tag(
        self, mediafile, release_name: str
    ) -> list[ValidationResult]:
        """Check 1: 3D content detection."""
        results: list[ValidationResult] = []

        if mediafile is None:
            return results

        # Check if 3D content (multiview_count > 1)
        try:
            is_3d = (
                hasattr(mediafile, 'multiview_count') and
                mediafile.multiview_count is not None and
                mediafile.multiview_count > 1
            )
        except Exception:
            is_3d = False

        if not is_3d:
            return results

        # Check if any 3D tag exists in release_name (dots as separators)
        tags_3d = ("3D", "SBS", "HSBS", "TAB", "HTAB", "MVC")
        has_3d_tag = any(
            re.search(rf'(?:^|[\s.])' + re.escape(tag) + r'(?:[\s.]|$)', release_name, re.IGNORECASE)
            for tag in tags_3d
        )

        if not has_3d_tag:
            results.append(
                ValidationResult(
                    rule="naming.3d_tag",
                    severity="WARNING",
                    message="3D content detected but no 3D tag found in release name",
                    source_doc="nommage",
                )
            )

        return results

    def _check_ad_tag(self, mediafile, release_name: str) -> list[ValidationResult]:
        """Check 2: Audio Description detection."""
        results: list[ValidationResult] = []

        if mediafile is None:
            return results

        # Check for visually impaired audio
        has_ad_audio = False
        try:
            if hasattr(mediafile, 'audio_formats') and mediafile.audio_formats:
                for audio in mediafile.audio_formats:
                    if isinstance(audio, dict):
                        service_kind = audio.get('service_kind', '')
                        if service_kind and 'visually impaired' in service_kind.lower():
                            has_ad_audio = True
                            break
        except Exception:
            pass

        if not has_ad_audio:
            return results

        # Check if AD tag exists in release_name (word boundary via dots/spaces)
        has_ad_tag = bool(re.search(r'(?:^|[\s.])AD(?:[\s.]|$)', release_name, re.IGNORECASE))

        if not has_ad_tag:
            results.append(
                ValidationResult(
                    rule="naming.ad_tag",
                    severity="WARNING",
                    message="Audio Description track detected but no AD tag in release name",
                    source_doc="nommage",
                )
            )

        return results

    def _check_custom_tag(
        self, mediafile, release_name: str
    ) -> list[ValidationResult]:
        """Check 3: CUSTOM tag suggestion."""
        results: list[ValidationResult] = []

        if mediafile is None:
            return results

        # Check for audio delay
        has_delay = False
        try:
            if hasattr(mediafile, 'audio_formats') and mediafile.audio_formats:
                for audio in mediafile.audio_formats:
                    if isinstance(audio, dict):
                        delay = audio.get('delay')
                        if delay is not None and delay != 0:
                            has_delay = True
                            break
        except Exception:
            pass

        if not has_delay:
            return results

        # Check if CUSTOM tag exists in release_name
        has_custom_tag = "CUSTOM" in release_name.upper()

        if not has_custom_tag:
            results.append(
                ValidationResult(
                    rule="naming.custom_tag",
                    severity="INFO",
                    message="Audio delay detected, consider adding CUSTOM tag",
                    source_doc="nommage",
                )
            )

        return results

    # Suffixes audio hyphenés qui ne sont PAS des tags de team
    _AUDIO_HYPHEN_SUFFIXES = {"HDMA", "HDHRA", "HD", "AC3"}

    # Placeholders that indicate no real release group (acceptable per upload.md §1).
    _PLACEHOLDER_TEAMS = {"NOTAG", "NOGRP"}

    def _check_invalid_team(self, release_name: str) -> list[ValidationResult]:
        """Check 5: Reject releases whose team is a year.

        NoTag/NoGRP placeholders are ALLOWED by upload.md §1 for unknown releases,
        so they are not flagged here (they are merely the fallback, not an error).
        """
        name_no_ext = re.sub(r'\.(mkv|mp4|avi|ts|m2ts|iso)$', '', release_name, flags=re.IGNORECASE)
        m = re.search(r'-([A-Za-z0-9]{2,})$', name_no_ext)
        if not m:
            return []

        team = m.group(1)
        if team.upper() in self._AUDIO_HYPHEN_SUFFIXES:
            return []

        if team.upper() in self._PLACEHOLDER_TEAMS:
            # Accepted placeholder — compliant with docs.
            return []

        if re.fullmatch(r'(?:19|20)\d{2}', team):
            return [ValidationResult(
                rule="naming.invalid_team",
                severity="ERROR",
                message=f"Release team appears to be a year ({team}) — missing release group",
                source_doc="upload",
            )]

        return []

    # ── Check 6: HARDSUB → SUBFRENCH ──────────────────────────────────────
    # upload.md §3: "Les sous-titres incrustes HARDSUBS sont interdits.
    # Sauf si presents dans la source officielle. Dans ce cas, utiliser le tag SUBFRENCH."
    def _check_hardsub_tag(self, release_name: str) -> list[ValidationResult]:
        has_hardsub = bool(re.search(
            r'(?:^|[\s.])(?:HARDSUBS?|HC)(?:[\s.]|$)',
            release_name, re.IGNORECASE,
        ))
        if not has_hardsub:
            return []
        has_subfrench = bool(re.search(
            r'(?:^|[\s.])SUBFRENCH(?:[\s.]|$)',
            release_name, re.IGNORECASE,
        ))
        if has_subfrench:
            return []
        return [ValidationResult(
            rule="naming.hardsub_subfrench",
            severity="ERROR",
            message="HARDSUB detected without SUBFRENCH tag — hardsubs are forbidden unless sourced officially (then use SUBFRENCH)",
            source_doc="upload",
        )]

    # ── Check 7: MULTi invariant (VO + VF + ST FR) ────────────────────────
    # encodage.md §1: "Une release MULTi contient au minimum la VO, la VF
    # et les sous-titres FR complets"
    def _check_multi_invariant(self, mediafile, release_name: str) -> list[ValidationResult]:
        if not re.search(r'(?:^|[\s.])MULTi(?:[\s.]|$)', release_name, re.IGNORECASE):
            return []
        if mediafile is None:
            return []

        audio_langs = []
        try:
            for a in (getattr(mediafile, 'audio_formats', None) or []):
                if isinstance(a, dict):
                    audio_langs.append(str(a.get('language', '')).strip().lower())
        except Exception:
            return []

        sub_langs = []
        try:
            for s in (getattr(mediafile, 'subtitle_formats', None) or []):
                if isinstance(s, dict):
                    sub_langs.append(str(s.get('language', '')).strip().lower())
        except Exception:
            sub_langs = []

        # Need at least 2 audio tracks for MULTi
        if len(audio_langs) < 2:
            return []  # Not enough info; skip silently

        def _is_fr(lang: str) -> bool:
            return lang.startswith('fr') or lang.startswith('french')

        has_fr_audio = any(_is_fr(l) for l in audio_langs)
        has_non_fr_audio = any(l and not _is_fr(l) and l != 'zxx' for l in audio_langs)
        has_fr_sub = any(_is_fr(l) for l in sub_langs)

        missing = []
        if not has_non_fr_audio: missing.append("VO audio")
        if not has_fr_audio:     missing.append("VF audio")
        if not has_fr_sub:       missing.append("FR subtitles")
        if missing:
            return [ValidationResult(
                rule="naming.multi_invariant",
                severity="WARNING",
                message=f"MULTi tag requires VO + VF + FR subtitles; missing: {', '.join(missing)}",
                source_doc="encodage",
            )]
        return []

    def _check_nogrp_tag(self, release_name: str) -> list[ValidationResult]:
        """Check 4: Releases without team should have NoGRP or NoTAG."""
        name_no_ext = re.sub(r'\.(mkv|mp4|avi|ts|m2ts|iso)$', '', release_name, flags=re.IGNORECASE)
        m = re.search(r'-([A-Za-z0-9]{2,})$', name_no_ext)
        has_team = bool(m) and m.group(1).upper() not in self._AUDIO_HYPHEN_SUFFIXES
        has_nogrp = bool(re.search(r'(?:^|[\s.])(?:NoGRP|NoTAG)(?:[\s.]|$)', release_name, re.IGNORECASE))

        if not has_team and not has_nogrp:
            return [ValidationResult(
                rule="naming.nogrp_tag",
                severity="WARNING",
                message="No team tag found — unknown releases must be tagged NoGRP or NoTAG",
                source_doc="upload",
            )]
        return []
