# -*- coding: utf-8 -*-
"""FastAPI application factory for the Unit3Dup web dashboard."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from unit3dup.state_db import StateDB
from unit3dup.web.api import router as api_router, init_api
from unit3dup.web.views import router as views_router, init_views
from unit3dup.web.upload_service import UploadService


def create_app(state_db: StateDB) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        state_db: initialized StateDB instance (shared with watcher thread)

    Returns:
        Configured FastAPI app
    """
    app = FastAPI(
        title="Unit3Dup Dashboard",
        description="Web dashboard for Unit3Dup torrent uploader",
        docs_url="/docs",
    )

    # Initialize services
    upload_service = UploadService(state_db=state_db)
    upload_service.start_worker()
    init_api(state_db, upload_service)
    init_views(state_db)

    # Mount static files (directory is part of the installed package)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Include routers
    app.include_router(api_router)
    app.include_router(views_router)

    @app.on_event("shutdown")
    def shutdown_event():
        upload_service.stop_worker()

    return app


def start_web(state_db: StateDB, host: str = "0.0.0.0", port: int = 8000):
    """Start the web server (blocking call).

    Args:
        state_db: initialized StateDB instance
        host: bind address
        port: bind port
    """
    import uvicorn

    app = create_app(state_db)
    uvicorn.run(app, host=host, port=port, log_level="info")
