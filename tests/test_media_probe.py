"""Tests for media probing utilities."""
import json

from clipper_agency.core.media_probe import probe_video


class TestProbeVideo:
    def test_probe_returns_resolution_codec_duration(self, tmp_path, mocker):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x" * 2048)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [{"codec_type": "video", "width": 720, "height": 1280,
                         "codec_name": "h264", "pix_fmt": "yuv420p"}],
            "format": {"duration": "5.0"},
        }).encode())

        info = probe_video(str(video), tmp_path)
        assert info is not None
        assert info.width == 720
        assert info.height == 1280
        assert info.codec == "h264"
        assert info.duration == 5.0

    def test_probe_returns_none_for_missing_file(self, tmp_path):
        info = probe_video(str(tmp_path / "missing.mp4"), tmp_path)
        assert info is None

    def test_probe_returns_none_for_ffprobe_failure(self, tmp_path, mocker):
        video = tmp_path / "broken.mp4"
        video.write_bytes(b"x")
        mocker.patch("subprocess.check_output", side_effect=OSError("ffprobe not found"))
        info = probe_video(str(video), tmp_path)
        assert info is None

    def test_probe_detects_audio_stream(self, tmp_path, mocker):
        video = tmp_path / "av.mp4"
        video.write_bytes(b"x" * 2048)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920,
                 "codec_name": "h264", "pix_fmt": "yuv420p"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "30.0"},
        }).encode())

        info = probe_video(str(video), tmp_path)
        assert info is not None
        assert info.has_audio is True

    def test_probe_no_audio_stream(self, tmp_path, mocker):
        video = tmp_path / "novoice.mp4"
        video.write_bytes(b"x" * 2048)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920,
                 "codec_name": "h264", "pix_fmt": "yuv420p"},
            ],
            "format": {"duration": "30.0"},
        }).encode())

        info = probe_video(str(video), tmp_path)
        assert info is not None
        assert info.has_audio is False

    def test_probe_handles_missing_format_section(self, tmp_path, mocker):
        video = tmp_path / "noformat.mp4"
        video.write_bytes(b"x" * 2048)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [
                {"codec_type": "video", "width": 640, "height": 480,
                 "codec_name": "h264", "pix_fmt": "yuv420p"},
            ],
        }).encode())

        info = probe_video(str(video), tmp_path)
        assert info is not None
        assert info.duration is None

    def test_probe_accepts_file_inside_allowed_base(self, tmp_path, mocker):
        video = tmp_path / "inside.mp4"
        video.write_bytes(b"x" * 2048)
        check_output = mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920,
                 "codec_name": "h264", "pix_fmt": "yuv420p"},
            ],
            "format": {"duration": "30.0"},
        }).encode())

        info = probe_video(str(video), allowed_base_dir=tmp_path)

        assert info is not None
        assert info.path == str(video.resolve())
        assert str(video.resolve()) in check_output.call_args.args[0]

    def test_probe_rejects_file_outside_allowed_base(self, tmp_path, mocker):
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"x" * 2048)
        check_output = mocker.patch("subprocess.check_output")

        info = probe_video(str(outside), allowed_base_dir=base)

        assert info is None
        check_output.assert_not_called()

    def test_probe_parses_sample_aspect_ratio(self, tmp_path, mocker):
        video = tmp_path / "sar.mp4"
        video.write_bytes(b"x" * 2048)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920,
                 "codec_name": "h264", "pix_fmt": "yuv420p",
                 "sample_aspect_ratio": "7664:7665"},
            ],
            "format": {"duration": "10.0"},
        }).encode())

        info = probe_video(str(video), tmp_path)
        assert info is not None
        assert info.sample_aspect_ratio == "7664:7665"

    def test_probe_defaults_sar_to_1_when_missing(self, tmp_path, mocker):
        video = tmp_path / "nosar.mp4"
        video.write_bytes(b"x" * 2048)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920,
                 "codec_name": "h264", "pix_fmt": "yuv420p"},
            ],
            "format": {"duration": "10.0"},
        }).encode())

        info = probe_video(str(video), tmp_path)
        assert info is not None
        assert info.sample_aspect_ratio == "1:1"

    def test_probe_defaults_sar_to_1_when_0_1(self, tmp_path, mocker):
        video = tmp_path / "invalidsar.mp4"
        video.write_bytes(b"x" * 2048)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920,
                 "codec_name": "h264", "pix_fmt": "yuv420p",
                 "sample_aspect_ratio": "0:1"},
            ],
            "format": {"duration": "10.0"},
        }).encode())

        info = probe_video(str(video), tmp_path)
        assert info is not None
        assert info.sample_aspect_ratio == "1:1"

    def test_probe_video_extracts_fps(self, tmp_path, mocker):
        """ffprobe returns r_frame_rate as part of video stream metadata."""
        video = tmp_path / "video.mp4"
        video.write_bytes(b"x" * 100)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [{
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "r_frame_rate": "30/1",
            }],
            "format": {"duration": "10.5"},
        }).encode())

        info = probe_video(str(video), str(tmp_path))
        assert info is not None
        assert info.fps == 30.0

    def test_probe_video_extracts_fractional_fps(self, tmp_path, mocker):
        """r_frame_rate like 30000/1001 (29.97fps) preserved as float."""
        video = tmp_path / "ntsc.mp4"
        video.write_bytes(b"x" * 100)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [{
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "r_frame_rate": "30000/1001",
            }],
            "format": {"duration": "10.5"},
        }).encode())

        info = probe_video(str(video), str(tmp_path))
        assert info is not None
        assert info.fps == 29.97

    def test_probe_video_preserves_near_30_fps(self, tmp_path, mocker):
        """1000/33 ≈ 30.3fps must NOT be floored to 30."""
        video = tmp_path / "near30.mp4"
        video.write_bytes(b"x" * 100)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [{
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "r_frame_rate": "1000/33",
            }],
            "format": {"duration": "10.5"},
        }).encode())

        info = probe_video(str(video), str(tmp_path))
        assert info is not None
        assert info.fps == 30.3

    def test_probe_video_defaults_fps_when_missing(self, tmp_path, mocker):
        """Missing r_frame_rate defaults to 30.0."""
        video = tmp_path / "nofps.mp4"
        video.write_bytes(b"x" * 100)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [{
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
            }],
            "format": {"duration": "10.5"},
        }).encode())

        info = probe_video(str(video), str(tmp_path))
        assert info is not None
        assert info.fps == 30.0

    def test_probe_returns_none_when_no_video_stream(self, tmp_path, mocker):
        """File with only audio streams (no video) returns None."""
        video = tmp_path / "audio_only.mp3"
        video.write_bytes(b"x" * 100)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
            "format": {"duration": "3.5"},
        }).encode())

        info = probe_video(str(video), str(tmp_path))
        assert info is None

    def test_probe_defaults_fps_on_malformed_frame_rate(self, tmp_path, mocker):
        """Malformed r_frame_rate (e.g. 'N/A') falls back to 30.0."""
        video = tmp_path / "bad_fps.mp4"
        video.write_bytes(b"x" * 100)

        mocker.patch("subprocess.check_output", return_value=json.dumps({
            "streams": [{
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "r_frame_rate": "N/A",
            }],
            "format": {"duration": "10.0"},
        }).encode())

        info = probe_video(str(video), str(tmp_path))
        assert info is not None
        assert info.fps == 30.0
