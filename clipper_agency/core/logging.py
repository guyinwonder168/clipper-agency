"""Centralized logging configuration for Clipper Agency."""

import logging
import sys
from pathlib import Path
from typing import Any


class ThirdPartyLogFilter(logging.Filter):
    """Prepend [LIB] to third-party library log messages."""

    THIRD_PARTY_PREFIXES = ("httpcore.", "httpx.", "urllib3.")

    def filter(self, record: logging.LogRecord) -> bool:
        if any(record.name.startswith(p) for p in self.THIRD_PARTY_PREFIXES):
            record.msg = f"[LIB] {record.msg}"
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured format.

    Called once at application startup. Subsequent calls are no-ops.
    """
    if logging.getLogger().hasHandlers():
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(numeric_level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    handler.addFilter(ThirdPartyLogFilter())

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a named component.

    Usage::

        logger = get_logger(__name__)
        logger.info("Agent starting")
        logger.error("Pipeline failed: %s", exc_info=True)
    """
    return logging.getLogger(name)


def add_job_file_handler(job_id: int, output_dir: str = "data/outputs") -> None:
    """Add a FileHandler writing per-job debug logs."""
    log_dir = Path(output_dir) / f"job_{job_id}"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "debug.log"

    handler = logging.FileHandler(str(log_file))
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    handler.addFilter(ThirdPartyLogFilter())
    logging.getLogger().addHandler(handler)


def remove_job_file_handler() -> None:
    """Remove the last FileHandler added by add_job_file_handler."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            root.removeHandler(handler)
            handler.close()
            return
