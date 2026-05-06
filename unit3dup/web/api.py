# -*- coding: utf-8 -*-
"""JSON API endpoints for the web dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from unit3dup.state_db import StateDB
from unit3dup.web.models import (
    ApproveRequest, RejectRequest, BulkApproveRequest, BulkRejectRequest, BulkRescanRequest,
    RescanTmdbRequest, UpdateCategoryRequest, UpdateSourceTypeRequest, UpdateResolutionRequest,
    UpdateSeasonEpisodeRequest, UpdateTracksRequest,
    StatsResponse, ItemDetail, ItemListResponse, ItemSummary, QueueStatusResponse,
    ComplianceListResponse, ComplianceScanStatus, ComplianceAckRequest,
    BulkComplianceDeleteRequest,
)
from unit3dup.web.upload_service import UploadService
from unit3dup.web.compliance_service import ComplianceService
from unit3dup.web.bbcode_renderer import bbcode_to_html
from unit3dup.prez import generate_prez
from unit3dup.compliance.scanner import build_prez_media_file

router = APIRouter(prefix="/api/v1", tags=["api"])

# These will be set by the app factory
_state_db: StateDB | None = None
_upload_service: UploadService | None = None
_compliance_service: ComplianceService | None = None


def init_api(
    state_db: StateDB,
    upload_service: UploadService,
    compliance_service: ComplianceService | None = None,
):
    global _state_db, _upload_service, _compliance_service
    _state_db = state_db
    _upload_service = upload_service
    _compliance_service = compliance_service


def _db() -> StateDB:
    if _state_db is None:
        raise HTTPException(500, "Database not initialized")
    return _state_db


def _svc() -> UploadService:
    if _upload_service is None:
        raise HTTPException(500, "Upload service not initialized")
    return _upload_service


@router.get("/stats", response_model=StatsResponse)
def get_stats():
    counts = _db().count_by_status()
    return StatsResponse(
        pending=counts.get("pending", 0),
        queued=counts.get("queued", 0),
        rescanning=counts.get("rescanning", 0),
        uploaded=counts.get("uploaded", 0),
        rejected=counts.get("rejected", 0),
        skipped=counts.get("skipped", 0),
        error=counts.get("error", 0),
        total=sum(counts.values()),
    )


@router.get("/items")
def list_items(status: str | None = None, category: str | None = None,
               page: int = 1, per_page: int = 50):
    items = _db().list_items(status=status, category=category, page=page, per_page=per_page)
    return {
        "items": items,
        "total": len(items),
        "page": page,
        "per_page": per_page,
    }


@router.get("/items/{item_id}")
def get_item(item_id: int):
    item = _db().get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


@router.post("/items/{item_id}/approve")
def approve_item(item_id: int, req: ApproveRequest = Body(default=ApproveRequest())):
    result = _svc().approve_and_upload(item_id, req.release_name, req.description)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/items/{item_id}/reject")
def reject_item(item_id: int, req: RejectRequest):
    result = _svc().reject_item(item_id, req.reason)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/items/{item_id}/retry")
def retry_item(item_id: int):
    result = _svc().retry_item(item_id)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/items/{item_id}/cancel")
def cancel_item(item_id: int):
    result = _svc().cancel_item(item_id)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/items/{item_id}/reset")
def reset_uploaded_item(item_id: int):
    result = _svc().reset_uploaded_item(item_id)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/items/{item_id}/save")
def save_item(item_id: int, req: ApproveRequest):
    """Save release name / description edits without changing status."""
    item = _db().get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    updates = {}
    if req.release_name is not None:
        updates["user_edited_name"] = req.release_name
    if req.description is not None:
        updates["user_edited_desc"] = req.description
    if updates:
        _db().update_item(item_id, **updates)
    return {"success": True, "message": "Changes saved"}


@router.post("/items/{item_id}/rescan")
def rescan_item(item_id: int):
    """Re-run the full prepare pipeline on the source file."""
    result = _svc().rescan_item(item_id)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/items/{item_id}/force-rescan")
def force_rescan_item(item_id: int):
    """Re-run the prepare pipeline, bypassing the duplicate-on-tracker check."""
    result = _svc().force_rescan_item(item_id)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/items/{item_id}/update-category")
def update_category(item_id: int, req: UpdateCategoryRequest):
    """Update the category (category_id) for an item."""
    import json
    item = _db().get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    tracker_payload = item.get("tracker_payload")
    if isinstance(tracker_payload, str):
        tracker_payload = json.loads(tracker_payload)
    if tracker_payload:
        tracker_payload["category_id"] = req.category_id
    _db().update_item(item_id, content_category=req.category_label, tracker_payload=tracker_payload)
    return {"success": True, "message": f"Category updated to {req.category_label}"}


@router.post("/items/{item_id}/update-resolution")
def update_resolution(item_id: int, req: UpdateResolutionRequest):
    """Update the resolution (resolution_id) for an item."""
    import json
    item = _db().get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    tracker_payload = item.get("tracker_payload")
    if isinstance(tracker_payload, str):
        tracker_payload = json.loads(tracker_payload)
    if tracker_payload:
        tracker_payload["resolution_id"] = req.resolution_id
    _db().update_item(item_id, resolution=req.resolution_label, tracker_payload=tracker_payload)
    return {"success": True, "message": f"Resolution updated to {req.resolution_label}"}


@router.post("/items/{item_id}/update-source-type")
def update_source_type(item_id: int, req: UpdateSourceTypeRequest):
    """Update the source type (type_id) for an item."""
    import json
    item = _db().get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    tracker_payload = item.get("tracker_payload")
    if isinstance(tracker_payload, str):
        tracker_payload = json.loads(tracker_payload)
    if tracker_payload:
        tracker_payload["type_id"] = req.type_id
    _db().update_item(item_id, source_tag=req.source_label, tracker_payload=tracker_payload)
    return {"success": True, "message": f"Source type updated to {req.source_label}"}


@router.post("/items/{item_id}/update-season-episode")
def update_season_episode(item_id: int, req: UpdateSeasonEpisodeRequest):
    """Update the season_number and episode_number for an item."""
    import json
    item = _db().get_item(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    tracker_payload = item.get("tracker_payload")
    if isinstance(tracker_payload, str):
        tracker_payload = json.loads(tracker_payload)
    if not isinstance(tracker_payload, dict):
        tracker_payload = {}
    tracker_payload["season_number"] = req.season_number
    tracker_payload["episode_number"] = req.episode_number
    _db().update_item(item_id, tracker_payload=tracker_payload)
    return {"success": True, "message": f"Season/episode updated to S{req.season_number:02d}E{req.episode_number:02d}"}


@router.post("/items/{item_id}/update-tracks")
def update_tracks(item_id: int, req: UpdateTracksRequest):
    """Update audio/subtitle tracks and regenerate the prez description."""
    result = _svc().regenerate_prez(
        item_id,
        [t.model_dump() for t in req.audio_tracks],
        [t.model_dump() for t in req.subtitle_tracks],
    )
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/items/{item_id}/rescan-tmdb")
def rescan_tmdb(item_id: int, req: RescanTmdbRequest):
    result = _svc().rescan_tmdb(item_id, req.tmdb_id)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.delete("/items/{item_id}")
def delete_item(item_id: int):
    success = _db().delete_item(item_id)
    if not success:
        raise HTTPException(404, "Item not found")
    return {"success": True, "message": "Item deleted"}


@router.get("/queue/status", response_model=QueueStatusResponse)
def queue_status():
    return _svc().queue_status()


@router.post("/items/bulk-approve")
def bulk_approve(req: BulkApproveRequest):
    return _svc().bulk_approve(req.ids)


@router.post("/items/bulk-reject")
def bulk_reject(req: BulkRejectRequest):
    return _svc().bulk_reject(req.ids, req.reason)


@router.post("/items/bulk-rescan")
def bulk_rescan(req: BulkRescanRequest):
    return _svc().bulk_rescan(req.ids)


# ── Compliance ──────────────────────────────────────────────────────

def _compliance() -> ComplianceService:
    if _compliance_service is None:
        raise HTTPException(503, "Compliance service not initialized")
    return _compliance_service


@router.get("/compliance/items", response_model=ComplianceListResponse)
def compliance_list(
    severity: str | None = None,
    ack_status: str | None = None,
    diff_kind: str | None = None,
    page: int = 1,
    per_page: int = 100,
):
    items = _db().list_compliance(
        severity=severity,
        ack_status=ack_status,
        diff_kind=diff_kind,
        page=page,
        per_page=per_page,
    )
    counts = _db().count_compliance_by_severity(only_unchecked=True)
    return {
        "items": items,
        "total": _db().count_compliance_total(),
        "page": page,
        "per_page": per_page,
        "counts": counts,
    }


@router.get("/compliance/items/{row_id}")
def compliance_get(row_id: int):
    row = _db().get_compliance(row_id)
    if not row:
        raise HTTPException(404, "Compliance row not found")
    row["description_html"] = bbcode_to_html(row.get("description"))

    # Regenerate a fresh description from the stored MediaInfo text, using the
    # same generator the pending/upload flow uses. Done on the fly so it stays
    # in sync with the tool's prez template without a DB migration.
    generated_description = ""
    audio_tracks: list[dict] = []
    sub_tracks: list[dict] = []
    try:
        shim = build_prez_media_file(row.get("mediainfo"))
        if shim is not None:
            generated_description = generate_prez(shim) or ""
            audio_tracks = list(shim.audio_track or [])
            sub_tracks = list(shim.subtitle_track or [])
    except Exception:
        generated_description = ""
    row["generated_description"] = generated_description
    row["generated_description_html"] = bbcode_to_html(generated_description)
    row["audio_tracks"] = audio_tracks
    row["sub_tracks"] = sub_tracks
    return row


@router.post("/compliance/items/{row_id}/generate-description")
def compliance_generate_description(row_id: int, body: dict | None = Body(default=None)):
    """Regenerate the prez-format description, optionally with per-track overrides.

    Body (optional): {"audio_tracks": [...], "sub_tracks": [...]}.
    Each track is a dict with keys expected by generate_prez (language, title,
    format, channel_s, bit_rate, forced).
    """
    row = _db().get_compliance(row_id)
    if not row:
        raise HTTPException(404, "Compliance row not found")

    audio_override = (body or {}).get("audio_tracks")
    sub_override = (body or {}).get("sub_tracks")

    try:
        shim = build_prez_media_file(row.get("mediainfo"))
    except Exception:
        shim = None
    if shim is None:
        raise HTTPException(422, "MediaInfo unavailable or BDInfo format — cannot regenerate")

    audio_tracks = audio_override if isinstance(audio_override, list) else shim.audio_track
    sub_tracks = sub_override if isinstance(sub_override, list) else shim.subtitle_track

    try:
        generated = generate_prez(shim, audio_tracks=audio_tracks, sub_tracks=sub_tracks) or ""
    except Exception as exc:
        raise HTTPException(500, f"Generation failed: {exc}")

    return {
        "generated_description": generated,
        "generated_description_html": bbcode_to_html(generated),
    }


@router.post("/compliance/scan")
def compliance_scan():
    return _compliance().enqueue_full_scan()


@router.post("/compliance/items/{row_id}/ack")
def compliance_ack(row_id: int, req: ComplianceAckRequest | None = Body(default=None)):
    status = req.status if req else "acknowledged"
    ok = _db().set_compliance_ack(row_id, status)
    if not ok:
        raise HTTPException(404, "Compliance row not found")
    return {"success": True, "message": f"Status set to {status}"}


@router.post("/compliance/items/{row_id}/ignore")
def compliance_ignore(row_id: int):
    ok = _db().set_compliance_ack(row_id, "ignored")
    if not ok:
        raise HTTPException(404, "Compliance row not found")
    return {"success": True, "message": "Status set to ignored"}


@router.post("/compliance/items/{row_id}/recheck")
def compliance_recheck(row_id: int):
    row = _db().get_compliance(row_id)
    if not row:
        raise HTTPException(404, "Compliance row not found")
    return _compliance().enqueue_check_one(int(row["torrent_id"]))


@router.delete("/compliance/items/{row_id}")
def compliance_delete_and_rescan(row_id: int):
    row = _db().get_compliance(row_id)
    if not row:
        raise HTTPException(404, "Compliance row not found")
    torrent_id = int(row["torrent_id"])
    _db().delete_compliance(row_id)
    result = _compliance().enqueue_check_one(torrent_id)
    return {
        "success": result.get("success", True),
        "message": result.get("message", f"Row deleted, fresh check queued for torrent #{torrent_id}"),
    }


@router.post("/compliance/items/bulk-delete")
def compliance_bulk_delete_and_rescan(req: BulkComplianceDeleteRequest):
    deleted = 0
    queued = 0
    failed_queue = 0
    missing = 0
    for row_id in req.ids:
        row = _db().get_compliance(row_id)
        if not row:
            missing += 1
            continue
        torrent_id = int(row["torrent_id"])
        _db().delete_compliance(row_id)
        deleted += 1
        result = _compliance().enqueue_check_one(torrent_id)
        if result.get("success"):
            queued += 1
        else:
            failed_queue += 1
    return {
        "success": deleted > 0,
        "deleted": deleted,
        "queued": queued,
        "failed_queue": failed_queue,
        "missing": missing,
        "message": f"Deleted {deleted} row(s), queued {queued} fresh check(s)"
                   + (f", {failed_queue} queue failure(s)" if failed_queue else "")
                   + (f", {missing} not found" if missing else ""),
    }


@router.get("/compliance/scan-status", response_model=ComplianceScanStatus)
def compliance_status():
    return _compliance().scan_status()
