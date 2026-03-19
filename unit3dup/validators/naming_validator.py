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
