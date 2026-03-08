"""
Feed store — persists RSS feed items in a per-feed SQLite database.

Layout on disk:
    data/<feed_slug>/feed.db

The public API is unchanged:
    store.items          -> list[FeedItem], newest-first
    store.add_items(...) -> int (count of genuinely new items inserted)

SQLite is used via the stdlib `sqlite3` module — no extra dependency.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .models import FeedItem

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS feed_items (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    published   TEXT NOT NULL,
    link        TEXT,
    author      TEXT,
    category    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class FeedStore:
    def __init__(
        self,
        feed_slug: str,
        max_items: int = 100,
        data_dir: Path = Path("data"),
    ) -> None:
        self.feed_slug = feed_slug
        self.max_items = max_items
        self._db_path = data_dir / "feed.db"

        data_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

        count = self._conn.execute("SELECT COUNT(*) FROM feed_items").fetchone()[0]
        logger.info("[%s] SQLite store opened — %d persisted item(s)", feed_slug, count)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def items(self) -> List[FeedItem]:
        """Return all items sorted newest-first."""
        rows = self._conn.execute(
            "SELECT * FROM feed_items ORDER BY published DESC"
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def add_items(self, new_items: List[FeedItem]) -> int:
        """
        Upsert items into the store (deduplicated by id).
        Returns the count of genuinely new items inserted (updates not counted).
        """
        if not new_items:
            return 0

        # Determine which IDs already exist before the upsert
        ids = [item.id for item in new_items]
        existing = {
            row[0]
            for row in self._conn.execute(
                f"SELECT id FROM feed_items WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            ).fetchall()
        }

        added = 0
        with self._conn:
            for item in new_items:
                pub = item.published
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                self._conn.execute(
                    """
                    INSERT INTO feed_items (id, title, content, published, link, author, category)
                    VALUES (:id, :title, :content, :published, :link, :author, :category)
                    ON CONFLICT(id) DO UPDATE SET
                        title     = excluded.title,
                        content   = excluded.content,
                        published = excluded.published,
                        link      = excluded.link,
                        author    = excluded.author,
                        category  = excluded.category
                    """,
                    {
                        "id": item.id,
                        "title": item.title,
                        "content": item.content,
                        "published": pub.isoformat(),
                        "link": item.link,
                        "author": item.author,
                        "category": item.category,
                    },
                )
                if item.id not in existing:
                    added += 1

        if added:
            logger.info("[%s] %d new item(s) added", self.feed_slug, added)

        self._prune()
        return added

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_DDL)

    def _prune(self) -> None:
        """Delete oldest items beyond max_items."""
        total = self._conn.execute("SELECT COUNT(*) FROM feed_items").fetchone()[0]
        if total <= self.max_items:
            return
        excess = total - self.max_items
        with self._conn:
            self._conn.execute(
                """
                DELETE FROM feed_items WHERE id IN (
                    SELECT id FROM feed_items ORDER BY published ASC LIMIT ?
                )
                """,
                (excess,),
            )
        logger.debug("[%s] Pruned %d old item(s)", self.feed_slug, excess)

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> FeedItem:
        pub_str = row["published"]
        try:
            pub = datetime.fromisoformat(pub_str)
        except ValueError:
            pub = datetime.now(timezone.utc)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return FeedItem(
            id=row["id"],
            title=row["title"],
            content=row["content"],
            published=pub,
            link=row["link"],
            author=row["author"],
            category=row["category"],
        )
