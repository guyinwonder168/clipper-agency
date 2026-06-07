"""OpenRouter model metadata cache — auto-fetch, lazy-load, 7-day refresh."""

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("data/model_cache.json")
_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def get_model_metadata(model_name: str) -> dict[str, Any] | None:
    """Return cached metadata for *model_name*, or None if not found.

    Lazy-loads cache on first call.  Returns dict with keys like
    ``context_length`` and ``max_completion_tokens``.
    """
    cache = _load_cache()
    if cache is None:
        return None
    return cache.get("models", {}).get(model_name)


def refresh_model_cache(force: bool = False) -> None:
    """Fetch model list from OpenRouter and write to disk.

    Skips if cache is less than 7 days old unless *force* is True.
    """
    if not force and _cache_is_fresh():
        logger.debug("Model cache is fresh, skipping refresh")
        return

    try:
        with httpx.Client(base_url="", timeout=30) as client:
            resp = client.get(_OPENROUTER_MODELS_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Failed to refresh model cache: %s", exc)
        return

    models: dict[str, Any] = {}
    for entry in data.get("data", []):
        model_id = entry.get("id", "")
        models[model_id] = {
            "context_length": entry.get("context_length", 0),
            "max_completion_tokens": entry.get("max_completion_tokens", 0),
        }

    cache_data = {
        "fetched_at": time.time(),
        "models": models,
    }

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache_data, indent=2))
    logger.info("Model cache refreshed: %d models", len(models))


def _load_cache() -> dict[str, Any] | None:
    """Load cache from disk, triggering refresh if stale."""
    if not _CACHE_PATH.exists():
        refresh_model_cache()

    if not _CACHE_PATH.exists():
        return None

    try:
        return json.loads(_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read model cache: %s", exc)
        return None


def _cache_is_fresh() -> bool:
    """Return True if cache file exists and is less than 7 days old."""
    if not _CACHE_PATH.exists():
        return False
    try:
        data = json.loads(_CACHE_PATH.read_text())
        age = time.time() - data.get("fetched_at", 0)
        return age < _TTL_SECONDS
    except (json.JSONDecodeError, OSError):
        return False
