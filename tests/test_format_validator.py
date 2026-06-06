import pytest
from clipper_agency.orchestrator.validator import (
    validate_content_direction,
    ContentDirectionResult,
)
from clipper_agency.config.schema import ContentPlanningConfig


class TestFormatValidator:
    def test_valid_direction_passes(self):
        cfg = ContentPlanningConfig()
        direction = {
            "recommended_format": "three_story_roundup",
            "selected_story_count": 3,
            "selected_stories": ["a", "b", "c"],
        }
        result = validate_content_direction(direction, cfg)
        assert result.format == "three_story_roundup"
        assert result.story_count == 3

    def test_unknown_format_falls_back_to_default(self):
        cfg = ContentPlanningConfig(default_format="three_story_roundup")
        direction = {"recommended_format": "unknown_format"}
        result = validate_content_direction(direction, cfg)
        assert result.format == "three_story_roundup"

    def test_too_many_stories_clamped(self):
        cfg = ContentPlanningConfig(max_stories_per_video=3)
        direction = {
            "recommended_format": "three_story_roundup",
            "selected_story_count": 10,
            "selected_stories": ["a"] * 10,
        }
        result = validate_content_direction(direction, cfg)
        assert result.story_count == 3
        assert len(result.stories) == 3

    def test_missing_direction_uses_fallback(self):
        cfg = ContentPlanningConfig()
        result = validate_content_direction(None, cfg)
        assert result.format == "three_story_roundup"
        assert result.story_count == 3
        assert result.fallback is True

    def test_empty_stories_uses_fallback(self):
        cfg = ContentPlanningConfig(max_stories_per_video=3)
        direction = {
            "recommended_format": "three_story_roundup",
            "selected_story_count": 0,
            "selected_stories": [],
        }
        result = validate_content_direction(direction, cfg)
        assert result.story_count == 3

    def test_result_is_dataclass(self):
        cfg = ContentPlanningConfig()
        result = validate_content_direction(None, cfg)
        assert hasattr(result, "format")
        assert hasattr(result, "story_count")
        assert hasattr(result, "stories")
        assert hasattr(result, "content_angle")
        assert hasattr(result, "fallback")
