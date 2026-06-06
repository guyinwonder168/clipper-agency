"""Tests for retry path script_scenes fix and G10 configurable duration limit."""

from unittest.mock import MagicMock, patch

from clipper_agency.orchestrator.engine import Orchestrator
from clipper_agency.orchestrator.gates import GateVideoValidation


def _make_engine():
    """Create Orchestrator with DB init mocked out."""
    with patch("clipper_agency.orchestrator.engine.initialize_schema"), \
         patch("clipper_agency.orchestrator.engine.get_connection"):
        return Orchestrator(db_path=":memory:")


class TestRetryTimeline:
    """Bug 1: _retry_composer_stage must pass script_scenes from scriptwriter output."""

    def test_retry_composer_passes_script_scenes(self, tmp_path):
        engine = _make_engine()
        with patch.object(engine, "_load_agent_output") as mock_load:
            mock_load.return_value = {
                "script": [{"scene": 1, "text": "hello"}],
            }
            with patch.object(engine, "_run_composer") as mock_run:
                mock_run.return_value = {"status": "completed", "video_path": ""}
                with patch(
                    "clipper_agency.orchestrator.engine.load_settings",
                ) as mock_settings:
                    mock_settings.return_value.content_planning.hard_limit_sec = 60
                    engine._retry_composer_stage(
                        conn=MagicMock(),
                        job_id=2,
                        visual_output={"assets": []},
                        voice_output={"audio_files": []},
                        output_dir=str(tmp_path),
                        assets_cache=str(tmp_path),
                    )
                call_kwargs = mock_run.call_args[1]
                assert "script_scenes" in call_kwargs
                assert call_kwargs["script_scenes"] == [
                    {"scene": 1, "text": "hello"},
                ]

    def test_retry_composer_loads_scriptwriter_output(self, tmp_path):
        """Verify _load_agent_output is called with correct agent name."""
        engine = _make_engine()
        with patch.object(engine, "_load_agent_output") as mock_load:
            mock_load.return_value = {"script": []}
            with patch.object(engine, "_run_composer") as mock_run:
                mock_run.return_value = {"status": "completed", "video_path": ""}
                with patch(
                    "clipper_agency.orchestrator.engine.load_settings",
                ) as mock_settings:
                    mock_settings.return_value.content_planning.hard_limit_sec = 60
                    engine._retry_composer_stage(
                        conn=MagicMock(),
                        job_id=5,
                        visual_output={"assets": []},
                        voice_output={"audio_files": []},
                        output_dir=str(tmp_path),
                        assets_cache=str(tmp_path),
                    )
                mock_load.assert_called_once_with(
                    str(tmp_path), 5, "scriptwriter",
                )


class TestG10ConfigurableLimit:
    """Bug 2: GateVideoValidation must accept configurable hard_limit_sec."""

    def test_g10_default_limit_pass(self):
        g10 = GateVideoValidation()
        result = g10._check_duration_only(55.0, hard_limit_sec=60)
        assert result is None  # None means pass

    def test_g10_default_limit_fail(self):
        g10 = GateVideoValidation()
        result = g10._check_duration_only(62.0, hard_limit_sec=60)
        assert result is not None  # Not None means fail
        assert "too long" in result.message.lower()

    def test_g10_custom_limit_pass(self):
        g10 = GateVideoValidation()
        # Custom limit (75) — 62s should pass
        result = g10._check_duration_only(62.0, hard_limit_sec=75)
        assert result is None

    def test_g10_custom_limit_fail(self):
        g10 = GateVideoValidation()
        # Custom limit (75) — 76s should fail
        result = g10._check_duration_only(76.0, hard_limit_sec=75)
        assert result is not None
        assert "too long" in result.message.lower()
        assert "75s" in result.message

    def test_g10_none_uses_default(self):
        g10 = GateVideoValidation()
        # None should use DEFAULT_MAX_DURATION (60)
        result = g10._check_duration_only(55.0, hard_limit_sec=None)
        assert result is None

        result = g10._check_duration_only(61.0, hard_limit_sec=None)
        assert result is not None

    def test_g10_too_short(self):
        g10 = GateVideoValidation()
        result = g10._check_duration_only(15.0, hard_limit_sec=60)
        assert result is not None
        assert "too short" in result.message.lower()
