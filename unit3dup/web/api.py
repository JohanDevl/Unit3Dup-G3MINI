# -*- coding: utf-8 -*-
"""JSON API endpoints for the web dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from unit3dup.state_db import StateDB
from unit3dup.web.models import (
    ApproveRequest, RejectRequest, BulkApproveRequest, BulkRejectRequest,
    RescanTmdbRequest, UpdateCategoryRequest, UpdateSourceTypeRequest, UpdateResolutionRequest,
    UpdateSeasonEpisodeRequest,
    StatsResponse, ItemDetail, ItemListResponse, ItemSummary, QueueStatusResponse,
)
from unit3dup.web.upload_service import UploadService

router = APIRouter(prefix="/api/v1", tags=["api"])

# These will be set by the app factory
_state_db: StateDB | None = None
_upload_service: UploadService | None = None


def init_api(state_db: StateDB, upload_service: UploadService):
    global _state_db, _upload_service
    _state_db = state_db
    _upload_service = upload_service


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
