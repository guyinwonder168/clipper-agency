"""Tests for blueprint wiring from engine to Scriptwriter."""

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
class TestBlueprintWiring:
    """Verify blueprint is built from research_output and passed to Scriptwriter."""

    def test_validated_direction_enriches_blueprint(
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
            "story_beats": [{"beat": 1}],
            "verified_facts": ["fact1"],
            "unverified_claims": ["claim1"],
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
            bp = kwargs["blueprint"]
            assert bp["story_beats"] == [{"beat": 1}]
            assert bp["verified_facts"] == ["fact1"]
            assert bp["unverified_claims"] == ["claim1"]
            assert bp["story_format"] == "three_story_roundup"
            assert bp["story_count"] == 2
            assert bp["stories_list"] == ["story_a", "story_b"]
            # content_angle from direction overrides "info"
            assert kwargs["content_angle"] == "dramatic"

    def test_budget_params_in_blueprint(
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
            bp = kwargs["blueprint"]
            assert bp["target_duration_sec"] == 50
            assert bp["hard_limit_sec"] == 60
            assert bp["estimated_words_per_second"] == 2.0

    def test_no_direction_still_passes_blueprint(
        self, mock_schema, mock_conn, mock_settings,
    ):
        """When validated_direction is missing, blueprint still gets budget params."""
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
            bp = kwargs["blueprint"]
            # Budget params should still be present from config
            assert bp["target_duration_sec"] == 55
            assert bp["hard_limit_sec"] == 60
            # No story_format/stories_list when no direction
            assert "story_format" not in bp
            assert "stories_list" not in bp
