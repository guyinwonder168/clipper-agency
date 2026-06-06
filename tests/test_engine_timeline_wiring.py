"""Tests for engine.py timeline pipeline wiring."""

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


def _make_passing_gate():
    """Create a mock GateResult that passes."""
    gate = MagicMock()
    gate.passed = True
    gate.severity = "info"
    gate.message = "ok"
    return gate


@patch("clipper_agency.orchestrator.engine.get_connection")
@patch("clipper_agency.orchestrator.engine.initialize_schema")
class TestFormatValidatorWired:
    """Verify format validator is called after Researcher in pipeline."""

    def test_research_output_gets_validated_direction(
        self, mock_schema, mock_conn,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None

        settings = _make_settings()
        research_output = {
            "content_direction": {
                "recommended_format": "three_story_roundup",
                "selected_story_count": 2,
                "selected_stories": ["story_a", "story_b"],
            },
            "risk_flags": [],
            "sources": [{"url": "http://example.com", "type": "video"}],
        }

        with (
            patch(
                "clipper_agency.orchestrator.engine.load_settings",
                return_value=settings,
            ),
            patch.object(
                Orchestrator, "_run_researcher",
                return_value=research_output,
            ),
            patch.object(Orchestrator, "_record_gate"),
        ):
            orch = Orchestrator.__new__(Orchestrator)
            orch.db_path = "test.db"
            result = orch._stage_research(
                conn, 1, "test topic", [], "channel desc",
                "id", "casual", "gossip", "cache", "out",
            )

        assert "validated_direction" in result
        vd = result["validated_direction"]
        assert vd.format == "three_story_roundup"
        assert vd.story_count == 2


@patch("clipper_agency.orchestrator.engine.get_connection")
@patch("clipper_agency.orchestrator.engine.initialize_schema")
class TestDurationGateWired:
    """Verify duration gate fires after Scriptwriter."""

    def test_over_budget_script_fails_pipeline(
        self, mock_schema, mock_conn,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None

        settings = _make_settings(target=30, hard=35)
        # 200 total words → 200/2 + 2*0.5 = 101s >> 35s hard limit
        script_scenes = [
            {"scene": 1, "text": "word " * 100, "word_count": 100},
            {"scene": 2, "text": "word " * 100, "word_count": 100},
        ]
        script_output = {
            "script": script_scenes,
            "caption": "test caption",
        }

        with (
            patch(
                "clipper_agency.orchestrator.engine.load_settings",
                return_value=settings,
            ),
            patch.object(Orchestrator, "_run_scriptwriter",
                         return_value=script_output),
            patch.object(Orchestrator, "_record_gate"),
            patch.object(Orchestrator, "_complete_agent"),
        ):
            orch = Orchestrator.__new__(Orchestrator)
            orch.db_path = "test.db"
            result = orch._run_content_scriptwriter(
                conn, 1, "topic", [], "channel",
                "id", "casual", "gossip", {}, "cache",
            )

        assert result.get("status") == "failed"
        assert "exceeds hard limit" in result.get("error", "")

    def test_within_budget_script_passes(
        self, mock_schema, mock_conn,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None

        settings = _make_settings(target=30, hard=60)
        # 10 words * 2 wps + 1 * 0.5 = 5.5s << 60s
        script_scenes = [
            {"scene": 1, "text": "hello world test", "word_count": 10},
        ]
        script_output = {
            "script": script_scenes,
            "caption": "test caption",
        }

        with (
            patch(
                "clipper_agency.orchestrator.engine.load_settings",
                return_value=settings,
            ),
            patch.object(Orchestrator, "_run_scriptwriter",
                         return_value=script_output),
            patch.object(Orchestrator, "_record_gate"),
            patch.object(Orchestrator, "_complete_agent"),
        ):
            orch = Orchestrator.__new__(Orchestrator)
            orch.db_path = "test.db"
            result = orch._run_content_scriptwriter(
                conn, 1, "topic", [], "channel",
                "id", "casual", "gossip", {}, "cache",
            )

        assert result.get("status") != "failed"
        check = result.get("_duration_check", {})
        assert check.get("pass") is True


@patch("clipper_agency.orchestrator.engine.get_connection")
@patch("clipper_agency.orchestrator.engine.initialize_schema")
class TestTimelineReconcilerWired:
    """Verify timeline reconciler fires after Voice Producer."""

    def test_over_limit_timeline_fails_pipeline(
        self, mock_schema, mock_conn,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator
        from clipper_agency.orchestrator.gates import GateResult

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None

        # Hard limit = 35s but audio totals 60s
        settings = _make_settings(target=30, hard=35)
        script_scenes = [
            {"scene": 1, "role": "opening_hook", "text": "hook",
             "word_count": 5, "estimated_duration_sec": 5.0},
            {"scene": 2, "role": "body", "text": "story one story one",
             "word_count": 10, "estimated_duration_sec": 10.0},
        ]
        script_output = {"script": script_scenes, "caption": "test"}
        voice_output = {
            "audio_files": ["a1.wav", "a2.wav"],
            "audio_metadata": [
                {"scene": 1, "audio_path": "a1.wav",
                 "audio_duration_sec": 20.0},
                {"scene": 2, "audio_path": "a2.wav",
                 "audio_duration_sec": 40.0},
            ],
            "status": "ok",
        }
        pass_gate = GateResult(passed=True, severity="info",
                               message="ok", data={})

        with (
            patch(
                "clipper_agency.orchestrator.engine.load_settings",
                return_value=settings,
            ),
            patch(
                "clipper_agency.orchestrator.engine.GateAudioValidation",
                return_value=MagicMock(evaluate=MagicMock(
                    return_value=pass_gate)),
            ),
            patch.object(
                Orchestrator, "_run_content_scriptwriter",
                return_value=script_output,
            ),
            patch.object(
                Orchestrator, "_run_voice_producer",
                return_value=voice_output,
            ),
            patch.object(Orchestrator, "_record_gate"),
            patch.object(Orchestrator, "_complete_agent"),
        ):
            orch = Orchestrator.__new__(Orchestrator)
            orch.db_path = "test.db"
            result = orch._stage_content(
                conn, 1, "topic", [], "channel",
                "id", "casual", "gossip", {}, "cache", "out",
            )

        assert isinstance(result, dict)
        assert result.get("status") == "failed"
        assert result.get("failed_at") == "timeline_reconciler"

    def test_within_limit_returns_timeline(
        self, mock_schema, mock_conn,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator
        from clipper_agency.orchestrator.gates import GateResult

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None

        settings = _make_settings(target=30, hard=60)
        script_scenes = [
            {"scene": 1, "role": "opening_hook", "text": "hook",
             "word_count": 5, "estimated_duration_sec": 5.0},
            {"scene": 2, "role": "body", "text": "story one",
             "word_count": 10, "estimated_duration_sec": 10.0},
        ]
        script_output = {"script": script_scenes, "caption": "test"}
        voice_output = {
            "audio_files": ["a1.wav", "a2.wav"],
            "audio_metadata": [
                {"scene": 1, "audio_path": "a1.wav",
                 "audio_duration_sec": 5.0},
                {"scene": 2, "audio_path": "a2.wav",
                 "audio_duration_sec": 10.0},
            ],
            "status": "ok",
        }
        pass_gate = GateResult(passed=True, severity="info",
                               message="ok", data={})

        with (
            patch(
                "clipper_agency.orchestrator.engine.load_settings",
                return_value=settings,
            ),
            patch(
                "clipper_agency.orchestrator.engine.GateAudioValidation",
                return_value=MagicMock(evaluate=MagicMock(
                    return_value=pass_gate)),
            ),
            patch.object(
                Orchestrator, "_run_content_scriptwriter",
                return_value=script_output,
            ),
            patch.object(
                Orchestrator, "_run_voice_producer",
                return_value=voice_output,
            ),
            patch.object(Orchestrator, "_record_gate"),
            patch.object(Orchestrator, "_complete_agent"),
        ):
            orch = Orchestrator.__new__(Orchestrator)
            orch.db_path = "test.db"
            result = orch._stage_content(
                conn, 1, "topic", [], "channel",
                "id", "casual", "gossip", {}, "cache", "out",
            )

        # Should return tuple of 3 items: (script, voice, timeline)
        assert isinstance(result, tuple)
        assert len(result) == 3
        _script, _voice, timeline = result
        assert len(timeline) == 2
        assert timeline[0].target_duration_sec == 5.0
        assert timeline[1].target_duration_sec == 10.0


@patch("clipper_agency.orchestrator.engine.get_connection")
@patch("clipper_agency.orchestrator.engine.initialize_schema")
class TestTimelinePassedToDownstream:
    """Verify timeline kwarg reaches Visual Director and Composer."""

    def test_composition_receives_timeline(
        self, mock_schema, mock_conn,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator
        from clipper_agency.orchestrator.gates import GateResult
        from clipper_agency.orchestrator.timeline import TimelineItem

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None

        settings = _make_settings()
        timeline = [
            TimelineItem(
                scene=1, role="body", text="test", audio_path="a.wav",
                audio_duration_sec=5.0, start_sec=0.0, end_sec=5.0,
                target_duration_sec=5.0,
            ),
        ]
        visual_output = {
            "assets": [{"path": "img.jpg", "type": "image"}],
            "status": "ok",
        }
        compose_output = {"video_path": "out.mp4", "status": "ok"}
        pass_gate = GateResult(passed=True, severity="info",
                               message="ok", data={})

        with (
            patch(
                "clipper_agency.orchestrator.engine.load_settings",
                return_value=settings,
            ),
            patch(
                "clipper_agency.orchestrator.engine.GateAssetValidation",
                return_value=MagicMock(evaluate=MagicMock(
                    return_value=pass_gate)),
            ),
            patch(
                "clipper_agency.orchestrator.engine.GateVideoValidation",
                return_value=MagicMock(evaluate=MagicMock(
                    return_value=pass_gate)),
            ),
            patch.object(
                Orchestrator, "_run_visual_director_phase",
                return_value=visual_output,
            ) as mock_vd,
            patch.object(
                Orchestrator, "_run_composer",
                return_value=compose_output,
            ) as mock_composer,
            patch.object(Orchestrator, "_record_gate"),
            patch.object(Orchestrator, "_complete_agent"),
        ):
            orch = Orchestrator.__new__(Orchestrator)
            orch.db_path = "test.db"
            result = orch._stage_composition(
                conn, 1, "topic", {}, {"script": []},
                {"audio_files": []}, "cache", "out",
                timeline=timeline,
            )

        # Verify Visual Director received timeline
        vd_call_kwargs = mock_vd.call_args
        assert vd_call_kwargs.kwargs.get("timeline") == timeline

        # Verify Composer received timeline
        composer_call_kwargs = mock_composer.call_args
        assert composer_call_kwargs.kwargs.get("timeline") == timeline


@patch("clipper_agency.orchestrator.engine.get_connection")
@patch("clipper_agency.orchestrator.engine.initialize_schema")
class TestRetryDurationGateStopsPipeline:
    """Verify retry path stops when duration-gate fails scriptwriter."""

    def test_retry_stops_after_duration_gate_failure(
        self, mock_schema, mock_conn,
    ):
        from clipper_agency.orchestrator.engine import Orchestrator

        conn = MagicMock()
        mock_conn.return_value = conn
        mock_schema.return_value = None

        settings = _make_settings(target=30, hard=35)
        # Over-budget script: 200 words → ~101s >> 35s hard limit
        failed_script = {
            "script": [
                {"scene": 1, "text": "word " * 100, "word_count": 100},
                {"scene": 2, "text": "word " * 100, "word_count": 100},
            ],
            "caption": "test",
            "status": "failed",
            "error": "exceeds hard limit",
        }

        niche_ctx = {
            "safety_rules": [],
            "channel_description": "channel",
            "language": "id",
            "tone": "casual",
            "content_angle": "gossip",
        }

        with (
            patch(
                "clipper_agency.orchestrator.engine.load_settings",
                return_value=settings,
            ),
            patch(
                "clipper_agency.orchestrator.engine.PipelineOrder"
                if False else
                "clipper_agency.orchestrator.engine.PIPELINE_ORDER",
                ["safety", "segment_producer", "scriptwriter",
                 "voice_producer", "visual_director", "composer",
                 "reviewer"],
            ),
            patch.object(
                Orchestrator, "_run_content_scriptwriter",
                return_value=failed_script,
            ),
            patch.object(Orchestrator, "_fail_agent",
                         return_value={"status": "failed", "job_id": 1}),
            patch.object(
                Orchestrator, "_run_content_voice",
            ) as mock_voice,
        ):
            orch = Orchestrator.__new__(Orchestrator)
            orch.db_path = "test.db"
            result = orch._retry_downstream_stages(
                conn, 1, "topic", niche_ctx, "indonesian_artists",
                "out", "cache",
                from_idx=2,  # scriptwriter index
                use_cache=False,
                research_output={},
                script_output={},
                voice_output={},
                visual_output={},
            )

        # Should abort and NOT reach voice producer
        assert result is not None
        assert result.get("status") == "failed"
        mock_voice.assert_not_called()
