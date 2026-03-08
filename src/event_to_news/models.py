"""
Shared data models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class FeedItem(BaseModel):
    """A single item in an RSS feed."""

    # Stable unique identifier for deduplication (e.g. "pronote-grade-<id>")
    id: str
    # Item title shown in the aggregator
    title: str
    # Full content / description (HTML allowed)
    content: str
    # Publication date; defaults to now if not provided by the source
    published: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Optional URL to the original resource
    link: Optional[str] = None
    # Optional author name
    author: Optional[str] = None
    # Optional category / tag
    category: Optional[str] = None
