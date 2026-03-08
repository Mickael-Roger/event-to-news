"""
FastAPI HTTP server.

Exposes:
  GET /                       — list all available feeds
  GET /feed/<slug>            — RSS 2.0 XML for a specific feed
  GET /feed/<slug>/items      — JSON list of raw items (for debugging)
  GET /health                 — health check
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from .rss import build_rss

if TYPE_CHECKING:
    from .config import AppConfig
    from .scheduler import Scheduler

logger = logging.getLogger(__name__)


def create_app(app_config: "AppConfig", scheduler: "Scheduler") -> FastAPI:
    """
    Create and configure the FastAPI application.

    The scheduler must already be set up (setup() called) before this.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler.start()
        logger.info("Scheduler started — serving %d feed(s)", len(scheduler.feed_slugs))
        yield
        scheduler.stop()
        logger.info("Scheduler stopped")

    app = FastAPI(
        title="event-to-news",
        description="Expose arbitrary event sources as RSS feeds",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health():
        return {"status": "ok", "feeds": scheduler.feed_slugs}

    @app.get("/")
    async def index():
        base = app_config.server.base_url.rstrip("/")
        return {
            "feeds": {
                slug: {
                    "title": app_config.feeds[slug].title,
                    "description": app_config.feeds[slug].description,
                    "rss_url": f"{base}/feed/{slug}",
                }
                for slug in scheduler.feed_slugs
            }
        }

    @app.get("/feed/{slug}")
    async def get_feed(slug: str):
        feed_cfg = app_config.feeds.get(slug)
        if feed_cfg is None:
            raise HTTPException(status_code=404, detail=f"Feed '{slug}' not found")

        store = scheduler.get_store(slug)
        if store is None:
            raise HTTPException(
                status_code=404, detail=f"Feed '{slug}' not initialized"
            )

        xml_bytes = build_rss(
            slug=slug,
            title=feed_cfg.title,
            description=feed_cfg.description,
            base_url=app_config.server.base_url,
            items=store.items,
        )
        return Response(
            content=xml_bytes, media_type="application/rss+xml; charset=utf-8"
        )

    @app.get("/feed/{slug}/items")
    async def get_feed_items(slug: str):
        if slug not in app_config.feeds:
            raise HTTPException(status_code=404, detail=f"Feed '{slug}' not found")

        store = scheduler.get_store(slug)
        if store is None:
            raise HTTPException(
                status_code=404, detail=f"Feed '{slug}' not initialized"
            )

        return JSONResponse(
            content=[item.model_dump(mode="json") for item in store.items]
        )

    return app
