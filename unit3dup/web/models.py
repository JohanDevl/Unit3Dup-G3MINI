# -*- coding: utf-8 -*-
"""Pydantic models for the web dashboard API."""

from __future__ import annotations
from pydantic import BaseModel, Field


class ApproveRequest(BaseModel):
    release_name: str | None = None
    description: str | None = None


class RejectRequest(BaseModel):
    reason: str


class BulkApproveRequest(BaseModel):
    ids: list[int]


class BulkRejectRequest(BaseModel):
    ids: list[int]
    reason: str


class RetryRequest(BaseModel):
    pass


class RescanTmdbRequest(BaseModel):
    tmdb_id: int


class UpdateSourceTypeRequest(BaseModel):
    type_id: int
    source_label: str


class UpdateCategoryRequest(BaseModel):
    category_id: int
    category_label: str


class UpdateResolutionRequest(BaseModel):
    resolution_id: int
    resolution_label: str


class UpdateSeasonEpisodeRequest(BaseModel):
    season_number: int = Field(ge=0)
    episode_number: int = Field(ge=0)


class StatsResponse(BaseModel):
    pending: int = 0
    uploaded: int = 0
    rejected: int = 0
    skipped: int = 0
    error: int = 0
    total: int = 0


class ItemSummary(BaseModel):
    id: int
    source_basename: str
    display_name: str | None = None
    release_name: str | None = None
    status: str
    content_category: str | None = None
    source_tag: str | None = None
    resolution: str | None = None
    file_size: int | None = None
    has_errors: bool = False
    has_warnings: bool = False
    skip_reason: str | None = None
    rejection_reason: str | None = None
    discovered_at: str | None = None
    uploaded_at: str | None = None
    tmdb_title: str | None = None
    tmdb_year: int | None = None
    tracker_name: str | None = None


class ItemDetail(ItemSummary):
    source_path: str | None = None
    folder_path: str | None = None
    source_type: str | None = None
    qbit_category: str | None = None
    torrent_name: str | None = None
    tmdb_id: int | None = None
    imdb_id: int | None = None
    igdb_id: int | None = None
    description: str | None = None
    mediainfo: str | None = None
    nfo_content: str | None = None
    tracker_payload: dict | list | None = None
    trackers_list: list | None = None
    torrent_archive_path: str | None = None
    validation_report: list | None = None
    user_edited_name: str | None = None
    user_edited_desc: str | None = None
    prepared_at: str | None = None
    decided_at: str | None = None
    tracker_response: str | None = None
    upload_error: str | None = None


class ItemListResponse(BaseModel):
    items: list[ItemSummary]
    total: int
    page: int
    per_page: int
