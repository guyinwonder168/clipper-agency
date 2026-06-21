"""FFmpeg runtime quality integration tests.

These tests create synthetic videos using real FFmpeg, then run the
project's media detectors, frame extractor, and quality helpers against
them.  All tests are marked ``@pytest.mark.integration`` and are skipped
in offline runs (``-m "not integration"``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming
from clipper_agency.core.frame_extractor import extract_frames
from clipper_agency.core.frame_quality import (
    detect_empty_segments,
    is_empty_or_uniform_frame,
)
from clipper_agency.core.media_detectors import (
    MediaDetectionError,
    detect_black_segments,
    detect_freeze_segments,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers — synthetic video generation
# ---------------------------------------------------------------------------


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


def _create_synthetic_video(
    output_path: Path,
    duration_sec: float,
    fps: int,
    vf_filter: str,
) -> Path:
    """Create a synthetic video using FFmpeg's lavfi source and return its path."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=320x240:d={duration_sec}:r={fps}",
        "-vf",
        vf_filter,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    return output_path


@pytest.fixture
def synthetic_black_video(tmp_path: Path) -> Path:
    """5-second pure black video — should be fully detected as one black segment."""
    return _create_synthetic_video(
        tmp_path / "black.mp4",
        duration_sec=5.0,
        fps=24,
        vf_filter="null",
    )


@pytest.fixture
def synthetic_frozen_video(tmp_path: Path) -> Path:
    """5-second frozen-frame video (single grey frame held).

    FFmpeg freezedetect will flag the entire duration as frozen.
    """
    return _create_synthetic_video(
        tmp_path / "frozen.mp4",
        duration_sec=5.0,
        fps=24,
        vf_filter="colorbalance=rs=0.5:gs=0.5:bs=0.5",
    )


@pytest.fixture
def synthetic_clean_video(tmp_path: Path) -> Path:
    """5-second clean video with varying content (test pattern).

    Uses FFmpeg's ``testsrc`` which produces a counter + colour bars —
    never black, never frozen.
    """
    out = tmp_path / "clean.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=5:size=320x240:rate=24",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    return out


@pytest.fixture
def synthetic_text_video(tmp_path: Path) -> Path:
    """5-second video with burned-in text overlay (white text on black)."""
    return _create_synthetic_video(
        tmp_path / "text_overlay.mp4",
        duration_sec=5.0,
        fps=24,
        vf_filter="drawtext=text='SAMPLE TEXT':fontsize=48:fontcolor=white:x=40:y=100",
    )


@pytest.fixture
def synthetic_black_ending_video(tmp_path: Path) -> Path:
    """6-second video: 3 s of test pattern + 3 s of black.

    The first half has content; the last half is pure black.
    """
    out = tmp_path / "black_ending.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=3:size=320x240:rate=24",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x240:d=3:r=24",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[outv]",
        "-map",
        "[outv]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    return out


# ===========================================================================
# Tests — black segment detection
# ===========================================================================


@requires_ffmpeg
class TestBlackSegmentDetection:
    """Integration tests for ``detect_black_segments()`` with real FFmpeg."""

    def test_pure_black_video_detected_as_single_interval(
        self,
        synthetic_black_video: Path,
    ):
        segments = detect_black_segments(
            synthetic_black_video,
            min_duration_sec=0.5,
            pixel_threshold=0.1,
        )
        assert len(segments) >= 1
        first_start, first_end = segments[0]
        # The black segment should cover nearly the entire 5 s duration.
        assert first_start <= 0.1, f"Expected start near 0, got {first_start}"
        assert first_end >= 4.5, f"Expected end near 5.0, got {first_end}"

    def test_clean_video_has_no_black_segments(
        self,
        synthetic_clean_video: Path,
    ):
        segments = detect_black_segments(
            synthetic_clean_video,
            min_duration_sec=0.5,
            pixel_threshold=0.1,
        )
        assert segments == []

    def test_text_overlay_video_not_detected_as_black(
        self,
        synthetic_text_video: Path,
    ):
        """Burned-in text on black may register as black if the text covers
        very little area, so we use a lenient check: the detected black
        segment (if any) must be shorter than the full duration."""
        segments = detect_black_segments(
            synthetic_text_video,
            min_duration_sec=0.5,
            pixel_threshold=0.1,
        )
        for start, end in segments:
            assert (end - start) < 4.0, (
                f"Unexpected long black segment ({start}–{end}) in text video"
            )

    def test_black_ending_detected_in_second_half(
        self,
        synthetic_black_ending_video: Path,
    ):
        segments = detect_black_segments(
            synthetic_black_ending_video,
            min_duration_sec=0.5,
            pixel_threshold=0.1,
        )
        assert len(segments) >= 1
        # The black part starts at ~3 s.
        detected_start = segments[0][0]
        assert detected_start >= 2.5, f"Black segment should start near 3.0 s, got {detected_start}"


# ===========================================================================
# Tests — freeze frame detection
# ===========================================================================


@pytest.mark.integration
@requires_ffmpeg
class TestFreezeFrameDetection:
    """Integration tests for ``detect_freeze_segments()`` with real FFmpeg."""

    def test_frozen_video_detected_as_single_interval(
        self,
        synthetic_frozen_video: Path,
    ):
        segments = detect_freeze_segments(
            synthetic_frozen_video,
            min_duration_sec=0.5,
            noise_threshold=0.01,
        )
        assert len(segments) >= 1
        first_start, first_end = segments[0]
        assert first_start <= 0.5, f"Expected freeze start near 0, got {first_start}"
        assert first_end >= 4.0, f"Expected freeze end near 5.0, got {first_end}"

    def test_clean_video_has_no_freeze_segments(
        self,
        synthetic_clean_video: Path,
    ):
        segments = detect_freeze_segments(
            synthetic_clean_video,
            min_duration_sec=0.5,
            noise_threshold=0.01,
        )
        assert segments == []

    def test_black_video_also_detected_as_frozen(
        self,
        synthetic_black_video: Path,
    ):
        """A pure-black video is also a frozen video (no pixel change)."""
        segments = detect_freeze_segments(
            synthetic_black_video,
            min_duration_sec=0.5,
            noise_threshold=0.01,
        )
        assert len(segments) >= 1


# ===========================================================================
# Tests — frame extraction
# ===========================================================================


@requires_ffmpeg
class TestFrameExtraction:
    """Integration tests for ``extract_frames()`` with real FFmpeg."""

    def test_extracts_frames_at_specified_timestamps(
        self,
        synthetic_clean_video: Path,
        tmp_path: Path,
    ):
        timestamps = [0.0, 1.0, 2.0]
        frames = extract_frames(
            video_path=str(synthetic_clean_video),
            timestamps=timestamps,
            output_dir=str(tmp_path / "frames"),
            ffmpeg_runner=run_ffmpeg_streaming,
        )
        assert len(frames) == 3
        for frame in frames:
            assert frame.width > 0
            assert frame.height > 0
            assert Path(frame.path).exists()

    def test_extracts_no_frames_from_timestamp_beyond_duration(
        self,
        synthetic_clean_video: Path,
        tmp_path: Path,
    ):
        frames = extract_frames(
            video_path=str(synthetic_clean_video),
            timestamps=[99.0],
            output_dir=str(tmp_path / "frames_oob"),
            ffmpeg_runner=run_ffmpeg_streaming,
        )
        assert frames == []

    def test_extracted_black_frames_are_detected_as_uniform(
        self,
        synthetic_black_video: Path,
        tmp_path: Path,
    ):
        """Frames extracted from a black video should be flagged as uniform."""
        import cv2

        frames = extract_frames(
            video_path=str(synthetic_black_video),
            timestamps=[0.5, 1.5, 2.5],
            output_dir=str(tmp_path / "black_frames"),
            ffmpeg_runner=run_ffmpeg_streaming,
        )
        assert len(frames) == 3
        for frame in frames:
            img = cv2.imread(frame.path, cv2.IMREAD_COLOR)
            assert img is not None
            assert is_empty_or_uniform_frame(img, threshold=1.0)


# ===========================================================================
# Tests — empty segment detection on extracted frames
# ===========================================================================


@requires_ffmpeg
class TestEmptySegmentDetectionIntegration:
    """Integration: extract frames then run ``detect_empty_segments()``."""

    def test_black_video_frames_merge_into_single_empty_segment(
        self,
        synthetic_black_video: Path,
        tmp_path: Path,
    ):
        import cv2

        timestamps = [0.5, 1.5, 2.5, 3.5]
        frames = extract_frames(
            video_path=str(synthetic_black_video),
            timestamps=timestamps,
            output_dir=str(tmp_path / "seg_frames"),
            ffmpeg_runner=run_ffmpeg_streaming,
        )
        sampled = [(f.timestamp_sec, cv2.imread(f.path, cv2.IMREAD_COLOR)) for f in frames]
        intervals = detect_empty_segments(sampled, max_gap_sec=2.0)
        assert len(intervals) >= 1
        first_start, first_end = intervals[0]
        assert first_start <= 0.6
        assert first_end >= 3.4

    def test_black_ending_video_has_empty_segment_in_second_half(
        self,
        synthetic_black_ending_video: Path,
        tmp_path: Path,
    ):
        import cv2

        timestamps = [1.0, 2.0, 3.5, 4.5, 5.5]
        frames = extract_frames(
            video_path=str(synthetic_black_ending_video),
            timestamps=timestamps,
            output_dir=str(tmp_path / "ending_frames"),
            ffmpeg_runner=run_ffmpeg_streaming,
        )
        sampled = [(f.timestamp_sec, cv2.imread(f.path, cv2.IMREAD_COLOR)) for f in frames]
        intervals = detect_empty_segments(sampled, max_gap_sec=2.0)
        assert len(intervals) >= 1
        # The empty segment should only be from the black portion (≥ 3.0 s).
        for start, end in intervals:
            assert start >= 3.0, f"Empty segment at {start}–{end} should start ≥ 3.0 s"


# ===========================================================================
# Tests — error handling with invalid input
# ===========================================================================


@requires_ffmpeg
class TestDetectorErrorHandling:
    """Verify detectors raise ``MediaDetectionError`` for bad inputs."""

    def test_detect_black_segments_raises_on_missing_file(self, tmp_path: Path):
        with pytest.raises(MediaDetectionError):
            detect_black_segments(
                tmp_path / "nonexistent.mp4",
                min_duration_sec=0.5,
                pixel_threshold=0.1,
            )

    def test_detect_freeze_segments_raises_on_missing_file(self, tmp_path: Path):
        with pytest.raises(MediaDetectionError):
            detect_freeze_segments(
                tmp_path / "nonexistent.mp4",
                min_duration_sec=0.5,
                noise_threshold=-60,
            )
