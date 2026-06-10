"""Tests for Composer visual coverage diagnostics — real detector integration.

Task 5.1: Replace placeholder empty lists in _attach_visual_coverage_diagnostics()
with actual FFmpeg detector calls.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.config.schema import VisualCoverageResult
from clipper_agency.core.media_detectors import MediaDetectionError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _completed_output(video_path: str = "/tmp/job_1/video.mp4",
                      output_duration_sec: float = 30.0) -> dict:
    """Minimal completed output dict as produced by Composer."""
    return {
        "status": "completed",
        "video_path": video_path,
        "thumbnail_path": "/tmp/job_1/thumb.png",
        "scene_count": 3,
        "output_duration_sec": output_duration_sec,
    }


# ---------------------------------------------------------------------------
# Test: successful detection passes real results to evaluate_visual_coverage
# ---------------------------------------------------------------------------

class TestSuccessfulDetection:
    """When detectors return real data, it flows into evaluate_visual_coverage."""

    @patch("clipper_agency.agents.composer.detect_freeze_segments")
    @patch("clipper_agency.agents.composer.detect_black_segments")
    @patch("clipper_agency.agents.composer.evaluate_visual_coverage")
    def test_black_and_freeze_results_passed(
        self, mock_eval, mock_black, mock_freeze,
    ):
        black_data = [(1.0, 1.5), (5.0, 5.3)]
        freeze_data = [(10.0, 12.0)]
        mock_black.return_value = black_data
        mock_freeze.return_value = freeze_data
        mock_eval.return_value = VisualCoverageResult(
            status="pass",
            output_duration_sec=30.0,
            voiceover_duration_sec=30.0,
            coverage_ratio=1.0,
            issues=[],
        )

        agent = ComposerAgent()
        output = _completed_output()
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)

        # evaluate_visual_coverage was called with real black/freeze data
        eval_call = mock_eval.call_args
        assert eval_call.kwargs["black_segments"] == black_data
        assert eval_call.kwargs["freeze_segments"] == freeze_data

    @patch("clipper_agency.agents.composer.detect_freeze_segments")
    @patch("clipper_agency.agents.composer.detect_black_segments")
    @patch("clipper_agency.agents.composer.evaluate_visual_coverage")
    def test_scene_segments_derived_from_output(
        self, mock_eval, mock_black, mock_freeze,
    ):
        mock_black.return_value = []
        mock_freeze.return_value = []
        mock_eval.return_value = VisualCoverageResult(
            status="pass",
            output_duration_sec=30.0,
            voiceover_duration_sec=30.0,
            coverage_ratio=1.0,
            issues=[],
        )

        agent = ComposerAgent()
        output = _completed_output(output_duration_sec=30.0)
        # scene_count=3, duration=30 → 3 equal segments of 10s each
        output["scene_count"] = 3
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)

        eval_call = mock_eval.call_args
        scene_segs = eval_call.kwargs["scene_segments"]
        assert len(scene_segs) == 3
        assert scene_segs[0] == pytest.approx((0.0, 10.0))
        assert scene_segs[1] == pytest.approx((10.0, 20.0))
        assert scene_segs[2] == pytest.approx((20.0, 30.0))

    def test_empty_segments_passed_via_injectable_detector(self):
        """Empty segments flow from injectable empty detector to evaluate_visual_coverage."""
        empty_data = [(7.0, 9.5), (15.0, 17.0)]
        custom_empty = MagicMock(return_value=empty_data)

        with patch(
            "clipper_agency.agents.composer.detect_freeze_segments",
            return_value=[],
        ), patch(
            "clipper_agency.agents.composer.detect_black_segments",
            return_value=[],
        ), patch(
            "clipper_agency.agents.composer.evaluate_visual_coverage",
            return_value=VisualCoverageResult(
                status="pass",
                output_duration_sec=30.0,
                voiceover_duration_sec=30.0,
                coverage_ratio=1.0,
                issues=[],
            ),
        ) as mock_eval:
            agent = ComposerAgent()
            output = _completed_output()
            agent._attach_visual_coverage_diagnostics(
                output, 30.0,
                detect_empty=custom_empty,
            )

            custom_empty.assert_called_once()
            eval_call = mock_eval.call_args
            assert eval_call.kwargs["empty_segments"] == empty_data

    @patch("clipper_agency.agents.composer.detect_freeze_segments")
    @patch("clipper_agency.agents.composer.detect_black_segments")
    @patch("clipper_agency.agents.composer.evaluate_visual_coverage")
    def test_empty_segments_defaults_to_empty_when_no_detector(
        self, mock_eval, mock_black, mock_freeze,
    ):
        """Empty segments default to [] when no empty detector is configured."""
        mock_black.return_value = []
        mock_freeze.return_value = []
        mock_eval.return_value = VisualCoverageResult(
            status="pass",
            output_duration_sec=30.0,
            voiceover_duration_sec=30.0,
            coverage_ratio=1.0,
            issues=[],
        )

        agent = ComposerAgent()
        output = _completed_output()
        agent._attach_visual_coverage_diagnostics(output, 30.0)

        eval_call = mock_eval.call_args
        assert eval_call.kwargs["empty_segments"] == []


# ---------------------------------------------------------------------------
# Test: graceful fallback when detectors raise MediaDetectionError
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """Pipeline does not crash when FFmpeg detector calls fail."""

    @patch("clipper_agency.agents.composer.detect_freeze_segments")
    @patch("clipper_agency.agents.composer.detect_black_segments")
    @patch("clipper_agency.agents.composer.evaluate_visual_coverage")
    def test_black_detect_error_falls_back_to_empty(
        self, mock_eval, mock_black, mock_freeze,
    ):
        mock_black.side_effect = MediaDetectionError("FFmpeg blackdetect failed")
        mock_freeze.return_value = [(10.0, 12.0)]
        mock_eval.return_value = VisualCoverageResult(
            status="pass",
            output_duration_sec=30.0,
            voiceover_duration_sec=30.0,
            coverage_ratio=1.0,
            issues=[],
        )

        agent = ComposerAgent()
        output = _completed_output()
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)

        # Should NOT raise — falls back to empty black_segments
        assert result["status"] == "completed"
        eval_call = mock_eval.call_args
        assert eval_call.kwargs["black_segments"] == []
        # freeze still worked
        assert eval_call.kwargs["freeze_segments"] == [(10.0, 12.0)]

    @patch("clipper_agency.agents.composer.detect_freeze_segments")
    @patch("clipper_agency.agents.composer.detect_black_segments")
    @patch("clipper_agency.agents.composer.evaluate_visual_coverage")
    def test_freeze_detect_error_falls_back_to_empty(
        self, mock_eval, mock_black, mock_freeze,
    ):
        mock_black.return_value = [(1.0, 1.5)]
        mock_freeze.side_effect = MediaDetectionError("FFmpeg freezedetect failed")
        mock_eval.return_value = VisualCoverageResult(
            status="pass",
            output_duration_sec=30.0,
            voiceover_duration_sec=30.0,
            coverage_ratio=1.0,
            issues=[],
        )

        agent = ComposerAgent()
        output = _completed_output()
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)

        assert result["status"] == "completed"
        eval_call = mock_eval.call_args
        assert eval_call.kwargs["freeze_segments"] == []
        # black still worked
        assert eval_call.kwargs["black_segments"] == [(1.0, 1.5)]

    @patch("clipper_agency.agents.composer.detect_freeze_segments")
    @patch("clipper_agency.agents.composer.detect_black_segments")
    @patch("clipper_agency.agents.composer.evaluate_visual_coverage")
    def test_both_detectors_error_still_completes(
        self, mock_eval, mock_black, mock_freeze,
    ):
        mock_black.side_effect = MediaDetectionError("black fail")
        mock_freeze.side_effect = MediaDetectionError("freeze fail")
        mock_eval.return_value = VisualCoverageResult(
            status="pass",
            output_duration_sec=30.0,
            voiceover_duration_sec=30.0,
            coverage_ratio=1.0,
            issues=[],
        )

        agent = ComposerAgent()
        output = _completed_output()
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)

        # Should not raise — all segments empty
        assert result["status"] == "completed"
        eval_call = mock_eval.call_args
        assert eval_call.kwargs["black_segments"] == []
        assert eval_call.kwargs["freeze_segments"] == []


# ---------------------------------------------------------------------------
# Test: persistence of visual_coverage.json
# ---------------------------------------------------------------------------

class TestPersistence:
    """Visual coverage results are persisted to disk."""

    @patch("clipper_agency.agents.composer.detect_freeze_segments")
    @patch("clipper_agency.agents.composer.detect_black_segments")
    @patch("clipper_agency.agents.composer.evaluate_visual_coverage")
    def test_visual_coverage_json_persisted(
        self, mock_eval, mock_black, mock_freeze, tmp_path,
    ):
        mock_black.return_value = []
        mock_freeze.return_value = []
        mock_eval.return_value = VisualCoverageResult(
            status="pass",
            output_duration_sec=30.0,
            voiceover_duration_sec=30.0,
            coverage_ratio=1.0,
            issues=[],
        )

        agent = ComposerAgent()
        video_dir = tmp_path / "job_1"
        video_dir.mkdir()
        output = _completed_output(video_path=str(video_dir / "video.mp4"))
        # Add agent_dir to output so persistence triggers
        output["agent_dir"] = str(tmp_path / "job_1" / "agents" / "composer")

        result = agent._attach_visual_coverage_diagnostics(output, 30.0)

        # visual_coverage.json should be persisted alongside video
        coverage_file = video_dir / "visual_coverage.json"
        assert coverage_file.exists(), (
            f"visual_coverage.json not found at {coverage_file}"
        )
        data = json.loads(coverage_file.read_text())
        assert data["status"] == "pass"
        assert data["coverage_ratio"] == 1.0

    @patch("clipper_agency.agents.composer.detect_freeze_segments")
    @patch("clipper_agency.agents.composer.detect_black_segments")
    @patch("clipper_agency.agents.composer.evaluate_visual_coverage")
    def test_no_persistence_when_video_path_missing(
        self, mock_eval, mock_black, mock_freeze, tmp_path,
    ):
        mock_black.return_value = []
        mock_freeze.return_value = []
        mock_eval.return_value = VisualCoverageResult(
            status="pass",
            output_duration_sec=30.0,
            voiceover_duration_sec=30.0,
            coverage_ratio=1.0,
            issues=[],
        )

        agent = ComposerAgent()
        output = _completed_output(video_path="")
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)

        # No crash, no file created
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Test: early-return guards still work
# ---------------------------------------------------------------------------

class TestEarlyReturnGuards:
    """Method returns early when output is not completed or duration invalid."""

    def test_skips_when_status_failed(self):
        agent = ComposerAgent()
        output = {"status": "failed", "output_duration_sec": 30.0}
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)
        assert "diagnostics" not in result.get("visual_coverage", {})
        # No diagnostics key added at all
        assert result == output

    def test_skips_when_duration_zero(self):
        agent = ComposerAgent()
        output = {"status": "completed", "output_duration_sec": 0.0}
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)
        assert "diagnostics" not in result

    def test_skips_when_duration_negative(self):
        agent = ComposerAgent()
        output = {"status": "completed", "output_duration_sec": -5.0}
        result = agent._attach_visual_coverage_diagnostics(output, 30.0)
        assert "diagnostics" not in result


# ---------------------------------------------------------------------------
# Test: dependency injection for custom detector functions
# ---------------------------------------------------------------------------

class TestDependencyInjection:
    """Detector functions can be overridden for testability."""

    def test_custom_black_detector(self):
        custom_black = MagicMock(return_value=[(2.0, 2.5)])
        custom_freeze = MagicMock(return_value=[])

        with patch("clipper_agency.agents.composer.evaluate_visual_coverage") as mock_eval:
            mock_eval.return_value = VisualCoverageResult(
                status="pass",
                output_duration_sec=30.0,
                voiceover_duration_sec=30.0,
                coverage_ratio=1.0,
                issues=[],
            )
            agent = ComposerAgent()
            output = _completed_output()
            result = agent._attach_visual_coverage_diagnostics(
                output, 30.0,
                detect_black=custom_black,
                detect_freeze=custom_freeze,
            )

        custom_black.assert_called_once()
        eval_call = mock_eval.call_args
        assert eval_call.kwargs["black_segments"] == [(2.0, 2.5)]

    def test_custom_freeze_detector(self):
        custom_black = MagicMock(return_value=[])
        custom_freeze = MagicMock(return_value=[(8.0, 10.0)])

        with patch("clipper_agency.agents.composer.evaluate_visual_coverage") as mock_eval:
            mock_eval.return_value = VisualCoverageResult(
                status="pass",
                output_duration_sec=30.0,
                voiceover_duration_sec=30.0,
                coverage_ratio=1.0,
                issues=[],
            )
            agent = ComposerAgent()
            output = _completed_output()
            result = agent._attach_visual_coverage_diagnostics(
                output, 30.0,
                detect_black=custom_black,
                detect_freeze=custom_freeze,
            )

        custom_freeze.assert_called_once()
        eval_call = mock_eval.call_args
        assert eval_call.kwargs["freeze_segments"] == [(8.0, 10.0)]
