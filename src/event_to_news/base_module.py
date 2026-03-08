"""
Base class for all event-to-news modules.

To create a new module:
1. Create src/event_to_news/modules/<your_module>.py
2. Define a class that inherits from BaseModule
3. Implement the `fetch` async method
4. Reference the module by its file name (without .py) in config.yml

Each module instance receives its own private data directory:
    data/<feed_slug>/

Use `self.data_dir` inside your module to persist whatever you need
(SQLite database, JSON files, cached credentials, etc.).

Example:
    class MyModule(BaseModule):
        async def fetch(self) -> list[FeedItem]:
            db_path = self.data_dir / "cache.db"
            ...
            return [
                FeedItem(
                    id="unique-stable-id",
                    title="Something happened",
                    content="<b>Details</b> here",
                    category="MyCategory",
                )
            ]
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .models import FeedItem

logger = logging.getLogger(__name__)


class BaseModule(ABC):
    """
    Abstract base class that every module must implement.

    Attributes:
        feed_slug:  Unique identifier for this feed instance (from config.yml key).
        params:     Dict populated from the feed's `params:` block in config.yml.
        data_dir:   Private directory for this module instance's persistent data.
                    Created automatically before __init__ is called.
        logger:     Logger namespaced to this module class.
    """

    def __init__(self, feed_slug: str, params: dict[str, Any], data_dir: Path) -> None:
        self.feed_slug = feed_slug
        self.params = params
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(
            f"event_to_news.modules.{self.__class__.__name__}"
        )

    @abstractmethod
    async def fetch(self) -> list[FeedItem]:
        """
        Fetch current items from the source.

        Called on each scheduled poll. The module is free to use `self.data_dir`
        to cache state between polls and return only new items, or to always
        return all items and let the FeedStore deduplicate — either approach works.

        Raises:
            Any exception — the scheduler will catch and log it without
            crashing the whole application.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} feed={self.feed_slug!r}>"
