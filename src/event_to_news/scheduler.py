"""
Scheduler — polls each module on its configured schedule.

Supports:
  - Plain interval strings: "5m", "30m", "1h", "2h30m", "86400s"
  - Cron expressions:       "*/30 * * * *"
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import FeedConfig
from .feed_store import FeedStore
from .module_loader import instantiate_module

if TYPE_CHECKING:
    from .config import AppConfig

logger = logging.getLogger(__name__)

# Matches strings like "5m", "1h", "2h30m", "45s", "1h30m45s"
_INTERVAL_RE = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
)


def _parse_schedule(schedule: str) -> IntervalTrigger | CronTrigger:
    """Convert a schedule string to an APScheduler trigger."""
    schedule = schedule.strip()

    # Try interval format first
    m = _INTERVAL_RE.match(schedule)
    if m and any(m.group(g) for g in ("hours", "minutes", "seconds")):
        return IntervalTrigger(
            hours=int(m.group("hours") or 0),
            minutes=int(m.group("minutes") or 0),
            seconds=int(m.group("seconds") or 0),
        )

    # Fall back to cron
    parts = schedule.split()
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )

    raise ValueError(
        f"Invalid schedule format: {schedule!r}. "
        "Use an interval like '30m', '1h', or a 5-part cron expression."
    )


class FeedJob:
    """Wraps a module + store pair for scheduling."""

    def __init__(self, slug: str, config: FeedConfig, data_dir: Path) -> None:
        self.slug = slug
        self.config = config
        # Each feed gets its own subdirectory: data/<slug>/
        feed_dir = data_dir / slug
        feed_dir.mkdir(parents=True, exist_ok=True)
        self.store = FeedStore(
            feed_slug=slug,
            max_items=config.max_items,
            data_dir=feed_dir,
        )
        self.module = instantiate_module(
            module_name=config.module,
            feed_slug=slug,
            params=config.params,
            data_dir=feed_dir,
        )

    async def run(self) -> None:
        logger.info("[%s] Polling module %s …", self.slug, self.config.module)
        try:
            items = await self.module.fetch()
            added = self.store.add_items(items)
            logger.info("[%s] Poll complete — %d new item(s)", self.slug, added)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[%s] Module error: %s", self.slug, exc)


class Scheduler:
    def __init__(self, app_config: "AppConfig", data_dir: Path = Path("data")) -> None:
        self._config = app_config
        self._data_dir = data_dir
        self._jobs: dict[str, FeedJob] = {}
        self._scheduler = AsyncIOScheduler()

    def setup(self) -> None:
        """Instantiate all modules and register their jobs."""
        for slug, feed_cfg in self._config.feeds.items():
            try:
                job = FeedJob(slug=slug, config=feed_cfg, data_dir=self._data_dir)
                trigger = _parse_schedule(feed_cfg.schedule)
                self._scheduler.add_job(
                    job.run,
                    trigger=trigger,
                    id=slug,
                    name=f"feed:{slug}",
                    replace_existing=True,
                )
                self._jobs[slug] = job
                logger.info("[%s] Scheduled with %s", slug, feed_cfg.schedule)
            except Exception as exc:  # noqa: BLE001
                logger.error("[%s] Failed to set up feed: %s", slug, exc)

    def start(self) -> None:
        self._scheduler.start()
        # Run all jobs immediately on startup so feeds are populated right away
        for job in self._jobs.values():
            asyncio.ensure_future(job.run())

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)

    def get_store(self, slug: str) -> FeedStore | None:
        job = self._jobs.get(slug)
        return job.store if job else None

    @property
    def feed_slugs(self) -> list[str]:
        return list(self._jobs.keys())
