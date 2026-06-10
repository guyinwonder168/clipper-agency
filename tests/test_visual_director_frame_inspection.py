"""Tests for Visual Director — frame inspection pipeline wiring (Phase 23 Batch 1).

Worker A — Task 1.1: Enhanced frame inspection pipeline is wired into
_run_multimodal_inspection when enabled for video candidates.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.config.schema import (
    ExtractedFrame,
    FrameExtractionManifest,
    StoryBeat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(candidate_type="tiktok_clip", url="https://example.com/video.mp4"):
    """Create a minimal AssetCandidate-like mock."""
    c = MagicMock()
    c.type = candidate_type
    c.url = url
    c.source = "test"
    c.reason = "test"
    return c


def _make_beat(beat_id: int = 1):
    """Create a minimal StoryBeat for testing."""
    return StoryBeat(
        beat_id=beat_id,
        role="main_claim",
        narration_goal="Test narration",
        spoken_point="Test point",
        safe_wording="Test point",
        visual_must_show="anything",
        visual_must_not_show="",
        overlay_text="Test",
        caption_keywords=["test"],
        asset_candidates=[],
        fallback={"type": "text_card", "headline": "Test", "image_search": "test"},
    )


def _make_manifest(frame_paths):
    """Create a FrameExtractionManifest with given frame paths."""
    return FrameExtractionManifest(
        asset_id="test",
        beat_id="1",
        source_path="/fake/video.mp4",
        frames=[
            ExtractedFrame(
                path=p,
                timestamp_sec=0.5 * i,
                perceptual_hash="0" * 16,
                width=1920,
                height=1080,
            )
            for i, p in enumerate(frame_paths)
        ],
    )


def _make_agent(runtime_inspection_enabled=True):
    """Create a VisualDirectorAgent with inspection flag set."""
    agent = VisualDirectorAgent()
    agent._runtime_inspection_enabled = runtime_inspection_enabled
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTryEnhancedFrameInspection:
    """Unit tests for _try_enhanced_frame_inspection helper."""

    def test_returns_none_when_disabled(self, tmp_path):
        """Must return None when runtime_inspection_enabled is False."""
        agent = _make_agent(runtime_inspection_enabled=False)
        candidate = _make_candidate()
        beat = _make_beat()

        result = agent._try_enhanced_frame_inspection(
            candidate, beat, job_id=1, agent_dir=str(tmp_path),
        )
        assert result is None

    def test_returns_none_for_non_video_candidates(self, tmp_path):
        """Must return None for photo/screenshot candidates."""
        agent = _make_agent(runtime_inspection_enabled=True)

        for ctype in ("photo", "screenshot", "text_card", "text_overlay"):
            candidate = _make_candidate(candidate_type=ctype)
            beat = _make_beat()
            result = agent._try_enhanced_frame_inspection(
                candidate, beat, job_id=1, agent_dir=str(tmp_path),
            )
            assert result is None, f"Should be None for type={ctype}"

    @patch("clipper_agency.agents.visual_director.run_frame_inspection_pipeline")
    def test_calls_pipeline_for_video_with_local_file(self, mock_pipeline, tmp_path):
        """Must call run_frame_inspection_pipeline when a local video exists."""
        agent = _make_agent(runtime_inspection_enabled=True)
        candidate = _make_candidate()
        beat = _make_beat()

        # Create a fake local video file in candidate_frames dir
        frames_dir = tmp_path / "candidate_frames"
        frames_dir.mkdir()
        video_file = frames_dir / f"vid_{hash(candidate.url) & 0xFFFF}.mp4"
        video_file.write_text("fake video")

        manifest = _make_manifest(["frame_a.jpg", "frame_b.jpg"])
        mock_pipeline.return_value = manifest

        result = agent._try_enhanced_frame_inspection(
            candidate, beat, job_id=1, agent_dir=str(tmp_path),
        )

        assert result == ["frame_a.jpg", "frame_b.jpg"]
        mock_pipeline.assert_called_once()

    def test_returns_none_when_no_local_video(self, tmp_path):
        """Must return None gracefully when no video file found locally."""
        agent = _make_agent(runtime_inspection_enabled=True)
        candidate = _make_candidate()
        beat = _make_beat()

        # No video file created — frames dir may or may not exist
        result = agent._try_enhanced_frame_inspection(
            candidate, beat, job_id=1, agent_dir=str(tmp_path),
        )
        assert result is None

    @patch("clipper_agency.agents.visual_director.run_frame_inspection_pipeline")
    def test_returns_none_on_pipeline_exception(self, mock_pipeline, tmp_path):
        """Must return None (not crash) when pipeline raises."""
        agent = _make_agent(runtime_inspection_enabled=True)
        candidate = _make_candidate()
        beat = _make_beat()

        frames_dir = tmp_path / "candidate_frames"
        frames_dir.mkdir()
        video_file = frames_dir / f"vid_{hash(candidate.url) & 0xFFFF}.mp4"
        video_file.write_text("fake video")

        mock_pipeline.side_effect = RuntimeError("probe failed")

        result = agent._try_enhanced_frame_inspection(
            candidate, beat, job_id=1, agent_dir=str(tmp_path),
        )
        assert result is None

    @patch("clipper_agency.agents.visual_director.run_frame_inspection_pipeline")
    def test_returns_none_when_manifest_has_no_frames(self, mock_pipeline, tmp_path):
        """Must return None when pipeline returns manifest with zero frames."""
        agent = _make_agent(runtime_inspection_enabled=True)
        candidate = _make_candidate()
        beat = _make_beat()

        frames_dir = tmp_path / "candidate_frames"
        frames_dir.mkdir()
        video_file = frames_dir / f"vid_{hash(candidate.url) & 0xFFFF}.mp4"
        video_file.write_text("fake video")

        manifest = _make_manifest([])
        mock_pipeline.return_value = manifest

        result = agent._try_enhanced_frame_inspection(
            candidate, beat, job_id=1, agent_dir=str(tmp_path),
        )
        assert result is None


class TestRunMultimodalInspectionWiring:
    """Integration-level tests for _run_multimodal_inspection with pipeline."""

    @patch("clipper_agency.llm.client.OpenRouterClient")
    @patch("clipper_agency.llm.multimodal_client.MultimodalInspectionClient")
    @patch("clipper_agency.agents.visual_director.run_frame_inspection_pipeline")
    def test_enhanced_paths_used_for_video_candidates(
        self, mock_pipeline, mock_inspector_cls, mock_client_cls, tmp_path,
    ):
        """Enhanced pipeline frame paths must replace basic frame_paths."""
        agent = _make_agent(runtime_inspection_enabled=True)
        candidate = _make_candidate()
        beat = _make_beat()

        # Create local video
        frames_dir = tmp_path / "candidate_frames"
        frames_dir.mkdir()
        video_file = frames_dir / f"vid_{hash(candidate.url) & 0xFFFF}.mp4"
        video_file.write_text("fake video")

        manifest = _make_manifest(["enhanced_1.jpg", "enhanced_2.jpg"])
        mock_pipeline.return_value = manifest

        mock_inspector = MagicMock()
        mock_inspector.inspect_asset.return_value = {"decision": "accept"}
        mock_inspector_cls.return_value = mock_inspector

        with patch.object(
            agent, "_extract_candidate_frames", return_value=["basic.jpg"],
        ):
            result = agent._run_multimodal_inspection(
                candidate, beat, job_id=1,
                cache_dir=str(tmp_path), cache_key="test_key",
                agent_dir=str(tmp_path),
            )

        assert result is not None
        # Verify inspect_asset was called with enhanced paths (not basic)
        call_args = mock_inspector.inspect_asset.call_args
        assert call_args.kwargs["frame_paths"] == ["enhanced_1.jpg", "enhanced_2.jpg"]

    @patch("clipper_agency.llm.client.OpenRouterClient")
    @patch("clipper_agency.llm.multimodal_client.MultimodalInspectionClient")
    @patch("clipper_agency.agents.visual_director.run_frame_inspection_pipeline")
    def test_basic_paths_used_when_disabled(
        self, mock_pipeline, mock_inspector_cls, mock_client_cls, tmp_path,
    ):
        """Basic frame_paths must be used when runtime_inspection disabled."""
        agent = _make_agent(runtime_inspection_enabled=False)
        candidate = _make_candidate()
        beat = _make_beat()

        mock_inspector = MagicMock()
        mock_inspector.inspect_asset.return_value = {"decision": "accept"}
        mock_inspector_cls.return_value = mock_inspector

        # Patch _extract_candidate_frames to return basic paths
        with patch.object(
            agent, "_extract_candidate_frames", return_value=["basic.jpg"],
        ):
            result = agent._run_multimodal_inspection(
                candidate, beat, job_id=1,
                cache_dir=str(tmp_path), cache_key="test_key",
                agent_dir=str(tmp_path),
            )

        assert result is not None
        mock_pipeline.assert_not_called()
        call_args = mock_inspector.inspect_asset.call_args
        assert call_args.kwargs["frame_paths"] == ["basic.jpg"]

    @patch("clipper_agency.llm.client.OpenRouterClient")
    @patch("clipper_agency.llm.multimodal_client.MultimodalInspectionClient")
    @patch("clipper_agency.agents.visual_director.run_frame_inspection_pipeline")
    def test_pipeline_failure_falls_back_gracefully(
        self, mock_pipeline, mock_inspector_cls, mock_client_cls, tmp_path,
    ):
        """Pipeline exception must not crash — fall back to basic frame_paths."""
        agent = _make_agent(runtime_inspection_enabled=True)
        candidate = _make_candidate()
        beat = _make_beat()

        frames_dir = tmp_path / "candidate_frames"
        frames_dir.mkdir()
        video_file = frames_dir / f"vid_{hash(candidate.url) & 0xFFFF}.mp4"
        video_file.write_text("fake video")

        mock_pipeline.side_effect = RuntimeError("FFmpeg crashed")

        mock_inspector = MagicMock()
        mock_inspector.inspect_asset.return_value = {"decision": "accept"}
        mock_inspector_cls.return_value = mock_inspector

        with patch.object(
            agent, "_extract_candidate_frames", return_value=["fallback.jpg"],
        ):
            result = agent._run_multimodal_inspection(
                candidate, beat, job_id=1,
                cache_dir=str(tmp_path), cache_key="test_key",
                agent_dir=str(tmp_path),
            )

        assert result is not None
        call_args = mock_inspector.inspect_asset.call_args
        assert call_args.kwargs["frame_paths"] == ["fallback.jpg"]
