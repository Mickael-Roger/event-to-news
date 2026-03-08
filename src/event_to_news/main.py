"""
Application entry point.

Loads config, sets up the scheduler, then starts the FastAPI server.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn

from .config import load_config
from .scheduler import Scheduler
from .server import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    config_path = Path(os.environ.get("CONFIG_PATH", "config.yml"))
    data_dir = Path(os.environ.get("DATA_DIR", "data"))

    logger.info("Loading config from %s", config_path.absolute())
    app_config = load_config(config_path)

    scheduler = Scheduler(app_config=app_config, data_dir=data_dir)
    scheduler.setup()

    app = create_app(app_config=app_config, scheduler=scheduler)

    uvicorn.run(
        app,
        host=app_config.server.host,
        port=app_config.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
