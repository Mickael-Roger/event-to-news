"""
Configuration loader.

Reads config.yml and exposes typed Pydantic models.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class FeedConfig(BaseModel):
    """Configuration for a single RSS feed."""

    # Human-readable feed title shown in the aggregator
    title: str
    # Short description of the feed
    description: str = ""
    # Name of the module that produces items (must match a file in modules/)
    module: str
    # Cron expression OR plain interval string like "30m", "1h", "5m"
    schedule: str = "30m"
    # Maximum number of items to keep in the feed (oldest are pruned)
    max_items: int = 100
    # Module-specific parameters passed as-is to the module
    params: dict[str, Any] = Field(default_factory=dict)


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    # Base URL used in feed links (e.g. http://myserver:8000)
    base_url: str = "http://localhost:8000"


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    # Mapping of feed slug (used in URL) -> feed configuration
    feeds: dict[str, FeedConfig] = Field(default_factory=dict)
    # Logging level for the application. One of: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    # Defaults to WARNING if not set.
    log_level: str = "WARNING"


def load_config(path: Path | str = "config.yml") -> AppConfig:
    """Load and validate configuration from a YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path.absolute()}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig.model_validate(raw)
