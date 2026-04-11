# -*- coding: utf-8 -*-
"""HTML view endpoints for the web dashboard."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from unit3dup.state_db import StateDB
from unit3dup.web.bbcode_renderer import bbcode_to_html
from unit3dup.prez import ISO_TO_LANG_NAME
from common.trackers.data import trackers_api_data
from common.trackers.gemini import gemini_data

router = APIRouter(tags=["views"])

_templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_templates_dir)

# Will be set by app factory
_state_db: StateDB | None = None
_upload_service = None


def init_views(state_db: StateDB, upload_service=None):
    global _state_db, _upload_service
    _state_db = state_db
    _upload_service = upload_service
    # Register custom filters
    templates.env.filters["bbcode"] = bbcode_to_html
    templates.env.filters["filesize"] = _format_filesize
    templates.env.filters["reason_label"] = _format_reason
    templates.env.filters["datefmt"] = _format_datetime
    templates.env.filters["category_label"] = _format_category
    # Global context: pending + queued count for sidebar badge
    def _pending_and_queued():
        counts = state_db.count_by_status()
        return counts.get("analyzing", 0) + counts.get("rescanning", 0) + counts.get("pending", 0) + counts.get("queued", 0)
    templates.env.globals["get_pending_count"] = _pending_and_queued
    # Global context: queue count (queued + uploading) for sidebar badge
    def _queue_count():
        counts = state_db.count_by_status()
        return counts.get("queued", 0) + counts.get("approved", 0) + counts.get("rescanning", 0)
    templates.env.globals["get_queue_count"] = _queue_count
    templates.env.globals["similar_url"] = _build_similar_url


def _build_similar_url(item: dict) -> str | None:
    name = item.get("tracker_name")
    category = item.get("content_category")
    if not name or not category:
        return None
    tracker = trackers_api_data.get(name.upper())
    if not tracker:
        return None
    base_url = tracker["url"]
    cat_id = gemini_data["CATEGORY"].get(category)
    if cat_id is None:
        return None
    meta_id = item.get("igdb_id") if category == "game" else item.get("tmdb_id")
    if not meta_id:
        return None
    return f"{base_url}/torrents/similar/{cat_id}.{meta_id}"


def _db() -> StateDB:
    if _state_db is None:
        raise HTTPException(500, "Database not initialized")
    return _state_db


_REASON_LABELS = {
    "already_in_archive": "Already uploaded",
    "duplicate_on_tracker": "Duplicate on tracker",
    "no_tmdb_result": "TMDB not found",
    "no_igdb_result": "IGDB not found",
    "excluded_tag": "Excluded tag",
    "validation_error": "Validation error",
    "no_processable_media": "No media found",
}

_CATEGORY_LABELS = {
    "movie": "Movie",
    "tv": "TV",
    "tv_show": "TV Show",
    "game": "Game",
    "animation": "Animation",
    "tv_animation": "TV Animation",
    "documentary": "Documentary",
    "tv_documentary": "TV Documentary",
    "edicola": "Edicola",
}


def _format_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        from datetime import datetime
        # Handle both "2026-03-29T23:16:27.591250" and "2026-03-29 23:16:27"
        clean = value.replace("T", " ").split(".")[0]  # Remove T and microseconds
        dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        # Last resort: try to extract date parts manually
        try:
            clean = value.replace("T", " ").split(".")[0]
            return clean[:16].replace("-", "/")
        except Exception:
            return str(value)


def _format_reason(reason: str | None) -> str:
    if not reason:
        return "—"
    return _REASON_LABELS.get(reason, reason.replace("_", " ").capitalize())


def _format_category(value: str | None) -> str:
    if not value:
        return "—"
    return _CATEGORY_LABELS.get(value, value.replace("_", " ").title())


def _format_filesize(size: int | None) -> str:
    if not size:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    counts = _db().count_by_status()
    recent = _db().list_items(per_page=100)
    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": counts,
        "recent": recent,
        "page_title": "Dashboard",
    })


def _get_pending_and_queued() -> list[dict]:
    """Fetch analyzing + rescanning + pending + queued items, sorted by discovered date descending."""
    items = _db().list_items(status="analyzing", per_page=500)
    items += _db().list_items(status="rescanning", per_page=500)
    items += _db().list_items(status="pending", per_page=500)
    items += _db().list_items(status="queued", per_page=500)
    items.sort(key=lambda x: x.get("discovered_at", ""), reverse=True)
    return items


@router.get("/pending", response_class=HTMLResponse)
def pending_list(request: Request):
    return templates.TemplateResponse(request, "pending.html", {
        "items": _get_pending_and_queued(),
        "page_title": "Pending",
    })


def _parse_tracks(item: dict) -> tuple[list, list]:
    """Extract audio/subtitle track lists from a DB item."""
    audio_tracks = []
    subtitle_tracks = []
    if item.get("audio_tracks"):
        audio_tracks = item["audio_tracks"] if isinstance(item["audio_tracks"], list) else json.loads(item["audio_tracks"])
    if item.get("subtitle_tracks"):
        subtitle_tracks = item["subtitle_tracks"] if isinstance(item["subtitle_tracks"], list) else json.loads(item["subtitle_tracks"])
    return audio_tracks, subtitle_tracks


@router.get("/pending/{item_id}", response_class=HTMLResponse)
def pending_detail(request: Request, item_id: int):
    item = _db().get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    audio_tracks, subtitle_tracks = _parse_tracks(item)
    return templates.TemplateResponse(request, "item_detail.html", {
        "item": item,
        "page_title": item.get("release_name") or item.get("display_name") or "Detail",
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
        "lang_options": ISO_TO_LANG_NAME,
    })


@router.get("/history", response_class=HTMLResponse)
def history_list(request: Request, status: str | None = None):
    if status and status in ("uploaded", "rejected", "skipped", "error"):
        items = _db().list_items(status=status, per_page=500)
    else:
        # Show all non-pending
        all_items = []
        for s in ("uploaded", "rejected", "skipped", "error"):
            all_items.extend(_db().list_items(status=s, per_page=500))
        items = sorted(all_items, key=lambda x: x.get("discovered_at", ""), reverse=True)
    return templates.TemplateResponse(request, "history.html", {
        "items": items,
        "current_status": status,
        "page_title": "History",
    })


@router.get("/history/{item_id}", response_class=HTMLResponse)
def history_detail(request: Request, item_id: int):
    item = _db().get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    audio_tracks, subtitle_tracks = _parse_tracks(item)
    return templates.TemplateResponse(request, "item_detail.html", {
        "item": item,
        "page_title": item.get("release_name") or item.get("display_name") or "Detail",
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
        "lang_options": ISO_TO_LANG_NAME,
    })


# ── HTMX Partials ─────────────────────────────────────────────────

@router.get("/partials/pending-list", response_class=HTMLResponse)
def partial_pending_list(request: Request):
    return templates.TemplateResponse(request, "partials/pending_rows.html", {
        "items": _get_pending_and_queued(),
    })


@router.get("/partials/stats", response_class=HTMLResponse)
def partial_stats(request: Request):
    counts = _db().count_by_status()
    return templates.TemplateResponse(request, "partials/stats_bar.html", {
        "stats": counts,
    })


def _get_queue_items() -> tuple[list[dict], int | None, int | None]:
    """Fetch uploading + queued + rescanning items and the currently uploading/rescanning item IDs."""
    uploading = _db().list_items(status="approved", per_page=10)
    queued = _db().list_items(status="queued", per_page=100)
    rescanning = _db().list_items(status="rescanning", per_page=100)
    uploading_id = _upload_service._current_item_id if _upload_service else None
    rescanning_id = _upload_service._current_rescan_item_id if _upload_service else None
    return uploading + queued + rescanning, uploading_id, rescanning_id


@router.get("/queue", response_class=HTMLResponse)
def queue_page(request: Request):
    items, uploading_id, rescanning_id = _get_queue_items()
    return templates.TemplateResponse(request, "queue.html", {
        "items": items,
        "uploading_id": uploading_id,
        "rescanning_id": rescanning_id,
        "page_title": "Queue",
    })


@router.get("/partials/queue-list", response_class=HTMLResponse)
def partial_queue_list(request: Request):
    items, uploading_id, rescanning_id = _get_queue_items()
    return templates.TemplateResponse(request, "partials/queue_rows.html", {
        "items": items,
        "uploading_id": uploading_id,
        "rescanning_id": rescanning_id,
    })
