"""Tests for config YAML loader (load_niche, load_template, load_config)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from clipper_agency.config.loader import build_channel_description, load_config, load_niche, load_settings, load_template
from clipper_agency.config.schema import AppSettings, NicheConfig, TemplateConfig


class TestLoadSettings:
    """load_settings() — returns AppSettings from environment."""

    def test_load_settings_returns_app_settings(self):
        settings = load_settings()
        assert settings.db_path == "data/clipper.db"
        assert settings.debug is False

    def test_load_settings_reads_env_vars(self):
        """Verify that environment variables are picked up by AppSettings."""
        with patch.dict(os.environ, {"DB_PATH": "/tmp/test.db", "OUTPUT_DIR": "/tmp/out"}):
            settings = load_settings()
            assert settings.db_path == "/tmp/test.db"
            assert str(settings.output_dir) == "/tmp/out"

    def test_load_settings_defaults_when_env_unset(self):
        """Verify defaults when env vars are not set (no .env file)."""
        with patch.dict(os.environ, {}, clear=True):
            settings = AppSettings(_env_file=None)
            assert settings.db_path == "data/clipper.db"
            assert str(settings.output_dir) == "outputs"
            assert str(settings.assets_cache) == "assets/cache"


class TestLoadNiche:
    """load_niche() — reads niche YAML into NicheConfig."""

    def test_load_niche_from_fixture(self, fixtures_dir):
        niche = load_niche("test_niche", niches_dir=fixtures_dir)
        assert isinstance(niche, NicheConfig)
        assert niche.name == "indonesian_artists"
        assert niche.language == "id"
        assert niche.video_length.target == 30
        assert "no_defamation" in niche.safety_rules

    def test_load_niche_includes_new_fields(self, fixtures_dir):
        """NicheConfig should parse content_angle, search_terms, max_hashtags."""
        niche = load_niche("test_niche", niches_dir=fixtures_dir)
        assert niche.content_angle == "trending_artist_update"
        assert niche.search_terms == ["viral", "trending"]
        assert niche.max_hashtags == 5

    def test_load_niche_file_not_found(self, fixtures_dir):
        with pytest.raises(FileNotFoundError, match="Niche not found"):
            load_niche("nonexistent_niche", niches_dir=fixtures_dir)

    def test_load_default_indonesian_artists_niche(self):
        niche = load_niche("indonesian_artists")

        assert isinstance(niche, NicheConfig)
        assert niche.name == "indonesian_artists"
        assert niche.language == "id"
        assert niche.video_length.target == 30
        assert "no_defamation" in niche.safety_rules


class TestLoadTemplate:
    """load_template() — reads template YAML into TemplateConfig."""

    def test_load_template_from_fixture(self, fixtures_dir):
        template = load_template("test_template", templates_dir=fixtures_dir)
        assert isinstance(template, TemplateConfig)
        assert template.name == "rapid_update"
        assert template.type == "rapid_update"
        assert template.duration == 30
        assert "b_roll" in template.assets_required

    def test_load_template_file_not_found(self, fixtures_dir):
        with pytest.raises(FileNotFoundError, match="Template not found"):
            load_template("nonexistent_template", templates_dir=fixtures_dir)

    @pytest.mark.parametrize("template_name", ["news_card", "b_roll_narration", "rapid_update"])
    def test_load_default_templates(self, template_name):
        template = load_template(template_name)

        assert isinstance(template, TemplateConfig)
        assert template.name == template_name
        assert template.type == template_name


class TestLoadConfig:
    """load_config() — legacy dict loader."""

    def test_load_config_returns_dict_with_settings(self):
        config = load_config()
        assert isinstance(config, dict)
        assert "db_path" in config
        assert config["debug"] is False

    def test_load_config_merges_user_yaml(self, fixtures_dir, monkeypatch):
        user_yaml = fixtures_dir / "test_niche.yaml"
        config = load_config(config_path=str(user_yaml))
        assert isinstance(config, dict)
        # Should contain niche config merged in
        assert config.get("name") == "indonesian_artists"
        # Still has app settings
        assert "db_path" in config


class TestBuildChannelDescription:
    """build_channel_description() — builds identity string from NicheConfig."""

    def test_builds_description_from_niche_config(self, fixtures_dir):
        niche = load_niche("test_niche", niches_dir=fixtures_dir)
        desc = build_channel_description(niche)
        assert "Indonesian" in desc
        assert "trending artist update" in desc
        assert "casual TikTok" in desc

    def test_default_niche_builds_description(self):
        niche = load_niche("indonesian_artists")
        desc = build_channel_description(niche)
        assert desc  # non-empty
        assert "Indonesian" in desc

    def test_custom_niche_builds_description(self):
        from clipper_agency.config.schema import NicheConfig
        niche = NicheConfig(
            name="tech_reviews",
            language="en",
            tone="professional",
            content_angle="latest_gadget_reviews",
        )
        desc = build_channel_description(niche)
        assert desc  # non-empty


class TestGetAgentConfig:
    """get_agent_config() — resolves model + temperature from hierarchy."""

    def test_get_agent_config_returns_model_and_temperature(self, monkeypatch):
        """get_agent_config resolves model + temperature from hierarchy."""
        from clipper_agency.config.loader import get_agent_config

        monkeypatch.setattr(
            "clipper_agency.config.model_cache.get_model_metadata",
            lambda _: {"context_length": 8192, "max_completion_tokens": 4096},
        )
        # Mock load_settings to return settings with empty model fields
        # (simulates no .env overrides, hierarchy is the source of truth)
        from clipper_agency.config.schema import AppSettings
        empty_settings = AppSettings(
            _env_file=None,
            OPENROUTER_API_KEY="test",
            safety_model="",
            researcher_model="",
            scriptwriter_model="",
            visual_director_model="",
            reviewer_model="",
        )
        monkeypatch.setattr(
            "clipper_agency.config.loader.load_settings",
            lambda: empty_settings,
        )
        result = get_agent_config("safety")
        assert result["model"] == "glm-4.7-flash"
        assert result["temperature"] == 0.1
        assert result["max_completion_tokens"] == 4096

    def test_get_agent_config_env_override(self, monkeypatch):
        """SAFETY_MODEL env var overrides hierarchy preset."""
        from clipper_agency.config.loader import get_agent_config

        monkeypatch.setattr(
            "clipper_agency.config.model_cache.get_model_metadata",
            lambda _: {"context_length": 8192, "max_completion_tokens": 4096},
        )
        from clipper_agency.config.schema import AppSettings
        override_settings = AppSettings(
            _env_file=None,
            OPENROUTER_API_KEY="test",
            safety_model="custom-model",
        )
        monkeypatch.setattr(
            "clipper_agency.config.loader.load_settings",
            lambda: override_settings,
        )
        result = get_agent_config("safety")
        assert result["model"] == "custom-model"
