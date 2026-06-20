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
# Process-local dedupe: minimum seconds between network refresh attempts (even
# when force=True). Without this, a failed refresh leaves the cache stale, so
# every cache read via _load_cache (one per agent at startup) would re-attempt
# the 30s /models request — an offline `run --dry-run` could stack several 30s
# timeouts before degrading (PR 7 Codex P2#2).
_last_refresh_attempt_at: float = 0.0
_REFRESH_MIN_GAP: float = 30.0


def get_model_metadata(model_name: str) -> dict[str, Any] | None:
    """Return cached metadata for *model_name*, or None if not found.

    Lazy-loads cache on first call.  Returns dict with keys like
    ``context_length`` and ``max_completion_tokens``.
    """
    cache = _load_cache()
    if cache is None:
        return None
    return cache.get("models", {}).get(model_name)


def list_catalog_models() -> dict[str, Any]:
    """Return the cached catalog ``{model_id: metadata}``, refreshing if stale.

    Empty dict when no cache is available (refresh failed and nothing on disk).
    Used by the startup preflight (``config/preflight.py``) to validate that
    resolved agent slugs exist in the live OpenRouter catalog.
    """
    cache = _load_cache()
    if cache is None:
        return {}
    return cache.get("models", {})


def refresh_model_cache(force: bool = False) -> None:
    """Fetch model list from OpenRouter and write to disk.

    Skips if cache is less than 7 days old unless *force* is True. Also skips if
    a refresh was attempted within ``_REFRESH_MIN_GAP`` seconds (even when
    forced), so a flapping or unreachable catalog endpoint cannot trigger a
    30s-timeout storm across repeated cache reads.
    """
    global _last_refresh_attempt_at

    if not force and _cache_is_fresh():
        logger.debug("Model cache is fresh, skipping refresh")
        return

    now = time.time()
    if now - _last_refresh_attempt_at < _REFRESH_MIN_GAP:
        logger.debug(
            "Model cache refresh attempted %.1fs ago — skipping",
            now - _last_refresh_attempt_at,
        )
        return
    _last_refresh_attempt_at = now

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
    """Load cache from disk, refreshing when missing OR stale (older than TTL).

    Previously this only refreshed when the file was *missing*, which made the
    7-day ``_TTL_SECONDS`` check in ``_cache_is_fresh`` effectively dead code —
    a present-but-stale cache was never refreshed, so removed/deprecated models
    lingered. Now staleness triggers a force-refresh; ``refresh_model_cache``
    swallows network errors so this degrades to the stale cache offline.
    """
    if not _cache_is_fresh():
        refresh_model_cache(force=True)

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
