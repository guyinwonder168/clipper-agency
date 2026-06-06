"""Tests for config schema models and loader."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from clipper_agency.config.hierarchy import AgentDefaults, ConfigHierarchy
from clipper_agency.config.schema import AgentLLMConfig, NicheConfig


def test_niche_config_valid():
    data = {
        "name": "indonesian_artists",
        "language": "id",
        "tone": "casual_tiktok",
        "video_length": {"target": 30, "hard_limit": 60},
        "safety_rules": ["no_defamation"],
    }
    cfg = NicheConfig(**data)
    assert cfg.name == "indonesian_artists"
    assert cfg.video_length.target == 30


def test_niche_config_invalid_missing_name():
    data = {"language": "id"}
    with pytest.raises(ValidationError):
        NicheConfig(**data)


def test_app_settings_defaults():
    """AppSettings provides sensible defaults when no .env file is loaded."""
    from clipper_agency.config.schema import AppSettings

    with patch.dict("os.environ", {}, clear=True):
        settings = AppSettings(_env_file=None)
        assert settings.db_path == "data/clipper.db"
        assert str(settings.assets_cache) == "assets/cache"
        assert str(settings.output_dir) == "outputs"
        assert settings.gemini_api_key == ""
        assert settings.gemini_tts_voice_name == "Kore"
        assert settings.debug is False


def test_agent_llm_config():
    cfg = AgentLLMConfig(model="glm-4-9b", temperature=0.3)
    assert cfg.model == "glm-4-9b"
    assert cfg.temperature == pytest.approx(0.3)


# --- Task 5: Config Hierarchy ---


def test_config_hierarchy_defaults():
    hierarchy = ConfigHierarchy()
    assert hierarchy.get("segment_producer", "model") == "mimo-v2-flash"


def test_config_hierarchy_niche_override():
    hierarchy = ConfigHierarchy()
    hierarchy.set_niche_override("segment_producer", "model", "qwen3-32b")
    assert hierarchy.get("segment_producer", "model") == "qwen3-32b"


def test_config_hierarchy_job_override_wins():
    hierarchy = ConfigHierarchy()
    hierarchy.set_niche_override("segment_producer", "model", "qwen3-32b")
    hierarchy.set_job_override("segment_producer", "model", "deepseek-v3.2")
    assert hierarchy.get("segment_producer", "model") == "deepseek-v3.2"


def test_agent_defaults_preset():
    ad = AgentDefaults()
    assert "segment_producer" in ad.agents
    assert ad.agents["segment_producer"]["model"] == "mimo-v2-flash"


def test_config_hierarchy_account_override():
    """Account override takes precedence over niche but loses to job."""
    hierarchy = ConfigHierarchy()
    hierarchy.set_niche_override("segment_producer", "model", "qwen3-32b")
    hierarchy.set_account_override("segment_producer", "model", "gemini-2.5-flash")
    # Account beats niche
    assert hierarchy.get("segment_producer", "model") == "gemini-2.5-flash"
    # Job still beats account
    hierarchy.set_job_override("segment_producer", "model", "deepseek-v3.2")
    assert hierarchy.get("segment_producer", "model") == "deepseek-v3.2"


def test_config_hierarchy_account_override_for_unknown_agent():
    """Account override for an agent not in defaults returns the override."""
    hierarchy = ConfigHierarchy()
    hierarchy.set_account_override("custom_agent", "timeout", 120)
    assert hierarchy.get("custom_agent", "timeout") == 120
