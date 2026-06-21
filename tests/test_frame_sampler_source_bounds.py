"""RC-7 regression tests — frame-extraction offsets clamped to actual source media duration.

Symptom (job_12/job_13): the frame sampler logged dozens of
"Failed to extract frame metadata at 502.689s / 723.000s / 465.000s ..."
on short TikTok/YouTube clips (well under 60s). The candidate source
duration used to generate extraction offsets was NOT bounded to the
actual media length, so the sampler requested offsets far beyond the
clip -> wasted VLM-bound frame inspections + inspection failures.

These tests assert that every generated offset stays within the ACTUAL
probed source duration, and that an unprobeable source (probe returns
None/0) never produces offsets in the hundreds of seconds.
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

from clipper_agency.core.frame_inspection_pipeline import run_frame_inspection_pipeline
from clipper_agency.core.frame_sampler import plan_frame_samples

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_jpeg(path: Path, width: int, height: int) -> None:
    """Write enough JPEG structure for metadata parsing."""
    sof0_payload = struct.pack(">BHHB", 8, height, width, 3) + bytes(
        [
            1,
            0x11,
            0,
            2,
            0x11,
            0,
            3,
            0x11,
            0,
        ]
    )
    path.write_bytes(
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", len(sof0_payload) + 2)
        + sof0_payload
        + b"\xff\xd9"
    )


def _video_info(duration: float | None):
    """Build a VideoInfo with the requested duration."""
    from clipper_agency.core.media_probe import VideoInfo

    return VideoInfo(
        path="/fake/clip.mp4",
        width=1080,
        height=1920,
        codec="h264",
        pix_fmt="yuv420p",
        duration=duration,
        has_audio=True,
        file_size=1000,
    )


class TestPlanFrameSamplesSourceBounds:
    """plan_frame_samples must never emit offsets beyond the source media length."""

    def test_offsets_bounded_to_actual_duration(self):
        """A 30s clip must only produce offsets in [0.0, 30.0]."""
        offsets = plan_frame_samples(
            duration_sec=30.0,
            scene_boundaries=[],
            interval_sec=1.0,
        )
        assert offsets, "expected at least one offset"
        assert all(0.0 <= o <= 30.0 for o in offsets)
        assert max(offsets) <= 30.0

    def test_huge_probed_duration_is_clamped_to_safe_bound(self):
        """RED->GREEN: a bogus/huge probed duration (723s) for a short clip must
        NOT generate offsets in the hundreds of seconds.

        The caller bounds the offsets; plan_frame_samples clamps to max_offset_sec.
        """
        # Simulate the job_12/13 symptom: ffprobe reported 723.0s for a ~30s clip.
        # The pipeline must clamp the effective bound so no offset exceeds the
        # safe maximum, regardless of the raw probed value.
        offsets = plan_frame_samples(
            duration_sec=723.0,
            scene_boundaries=[],
            interval_sec=1.0,
            max_offset_sec=30.0,
        )
        assert offsets, "expected at least one offset"
        # No offset in the hundreds of seconds.
        assert max(offsets) <= 30.0, f"unbounded offset leaked: {max(offsets)}"
        assert all(0.0 <= o <= 30.0 for o in offsets)

    def test_missing_duration_falls_back_to_safe_bound(self):
        """When the probed duration is unavailable (0), offsets stay within the
        safe bound — never a huge value."""
        offsets = plan_frame_samples(
            duration_sec=0.0,
            scene_boundaries=[],
            interval_sec=1.0,
            max_offset_sec=30.0,
        )
        assert offsets == [0.0]
        assert max(offsets) <= 30.0


class TestRunFrameInspectionPipelineSourceBounds:
    """End-to-end: the pipeline must clamp offsets to the actual source media."""

    def test_offsets_bounded_to_probed_duration(self, tmp_path):
        """A source whose probed duration is 30s yields only offsets <= 30s."""
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"video")
        cache_root = tmp_path / "cache"

        captured_offsets: list[float] = []

        def ffmpeg_runner(cmd, _timeout, _label):
            ts = float(cmd[cmd.index("-ss") + 1])
            captured_offsets.append(ts)
            _write_minimal_jpeg(Path(cmd[-1]), width=640, height=360)
            return "ok"

        with patch(
            "clipper_agency.core.frame_inspection_pipeline.probe_video",
            return_value=_video_info(30.0),
        ):
            run_frame_inspection_pipeline(
                video_path=str(video_path),
                job_id=1,
                beat_id="beat_01",
                asset_id="asset_A",
                cache_root=cache_root,
                allowed_base_dir=tmp_path,
                interval_sec=1.0,
                ffmpeg_runner=ffmpeg_runner,
                hash_fn=lambda _p: "0000000000000000",
                dedup_max_distance=0,
            )

        assert captured_offsets, "extractor was never called"
        assert max(captured_offsets) <= 30.0, (
            f"offset exceeded probed duration: {max(captured_offsets)}"
        )

    def test_huge_probed_duration_clamped(self, tmp_path):
        """RED->GREEN: a bogus huge probed duration (723s) must NOT request
        offsets in the hundreds of seconds.

        Reproduces the job_12/13 storm of 'Failed to extract frame metadata at
        502.689s / 723.000s ...'. The pipeline must clamp offsets to a safe
        maximum bound regardless of the raw probed duration.
        """
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"video")
        cache_root = tmp_path / "cache"

        captured_offsets: list[float] = []

        def ffmpeg_runner(cmd, _timeout, _label):
            ts = float(cmd[cmd.index("-ss") + 1])
            captured_offsets.append(ts)
            _write_minimal_jpeg(Path(cmd[-1]), width=640, height=360)
            return "ok"

        # ffprobe falsely reports 723.0s for a short clip.
        with patch(
            "clipper_agency.core.frame_inspection_pipeline.probe_video",
            return_value=_video_info(723.0),
        ):
            run_frame_inspection_pipeline(
                video_path=str(video_path),
                job_id=1,
                beat_id="beat_01",
                asset_id="asset_A",
                cache_root=cache_root,
                allowed_base_dir=tmp_path,
                interval_sec=1.0,
                ffmpeg_runner=ffmpeg_runner,
                hash_fn=lambda _p: "0000000000000000",
                dedup_max_distance=0,
            )

        assert captured_offsets, "extractor was never called"
        # The fix must bound offsets to a safe maximum — no hundreds of seconds.
        assert max(captured_offsets) <= 30.0, (
            f"unbounded offset leaked through pipeline: {max(captured_offsets)}"
        )

    def test_unprobeable_source_uses_safe_small_bound(self, tmp_path):
        """When the probe returns a duration of 0 / unavailable, offsets stay
        within the safe bound — not hundreds of seconds."""
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"video")
        cache_root = tmp_path / "cache"

        captured_offsets: list[float] = []

        def ffmpeg_runner(cmd, _timeout, _label):
            ts = float(cmd[cmd.index("-ss") + 1])
            captured_offsets.append(ts)
            _write_minimal_jpeg(Path(cmd[-1]), width=640, height=360)
            return "ok"

        with patch(
            "clipper_agency.core.frame_inspection_pipeline.probe_video",
            return_value=_video_info(0.0),
        ):
            run_frame_inspection_pipeline(
                video_path=str(video_path),
                job_id=1,
                beat_id="beat_01",
                asset_id="asset_A",
                cache_root=cache_root,
                allowed_base_dir=tmp_path,
                interval_sec=1.0,
                ffmpeg_runner=ffmpeg_runner,
                hash_fn=lambda _p: "0000000000000000",
                dedup_max_distance=0,
            )

        assert captured_offsets, "extractor was never called"
        assert max(captured_offsets) <= 30.0, (
            f"unsafe offset for unprobeable source: {max(captured_offsets)}"
        )
        # Codex P2 (RC-7): a missing/<=0 probed duration must still sample the
        # 0-30s fallback window -- NOT collapse to a single [0.0] frame (which
        # would judge a valid clip from one unrepresentative frame). The pipeline
        # passes safe_bound (not raw_duration) as the sampling window.
        assert len(captured_offsets) > 1, (
            f"missing-duration collapsed to a single frame: {captured_offsets}"
        )
