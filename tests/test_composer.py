"""Tests for ComposerAgent artifact persistence and output naming."""

import json
from pathlib import Path

import pytest

from clipper_agency.agents.composer import ComposerAgent


def _mock_preflight_ok(mocker):
    """Mock FFmpegPreflight.probe() to return a passing result."""
    mock_result = mocker.MagicMock()
    mock_result.ffmpeg_found = True
    mock_result.ffprobe_found = True
    mock_result.libx264_available = True
    mock_result.aac_available = True
    mock_result.mp3_decode_available = True
    mock_result.all_ok.return_value = True
    mocker.patch(
        "clipper_agency.core.ffmpeg_preflight.FFmpegPreflight.probe",
        return_value=mock_result,
    )
    mocker.patch("dataclasses.asdict", return_value={"ffmpeg_found": True})


class TestComposerArtifacts:
    """Composer writes input/output, FFmpeg diagnostics to agent dir."""

    def test_output_video_named_video_mp4(self, tmp_path, mocker):
        """Output video should be video.mp4, not final.mp4."""
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        # Bypass scene validation/normalization (no real files on CI)
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mocker.MagicMock(success=True, error=""),
        )
        agent = ComposerAgent()
        result = agent.execute(
            job_id=30,
            assets=[{"scene": 1, "path": "/tmp/scene_1.mp4"}],
            audio_files=["/tmp/scene_0.mp3"],
            output_dir=str(tmp_path),
        )
        video_path = result["video_path"]
        assert video_path.endswith("video.mp4")
        assert "final.mp4" not in video_path

    def test_persists_input_json(self, tmp_path, mocker):
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        agent = ComposerAgent()
        agent.execute(
            job_id=31,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )

        input_file = tmp_path / "job_31" / "agents" / "composer" / "input.json"
        assert input_file.exists()
        data = json.loads(input_file.read_text())
        assert data["job_id"] == 31
        assert data["video_asset_count"] == 1
        assert data["audio_file_count"] == 1

    def test_persists_ffmpeg_command(self, tmp_path, mocker):
        _mock_preflight_ok(mocker)
        mock_ffmpeg = mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        # Bypass new scene validation/normalization chain
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )
        agent = ComposerAgent()
        agent.execute(
            job_id=32,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )

        cmd_file = tmp_path / "job_32" / "agents" / "composer" / "ffmpeg_command.txt"
        assert cmd_file.exists()
        content = cmd_file.read_text()
        assert "ffmpeg" in content
        assert "-filter_complex" in content

    def test_persists_output_json(self, tmp_path, mocker):
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )
        agent = ComposerAgent()
        agent.execute(
            job_id=33,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )

        output_file = tmp_path / "job_33" / "agents" / "composer" / "output.json"
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["status"] == "completed"
        assert "video_path" in data

    def test_ffmpeg_stderr_log_on_failure(self, tmp_path, mocker):
        """When ffmpeg fails, stderr should be persisted."""
        import subprocess

        err = subprocess.CalledProcessError(
            1, "ffmpeg",
            stderr="File not found: invalid input\n",
        )
        # Preflight must pass; actual ffmpeg compose fails
        mock_result = mocker.MagicMock()
        mock_result.ffmpeg_found = True
        mock_result.ffprobe_found = True
        mock_result.libx264_available = True
        mock_result.aac_available = True
        mock_result.mp3_decode_available = True
        mock_result.all_ok.return_value = True
        mocker.patch(
            "clipper_agency.core.ffmpeg_preflight.FFmpegPreflight.probe",
            return_value=mock_result,
        )
        mocker.patch("dataclasses.asdict", return_value={"ffmpeg_found": True})
        # Mock run_ffmpeg_streaming to raise on concat call, succeed on thumbnail
        mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming",
            side_effect=err,
        )
        mocker.patch("subprocess.check_output", return_value=b"libx264\naac\nmp3")
        # Bypass scene validation/normalization — only concat should fail
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )
        agent = ComposerAgent()
        agent.execute(
            job_id=34,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir=str(tmp_path),
            assets_cache=str(tmp_path),
        )

        log_file = tmp_path / "job_34" / "agents" / "composer" / "ffmpeg_stderr.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "File not found" in content


class TestComposerOutputNaming:
    """Video output uses video.mp4 naming convention."""

    def test_video_path_includes_job_id(self, mocker):
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
        # Bypass scene validation/normalization (no real files on CI)
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.MagicMock(
                         width=1080, height=1920, codec="h264",
                         duration=30.0, has_audio=False,
                         pix_fmt="yuv420p", file_size=10000))
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mocker.MagicMock(success=True, error=""),
        )
        agent = ComposerAgent()
        result = agent.execute(
            job_id=35,
            assets=[{"scene": 1, "path": "/tmp/a.mp4"}],
            audio_files=["/tmp/voice.mp3"],
            output_dir="/tmp/output",
        )
        assert "/job_35/" in result["video_path"]
        assert result["video_path"].endswith("video.mp4")


class TestComposerTreatmentMetadata:
    """Composer preserves treatment metadata from visual director in output."""

    def test_composer_preserves_treatment_in_assembly(self, tmp_path, mocker):
        """Assets with treatment fields should pass through to the FFmpeg pipeline."""
        _mock_preflight_ok(mocker)
        mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")

        # Mock scene validation + normalization
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                      return_value=mocker.MagicMock(
                          width=1080, height=1920, codec="h264",
                          duration=30.0, has_audio=False,
                          pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mock_norm.path = "/tmp/norm_scene1.mp4"
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )

        agent = ComposerAgent()
        assets_with_treatment = [{
            "scene": 1,
            "path": "/tmp/scene_1.mp4",
            "treatment": "broll_standard",
            "target_duration": 5,
            "transition_in": "crossfade",
            "transition_out": "hard_cut",
        }]

        # Create output dir so _assemble_video can write card_fallback.json
        output_dir = tmp_path / "job_40"
        output_dir.mkdir(parents=True)

        result = agent._assemble_video(
            assets_with_treatment,
            ["/tmp/voice.mp3"],
            str(output_dir / "video.mp4"),
        )

        # The command should have been built successfully
        assert result["cmd"]  # non-empty command
        # Card fallback should be empty (scene was valid)
        assert result["card_fallback_scenes"] == []

    def test_composer_process_scene_accepts_asset_param(self, tmp_path, mocker):
        """_process_scene should accept asset dict without breaking."""
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                      return_value=mocker.MagicMock(
                          width=1080, height=1920, codec="h264",
                          duration=30.0, has_audio=False,
                          pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mock_norm.path = str(tmp_path / "norm.mp4")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )

        agent = ComposerAgent()
        asset = {"scene": 1, "path": "/tmp/scene_1.mp4", "treatment": "ken_burns_zoom_in"}
        norm_path, was_card = agent._process_scene(
            tmp_path, mocker.MagicMock(), mocker.MagicMock(),
            1, "/tmp/scene_1.mp4", asset=asset,
        )

        assert norm_path is not None
        assert was_card is False

    def test_composer_process_scene_backward_compat_no_asset(self, tmp_path, mocker):
        """_process_scene works without asset param (backward compat)."""
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                      return_value=mocker.MagicMock(
                          width=1080, height=1920, codec="h264",
                          duration=30.0, has_audio=False,
                          pix_fmt="yuv420p", file_size=10000))
        mock_norm = mocker.MagicMock(success=True, error="")
        mock_norm.path = str(tmp_path / "norm.mp4")
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mock_norm,
        )

        agent = ComposerAgent()
        norm_path, was_card = agent._process_scene(
            tmp_path, mocker.MagicMock(), mocker.MagicMock(),
            1, "/tmp/scene_1.mp4",
        )

        assert norm_path is not None
        assert was_card is False
