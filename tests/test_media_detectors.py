"""Tests for FFmpeg-backed black and freeze segment detectors."""

import subprocess
from unittest.mock import patch

import pytest

from clipper_agency.core.media_detectors import (
    MediaDetectionError,
    detect_black_segments,
    detect_freeze_segments,
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
                "input.mp4", min_duration_sec=0.5, pixel_threshold=0.1,
            )

        assert segments == [(0.0, 1.4), (3.25, 5.0)]

    def test_ignores_black_start_without_end_marker(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value=BLACKDETECT_MISSING_END_STDERR,
        ):
            segments = detect_black_segments(
                "input.mp4", min_duration_sec=0.5, pixel_threshold=0.1,
            )

        assert segments == [(0.0, 1.4)]

    def test_runs_blackdetect_filter_with_expected_thresholds(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value="",
        ) as run_ffmpeg:
            detect_black_segments(
                "input.mp4", min_duration_sec=0.75, pixel_threshold=0.08,
            )

        cmd = run_ffmpeg.call_args.args[0]
        assert cmd[:5] == ["ffmpeg", "-hide_banner", "-nostats", "-i", "input.mp4"]
        assert "blackdetect=d=0.75:pix_th=0.08" in cmd
        assert cmd[-3:] == ["-f", "null", "-"]

    def test_raises_typed_error_when_blackdetect_subprocess_fails(self):
        failure = subprocess.CalledProcessError(
            1, ["ffmpeg"], stderr="invalid video",
        )
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            side_effect=failure,
        ):
            with pytest.raises(MediaDetectionError) as exc_info:
                detect_black_segments(
                    "input.mp4", min_duration_sec=0.5, pixel_threshold=0.1,
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
                "input.mp4", min_duration_sec=0.5, noise_threshold=-60,
            )

        assert segments == [(2.0, 3.25), (8.5, 10.5)]

    def test_ignores_freeze_start_without_end_marker(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value=FREEZEDETECT_MISSING_END_STDERR,
        ):
            segments = detect_freeze_segments(
                "input.mp4", min_duration_sec=0.5, noise_threshold=-60,
            )

        assert segments == [(2.0, 3.25)]

    def test_runs_freezedetect_filter_with_expected_thresholds(self):
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            return_value="",
        ) as run_ffmpeg:
            detect_freeze_segments(
                "input.mp4", min_duration_sec=1.25, noise_threshold=-55,
            )

        cmd = run_ffmpeg.call_args.args[0]
        assert cmd[:5] == ["ffmpeg", "-hide_banner", "-nostats", "-i", "input.mp4"]
        assert "freezedetect=n=-55:d=1.25" in cmd
        assert cmd[-3:] == ["-f", "null", "-"]

    def test_raises_typed_error_when_freezedetect_subprocess_fails(self):
        failure = subprocess.CalledProcessError(
            1, ["ffmpeg"], stderr="invalid video",
        )
        with patch(
            "clipper_agency.core.media_detectors.run_ffmpeg_streaming",
            side_effect=failure,
        ):
            with pytest.raises(MediaDetectionError) as exc_info:
                detect_freeze_segments(
                    "input.mp4", min_duration_sec=0.5, noise_threshold=-60,
                )

        assert "freezedetect" in str(exc_info.value)
        assert "invalid video" in str(exc_info.value)
