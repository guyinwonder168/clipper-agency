"""Tests for FFmpeg-backed black and freeze segment detectors."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from clipper_agency.core.media_detectors import (
    MediaDetectionError,
    detect_black_segments,
    detect_freeze_segments,
)


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


requires_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_available(),
    reason="FFmpeg not available on PATH",
)


BLACKDETECT_STDERR = """
[blackdetect @ 0x123] black_start:0 black_end:1.4 black_duration:1.4
[blackdetect @ 0x123] black_start:3.25 black_end:5 black_duration:1.75
"""

BLACKDETECT_MISSING_END_STDERR = """
[blackdetect @ 0x123] black_start:0 black_end:1.4 black_duration:1.4
[blackdetect @ 0x123] black_start:8.5
"""

FREEZEDETECT_STDERR = """
[freezedetect @ 0x456] lavfi.freezedetect.freeze_start: 2
[freezedetect @ 0x456] lavfi.freezedetect.freeze_duration: 1.25
[freezedetect @ 0x456] lavfi.freezedetect.freeze_end: 3.25
[freezedetect @ 0x456] lavfi.freezedetect.freeze_start: 8.5
[freezedetect @ 0x456] lavfi.freezedetect.freeze_duration: 2
[freezedetect @ 0x456] lavfi.freezedetect.freeze_end: 10.5
"""

FREEZEDETECT_MISSING_END_STDERR = """
[freezedetect @ 0x456] lavfi.freezedetect.freeze_start: 2
[freezedetect @ 0x456] lavfi.freezedetect.freeze_end: 3.25
[freezedetect @ 0x456] lavfi.freezedetect.freeze_start: 8.5
"""


class TestDetectBlackSegments:
    def test_parses_multiple_black_segments_from_ffmpeg_stderr(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value=BLACKDETECT_STDERR,
        ):
            segments = detect_black_segments(
                "input.mp4",
                min_duration_sec=0.5,
                pixel_threshold=0.1,
            )

        assert segments == [(0.0, 1.4), (3.25, 5.0)]

    def test_ignores_black_start_without_end_marker(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value=BLACKDETECT_MISSING_END_STDERR,
        ):
            segments = detect_black_segments(
                "input.mp4",
                min_duration_sec=0.5,
                pixel_threshold=0.1,
            )

        assert segments == [(0.0, 1.4)]

    def test_runs_blackdetect_filter_with_expected_thresholds(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value="",
        ) as run_ffmpeg:
            detect_black_segments(
                "input.mp4",
                min_duration_sec=0.75,
                pixel_threshold=0.08,
            )

        cmd = run_ffmpeg.call_args.args[0]
        assert cmd[:5] == ["ffmpeg", "-hide_banner", "-nostats", "-i", "input.mp4"]
        assert "blackdetect=d=0.75:pix_th=0.08" in cmd
        assert cmd[-3:] == ["-f", "null", "-"]

    def test_raises_typed_error_when_blackdetect_subprocess_fails(self):
        failure = subprocess.CalledProcessError(
            1,
            ["ffmpeg"],
            stderr="invalid video",
        )
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            side_effect=failure,
        ):
            with pytest.raises(MediaDetectionError) as exc_info:
                detect_black_segments(
                    "input.mp4",
                    min_duration_sec=0.5,
                    pixel_threshold=0.1,
                )

        assert "blackdetect" in str(exc_info.value)
        assert "invalid video" in str(exc_info.value)


class TestDetectFreezeSegments:
    def test_parses_multiple_freeze_segments_from_ffmpeg_stderr(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value=FREEZEDETECT_STDERR,
        ):
            segments = detect_freeze_segments(
                "input.mp4",
                min_duration_sec=0.5,
                noise_threshold=0.001,
            )

        assert segments == [(2.0, 3.25), (8.5, 10.5)]

    def test_ignores_freeze_start_without_end_marker(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value=FREEZEDETECT_MISSING_END_STDERR,
        ):
            segments = detect_freeze_segments(
                "input.mp4",
                min_duration_sec=0.5,
                noise_threshold=0.001,
            )

        assert segments == [(2.0, 3.25)]

    def test_runs_freezedetect_filter_with_expected_thresholds(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value="",
        ) as run_ffmpeg:
            detect_freeze_segments(
                "input.mp4",
                min_duration_sec=1.25,
                noise_threshold=0.001,
            )

        cmd = run_ffmpeg.call_args.args[0]
        assert cmd[:5] == ["ffmpeg", "-hide_banner", "-nostats", "-i", "input.mp4"]
        assert "freezedetect=n=0.001:d=1.25" in cmd
        assert cmd[-3:] == ["-f", "null", "-"]

    def test_raises_typed_error_when_freezedetect_subprocess_fails(self):
        failure = subprocess.CalledProcessError(
            1,
            ["ffmpeg"],
            stderr="invalid video",
        )
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            side_effect=failure,
        ):
            with pytest.raises(MediaDetectionError) as exc_info:
                detect_freeze_segments(
                    "input.mp4",
                    min_duration_sec=0.5,
                    noise_threshold=0.001,
                )

        assert "freezedetect" in str(exc_info.value)
        assert "invalid video" in str(exc_info.value)

    @pytest.mark.integration
    @requires_ffmpeg
    def test_real_ffmpeg_accepts_default_freezedetect_noise_threshold(
        self,
        tmp_path: Path,
    ):
        """RC-8 regression: the default noise threshold Composer ships must be
        a value ffmpeg's freezedetect filter actually accepts.

        freezedetect's ``n`` parameter is a noise-tolerance ratio in [0, 1],
        NOT a dB value. A negative dB threshold (e.g. the historical
        ``-30.0``) is rejected by ffmpeg with
        ``Value ... for parameter 'n' out of range [0 - 1]`` (rc=1) on every
        run, so freeze detection silently never worked. This test builds the
        exact filter string ``detect_freeze_segments`` produces for the
        production default and runs it against real ffmpeg on a tiny frozen
        video, asserting rc==0 and no "out of range" error.
        """
        from clipper_agency.agents.composer import (
            _FREEZE_MIN_DURATION_SEC,
            _FREEZE_NOISE_THRESHOLD,
        )

        # Sanity: the constant must lie in ffmpeg's legal range.
        assert 0.0 <= _FREEZE_NOISE_THRESHOLD <= 1.0

        frozen_video = tmp_path / "frozen.mp4"
        gen_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=1:r=25",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(frozen_video),
        ]
        subprocess.run(gen_cmd, check=True, capture_output=True, timeout=30)

        filter_expr = f"freezedetect=n={_FREEZE_NOISE_THRESHOLD}:d={_FREEZE_MIN_DURATION_SEC}"
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(frozen_video),
                "-vf",
                filter_expr,
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"freezedetect rejected filter {filter_expr!r}: "
            f"rc={result.returncode}, stderr tail=\n{result.stderr[-500:]}"
        )
        assert "out of range" not in result.stderr, (
            f"freezedetect 'n' out of range for {filter_expr!r}: {result.stderr[-300:]}"
        )
