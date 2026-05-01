# -*- coding: utf-8 -*-
"""Compliance scanner: fetches past uploads from UnIT3D and validates their
release names against the G3MINI naming rules.

Read-only: never issues PATCH/PUT/DELETE. Edits happen via deep-links to the
UnIT3D web edit page.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urljoin, urlparse

import requests

from common.trackers.data import trackers_api_data
from unit3dup.release_normalizer import normalize_release_name
from unit3dup.state_db import StateDB
from unit3dup.validators.naming_validator import NamingValidator
from unit3dup.validators.encoding_validator import EncodingValidator
from unit3dup.prez import _LANG_NAME_TO_ISO

try:
    from view import custom_console
except Exception:  # pragma: no cover - logging fallback
    class _Noop:
        def bot_log(self, *a, **k): pass
        def bot_warning_log(self, *a, **k): pass
        def bot_error_log(self, *a, **k): pass
    custom_console = _Noop()


# ── Severity ranking ───────────────────────────────────────────────────────

_SEVERITY_ORDER = {"NONE": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
_REVERSE_SEVERITY = {v: k for k, v in _SEVERITY_ORDER.items()}


def _max_severity(severities: list[str]) -> str:
    if not severities:
        return "NONE"
    best = 0
    for s in severities:
        best = max(best, _SEVERITY_ORDER.get(s, 0))
    return _REVERSE_SEVERITY[best]


# ── Mediainfo text parsing ─────────────────────────────────────────────────

_RE_MULTIVIEW = re.compile(r"^\s*MultiView[ _]?Count\s*:\s*(\d+)", re.IGNORECASE | re.MULTILINE)
# Top-level MediaInfo section header. We accept common localizations too so
# a French/Italian/Spanish-generated mediainfo doesn't parse as "0 sections".
_RE_SECTION = re.compile(
    r"^\s*(General|Général|Generale|Video|Vidéo|V[ií]deo|Audio|Text|Texto|Testo|Menu|Men[uú])"
    r"(?:\s*#\d+)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_KV = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_ /()-]*?)\s*:\s*(.+?)\s*$")

# BDInfo dumps use completely different delimiters; parsing them as MediaInfo
# yields 0 audio sections, which would make release_normalizer think the disc
# is silent. We detect them up-front and skip the facts extraction.
_BDINFO_MARKERS = ("DISC INFO:", "Disc Title:", "PLAYLIST REPORT:", "VIDEO:\n")


def _looks_like_bdinfo(text: str) -> bool:
    if not text:
        return False
    head = text[:4096]
    return any(marker in head for marker in _BDINFO_MARKERS)


def extract_mediainfo_text(payload: dict) -> Optional[str]:
    """Prefer the MediaInfo dump; fall back to BDInfo if unset.

    UnIT3D's JSON:API resource exposes these under the snake_case keys
    `media_info` / `bd_info` (see TorrentResource::toArray). Older/custom
    deployments sometimes return the raw DB column names `mediainfo` /
    `bdinfo`, so we accept both.
    """
    for key in ("media_info", "mediainfo"):
        value = payload.get(key)
        if value and isinstance(value, str) and value.strip():
            return value
    for key in ("bd_info", "bdinfo"):
        value = payload.get(key)
        if value and isinstance(value, str) and value.strip():
            return value
    return None


def _iter_sections(mi_text: str) -> Iterator[tuple[str, dict[str, str]]]:
    """Yield (section_name_lower, dict-of-lowercased-keys → raw-values) for each
    top-level MediaInfo section. Works on the human-readable text representation
    returned by pymediainfo --Output=""."""
    lines = mi_text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _RE_SECTION.match(line)
        if not m:
            i += 1
            continue
        section = m.group(1).strip().lower()
        fields: dict[str, str] = {}
        i += 1
        while i < n and not _RE_SECTION.match(lines[i]):
            kv = _RE_KV.match(lines[i])
            if kv:
                key = kv.group(1).strip().lower()
                val = kv.group(2).strip()
                if key and key not in fields:
                    fields[key] = val
            i += 1
        yield section, fields


def mediainfo_facts_from_text(mi_text: str) -> dict:
    """Extract only the facts the naming validator actually uses.

    Returns a dict with:
      - multiview_count: int | None
      - audio_formats: list[{service_kind, delay, language}]
      - audio_track_count: int
      - is_bdinfo: bool (True when we cannot extract MediaInfo-style facts)
    """
    if not mi_text:
        return {"multiview_count": None, "audio_formats": [], "audio_track_count": 0, "is_bdinfo": False}

    # BDInfo uses a different grammar; bail out so callers know not to
    # infer is_silent from a zero audio count.
    if _looks_like_bdinfo(mi_text):
        return {
            "multiview_count": None,
            "audio_formats": [],
            "audio_track_count": 0,
            "is_bdinfo": True,
        }

    multiview = None
    m = _RE_MULTIVIEW.search(mi_text)
    if m:
        try:
            multiview = int(m.group(1))
        except (TypeError, ValueError):
            multiview = None

    audio_formats: list[dict[str, Any]] = []
    subtitle_formats: list[dict[str, Any]] = []
    writing_library: Optional[str] = None
    video_width: Optional[int] = None
    video_height: Optional[int] = None
    video_aspect_ratio: Optional[str] = None
    for section, fields in _iter_sections(mi_text):
        if section == "audio":
            track: dict[str, Any] = {}
            service_kind = fields.get("servicekind") or fields.get("service kind") or ""
            if service_kind:
                track["service_kind"] = service_kind
            delay_raw = (
                fields.get("delay relative to video")
                or fields.get("delay")
                or ""
            )
            if delay_raw:
                num = re.search(r"-?\d+(?:\.\d+)?", delay_raw)
                if num:
                    try:
                        track["delay"] = float(num.group(0))
                    except (TypeError, ValueError):
                        pass
            lang = fields.get("language") or ""
            if lang:
                track["language"] = lang
            audio_formats.append(track)

        elif section == "text":
            lang = fields.get("language") or ""
            fmt = fields.get("format") or ""
            subtitle_formats.append({"language": lang, "format": fmt})

        elif section in ("video", "vidéo", "video"):
            if writing_library is None:
                lib = (
                    fields.get("writing library")
                    or fields.get("encoded library name")
                    or fields.get("encoded_library_name")
                    or ""
                )
                if lib:
                    writing_library = lib
            if video_width is None:
                w_raw = fields.get("width") or ""
                # MediaInfo formats widths as "1 920 pixels" — strip separators
                wm = re.search(r"\d[\d\s\u00a0]*", w_raw)
                if wm:
                    try:
                        video_width = int(re.sub(r"\s", "", wm.group(0)))
                    except ValueError:
                        pass
            if video_height is None:
                h_raw = fields.get("height") or ""
                hm = re.search(r"\d[\d\s\u00a0]*", h_raw)
                if hm:
                    try:
                        video_height = int(re.sub(r"\s", "", hm.group(0)))
                    except ValueError:
                        pass
            if video_aspect_ratio is None:
                ar = fields.get("display aspect ratio") or fields.get("aspect ratio") or ""
                if ar:
                    video_aspect_ratio = ar

    # Multiview fallback: scan Video section too
    if multiview is None:
        for section, fields in _iter_sections(mi_text):
            if section != "video":
                continue
            mv = fields.get("multiview_count") or fields.get("multiview count")
            if mv:
                try:
                    multiview = int(mv)
                    break
                except (TypeError, ValueError):
                    pass

    return {
        "multiview_count": multiview,
        "audio_formats": audio_formats,
        "audio_track_count": len(audio_formats),
        "subtitle_formats": subtitle_formats,
        "writing_library": writing_library,
        "video_width": video_width,
        "video_height": video_height,
        "video_aspect_ratio": video_aspect_ratio,
        "is_bdinfo": False,
    }


@dataclass
class _FakeMediaFile:
    """Duck-typed stand-in for common.mediainfo.MediaFile.

    Exposes only the attributes validators read (naming + encoding)
    so they can run without file access.
    """
    multiview_count: Optional[int] = None
    audio_formats: Optional[list[dict]] = None
    audio_track_count: int = 0
    subtitle_formats: Optional[list[dict]] = None
    writing_library: Optional[str] = None
    video_width: Optional[int] = None
    video_height: Optional[int] = None
    video_aspect_ratio: Optional[str] = None


@dataclass
class _PrezMediaFile:
    """Duck-typed stand-in for common.mediainfo.MediaFile, shaped for
    prez.generate_prez. Built from the raw MediaInfo text returned by the
    tracker, so we can render a tool-format description without file access.
    """
    video_format: Optional[str] = None
    video_bit_depth: Optional[str] = None
    video_width: Optional[int] = None
    video_height: Optional[int] = None
    audio_track: list[dict] = None
    subtitle_track: list[dict] = None

    def __post_init__(self):
        if self.audio_track is None:
            self.audio_track = []
        if self.subtitle_track is None:
            self.subtitle_track = []


_RE_LEADING_INT = re.compile(r"-?\d+")


def _parse_int_prefix(value: str) -> Optional[int]:
    """Extract the leading integer from strings like '6 channels' or '1 920 pixels'."""
    if not value:
        return None
    cleaned = re.sub(r"[\s\u00a0]", "", value)
    m = _RE_LEADING_INT.match(cleaned)
    if not m:
        return None
    try:
        return int(m.group(0))
    except (TypeError, ValueError):
        return None


def _normalize_language_to_iso(value: str) -> str:
    """Map a MediaInfo `Language` value to an ISO code when possible.

    MediaInfo text dumps usually store the full English/French name
    ("French", "English"), but prez expects the 2-letter ISO code so the
    flag lookup works. Returns the original string when no mapping applies.
    """
    if not value:
        return ""
    raw = value.strip()
    # Already an ISO code like "fr" or "fr-FR"
    short = raw.lower().split("-")[0]
    if len(short) == 2 and short.isalpha():
        return short
    iso = _LANG_NAME_TO_ISO.get(raw.lower())
    return iso or raw


def build_prez_media_file(mi_text: Optional[str]) -> Optional[_PrezMediaFile]:
    """Convert a raw MediaInfo text dump into a prez-compatible shim.

    Returns None when the text is missing or looks like BDInfo (which prez
    isn't wired to consume).
    """
    if not mi_text or _looks_like_bdinfo(mi_text):
        return None

    pmf = _PrezMediaFile()
    for section, fields in _iter_sections(mi_text):
        if section in ("video", "vidéo", "vídeo", "video"):
            if not pmf.video_format:
                pmf.video_format = fields.get("format") or None
            if not pmf.video_bit_depth:
                bd = fields.get("bit depth") or ""
                if bd:
                    m = _RE_LEADING_INT.search(bd)
                    pmf.video_bit_depth = m.group(0) if m else bd
            if pmf.video_width is None:
                pmf.video_width = _parse_int_prefix(fields.get("width") or "")
            if pmf.video_height is None:
                pmf.video_height = _parse_int_prefix(fields.get("height") or "")

        elif section == "audio":
            channel_raw = (
                fields.get("channel(s)")
                or fields.get("channels")
                or ""
            )
            channel_int = _parse_int_prefix(channel_raw)
            pmf.audio_track.append({
                "language": _normalize_language_to_iso(fields.get("language", "")),
                "title": fields.get("title", ""),
                "format": fields.get("format", ""),
                "channel_s": str(channel_int) if channel_int is not None else "",
                "bit_rate": fields.get("bit rate", ""),
            })

        elif section in ("text", "texto", "testo"):
            pmf.subtitle_track.append({
                "language": _normalize_language_to_iso(fields.get("language", "")),
                "title": fields.get("title", ""),
                "forced": fields.get("forced", ""),
                "format": fields.get("format", ""),
            })

    return pmf


# ── Rate limiter ───────────────────────────────────────────────────────────

class RateLimiter:
    """Thread-safe sleep-based rate limiter.

    Defaults to 2.1s between calls (safe margin under 30 req/min).
    """

    def __init__(self, min_interval_s: float = 2.1):
        self._min_interval = max(0.0, float(min_interval_s))
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


# ── UnIT3D HTTP client ─────────────────────────────────────────────────────

class UnIT3DClient:
    """Minimal read-only HTTP wrapper around the UnIT3D API.

    Reuses the base_url / api_token from `trackers_api_data` for the given
    tracker name. Honors 429 via a 60s back-off (matches pvtTracker.Tracker._get).
    """

    _PLACEHOLDER_USERNAMES = {"", "no_key", "no_user", "none"}

    def __init__(
        self,
        tracker_name: str = "GEMINI",
        rate_limiter: Optional[RateLimiter] = None,
        timeout: float = 15.0,
        stop_event: Optional[threading.Event] = None,
    ):
        api_data = trackers_api_data.get(tracker_name.upper())
        if not api_data:
            raise ValueError(f"Tracker '{tracker_name}' not found in trackers_api_data")

        self.tracker_name = tracker_name.upper()
        self.base_url = api_data["url"].rstrip("/")
        self.api_token = api_data["api_key"]
        raw_username = (api_data.get("username") or "").strip()
        # Match the ComplianceService placeholder treatment so we don't
        # accidentally fire queries with uploader="no_key".
        if raw_username.lower() in self._PLACEHOLDER_USERNAMES:
            self.username = ""
        else:
            self.username = raw_username
        self.filter_url = urljoin(self.base_url + "/", "api/torrents/filter")
        self.fetch_url = urljoin(self.base_url + "/", "api/torrents/")

        self._rate = rate_limiter or RateLimiter()
        self._timeout = timeout
        self._stop_event = stop_event
        self._headers = {
            "User-Agent": "Unit3D-up/compliance/1.0",
            "Accept": "application/json",
        }

    def set_stop_event(self, event: Optional[threading.Event]) -> None:
        """Make HTTP sleeps interruptible by `event.set()`."""
        self._stop_event = event

    # Deep-link to the web edit form (read-only from our side).
    def edit_url(self, torrent_id: int) -> str:
        return f"{self.base_url}/torrents/{int(torrent_id)}/edit"

    def _get_json(self, url: str, params: Optional[dict] = None, max_retries: int = 5) -> Optional[dict]:
        """GET a JSON endpoint with 429/5xx backoff.

        Raises requests.HTTPError on 4xx non-429 after a single pass. Raises
        after `max_retries` for repeated 429/5xx/network failures. Respects
        the rate limiter on every attempt.
        """
        attempt = 0
        while True:
            self._rate.wait()
            try:
                response = requests.get(
                    url=url,
                    params=params,
                    headers=self._headers,
                    timeout=self._timeout,
                )
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as exc:
                custom_console.bot_warning_log(f"[Compliance] Network error ({exc}); retrying in 10s")
                attempt += 1
                if attempt >= max_retries:
                    raise
                self._sleep(10)
                continue

            if response.status_code == 429:
                custom_console.bot_warning_log("[Compliance] 429 rate limit — sleeping 60s")
                self._sleep(60)
                attempt += 1
                if attempt >= max_retries:
                    response.raise_for_status()
                continue

            if 500 <= response.status_code < 600:
                attempt += 1
                if attempt >= max_retries:
                    response.raise_for_status()
                self._sleep(5 * attempt)
                continue

            # 4xx non-429: bubble up immediately so the caller can decide
            # whether to drop this one item or abort the whole scan.
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return None

    def _sleep(self, seconds: float) -> None:
        """Interruptible sleep: honors stop_event when present."""
        if self._stop_event is not None:
            # wait() returns True as soon as the event is set.
            self._stop_event.wait(seconds)
        else:
            time.sleep(seconds)

    def iter_user_torrents(
        self,
        uploader: str,
        per_page: int = 100,
        max_pages: int = 2000,
    ) -> Iterator[dict]:
        """Stream every torrent for the given uploader, page by page.

        Yields the raw torrent dicts (attributes under `data[].attributes`).
        Guards against infinite/cyclic pagination by tracking visited URLs
        and capping the total page count.
        """
        if not uploader:
            raise ValueError("uploader is required")

        params = {
            "api_token": self.api_token,
            "uploader": uploader,
            "perPage": per_page,
            "page": 1,
        }

        next_url: Optional[str] = self.filter_url
        next_params: Optional[dict] = dict(params)

        visited: set[str] = set()
        pages = 0

        while next_url:
            pages += 1
            if pages > max_pages:
                custom_console.bot_warning_log(
                    f"[Compliance] Pagination capped at {max_pages} pages"
                )
                return

            # Cycle guard: include the resolved next_params so ?page=N differs.
            cycle_key = next_url if not next_params else f"{next_url}|{sorted(next_params.items())}"
            if cycle_key in visited:
                custom_console.bot_warning_log(
                    f"[Compliance] Pagination cycle detected at page {pages}; stopping"
                )
                return
            visited.add(cycle_key)

            try:
                payload = self._get_json(next_url, params=next_params)
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "?"
                custom_console.bot_warning_log(
                    f"[Compliance] Page {pages} failed with HTTP {status}; stopping"
                )
                return
            if not payload:
                return

            data = payload.get("data") or []
            for entry in data:
                if isinstance(entry, dict) and "attributes" in entry and "id" in entry:
                    yield self._flatten_entry(entry)
                elif isinstance(entry, dict):
                    # Some deployments return flat objects already
                    yield entry

            links = payload.get("links") or {}
            nxt = links.get("next")
            if not nxt:
                break

            parsed = urlparse(nxt)
            if not parsed.scheme:
                nxt = urljoin(self.base_url + "/", nxt.lstrip("/"))
            next_url = nxt
            # The next URL from Laravel already includes page & uploader in
            # its query string; don't double-send them via params. Trust the
            # URL and only re-inject api_token when it's missing.
            if "api_token=" in (urlparse(next_url).query or ""):
                next_params = None
            else:
                next_params = {"api_token": self.api_token}

    @staticmethod
    def _flatten_entry(entry: dict) -> dict:
        """Flatten the JSON:API-ish envelope into a single dict."""
        out = dict(entry.get("attributes") or {})
        out["id"] = entry.get("id")
        return out

    def get_torrent(self, torrent_id: int) -> Optional[dict]:
        url = urljoin(self.fetch_url, str(int(torrent_id)))
        payload = self._get_json(url, params={"api_token": self.api_token})
        if not payload:
            return None
        # /api/torrents/{id} calls TorrentResource::withoutWrapping(), so the
        # response is `{type, id, attributes}` with NO outer `data` key. Older
        # deployments (or wrapped resources) still expose `{data: {...}}`.
        data = payload.get("data")
        if isinstance(data, dict):
            if "attributes" in data:
                return self._flatten_entry(data)
            return data
        if "attributes" in payload and "id" in payload:
            return self._flatten_entry(payload)
        return payload

    def find_by_name(self, name: str, uploader: Optional[str] = None, per_page: int = 10) -> list[dict]:
        """Used by the post-upload hook when we couldn't extract the id from
        the tracker response URL."""
        if not name:
            return []
        params: dict[str, Any] = {
            "api_token": self.api_token,
            "name": name,
            "perPage": per_page,
        }
        if uploader:
            params["uploader"] = uploader
        payload = self._get_json(self.filter_url, params=params)
        if not payload:
            return []
        out: list[dict] = []
        for entry in payload.get("data") or []:
            if isinstance(entry, dict) and "attributes" in entry and "id" in entry:
                out.append(self._flatten_entry(entry))
            elif isinstance(entry, dict):
                out.append(entry)
        return out


# ── Single-torrent check ───────────────────────────────────────────────────

def _extract_torrent_id(payload: dict) -> Optional[int]:
    raw = payload.get("id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _extract_category(payload: dict) -> Optional[str]:
    cat = payload.get("category")
    if isinstance(cat, dict):
        return cat.get("name") or cat.get("slug")
    if isinstance(cat, str):
        return cat
    return None


def _classify_diff(has_any_violation: bool, normalizer_diff: bool) -> str:
    if has_any_violation and normalizer_diff:
        return "both"
    if has_any_violation:
        return "rule_violation"
    if normalizer_diff:
        return "normalizer_diff"
    return "clean"


def check_one_torrent(
    payload: dict,
    *,
    tracker_name: str,
    db: StateDB,
    edit_url: str,
    uploader: Optional[str] = None,
    linked_item_id: Optional[int] = None,
) -> dict:
    """Run the naming checks on one torrent payload and upsert the result.

    Returns the stored compliance row.
    """
    torrent_id = _extract_torrent_id(payload)
    if torrent_id is None:
        raise ValueError("torrent payload missing 'id'")

    # UnIT3D stores the release name in `name`, and the file/folder name
    # inside the torrent in `folder`. The folder is what actually hits disk,
    # so we check that primarily; when unavailable, fall back to `name`.
    current_name = payload.get("folder") or payload.get("name") or ""
    release_name = current_name or ""
    if not release_name:
        raise ValueError(f"torrent #{torrent_id} has no name/folder to check")

    mi_text = extract_mediainfo_text(payload)
    facts = mediainfo_facts_from_text(mi_text or "")

    fake_media = _FakeMediaFile(
        multiview_count=facts.get("multiview_count"),
        audio_formats=facts.get("audio_formats") or [],
        audio_track_count=facts.get("audio_track_count", 0),
        subtitle_formats=facts.get("subtitle_formats") or [],
        writing_library=facts.get("writing_library"),
        video_width=facts.get("video_width"),
        video_height=facts.get("video_height"),
        video_aspect_ratio=facts.get("video_aspect_ratio"),
    )

    violations = []
    for validator in (NamingValidator(), EncodingValidator()):
        try:
            violations.extend(validator.validate(
                media=None,
                mediafile=fake_media,
                release_name=release_name,
                mediainfo_text=mi_text,
            ))
        except Exception as exc:
            custom_console.bot_warning_log(
                f"[Compliance] {validator.__class__.__name__} failed for #{torrent_id}: {exc}"
            )

    # Only trust audio_track_count==0 to mean "silent" when we actually
    # parsed MediaInfo. With BDInfo (or any unparsable text) we default to
    # is_silent=False — otherwise every BD release would be flagged as silent.
    if facts.get("is_bdinfo"):
        is_silent = False
    else:
        is_silent = facts.get("audio_track_count", 0) == 0

    # release_year est exposé par UnIT3D dans `attributes.release_year`.
    # On le passe au normalizer comme fallback : utile surtout pour les séries
    # dont le nom source n'inclut généralement pas l'année.
    raw_year = payload.get("release_year")
    year_hint: Optional[str] = None
    if raw_year is not None:
        try:
            year_int = int(raw_year)
            if 1900 <= year_int <= 2999:
                year_hint = str(year_int)
        except (TypeError, ValueError):
            year_hint = None

    try:
        proposed = normalize_release_name(release_name, mi_text, is_silent=is_silent, year=year_hint)
    except Exception as exc:
        custom_console.bot_warning_log(f"[Compliance] normalizer failed for torrent #{torrent_id}: {exc}")
        proposed = release_name

    normalizer_diff = bool(proposed) and proposed != release_name
    # Any violation — including INFO — is treated as non-clean so the severity
    # filter and the diff_kind stay consistent with each other.
    has_any_violation = bool(violations)
    diff_kind = _classify_diff(has_any_violation, normalizer_diff)

    if violations:
        severity_max = _max_severity([v.severity for v in violations])
    elif normalizer_diff:
        severity_max = "INFO"
    else:
        severity_max = "NONE"

    violations_serialised = [
        {
            "rule": v.rule,
            "severity": v.severity,
            "message": v.message,
            "source_doc": v.source_doc,
        }
        for v in violations
    ]

    description_text = payload.get("description")
    if description_text is not None and not isinstance(description_text, str):
        description_text = str(description_text)

    fields: dict[str, Any] = dict(
        torrent_id=torrent_id,
        tracker_name=tracker_name,
        current_name=release_name,
        proposed_name=proposed,
        violations=violations_serialised,
        diff_kind=diff_kind,
        severity_max=severity_max,
        category=_extract_category(payload),
        edit_url=edit_url,
        description=description_text,
        mediainfo=mi_text,
    )
    if uploader:
        fields["uploader"] = uploader
    if linked_item_id is not None:
        fields["linked_item_id"] = int(linked_item_id)

    db.upsert_compliance(**fields)
    row = db.get_compliance_by_torrent(torrent_id)
    return row or fields


# ── Scanner façade ─────────────────────────────────────────────────────────

class ComplianceScanner:
    def __init__(
        self,
        db: StateDB,
        tracker_name: str = "GEMINI",
        client: Optional[UnIT3DClient] = None,
    ):
        self.db = db
        self.tracker_name = tracker_name.upper()
        self.client = client or UnIT3DClient(tracker_name=self.tracker_name)

    def scan_all(
        self,
        uploader: str,
        *,
        stop_event: Optional[threading.Event] = None,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Paginate every torrent for `uploader`, check each one, return a summary."""
        if not uploader:
            raise ValueError("uploader is required for scan_all")

        total = 0
        clean = 0
        violations = 0
        errors = 0
        started_at = datetime.now().isoformat()

        # Make HTTP sleeps (429 back-off, retries) interruptible too.
        previous_event = getattr(self.client, "_stop_event", None)
        if stop_event is not None:
            self.client.set_stop_event(stop_event)

        try:
            iterator = self.client.iter_user_torrents(uploader)
        except Exception as exc:
            if stop_event is not None:
                self.client.set_stop_event(previous_event)
            custom_console.bot_error_log(f"[Compliance] scan_all init failed: {exc}")
            return {
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(),
                "total": 0, "clean": 0, "violations": 0, "errors": 1,
                "last_error": str(exc),
            }

        for payload in iterator:
            if stop_event is not None and stop_event.is_set():
                custom_console.bot_log("[Compliance] Scan interrupted by stop_event")
                break
            try:
                torrent_id = _extract_torrent_id(payload) or 0
                edit_url = self.client.edit_url(torrent_id) if torrent_id else ""
                row = check_one_torrent(
                    payload,
                    tracker_name=self.tracker_name,
                    db=self.db,
                    edit_url=edit_url,
                    uploader=uploader,
                )
                if row.get("severity_max") in (None, "NONE"):
                    clean += 1
                else:
                    violations += 1
                total += 1
                if progress_cb:
                    progress_cb({"processed": total, "current": row.get("current_name", "")})
            except Exception as exc:
                errors += 1
                custom_console.bot_error_log(
                    f"[Compliance] Error while checking torrent: {exc}"
                )

        if stop_event is not None:
            self.client.set_stop_event(previous_event)

        return {
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "total": total,
            "clean": clean,
            "violations": violations,
            "errors": errors,
        }

    def scan_one(self, torrent_id: int, uploader: Optional[str] = None) -> Optional[dict]:
        payload = self.client.get_torrent(int(torrent_id))
        if not payload:
            return None
        return check_one_torrent(
            payload,
            tracker_name=self.tracker_name,
            db=self.db,
            edit_url=self.client.edit_url(int(torrent_id)),
            uploader=uploader or self.client.username or None,
        )

    def scan_by_name(
        self,
        name: str,
        uploader: Optional[str] = None,
        linked_item_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Fuzzy-lookup a torrent by name and check it. Used by the post-upload
        hook when we can't parse the id from the tracker response URL."""
        uploader = uploader or self.client.username or None
        matches = self.client.find_by_name(name=name, uploader=uploader)
        # Prefer an exact name or folder match if any; otherwise take the first.
        chosen: Optional[dict] = None
        for m in matches:
            if (m.get("name") == name) or (m.get("folder") == name):
                chosen = m
                break
        if chosen is None and matches:
            chosen = matches[0]
        if not chosen:
            return None
        torrent_id = _extract_torrent_id(chosen) or 0
        return check_one_torrent(
            chosen,
            tracker_name=self.tracker_name,
            db=self.db,
            edit_url=self.client.edit_url(torrent_id) if torrent_id else "",
            uploader=uploader,
            linked_item_id=linked_item_id,
        )
