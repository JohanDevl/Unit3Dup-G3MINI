# -*- coding: utf-8 -*-
"""JSON API endpoints for the web dashboard."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from unit3dup.state_db import StateDB
from unit3dup.web.models import (
    ApproveRequest, RejectRequest, BulkApproveRequest, BulkRejectRequest,
    StatsResponse, ItemDetail, ItemListResponse, ItemSummary,
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
def approve_item(item_id: int, req: ApproveRequest | None = None):
    if req is None:
        req = ApproveRequest()
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


@router.delete("/items/{item_id}")
def delete_item(item_id: int):
    success = _db().delete_item(item_id)
    if not success:
        raise HTTPException(404, "Item not found")
    return {"success": True, "message": "Item deleted"}


@router.post("/items/bulk-approve")
def bulk_approve(req: BulkApproveRequest):
    return _svc().bulk_approve(req.ids)


@router.post("/items/bulk-reject")
def bulk_reject(req: BulkRejectRequest):
    return _svc().bulk_reject(req.ids, req.reason)
