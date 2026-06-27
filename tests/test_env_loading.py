"""Tests for central .env loading + ElevenLabs env-driven config knobs.

Covers the complete-.env-load fix (bootstrap wires every entry point) and the
mitigation contract (missing/unparseable env vars fall back to defaults, never
raise). Hermetic — uses monkeypatch; no real .env / network. AAA pattern.
"""

from __future__ import annotations

import pytest

from clipper_agency import bootstrap
from clipper_agency.services.elevenlabs import (
    DEFAULT_MODEL_ID,
    DEFAULT_VOICE_SETTINGS,
    _env_bool,
    _env_float,
    _model_id,
    _voice_settings_from_env,
)

# ---------------------------------------------------------------------------
# bootstrap.load_env — idempotent, calls load_dotenv.
# ---------------------------------------------------------------------------


def test_load_env_calls_load_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_env delegates to dotenv.load_dotenv exactly once per call."""
    # Arrange
    calls: list[int] = []
    monkeypatch.setattr(bootstrap, "load_dotenv", lambda: calls.append(1))
    # Act
    bootstrap.load_env()
    # Assert
    assert calls == [1]


def test_load_env_is_safe_to_call_repeatedly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple entry points may call load_env; it must not blow up."""
    # Arrange — real load_dotenv is idempotent; this just asserts no raise.
    monkeypatch.setattr(bootstrap, "load_dotenv", lambda: None)
    # Act / Assert
    bootstrap.load_env()
    bootstrap.load_env()


# ---------------------------------------------------------------------------
# ElevenLabs model id — env override + default mitigation.
# ---------------------------------------------------------------------------


def test_model_id_defaults_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — no ELEVENLABS_MODEL set.
    monkeypatch.delenv("ELEVENLABS_MODEL", raising=False)
    # Act / Assert
    assert _model_id() == DEFAULT_MODEL_ID


def test_model_id_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("ELEVENLABS_MODEL", "eleven_v3")
    # Act / Assert
    assert _model_id() == "eleven_v3"


def test_model_id_empty_string_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty ELEVENLABS_MODEL must not yield an empty model id."""
    # Arrange
    monkeypatch.setenv("ELEVENLABS_MODEL", "")
    # Act / Assert
    assert _model_id() == DEFAULT_MODEL_ID


# ---------------------------------------------------------------------------
# _env_float / _env_bool primitives.
# ---------------------------------------------------------------------------


def test_env_float_missing_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_FLOAT", raising=False)
    assert _env_float("X_FLOAT", 0.42) == 0.42


def test_env_float_bad_value_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_FLOAT", "not-a-number")
    assert _env_float("X_FLOAT", 0.42) == 0.42


def test_env_bool_false_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    for token in ("false", "0", "no", "off", "FALSE"):
        monkeypatch.setenv("X_BOOL", token)
        assert _env_bool("X_BOOL", True) is False


def test_env_bool_missing_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_BOOL", raising=False)
    assert _env_bool("X_BOOL", True) is True


# ---------------------------------------------------------------------------
# _voice_settings_from_env — partial .env still yields a valid dict.
# ---------------------------------------------------------------------------


def test_voice_settings_defaults_match_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no env knobs set, the dict equals DEFAULT_VOICE_SETTINGS + speed 1.0."""
    # Arrange — clear every knob.
    for key in (
        "ELEVENLABS_VOICE_STABILITY",
        "ELEVENLABS_VOICE_SIMILARITY",
        "ELEVENLABS_VOICE_STYLE",
        "ELEVENLABS_VOICE_SPEAKER_BOOST",
        "ELEVENLABS_VOICE_SPEED",
    ):
        monkeypatch.delenv(key, raising=False)
    # Act
    settings = _voice_settings_from_env()
    # Assert
    assert settings["stability"] == DEFAULT_VOICE_SETTINGS["stability"]
    assert settings["similarity_boost"] == DEFAULT_VOICE_SETTINGS["similarity_boost"]
    assert settings["style"] == DEFAULT_VOICE_SETTINGS["style"]
    assert settings["use_speaker_boost"] == DEFAULT_VOICE_SETTINGS["use_speaker_boost"]
    assert settings["speed"] == 1.0


def test_voice_settings_partial_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting only STYLE overrides that knob; the rest stay at default."""
    # Arrange
    monkeypatch.setenv("ELEVENLABS_VOICE_STYLE", "0.9")
    for key in (
        "ELEVENLABS_VOICE_STABILITY",
        "ELEVENLABS_VOICE_SIMILARITY",
        "ELEVENLABS_VOICE_SPEAKER_BOOST",
        "ELEVENLABS_VOICE_SPEED",
    ):
        monkeypatch.delenv(key, raising=False)
    # Act
    settings = _voice_settings_from_env()
    # Assert
    assert settings["style"] == 0.9
    assert settings["stability"] == DEFAULT_VOICE_SETTINGS["stability"]


def test_voice_settings_bad_style_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A garbage STYLE value must not raise — it falls back to the default."""
    # Arrange
    monkeypatch.setenv("ELEVENLABS_VOICE_STYLE", "loud")
    # Act
    settings = _voice_settings_from_env()
    # Assert
    assert settings["style"] == DEFAULT_VOICE_SETTINGS["style"]


# ---------------------------------------------------------------------------
# Entry-point chokepoints — every runtime entry triggers load_env().
# Regression guard: if someone removes load_env from dashboard/app.py or
# Orchestrator.__init__, the corresponding test below fails.
# ---------------------------------------------------------------------------


def test_dashboard_import_triggers_load_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing clipper_agency.dashboard.app calls load_env() at import time."""
    # Arrange — spy on the symbol bootstrap actually resolves (see finding 1:
    # patching dotenv.load_dotenv would miss; bootstrap bound the name already).
    import importlib
    import sys

    calls: list[int] = []
    monkeypatch.setattr(bootstrap, "load_dotenv", lambda: calls.append(1))
    # Drop the cached dashboard module so re-import re-runs its import-time code.
    sys.modules.pop("clipper_agency.dashboard.app", None)

    # Act
    import clipper_agency.dashboard.app as _dashboard  # noqa: F401

    importlib.reload(_dashboard)

    # Assert
    assert calls, "dashboard.app import-time load_env() did not call bootstrap.load_dotenv"


def test_orchestrator_init_triggers_load_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Orchestrator.__init__ calls load_env() before any service reads env vars."""
    # Arrange — spy on bootstrap.load_dotenv; use an isolated temp DB so the
    # constructor's schema init is hermetic.
    from clipper_agency.orchestrator.engine import Orchestrator

    calls: list[int] = []
    monkeypatch.setattr(bootstrap, "load_dotenv", lambda: calls.append(1))
    db_path = str(tmp_path / "bootstrap_test.db")

    # Act
    Orchestrator(db_path=db_path)

    # Assert
    assert calls, "Orchestrator.__init__ did not call bootstrap.load_dotenv via load_env"
