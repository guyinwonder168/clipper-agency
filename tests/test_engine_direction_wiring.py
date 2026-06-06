"""Tests for validated_direction wiring from engine to Scriptwriter."""

from unittest.mock import MagicMock, patch

import pytest


def _make_settings(target=55, hard=60):
    """Create a mock AppSettings with ContentPlanningConfig."""
    cp = MagicMock()
    cp.target_duration_sec = target
    cp.hard_limit_sec = hard
    cp.default_format = "three_story_roundup"
    cp.max_stories_per_video = 3
    cp.estimated_words_per_second = 2.0
    settings = MagicMock()
    settings.content_planning = cp
    settings.assets_cache = "data/assets/cache"
    return settings


@patch("clipper_agency.orchestrator.engine.load_settings")
@patch("clipper_agency.orchestrator.engine.get_connection")
@patch("clipper_agency.orchestrator.engine.initialize_schema")
class TestValidatedDirectionWiring:
    """Verify validated_direction is extracted and passed to Scriptwriter."""

    def test_validated_direction_passed_to_scriptwriter(
        self, mock_schema, mock_conn, mock_settings,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator
        from clipper_agency.orchestrator.validator import ContentDirectionResult

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None
        mock_settings.return_value = _make_settings()

        direction = ContentDirectionResult(
            format="three_story_roundup",
            story_count=2,
            stories=["story_a", "story_b"],
            content_angle="dramatic",
        )
        research_output = {
            "research_brief": "brief text",
            "validated_direction": direction,
        }

        with patch.object(
            Orchestrator, "_record_gate",
        ), patch.object(
            Orchestrator, "_complete_agent",
        ), patch.object(
            Orchestrator, "_run_scriptwriter", return_value={"script": []},
        ) as mock_sw:
            orch = Orchestrator()
            orch._run_content_scriptwriter(
                conn, job_id=1, topic="test",
                safety_rules=[], channel_description="chan",
                language="id", tone="casual", content_angle="info",
                research_output=research_output,
                assets_cache="/tmp/cache",
            )
            _, kwargs = mock_sw.call_args
            sd = kwargs["story_direction"]
            assert sd["story_format"] == "three_story_roundup"
            assert sd["story_count"] == 2
            assert sd["stories_list"] == ["story_a", "story_b"]
            # content_angle from direction overrides "info"
            assert kwargs["content_angle"] == "dramatic"

    def test_budget_params_passed_to_scriptwriter(
        self, mock_schema, mock_conn, mock_settings,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator
        from clipper_agency.orchestrator.validator import ContentDirectionResult

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None
        mock_settings.return_value = _make_settings(target=50, hard=60)

        direction = ContentDirectionResult(
            format="single_story_deep",
            story_count=1,
            stories=["story_x"],
            content_angle="analytical",
        )
        research_output = {
            "research_brief": "brief",
            "validated_direction": direction,
        }

        with patch.object(
            Orchestrator, "_record_gate",
        ), patch.object(
            Orchestrator, "_complete_agent",
        ), patch.object(
            Orchestrator, "_run_scriptwriter", return_value={"script": []},
        ) as mock_sw:
            orch = Orchestrator()
            orch._run_content_scriptwriter(
                conn, job_id=1, topic="test",
                safety_rules=[], channel_description="chan",
                language="id", tone="casual", content_angle="info",
                research_output=research_output,
                assets_cache="/tmp/cache",
            )
            _, kwargs = mock_sw.call_args
            sd = kwargs["story_direction"]
            assert sd["target_duration_sec"] == 50
            assert sd["hard_limit_sec"] == 60
            assert sd["estimated_words_per_second"] == 2.0
            # 1 story * 2 + 2 = 4
            assert sd["max_scenes"] == 4

    def test_no_direction_uses_config_defaults(
        self, mock_schema, mock_conn, mock_settings,
    ):
        """When validated_direction is missing, budget params still pass."""
        from clipper_agency.orchestrator.engine import Orchestrator

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None
        mock_settings.return_value = _make_settings()

        research_output = {"research_brief": "brief"}

        with patch.object(
            Orchestrator, "_record_gate",
        ), patch.object(
            Orchestrator, "_complete_agent",
        ), patch.object(
            Orchestrator, "_run_scriptwriter", return_value={"script": []},
        ) as mock_sw:
            orch = Orchestrator()
            orch._run_content_scriptwriter(
                conn, job_id=1, topic="test",
                safety_rules=[], channel_description="chan",
                language="id", tone="casual", content_angle="info",
                research_output=research_output,
                assets_cache="/tmp/cache",
            )
            _, kwargs = mock_sw.call_args
            sd = kwargs["story_direction"]
            # Budget params should still be present from config
            assert sd["target_duration_sec"] == 55
            assert sd["hard_limit_sec"] == 60
            # 3 (config default) * 2 + 2 = 8
            assert sd["max_scenes"] == 8
            # No story_format/stories_list when no direction
            assert "story_format" not in sd
            assert "stories_list" not in sd
