# event-to-news — Agent Guidelines

## Overview

**Purpose:** Expose arbitrary event sources (school platforms, home appliances, etc.)
as RSS feeds consumable by aggregators such as FreshRSS.

**Key files:**
| File | Role |
|---|---|
| `config.yml` | User configuration (feeds, schedule, module params) |
| `src/event_to_news/config.py` | Pydantic config loader |
| `src/event_to_news/models.py` | `FeedItem` dataclass |
| `src/event_to_news/base_module.py` | Abstract base class for all modules |
| `src/event_to_news/module_loader.py` | Dynamic module discovery |
| `src/event_to_news/feed_store.py` | JSON-backed item persistence + deduplication |
| `src/event_to_news/scheduler.py` | APScheduler-based polling |
| `src/event_to_news/rss.py` | feedgen-based RSS 2.0 generation |
| `src/event_to_news/server.py` | FastAPI HTTP server |
| `src/event_to_news/main.py` | Entry point |
| `src/event_to_news/modules/pronote.py` | Pronote school module |
| `src/event_to_news/modules/cafetaria.py` | Cafetaria credit module |

---

## Tech Stack

- **Python 3.12+** with **uv** for dependency management
- **FastAPI** + **uvicorn** for the HTTP server
- **APScheduler 3.x** (AsyncIOScheduler) for polling
- **feedgen** for RSS 2.0 XML generation
- **pydantic v2** for config validation and data models
- **pronotepy** for Pronote school platform integration
- **Docker / Docker Compose** for deployment

---

## Architecture

```
config.yml
    │
    ▼
AppConfig (pydantic)
    │
    ├── Scheduler ──► FeedJob ──► BaseModule.fetch() ──► FeedStore (JSON)
    │                                                         │
    └── FastAPI server ──────────────────────────────────────►│ /feed/<slug>
                                                              │ (RSS XML)
```

Each feed in `config.yml` maps to:
1. A **module** (file in `src/event_to_news/modules/`)
2. A **schedule** (interval like `30m` or cron `*/30 * * * *`)
3. A **FeedStore** persisted to `data/<slug>.json`

---

## Data Storage Layout

Each feed instance gets its own private directory:

```
data/
  <feed_slug>/
    feed.db          # FeedStore SQLite (RSS items served to the aggregator)
    seen.db          # Module-owned SQLite (e.g. Pronote seen-item cache)
    credentials.json # Module-owned credentials (e.g. Pronote rotating token)
```

- **`feed.db`** is owned by the framework (`FeedStore`). It holds the items that are served as RSS XML.
- Everything else in `data/<slug>/` is owned by the module itself. Modules may create any files they need (SQLite, JSON, etc.) or nothing at all.

---

## Adding a New Module

1. Create `src/event_to_news/modules/<name>.py`
2. Define exactly one class inheriting from `BaseModule`
3. Implement `async def fetch(self) -> list[FeedItem]`
4. Reference `module: <name>` in `config.yml`

```python
from pathlib import Path
from typing import Any
from event_to_news.base_module import BaseModule
from event_to_news.models import FeedItem

class MyModule(BaseModule):
    def __init__(self, feed_slug: str, params: dict[str, Any], data_dir: Path) -> None:
        super().__init__(feed_slug, params, data_dir)
        # self.data_dir is guaranteed to exist at this point
        # Use it to open a SQLite DB, load cached state, etc.

    async def fetch(self) -> list[FeedItem]:
        # Return ONLY new items — use self.data_dir to cache what was seen
        return [
            FeedItem(
                id="unique-stable-id",
                title="Something happened",
                content="<b>Details</b> here",
                category="MyCategory",
            )
        ]
```

**Rules:**
- `FeedItem.id` must be **stable and unique** across runs — it is the deduplication key in `FeedStore`.
- Modules are responsible for their own caching strategy. Returning only new items is preferred (avoids redundant FeedStore writes), but returning duplicates is safe — `FeedStore` deduplicates by id.
- Synchronous blocking code must be wrapped with `asyncio.get_event_loop().run_in_executor(None, sync_func)`.
- Never raise from `fetch()` without catching — let exceptions propagate so the scheduler logs them gracefully.

---

## Schedule Format

| Format | Example | Meaning |
|---|---|---|
| Interval | `30m` | Every 30 minutes |
| Interval | `1h30m` | Every 1 hour 30 minutes |
| Interval | `45s` | Every 45 seconds |
| Cron | `*/30 * * * *` | Every 30 minutes (cron) |
| Cron | `0 7 * * 1-5` | Every weekday at 07:00 |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | List all feeds with their RSS URLs |
| GET | `/feed/<slug>` | RSS 2.0 XML feed |
| GET | `/feed/<slug>/items` | Raw JSON items (debug) |
| GET | `/health` | Health check + active feed slugs |

---

## Pronote Module

Authentication:
- The **only** auth mechanism is `data/<feed_slug>/credentials.json`.
- Generate it once before first run:
  ```bash
  uv run python -m pronotepy.create_login
  # copy the resulting file to data/<feed_slug>/credentials.json
  ```
- The module reads, uses, and overwrites this file on every poll (PRONOTE rotates the token each session).
- No auth fields belong in `config.yml` or `params`.
- The file format matches what `pronotepy.export_credentials()` produces: keys are `pronote_url`, `username`, `password` (the token), `uuid`, `client_identifier`.

Supported `params` (all optional):
- `student_name` — cosmetic prefix added to item titles (e.g. `"Alice"`)
- `fetch_grades` — bool, default `true`
- `fetch_homework` — bool, default `true`
- `fetch_punishments` — bool, default `true`
- `fetch_absences` — bool, default `true`

---

## Cafetaria Module

Authentication:
- Credentials are set directly in `params` in `config.yml` (`username` and `password`).
- No separate credentials file is needed.

Schedule recommendation: use a daily cron at 20:00 — `"0 20 * * *"`.

Supported `params`:
- `username` — **(required)** portal login username
- `password` — **(required)** portal login password
- `student_name` — (optional) cosmetic prefix added to item titles (e.g. `"Alice"`)
- `site` — (optional) portal site identifier (default `"aes00152"`)

Item ID format: `cafetaria-<slug>-credit-<YYYY-MM-DD>` — one item per calendar day, deduplicated via `seen.db`.

---

## Running

**Local:**
```bash
uv sync
uv run event-to-news
```

**Docker:**
```bash
docker compose up -d
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CONFIG_PATH` | `config.yml` | Path to the YAML config file |
| `DATA_DIR` | `data` | Directory for persisted feed JSON files |

---

## Logging Configuration

Set `log_level` at the top level of `config.yml` to control verbosity:

```yaml
log_level: "DEBUG"   # DEBUG | INFO | WARNING | ERROR | CRITICAL
```

- Defaults to `WARNING` if omitted.
- Set to `DEBUG` to see per-item logs in every Pronote collector (grades, homework, punishments, absences), including raw counts returned by pronotepy and individual item IDs.
- The level is applied via `logging.basicConfig` in `main.py` after the config is loaded.

---

## Lessons Learned

- pronotepy uses a **rotating token**: after each login the token changes. Always call
  `client.export_credentials()` and persist the result to a file immediately after login.
- pronotepy is **synchronous** — always wrap calls in `run_in_executor` to avoid blocking
  the asyncio event loop.
- `FeedItem.id` stability is critical: if the id changes between polls, items appear
  as new in the aggregator even though the content is the same.
- **NEVER use pronotepy internal `.id` attributes** (e.g. `period.id`, `grade.id`) in
  `FeedItem.id` construction — PRONOTE regenerates all internal IDs on every session.
  Use stable human-readable attributes instead (e.g. `period.name`, `subject.name`, date, grade value).
- APScheduler 3.x (`AsyncIOScheduler`) must be started **after** the asyncio loop is running
  (i.e., inside a FastAPI lifespan handler).
- Each module instance must have its own private data directory (`data/<feed_slug>/`).
  The framework creates and passes this directory; modules must not hardcode paths.
