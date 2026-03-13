"""
Cafetaria module — fetches the current cafeteria credit balance from
the webparent.paiementdp.com portal and publishes one RSS item per day.

Authentication:
  Provide username and password directly in the feed's params block in config.yml:

      params:
        username: "your_username"
        password: "your_password"

Data directory layout (data/<feed_slug>/):
    seen.db     SQLite cache of already-emitted item IDs (one per day)

config.yml params:
    username        (required) Login username for the portal
    password        (required) Login password for the portal
    student_name    (optional) Cosmetic prefix added to item titles, e.g. "Alice"
    site            (optional) Portal site identifier, default "aes00152"

Schedule recommendation:
    Use a cron expression to fire once a day at 20:00:
        schedule: "0 20 * * *"
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from ..base_module import BaseModule
from ..models import FeedItem

_SEEN_DDL = """
CREATE TABLE IF NOT EXISTS seen_items (
    id         TEXT PRIMARY KEY,
    seen_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_BASE_URL = "https://webparent.paiementdp.com"
_AUTH_PATH = "/aliAuthentification.php"
_LOGOUT_PATH = "/aliDeconnexion.php"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Origin": _BASE_URL,
}


class CafetariaModule(BaseModule):
    """Fetch cafeteria credit balance and publish one RSS item per day."""

    def __init__(self, feed_slug: str, params: dict[str, Any], data_dir: Path) -> None:
        super().__init__(feed_slug, params, data_dir)

        self._username: str = params.get("username", "")
        self._password: str = params.get("password", "")
        self._student_name: str = params.get("student_name", "")
        self._site: str = params.get("site", "aes00152")

        # SQLite cache — one row per item ID, preventing duplicate daily entries
        self._seen_conn = sqlite3.connect(
            str(self.data_dir / "seen.db"), check_same_thread=False
        )
        with self._seen_conn:
            self._seen_conn.executescript(_SEEN_DDL)

    # ------------------------------------------------------------------
    # BaseModule interface
    # ------------------------------------------------------------------

    async def fetch(self) -> list[FeedItem]:
        """Fetch current credit; emit one item per calendar day."""
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_fetch)

    # ------------------------------------------------------------------
    # Synchronous implementation
    # ------------------------------------------------------------------

    def _sync_fetch(self) -> list[FeedItem]:
        if not self._username or not self._password:
            self.logger.error(
                "Missing 'username' or 'password' in params for feed %r", self.feed_slug
            )
            return []

        credit = self._fetch_credit()
        if credit is None:
            return []

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        item_id = f"cafetaria-{self.feed_slug}-credit-{today}"

        if self._already_seen(item_id):
            self.logger.debug("Item %r already emitted today — skipping", item_id)
            return []

        prefix = f"[{self._student_name}] " if self._student_name else ""
        title = f"{prefix}Cafeteria credit: {credit}"

        content_parts = [
            f"<b>Credit:</b> {credit}",
            f"<b>Date:</b> {today}",
        ]
        if self._student_name:
            content_parts.insert(0, f"<b>Student:</b> {self._student_name}")

        item = FeedItem(
            id=item_id,
            title=title,
            content="<br/>".join(content_parts),
            published=datetime.now(timezone.utc),
            category="Cafeteria",
        )

        self._mark_seen([item])
        self.logger.info("Emitting cafeteria credit item: %r", item_id)
        return [item]

    # ------------------------------------------------------------------
    # Web scraping
    # ------------------------------------------------------------------

    def _fetch_credit(self) -> str | None:
        """Log in, scrape the credit balance, log out, and return it."""
        auth_url = f"{_BASE_URL}{_AUTH_PATH}?site={quote(self._site)}"
        headers = {**_HEADERS, "Referer": auth_url}

        session = requests.Session()
        try:
            # Load login page (sets session cookies)
            session.get(auth_url, timeout=30)

            # Authenticate
            resp = session.post(
                auth_url,
                data={
                    "txtLogin": self._username,
                    "txtMdp": self._password,
                    "y": "19",
                },
                headers=headers,
                timeout=30,
            )

            if resp.status_code != 200:
                self.logger.error(
                    "Authentication failed with HTTP %d", resp.status_code
                )
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            solde_element = soup.find("label", {"for": "CLI_ID"})
            if not solde_element:
                self.logger.error(
                    "Could not find credit element in page (selector 'label[for=CLI_ID]')"
                )
                return None

            credit = solde_element.get_text(strip=True)
            self.logger.debug("Raw credit text scraped: %r", credit)
            return credit

        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Error fetching cafeteria credit: %s", exc)
            return None
        finally:
            try:
                session.get(f"{_BASE_URL}{_LOGOUT_PATH}", timeout=10)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Seen-item cache
    # ------------------------------------------------------------------

    def _already_seen(self, item_id: str) -> bool:
        row = self._seen_conn.execute(
            "SELECT 1 FROM seen_items WHERE id = ?", (item_id,)
        ).fetchone()
        return row is not None

    def _mark_seen(self, items: list[FeedItem]) -> None:
        if not items:
            return
        with self._seen_conn:
            self._seen_conn.executemany(
                "INSERT OR IGNORE INTO seen_items (id) VALUES (?)",
                [(item.id,) for item in items],
            )
