"""Tests for scene normalization to 1080x1920."""
import subprocess

import pytest
from clipper_agency.core.scene_normalizer import SceneNormalizer, NormalizeResult


class TestSceneNormalizer:
    def test_normalize_scales_to_1080x1920(self, tmp_path, mocker):
        """Non-9:16 input gets scaled/padded to 1080x1920."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
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
                                               sample_aspect_ratio="1:1",
                                               fps=30))

        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
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
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
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
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
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
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
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
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
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
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is True
        mock_ffmpeg.assert_called()

    def test_normalize_sets_framerate_to_30(self, tmp_path, mocker):
        """All video output must be 30fps for TikTok concat compatibility."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        cmd_list = mock_ffmpeg.call_args[0][0]
        assert "-r" in cmd_list
        r_index = cmd_list.index("-r")
        assert cmd_list[r_index + 1] == "30"

    def test_normalize_does_not_skip_when_fps_not_30(self, tmp_path, mocker):
        """Clip already 1080x1920 SAR 1:1 but 50fps must still be normalized."""
        mocker.patch("clipper_agency.core.media_probe.probe_video",
                      return_value=mocker.Mock(
                          width=1080, height=1920,
                          sample_aspect_ratio="1:1",
                          fps=50))

        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is True
        mock_ffmpeg.assert_called_once()

    def test_normalize_image_uses_zoompan(self, tmp_path, mocker):
        """Image files (.jpg/.png) get zoompan Ken Burns animation, 5s at 30fps."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "scene_1.jpg"
        input_file.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 10000)  # JPEG-ish bytes

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is True
        mock_ffmpeg.assert_called_once()
        cmd_list = mock_ffmpeg.call_args[0][0]
        cmd_args = " ".join(cmd_list)

        assert "zoompan" in cmd_args
        assert "-t" in cmd_list
        t_index = cmd_list.index("-t")
        assert cmd_list[t_index + 1] == "5"

    def test_normalize_image_ken_burns_zoom_in(self, tmp_path, mocker):
        """Default zoompan direction is zoom-in (scale goes from 1.0 to 1.2)."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "scene_1.png"
        input_file.write_bytes(b"\x89PNG" + b"x" * 10000)  # PNG-ish bytes

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is True
        cmd_args = " ".join(mock_ffmpeg.call_args[0][0])
        # zoompan=z='min(zoom+0.001,1.2)' means slow zoom in from 1.0 to 1.2
        assert "zoom+0.001" in cmd_args

    def test_normalize_image_png_detected(self, tmp_path, mocker):
        """PNG files are also detected as images."""
        mock_ffmpeg = mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            return_value="",
        )

        input_file = tmp_path / "image.png"
        input_file.write_bytes(b"x" * 100)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is True
        mock_ffmpeg.assert_called_once()


    def test_normalize_video_ffmpeg_not_found(self, tmp_path, mocker):
        """FileNotFoundError from FFmpeg returns failure with clear message."""
        mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            side_effect=FileNotFoundError("ffmpeg not on PATH"),
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_normalize_video_ffmpeg_timeout(self, tmp_path, mocker):
        """TimeoutExpired from FFmpeg returns failure with timeout message."""
        import subprocess
        mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=120),
        )

        input_file = tmp_path / "in.mp4"
        input_file.write_bytes(b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_normalize_image_ffmpeg_not_found(self, tmp_path, mocker):
        """Image path: FileNotFoundError from FFmpeg returns failure."""
        mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            side_effect=FileNotFoundError("ffmpeg not on PATH"),
        )

        input_file = tmp_path / "scene.jpg"
        input_file.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_normalize_image_ffmpeg_timeout(self, tmp_path, mocker):
        """Image path: TimeoutExpired from FFmpeg returns failure."""
        import subprocess
        mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=300),
        )

        input_file = tmp_path / "scene.jpg"
        input_file.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_normalize_image_ffmpeg_error(self, tmp_path, mocker):
        """Image path: CalledProcessError returns failure with exit code."""
        import subprocess
        mocker.patch(
            "clipper_agency.core.scene_normalizer.run_ffmpeg_streaming",
            side_effect=subprocess.CalledProcessError(1, ["ffmpeg"], stderr="zoompan failed"),
        )

        input_file = tmp_path / "scene.jpg"
        input_file.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 10000)

        normalizer = SceneNormalizer()
        result = normalizer.normalize(str(input_file), str(tmp_path / "out.mp4"))

        assert result.success is False
        assert "exit code" in result.error.lower()
        assert result.stderr == "zoompan failed"


class TestSceneNormalizerImageDetection:
    """Tests for _is_image static method."""

    def test_jpg_detected(self):
        assert SceneNormalizer._is_image("photo.jpg") is True

    def test_jpeg_detected(self):
        assert SceneNormalizer._is_image("photo.jpeg") is True

    def test_png_detected(self):
        assert SceneNormalizer._is_image("image.png") is True

    def test_webp_detected(self):
        assert SceneNormalizer._is_image("image.webp") is True

    def test_mp4_not_detected(self):
        assert SceneNormalizer._is_image("video.mp4") is False

    def test_case_insensitive(self):
        assert SceneNormalizer._is_image("photo.JPG") is True
