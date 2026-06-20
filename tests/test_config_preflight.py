"""Tests for config/preflight — startup agent-model catalog validation."""

import pytest

from clipper_agency.config.loader import _SETTINGS_MODEL_MAP


def _canonical_catalog() -> dict:
    return {
        "z-ai/glm-4.7-flash": {"context_length": 128000},
        "xiaomi/mimo-v2.5": {"context_length": 64000},
        "qwen/qwen3-32b": {"context_length": 40960},
        "google/gemini-2.5-flash": {"context_length": 1000000},
    }


def _canonical_models() -> dict:
    return {
        "safety": "z-ai/glm-4.7-flash",
        "segment_producer": "xiaomi/mimo-v2.5",
        "scriptwriter": "qwen/qwen3-32b",
        "visual_director": "xiaomi/mimo-v2.5",
        "reviewer": "google/gemini-2.5-flash",
    }


def _patch(monkeypatch, catalog: dict, models_by_agent: dict) -> None:
    """Patch the preflight's external seams: refresh, catalog, agent resolution."""
    monkeypatch.setattr(
        "clipper_agency.config.preflight.refresh_model_cache", lambda force=False: None
    )
    monkeypatch.setattr("clipper_agency.config.preflight.list_catalog_models", lambda: catalog)
    monkeypatch.setattr(
        "clipper_agency.config.preflight.get_agent_config",
        lambda name: {"model": models_by_agent[name]},
    )


def test_preflight_passes_when_all_slugs_in_catalog(monkeypatch):
    """All canonical preset slugs present in a populated catalog → validated list."""
    from clipper_agency.config.preflight import preflight_agent_models

    _patch(monkeypatch, _canonical_catalog(), _canonical_models())

    validated = preflight_agent_models()
    assert {name for name, _ in validated} == set(_canonical_models())
    assert all(model in _canonical_catalog() for _, model in validated)


def test_preflight_raises_on_unknown_slug_in_populated_catalog(monkeypatch):
    """A slug missing from a POPULATED catalog fails fast (RuntimeError)."""
    from clipper_agency.config.preflight import preflight_agent_models

    models = _canonical_models() | {"safety": "bogus/missing-model"}
    _patch(monkeypatch, _canonical_catalog(), models)

    with pytest.raises(RuntimeError, match="not in the OpenRouter catalog"):
        preflight_agent_models()


def test_preflight_warns_and_continues_when_no_catalog(monkeypatch):
    """No catalog available → cannot validate → warn, do not block the run."""
    from clipper_agency.config.preflight import preflight_agent_models

    models = _canonical_models() | {"safety": "bogus/missing-model"}
    _patch(monkeypatch, {}, models)  # empty catalog = unavailable

    validated = preflight_agent_models()  # must NOT raise
    assert ("safety", "bogus/missing-model") in validated


def test_preflight_force_refreshes_cache_once(monkeypatch):
    """Preflight always force-refreshes so stale/removed models are caught."""
    from clipper_agency.config import preflight

    refreshed: list[bool] = []
    monkeypatch.setattr(
        preflight, "refresh_model_cache", lambda force=False: refreshed.append(force)
    )
    monkeypatch.setattr(preflight, "list_catalog_models", _canonical_catalog)
    monkeypatch.setattr(
        preflight, "get_agent_config", lambda name: {"model": _canonical_models()[name]}
    )

    preflight.preflight_agent_models()
    assert refreshed == [True]


def test_preflight_skips_agents_without_model(monkeypatch):
    """Agents whose resolved model is empty are skipped (defensive guard)."""
    from clipper_agency.config.preflight import preflight_agent_models

    models = {name: "" for name in _SETTINGS_MODEL_MAP}
    _patch(monkeypatch, _canonical_catalog(), models)

    assert preflight_agent_models() == []
