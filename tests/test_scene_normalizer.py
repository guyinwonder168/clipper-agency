"""Tests for scene normalization to 1080x1920."""
import subprocess

import pytest
from clipper_agency.core.scene_normalizer import SceneNormalizer, NormalizeResult


class TestSceneNormalizer:
    def test_normalize_scales_to_1080x1920(self, tmp_path, mocker):
        """Non-9:16 input gets scaled/padded to 1080x1920."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer._run_ffmpeg_streaming",
            return_value="",
        )
        mocker.patch("subprocess.check_output", return_value=b"")

        input_file = tmp_path / "input.mp4"
        input_file.write_bytes(b"x" * 10000)
        input_path = str(input_file)
        output_path = str(tmp_path / "output.mp4")

        normalizer = SceneNormalizer()
        result = normalizer.normalize(input_path, output_path)

        assert result.success is True
        mock_ffmpeg.assert_called_once()
        cmd_args = " ".join(mock_ffmpeg.call_args[0][0])
        assert "scale=1080:1920" in cmd_args
        assert "pad=1080:1920" in cmd_args
        assert "libx264" in cmd_args
        assert "yuv420p" in cmd_args

    def test_normalize_already_1080x1920_skips(self, tmp_path, mocker):
        """Already correct resolution — no ffmpeg call needed."""
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                     return_value=mocker.Mock(width=1080, height=1920,
                                              sample_aspect_ratio="1:1"))

        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer._run_ffmpeg_streaming",
        )
        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is True
        mock_ffmpeg.assert_not_called()

    def test_normalize_strips_audio_from_source(self, tmp_path, mocker):
        """Source audio is stripped (-an flag)."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer._run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        cmd_args = " ".join(mock_ffmpeg.call_args[0][0])
        assert "-an" in cmd_args

    def test_normalize_handles_missing_input(self, tmp_path, mocker):
        """Missing input returns failure."""
        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(tmp_path / "nonexistent.mp4"), str(tmp_path / "out.mp4"))
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_normalize_handles_ffmpeg_error(self, tmp_path, mocker):
        """FFmpeg non-zero exit returns failure."""
        mocker.patch(
            "clipper_agency.core.scene_normalizer._run_ffmpeg_streaming",
            side_effect=subprocess.CalledProcessError(1, ["ffmpeg"], stderr="ffmpeg error"),
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))
        assert result.success is False
        assert result.stderr is not None

    def test_normalize_sets_sar_to_1(self, tmp_path, mocker):
        """Filter chain ends with setsar=1 for consistent concat compatibility."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer._run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        cmd_args = " ".join(mock_ffmpeg.call_args[0][0])
        assert "setsar=1" in cmd_args

    def test_normalize_uses_force_original_aspect_ratio(self, tmp_path, mocker):
        """Scale filter includes force_original_aspect_ratio=decrease."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer._run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        cmd_args = " ".join(mock_ffmpeg.call_args[0][0])
        assert "force_original_aspect_ratio" in cmd_args

    def test_normalize_does_not_skip_when_sar_not_1(self, tmp_path, mocker):
        """Clip already 1080x1920 but with non-1:1 SAR must still be normalized."""
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                      return_value=mocker.Mock(
                          width=1080, height=1920,
                          sample_aspect_ratio="7664:7665"))

        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer._run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is True
        mock_ffmpeg.assert_called()
