"""Tests for config/model_cache — OpenRouter model metadata caching."""

import json
import time
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_refresh_dedupe(monkeypatch):
    """Reset the process-local refresh-dedupe window before each test.

    ``refresh_model_cache`` skips refreshes attempted within ``_REFRESH_MIN_GAP``
    (30s). Without this reset, a test that triggers a real refresh would suppress
    refreshes in every later test in the same session — breaking the
    ``triggers_refresh`` assertions.
    """
    from clipper_agency.config import model_cache

    monkeypatch.setattr(model_cache, "_last_refresh_attempt_at", 0.0)


def test_get_model_metadata_returns_cached_data(tmp_path, monkeypatch):
    """get_model_metadata reads from cache file."""
    from clipper_agency.config.model_cache import get_model_metadata

    cache_data = {
        "fetched_at": time.time(),
        "models": {
            "test-model": {"context_length": 8192, "max_completion_tokens": 4096},
        },
    }
    cache_file = tmp_path / "model_cache.json"
    cache_file.write_text(json.dumps(cache_data))
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    result = get_model_metadata("test-model")
    assert result is not None
    assert result["max_completion_tokens"] == 4096


def test_get_model_metadata_returns_none_for_unknown(tmp_path, monkeypatch):
    """Unknown model name returns None."""
    from clipper_agency.config.model_cache import get_model_metadata

    cache_file = tmp_path / "model_cache.json"
    cache_file.write_text(json.dumps({"fetched_at": time.time(), "models": {}}))
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    assert get_model_metadata("nonexistent-model") is None


def test_refresh_model_cache_writes_file(tmp_path, monkeypatch):
    """refresh_model_cache fetches API and writes cache."""
    from clipper_agency.config.model_cache import refresh_model_cache

    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    mock_response = {
        "data": [
            {"id": "test-model", "context_length": 8192, "max_completion_tokens": 4096},
        ],
    }
    with patch("httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.return_value.json.return_value = mock_response
        mock_client.get.return_value.raise_for_status.return_value = None

        refresh_model_cache(force=True)

    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert "test-model" in data["models"]
    assert data["models"]["test-model"]["max_completion_tokens"] == 4096


def test_cache_not_refreshed_when_fresh(tmp_path, monkeypatch):
    """Cache < 7 days old is not refreshed (unless force)."""
    from clipper_agency.config.model_cache import refresh_model_cache

    cache_file = tmp_path / "model_cache.json"
    fresh_data = {"fetched_at": time.time(), "models": {}}
    cache_file.write_text(json.dumps(fresh_data))
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    with patch("httpx.Client") as mock_client_cls:
        refresh_model_cache(force=False)
        # httpx.Client should NOT be instantiated for fresh cache
        mock_client_cls.assert_not_called()


def test_get_model_metadata_returns_none_when_cache_unavailable(tmp_path, monkeypatch):
    """get_model_metadata returns None when cache file can't be loaded."""
    from clipper_agency.config import model_cache

    # Cache file doesn't exist and refresh fails silently
    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr(model_cache, "_CACHE_PATH", cache_file)
    monkeypatch.setattr(model_cache, "_load_cache", lambda: None)

    assert model_cache.get_model_metadata("any-model") is None


def test_refresh_model_cache_handles_network_failure(tmp_path, monkeypatch):
    """refresh_model_cache logs warning and returns on network error."""
    from clipper_agency.config.model_cache import refresh_model_cache

    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.side_effect = OSError("connection refused")
        # Should not raise
        refresh_model_cache(force=True)

    assert not cache_file.exists()


def test_load_cache_triggers_refresh_when_missing(tmp_path, monkeypatch):
    """_load_cache calls refresh_model_cache when cache file doesn't exist."""
    from clipper_agency.config import model_cache

    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr(model_cache, "_CACHE_PATH", cache_file)

    refresh_called = []
    monkeypatch.setattr(
        model_cache, "refresh_model_cache", lambda force=False: refresh_called.append(True)
    )

    model_cache._load_cache()
    assert len(refresh_called) == 1


def test_load_cache_returns_none_when_refresh_fails(tmp_path, monkeypatch):
    """_load_cache returns None when refresh doesn't create the file."""
    from clipper_agency.config import model_cache

    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr(model_cache, "_CACHE_PATH", cache_file)
    # refresh_model_cache is a no-op (simulating network failure)
    monkeypatch.setattr(model_cache, "refresh_model_cache", lambda force=False: None)

    assert model_cache._load_cache() is None


def test_load_cache_returns_none_on_corrupted_json(tmp_path, monkeypatch):
    """_load_cache returns None when cache file has invalid JSON.

    A corrupted cache is treated as stale and would force-refresh; mock the
    refresh so this test exercises the read-failure path offline.
    """
    from clipper_agency.config import model_cache

    cache_file = tmp_path / "model_cache.json"
    cache_file.write_text("{invalid json content")
    monkeypatch.setattr(model_cache, "_CACHE_PATH", cache_file)
    monkeypatch.setattr(model_cache, "refresh_model_cache", lambda force=False: None)

    assert model_cache._load_cache() is None


def test_load_cache_triggers_refresh_when_stale(tmp_path, monkeypatch):
    """_load_cache force-refreshes when cache is older than TTL.

    Regression: previously _load_cache only refreshed when the file was MISSING,
    so the 7-day TTL was dead code and stale caches (with removed models) lingered.
    """
    from clipper_agency.config import model_cache

    cache_file = tmp_path / "model_cache.json"
    stale = {"fetched_at": time.time() - (8 * 24 * 3600), "models": {"old/model": {}}}
    cache_file.write_text(json.dumps(stale))
    monkeypatch.setattr(model_cache, "_CACHE_PATH", cache_file)

    refreshed: list[bool] = []
    monkeypatch.setattr(
        model_cache, "refresh_model_cache", lambda force=False: refreshed.append(force)
    )

    model_cache._load_cache()
    assert refreshed == [True]


def test_list_catalog_models_returns_models(tmp_path, monkeypatch):
    """list_catalog_models returns the cached {model_id: metadata} dict."""
    from clipper_agency.config.model_cache import list_catalog_models

    cache_file = tmp_path / "model_cache.json"
    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "models": {"z-ai/glm-4.7-flash": {"context_length": 128000}},
            }
        )
    )
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    catalog = list_catalog_models()
    assert "z-ai/glm-4.7-flash" in catalog
    assert catalog["z-ai/glm-4.7-flash"]["context_length"] == 128000


def test_list_catalog_models_empty_when_no_cache(tmp_path, monkeypatch):
    """list_catalog_models returns {} when no cache is available."""
    from clipper_agency.config import model_cache

    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr(model_cache, "_CACHE_PATH", cache_file)
    monkeypatch.setattr(model_cache, "refresh_model_cache", lambda force=False: None)

    assert model_cache.list_catalog_models() == {}


def test_cache_is_fresh_returns_false_when_missing(tmp_path, monkeypatch):
    """_cache_is_fresh returns False when cache file doesn't exist."""
    from clipper_agency.config.model_cache import _cache_is_fresh

    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    assert _cache_is_fresh() is False


def test_cache_is_fresh_returns_false_on_corrupted_json(tmp_path, monkeypatch):
    """_cache_is_fresh returns False when cache file has invalid JSON."""
    from clipper_agency.config.model_cache import _cache_is_fresh

    cache_file = tmp_path / "model_cache.json"
    cache_file.write_text("not json at all")
    monkeypatch.setattr("clipper_agency.config.model_cache._CACHE_PATH", cache_file)

    assert _cache_is_fresh() is False
