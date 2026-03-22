# -*- coding: utf-8 -*-
"""
validators — Validation des releases selon les règles du tracker G3MINI

Modules :
  - naming_validator    : Règles de nommage (nommage.md)
  - encoding_validator  : Règles d'encodage (encodage.md)
  - upload_validator    : Règles d'upload (upload.md)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from rich.table import Table

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Résultat d'une vérification de règle."""
    rule: str           # ex: "encoding.crf_range"
    severity: str       # "ERROR", "WARNING", "INFO"
    message: str        # Explication lisible
    source_doc: str     # "nommage", "encodage", "upload"


class BaseValidator(ABC):
    """Classe de base pour tous les validators."""

    @abstractmethod
    def validate(
        self,
        media,                              # unit3dup.media.Media
        mediafile,                          # common.mediainfo.MediaFile | None
        release_name: str,
        mediainfo_text: Optional[str] = None,
    ) -> list[ValidationResult]:
        ...


class ValidationRunner:
    """Agrégateur : exécute une liste de validators et produit un rapport."""

    _SEVERITY_STYLE = {
        "ERROR":   "[bold red]ERROR[/bold red]",
        "WARNING": "[bold yellow]WARN[/bold yellow]",
        "INFO":    "[cyan]INFO[/cyan]",
    }

    def __init__(self, validators: list[BaseValidator]):
        self._validators = validators
        self._results: list[ValidationResult] = []

    def validate(
        self,
        media,
        mediafile,
        release_name: str,
        mediainfo_text: Optional[str] = None,
    ) -> list[ValidationResult]:
        self._results = []
        for v in self._validators:
            try:
                self._results.extend(
                    v.validate(media, mediafile, release_name, mediainfo_text)
                )
            except Exception as e:
                logger.warning("Validator %s failed: %s", v.__class__.__name__, e)
        return self._results

    def has_errors(self) -> bool:
        return any(r.severity == "ERROR" for r in self._results)

    def has_warnings(self) -> bool:
        return any(r.severity == "WARNING" for r in self._results)

    def print_report(self, console) -> None:
        """Affiche un tableau Rich des résultats."""
        if not self._results:
            return

        table = Table(title="Validation Report", show_lines=False)
        table.add_column("Sev", style="bold", width=7)
        table.add_column("Rule", min_width=25)
        table.add_column("Message")
        table.add_column("Doc", width=10)

        for r in self._results:
            sev_display = self._SEVERITY_STYLE.get(r.severity, r.severity)
            table.add_row(sev_display, r.rule, r.message, r.source_doc)

        console.print(table)

        errors = sum(1 for r in self._results if r.severity == "ERROR")
        warnings = sum(1 for r in self._results if r.severity == "WARNING")
        infos = sum(1 for r in self._results if r.severity == "INFO")
        console.print(
            f"  [bold red]{errors} error(s)[/bold red]  "
            f"[bold yellow]{warnings} warning(s)[/bold yellow]  "
            f"[cyan]{infos} info(s)[/cyan]"
        )

    def to_dicts(self) -> list[dict]:
        """Serialize results to plain dicts for JSON storage."""
        return [
            {"severity": r.severity, "rule": r.rule, "message": r.message, "doc": r.source_doc}
            for r in self._results
        ]


def create_default_validators() -> list[BaseValidator]:
    """Factory : retourne la liste de tous les validators actifs."""
    from unit3dup.validators.naming_validator import NamingValidator
    from unit3dup.validators.encoding_validator import EncodingValidator
    from unit3dup.validators.upload_validator import UploadValidator

    return [
        NamingValidator(),
        EncodingValidator(),
        UploadValidator(),
    ]
