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


def test_content_planning_config_aliases():
    """ContentPlanningConfig provides semantic aliases for clarity."""
    from clipper_agency.config.schema import ContentPlanningConfig

    cp = ContentPlanningConfig(
        target_duration_sec=45,
        hard_limit_sec=50,
    )
    # Aliases mirror primary fields
    assert cp.target_script_duration_sec == 45
    assert cp.max_final_duration_sec == 50
    # Primary fields unchanged
    assert cp.target_duration_sec == 45
    assert cp.hard_limit_sec == 50
    # Defaults
    defaults = ContentPlanningConfig()
    assert defaults.target_script_duration_sec == 55
    assert defaults.max_final_duration_sec == 60


# --- Task 5: Config Hierarchy ---


def test_config_hierarchy_defaults():
    hierarchy = ConfigHierarchy()
    assert hierarchy.get("segment_producer", "model") == "xiaomi/mimo-v2.5"


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
    assert ad.agents["segment_producer"]["model"] == "xiaomi/mimo-v2.5"


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


# --- Task 0.2: Quality Gate Configuration Defaults ---


def test_app_settings_include_quality_gate_defaults():
    from clipper_agency.config.schema import AppSettings

    with patch.dict("os.environ", {}, clear=True):
        settings = AppSettings(_env_file=None)

        assert settings.quality.visual_coverage.black_frame_max_ms == 200
        assert settings.quality.visual_coverage.empty_frame_max_ms == 300
        assert settings.quality.visual_coverage.freeze_warning_ms == 1500
        assert settings.quality.visual_coverage.final_visual_gap_max_ms == 200
        assert settings.quality.text_collision.subtitle_overlap_max == 0.20
        assert settings.quality.safe_area.face_overlap_max == 0.15
        assert settings.quality.semantic_review.max_repair_cycles == 2


def test_app_settings_include_runtime_inspection_quality_defaults():
    from clipper_agency.config.schema import AppSettings

    with patch.dict("os.environ", {}, clear=True):
        settings = AppSettings(_env_file=None)

        assert settings.quality.runtime_inspection.enabled is True
        assert settings.quality.runtime_inspection.persist_keyframes is True
        assert settings.quality.runtime_inspection.frame_interval_sec == 0.5
        assert settings.quality.runtime_inspection.max_frames_per_asset == 8
        assert settings.quality.runtime_inspection.perceptual_hash_distance == 6
        assert settings.quality.ocr.enabled is True
        assert settings.quality.ocr.provider == "paddleocr"
        assert settings.quality.ocr.min_confidence == 0.55
        assert settings.quality.ocr.large_region_area_ratio == 0.20
        assert settings.quality.face_detection.enabled is True
        assert settings.quality.face_detection.provider == "mediapipe"
        assert settings.quality.face_detection.min_confidence == 0.60
        assert settings.quality.semantic_review.enabled is True
        assert settings.quality.semantic_review.provider == "existing_multimodal_llm"
        assert settings.quality.semantic_review.max_assets_per_beat == 3
        assert settings.quality.semantic_review.max_frames_per_asset == 4
        assert settings.quality.semantic_review.minimum_claim_support == 0.70
        assert settings.quality.semantic_review.maximum_misleading_risk == 0.30
        assert settings.quality.semantic_review.max_repair_cycles == 2
        assert settings.quality.enforcement.block_on_reviewer_fail is True
        assert settings.quality.enforcement.block_publication_on_quality_fail is True


def test_app_settings_include_llm_trace_observability_defaults():
    from clipper_agency.config.schema import AppSettings

    with patch.dict("os.environ", {}, clear=True):
        settings = AppSettings(_env_file=None)

        assert settings.observability.llm_traces.enabled is True
        assert settings.observability.llm_traces.persist_resolved_prompts is True
        assert settings.observability.llm_traces.persist_raw_responses is True
        assert settings.observability.llm_traces.persist_parsed_responses is True
        assert settings.observability.llm_traces.persist_validation_results is True
        assert settings.observability.llm_traces.log_full_payload_inline is False
        assert settings.observability.llm_traces.redact_secrets is True
        assert settings.observability.llm_traces.retention_days == 30
        assert settings.observability.llm_traces.required is False


def test_app_settings_include_tavily_brave_keys():
    """Tavily and Brave API keys load from environment with empty defaults."""
    from clipper_agency.config.schema import AppSettings

    with patch.dict("os.environ", {}, clear=True):
        settings = AppSettings(_env_file=None)
        assert settings.tavily_api_key == ""
        assert settings.brave_api_key == ""

    with patch.dict(
        "os.environ", {"TAVILY_API_KEY": "tvly-123", "BRAVE_API_KEY": "brv-456"}, clear=True
    ):
        settings = AppSettings(_env_file=None)
        assert settings.tavily_api_key == "tvly-123"
        assert settings.brave_api_key == "brv-456"
