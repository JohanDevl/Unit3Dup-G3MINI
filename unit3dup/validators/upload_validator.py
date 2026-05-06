# -*- coding: utf-8 -*-
"""
upload_validator.py — Validation des règles d'upload (upload.md)
"""

import os
import re
from typing import Optional

from unit3dup.validators import BaseValidator, ValidationResult


class UploadValidator(BaseValidator):
    """Validator pour les règles d'upload G3MINI."""

    def validate(
        self,
        media,
        mediafile,
        release_name: str,
        mediainfo_text: Optional[str] = None,
    ) -> list[ValidationResult]:
        """
        Valide les règles d'upload :
        - Check 1: External subtitle files detection
        - Check 2: Archive files detection
        - Check 3: Season completeness (for packs)
        - Check 4: Multi-format/multi-tag detection
        """
        results: list[ValidationResult] = []

        try:
            # Check 1: External subtitle files
            results.extend(self._check_external_subtitles(media))

            # Check 2: Archive files
            results.extend(self._check_archive_files(media))

            # Check 3: Season completeness
            results.extend(self._check_season_completeness(media))

            # Check 4: Multi-format/multi-tag detection
            results.extend(self._check_multi_format(media))

            # Check 5: Pack consistency — same team and language across files
            results.extend(self._check_pack_consistency(media))

        except Exception:
            pass

        return results

    def _check_external_subtitles(self, media) -> list[ValidationResult]:
        """Check 1: External subtitle files detection."""
        results: list[ValidationResult] = []

        if media is None or not hasattr(media, 'torrent_path'):
            return results

        try:
            torrent_path = media.torrent_path
            if os.path.isfile(torrent_path):
                directory = os.path.dirname(torrent_path)
            else:
                directory = torrent_path

            files = os.listdir(directory)
            subtitle_extensions = ('.srt', '.ass', '.ssa', '.sub')
            video_extensions = ('.mkv', '.mp4', '.avi', '.mov', '.flv', '.wmv')

            has_subtitles = any(
                f.lower().endswith(subtitle_extensions) for f in files
            )
            has_videos = any(
                f.lower().endswith(video_extensions) for f in files
            )

            if has_subtitles and has_videos:
                results.append(
                    ValidationResult(
                        rule="upload.external_subtitles",
                        severity="ERROR",
                        message="Fichiers sous-titres externes detectes - ils doivent etre muxes dans le MKV",
                        source_doc="upload",
                    )
                )

        except Exception:
            pass

        return results

    def _check_archive_files(self, media) -> list[ValidationResult]:
        """Check 2: Archive files detection."""
        results: list[ValidationResult] = []

        if media is None or not hasattr(media, 'torrent_path'):
            return results

        try:
            torrent_path = media.torrent_path
            if os.path.isfile(torrent_path):
                directory = os.path.dirname(torrent_path)
            else:
                directory = torrent_path

            files = os.listdir(directory)
            archive_extensions = ('.rar', '.zip', '.7z', '.tar', '.gz')

            has_archives = any(
                f.lower().endswith(archive_extensions) for f in files
            )

            if has_archives:
                results.append(
                    ValidationResult(
                        rule="upload.archive_files",
                        severity="ERROR",
                        message="Archives interdites dans le torrent",
                        source_doc="upload",
                    )
                )

        except Exception:
            pass

        return results

    def _check_season_completeness(self, media) -> list[ValidationResult]:
        """Check 3: Season completeness (for packs/folders)."""
        results: list[ValidationResult] = []

        if media is None or not hasattr(media, 'torrent_path'):
            return results

        try:
            torrent_path = media.torrent_path
            if not os.path.isdir(torrent_path):
                return results

            files = os.listdir(torrent_path)
            season_episodes: dict[int, list[int]] = {}

            for file in files:
                match = re.search(r'[Ss](\d{1,2})[Ee](\d{1,3})', file)
                if match:
                    season = int(match.group(1))
                    episode = int(match.group(2))
                    if season not in season_episodes:
                        season_episodes[season] = []
                    season_episodes[season].append(episode)

            for season, episodes in season_episodes.items():
                episodes = sorted(set(episodes))
                if len(episodes) > 1:
                    expected = list(range(episodes[0], episodes[-1] + 1))
                    if episodes != expected:
                        results.append(
                            ValidationResult(
                                rule="upload.season_incomplete",
                                severity="WARNING",
                                message=f"Season {season} has gaps in episode numbers",
                                source_doc="upload",
                            )
                        )
                        break

        except Exception:
            pass

        return results

    # upload.md §4:
    #   "Pas de multi-tag (plusieurs teams dans un meme pack)"
    #   "Pas de mix de langues (FRENCH et MULTi dans un meme pack)"
    def _check_pack_consistency(self, media) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        if media is None or not hasattr(media, 'torrent_path'):
            return results
        try:
            torrent_path = media.torrent_path
            if not os.path.isdir(torrent_path):
                return results

            video_ext = ('.mkv', '.mp4', '.avi', '.mov', '.flv', '.wmv', '.ts', '.m2ts')
            teams: set[str] = set()
            lang_categories: set[str] = set()  # "MULTi" or "MONO" (FRENCH/VFF/VFQ/...)

            for file in os.listdir(torrent_path):
                if not any(file.lower().endswith(e) for e in video_ext):
                    continue
                stem = re.sub(r'\.[^.]+$', '', file)

                team_m = re.search(r'-([A-Za-z0-9]{2,})$', stem)
                if team_m:
                    t = team_m.group(1).upper()
                    if t not in ("HDMA", "HDHRA", "HD", "AC3", "NOTAG", "NOGRP"):
                        teams.add(t)

                if re.search(r'(?:^|[\s.])MULTi(?:[\s.]|$)', stem, re.IGNORECASE):
                    lang_categories.add("MULTi")
                elif re.search(r'(?:^|[\s.])(?:FRENCH|VFF|VFQ|VFB|VF2|VOF|VOQ|VOB|VOSTFR)(?:[\s.]|$)', stem, re.IGNORECASE):
                    lang_categories.add("MONO")

            if len(teams) > 1:
                results.append(ValidationResult(
                    rule="upload.multi_team_pack",
                    severity="WARNING",
                    message=f"Multi-team detecte dans le pack: {', '.join(sorted(teams))}",
                    source_doc="upload",
                ))
            if len(lang_categories) > 1:
                results.append(ValidationResult(
                    rule="upload.mixed_languages_pack",
                    severity="WARNING",
                    message="Mix de langues detecte (MULTi + tag mono) dans le meme pack",
                    source_doc="upload",
                ))
        except Exception:
            pass
        return results

    def _check_multi_format(self, media) -> list[ValidationResult]:
        """Check 4: Multi-format/multi-tag detection (for packs)."""
        results: list[ValidationResult] = []

        if media is None or not hasattr(media, 'torrent_path'):
            return results

        try:
            torrent_path = media.torrent_path
            if not os.path.isdir(torrent_path):
                return results

            files = os.listdir(torrent_path)
            video_extensions = ('.mkv', '.mp4', '.avi', '.mov', '.flv', '.wmv')
            resolutions = set()

            for file in files:
                if any(file.lower().endswith(ext) for ext in video_extensions):
                    resolution_match = re.search(r'(\d{3,4})p', file, re.IGNORECASE)
                    if resolution_match:
                        resolutions.add(resolution_match.group(1))

            if len(resolutions) > 1:
                results.append(
                    ValidationResult(
                        rule="upload.multi_format",
                        severity="WARNING",
                        message="Multi-resolution detecte dans le pack",
                        source_doc="upload",
                    )
                )

        except Exception:
            pass

        return results
