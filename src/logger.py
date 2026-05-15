from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger


def setup_logging(logs_dir: str | Path = "logs", level: str | None = None) -> None:
    """Configure structured console and file logging."""
    log_level = level or os.getenv("ARENA_LOG_LEVEL", "INFO")
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=log_level, colorize=True, enqueue=True)
    logger.add(Path(logs_dir) / "arena.log", level=log_level, rotation="10 MB", retention="14 days", enqueue=True)


__all__ = ["logger", "setup_logging"]
