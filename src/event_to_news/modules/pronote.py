"""
Pronote module — fetches grades, homework, absences, and punishments
from a PRONOTE parent account and publishes them as feed items.

Authentication:
  Place a credentials.json file in the module's data directory before first run:
      data/<feed_slug>/credentials.json

  Generate it once with:
      uv run python -m pronotepy.create_login

  The file is updated automatically after every successful login because
  PRONOTE rotates the token on each session.

  Expected credentials.json format (produced by pronotepy):
      {
        "pronote_url": "https://...",
        "username": "...",
        "password": "...",   (this IS the rotating token — pronotepy names it "password")
        "uuid": "...",
        "client_identifier": "..."   (optional)
      }

Data directory layout (data/<feed_slug>/):
    credentials.json    Token credentials — read and refreshed on every poll
    seen.db             SQLite cache of already-emitted item IDs

config.yml params (all optional):
    student_name:       Prefix added to item titles, e.g. "Alice"
    fetch_grades:       true (default)
    fetch_homework:     true (default)
    fetch_punishments:  true (default)
    fetch_absences:     true (default)
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..base_module import BaseModule
from ..models import FeedItem

_SEEN_DDL = """
CREATE TABLE IF NOT EXISTS seen_items (
    id         TEXT PRIMARY KEY,
    seen_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class PronoteModule(BaseModule):
    """Fetch school events from a PRONOTE parent account."""

    def __init__(self, feed_slug: str, params: dict[str, Any], data_dir: Path) -> None:
        super().__init__(feed_slug, params, data_dir)

        # What to fetch (all enabled by default)
        self._fetch_grades: bool = params.get("fetch_grades", True)
        self._fetch_homework: bool = params.get("fetch_homework", True)
        self._fetch_punishments: bool = params.get("fetch_punishments", True)
        self._fetch_absences: bool = params.get("fetch_absences", True)

        # Cosmetic prefix added to item titles
        self._student_name: str = params.get("student_name", "")

        # Credentials are always read from this fixed path
        self._credentials_path: Path = self.data_dir / "credentials.json"

        # SQLite cache of seen item IDs — only new items are emitted per poll
        self._seen_conn = sqlite3.connect(
            str(self.data_dir / "seen.db"), check_same_thread=False
        )
        with self._seen_conn:
            self._seen_conn.executescript(_SEEN_DDL)

    # ------------------------------------------------------------------
    # BaseModule interface
    # ------------------------------------------------------------------

    async def fetch(self) -> list[FeedItem]:
        # pronotepy is synchronous — offload to a thread to avoid blocking asyncio
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_fetch)

    # ------------------------------------------------------------------
    # Synchronous implementation
    # ------------------------------------------------------------------

    def _sync_fetch(self) -> list[FeedItem]:
        import pronotepy  # lazy import so a missing dep only fails this module

        client = self._login(pronotepy)
        if client is None or not client.logged_in:
            self.logger.error(
                "Failed to log in to PRONOTE — make sure %s exists",
                self._credentials_path,
            )
            return []

        # PRONOTE rotates the token on every session — persist immediately
        self._save_credentials(client.export_credentials())

        prefix = f"[{self._student_name}] " if self._student_name else ""
        all_items: list[FeedItem] = []

        if self._fetch_grades:
            all_items.extend(self._collect_grades(client, prefix))
        if self._fetch_homework:
            all_items.extend(self._collect_homework(client, prefix))
        if self._fetch_punishments:
            all_items.extend(self._collect_punishments(client, prefix))
        if self._fetch_absences:
            all_items.extend(self._collect_absences(client, prefix))

        new_items = self._filter_unseen(all_items)
        self._mark_seen(new_items)
        return new_items

    def _login(self, pronotepy):
        """Load credentials.json and return an authenticated ParentClient, or None."""
        if not self._credentials_path.exists():
            self.logger.error(
                "credentials.json not found at %s. "
                "Run: uv run python -m pronotepy.create_login",
                self._credentials_path,
            )
            return None

        try:
            creds = json.loads(self._credentials_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Failed to read credentials.json: %s", exc)
            return None

        try:
            # Use ParentClient (not Client) — required for parent accounts
            client = pronotepy.ParentClient.token_login(**creds)
            return client
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Login failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Seen-item cache
    # ------------------------------------------------------------------

    def _filter_unseen(self, items: list[FeedItem]) -> list[FeedItem]:
        if not items:
            return []
        ids = [item.id for item in items]
        existing = {
            row[0]
            for row in self._seen_conn.execute(
                f"SELECT id FROM seen_items WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            ).fetchall()
        }
        new = [item for item in items if item.id not in existing]
        self.logger.info(
            "Poll: %d total items from Pronote, %d new", len(items), len(new)
        )
        return new

    def _mark_seen(self, items: list[FeedItem]) -> None:
        if not items:
            return
        with self._seen_conn:
            self._seen_conn.executemany(
                "INSERT OR IGNORE INTO seen_items (id) VALUES (?)",
                [(item.id,) for item in items],
            )

    # ------------------------------------------------------------------
    # Data collectors
    # ------------------------------------------------------------------

    def _collect_grades(self, client, prefix: str) -> list[FeedItem]:
        """Collect grades across all periods."""
        items = []
        try:
            for period in client.periods:
                for grade in period.grades:
                    subject = (
                        getattr(grade.subject, "name", "Unknown")
                        if grade.subject
                        else "Unknown"
                    )
                    grade_value = str(grade.grade)
                    out_of = str(grade.out_of)
                    date = getattr(grade, "date", None)
                    comment = getattr(grade, "comment", "") or ""

                    item_id = (
                        f"pronote-{self.feed_slug}-grade-{period.id}-{subject}-{date}"
                    )
                    content_parts = [
                        f"<b>Subject:</b> {subject}",
                        f"<b>Grade:</b> {grade_value} / {out_of}",
                        f"<b>Period:</b> {period.name}",
                    ]
                    if comment:
                        content_parts.append(f"<b>Comment:</b> {comment}")
                    if date:
                        content_parts.append(f"<b>Date:</b> {date}")

                    items.append(
                        FeedItem(
                            id=item_id,
                            title=f"{prefix}Grade: {subject} — {grade_value}/{out_of}",
                            content="<br/>".join(content_parts),
                            published=self._to_datetime(date),
                            category="Grade",
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to collect grades: %s", exc)
        return items

    def _collect_homework(self, client, prefix: str) -> list[FeedItem]:
        """Collect homework due from today onwards."""
        import datetime as dt

        items = []
        try:
            for hw in client.homework(dt.date.today()):
                subject = (
                    getattr(hw.subject, "name", "Unknown") if hw.subject else "Unknown"
                )
                due = getattr(hw, "date", None)
                description = getattr(hw, "description", "") or ""
                done = getattr(hw, "done", False)

                item_id = f"pronote-{self.feed_slug}-homework-{subject}-{due}"
                title = f"{prefix}Homework: {subject}"
                if due:
                    title += f" (due {due})"

                content_parts = [
                    f"<b>Subject:</b> {subject}",
                    f"<b>Due:</b> {due}",
                    f"<b>Done:</b> {'Yes' if done else 'No'}",
                ]
                if description:
                    content_parts.append(f"<b>Description:</b> {description}")

                items.append(
                    FeedItem(
                        id=item_id,
                        title=title,
                        content="<br/>".join(content_parts),
                        published=self._to_datetime(due),
                        category="Homework",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to collect homework: %s", exc)
        return items

    def _collect_punishments(self, client, prefix: str) -> list[FeedItem]:
        """Collect punishments from the current period only."""
        items = []
        try:
            for p in client.current_period.punishments:
                date = getattr(p, "date", None)
                nature = getattr(p, "nature", "") or ""
                given_by = getattr(p, "given_by", "") or ""
                circumstances = getattr(p, "circumstances", "") or ""
                reasons = getattr(p, "reasons", []) or []
                duration = getattr(p, "duration", None)

                reason_txt = "\n".join(str(r) for r in reasons) if reasons else ""
                item_id = f"pronote-{self.feed_slug}-punishment-{date}-{nature}"
                title = (
                    f"{prefix}Punishment: {nature}" if nature else f"{prefix}Punishment"
                )

                content_parts: list[str] = []
                if nature:
                    content_parts.append(f"<b>Nature:</b> {nature}")
                if given_by:
                    content_parts.append(f"<b>Given by:</b> {given_by}")
                if circumstances:
                    content_parts.append(f"<b>Circumstances:</b> {circumstances}")
                if reason_txt:
                    content_parts.append(f"<b>Reason:</b> {reason_txt}")
                if date:
                    content_parts.append(f"<b>Date:</b> {date}")
                if duration:
                    content_parts.append(f"<b>Duration:</b> {duration}")

                items.append(
                    FeedItem(
                        id=item_id,
                        title=title,
                        content="<br/>".join(content_parts),
                        published=self._to_datetime(date),
                        category="Punishment",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to collect punishments: %s", exc)
        return items

    def _collect_absences(self, client, prefix: str) -> list[FeedItem]:
        """Collect absences from the current period only."""
        items = []
        try:
            for absence in client.current_period.absences:
                from_date = getattr(absence, "from_date", None)
                to_date = getattr(absence, "to_date", None)
                justified = getattr(absence, "justified", False)
                hours = getattr(absence, "hours", None)
                reasons = getattr(absence, "reasons", []) or []

                reason_txt = "\n".join(str(r) for r in reasons) if reasons else ""
                item_id = f"pronote-{self.feed_slug}-absence-{from_date}"
                date_label = str(from_date) if from_date else "Unknown date"
                title = f"{prefix}Absence on {date_label}"

                content_parts = [
                    f"<b>From:</b> {from_date}",
                    f"<b>To:</b> {to_date}",
                    f"<b>Justified:</b> {'Yes' if justified else 'No'}",
                ]
                if hours:
                    content_parts.append(f"<b>Duration:</b> {hours}")
                if reason_txt:
                    content_parts.append(f"<b>Reason:</b> {reason_txt}")

                items.append(
                    FeedItem(
                        id=item_id,
                        title=title,
                        content="<br/>".join(content_parts),
                        published=self._to_datetime(from_date),
                        category="Absence",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to collect absences: %s", exc)
        return items

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_datetime(value) -> datetime:
        import datetime as dt

        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, dt.datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, dt.date):
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    def _save_credentials(self, credentials: dict) -> None:
        try:
            self._credentials_path.write_text(
                json.dumps(credentials, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Could not save credentials.json: %s", exc)
