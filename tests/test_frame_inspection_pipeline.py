"""Tests for candidate frame inspection pipeline."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from clipper_agency.config.schema import ExtractedFrame, FrameExtractionManifest
from clipper_agency.core.frame_inspection_pipeline import run_frame_inspection_pipeline


def _write_minimal_jpeg(path: Path, width: int, height: int) -> None:
    """Write enough JPEG structure for metadata parsing tests."""
    sof0_payload = struct.pack(">BHHB", 8, height, width, 3) + bytes([
        1, 0x11, 0,
        2, 0x11, 0,
        3, 0x11, 0,
    ])
    path.write_bytes(
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", len(sof0_payload) + 2)
        + sof0_payload
        + b"\xff\xd9"
    )


def _mock_video_info(video_path: str) -> object:
    """Create a minimal VideoInfo for patching probe_video."""
    from clipper_agency.core.media_probe import VideoInfo
    return VideoInfo(
        path=video_path,
        width=1920,
        height=1080,
        codec="h264",
        pix_fmt="yuv420p",
        duration=3.0,
        has_audio=True,
        file_size=1000,
    )


def _mock_video_info_long(video_path: str) -> object:
    """Create a VideoInfo with 10s duration for cap testing."""
    from clipper_agency.core.media_probe import VideoInfo
    return VideoInfo(
        path=video_path,
        width=1920,
        height=1080,
        codec="h264",
        pix_fmt="yuv420p",
        duration=10.0,
        has_audio=True,
        file_size=5000,
    )


class TestRunFrameInspectionPipeline:
    """Tests for run_frame_inspection_pipeline()."""

    def test_full_pipeline_returns_manifest_with_correct_structure(self, tmp_path):
        """Pipeline produces a manifest with correct asset/beat IDs and frames."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"video")
        cache_root = tmp_path / "cache"

        hash_seq = iter(["0000000000000000", "1111111111111111", "2222222222222222",
                         "3333333333333333", "4444444444444444", "5555555555555555",
                         "6666666666666666"])

        def ffmpeg_runner(cmd, _timeout, _label):
            _write_minimal_jpeg(Path(cmd[-1]), width=640, height=360)
            return "ok"

        def hash_fn(_image_path):
            return next(hash_seq)

        with patch(
            "clipper_agency.core.frame_inspection_pipeline.probe_video",
            return_value=_mock_video_info(str(video_path)),
        ):
            manifest = run_frame_inspection_pipeline(
                video_path=str(video_path),
                job_id=1,
                beat_id="beat_01",
                asset_id="asset_A",
                cache_root=cache_root,
                allowed_base_dir=tmp_path,
                interval_sec=0.5,
                ffmpeg_runner=ffmpeg_runner,
                hash_fn=hash_fn,
                dedup_max_distance=0,
            )

        assert isinstance(manifest, FrameExtractionManifest)
        assert manifest.asset_id == "asset_A"
        assert manifest.beat_id == "beat_01"
        assert manifest.source_path == str(video_path)
        # 3.0s duration at 0.5s interval → 7 timestamps (0.0,0.5,1.0,...,3.0)
        assert len(manifest.frames) == 7
        assert all(isinstance(f, ExtractedFrame) for f in manifest.frames)
        assert all(f.width == 640 and f.height == 360 for f in manifest.frames)

    def test_caps_frames_at_specified_maximum(self, tmp_path):
        """When many frames are planned, the pipeline caps output to max_frames."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"video")
        cache_root = tmp_path / "cache"

        counter = 0

        def ffmpeg_runner(cmd, _timeout, _label):
            _write_minimal_jpeg(Path(cmd[-1]), width=640, height=360)
            return "ok"

        def hash_fn(_image_path):
            nonlocal counter
            h = f"000000000000{counter:04x}"
            counter += 1
            return h

        with patch(
            "clipper_agency.core.frame_inspection_pipeline.probe_video",
            return_value=_mock_video_info_long(str(video_path)),
        ):
            manifest = run_frame_inspection_pipeline(
                video_path=str(video_path),
                job_id=1,
                beat_id="beat_01",
                asset_id="asset_A",
                cache_root=cache_root,
                allowed_base_dir=tmp_path,
                interval_sec=0.1,
                max_frames=5,
                ffmpeg_runner=ffmpeg_runner,
                hash_fn=hash_fn,
                dedup_max_distance=0,
            )

        # 10s at 0.1s → 101 timestamps, capped to 5
        assert len(manifest.frames) == 5

    def test_deduplicates_near_identical_frames(self, tmp_path):
        """Frames with perceptually similar hashes are collapsed to first occurrence."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"video")
        cache_root = tmp_path / "cache"

        # Simulate: first 3 frames near-identical, next 3 different, last 2 near-identical
        hash_seq = iter([
            "0000000000000000", "0000000000000001", "0000000000000002",  # near group 1
            "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc",  # unique
            "ffffffffffffffff", "fffffffffffffffe",                        # near group 2
        ])

        def ffmpeg_runner(cmd, _timeout, _label):
            _write_minimal_jpeg(Path(cmd[-1]), width=640, height=360)
            return "ok"

        def hash_fn(_image_path):
            return next(hash_seq)

        with patch(
            "clipper_agency.core.frame_inspection_pipeline.probe_video",
            return_value=_mock_video_info(str(video_path)),
        ):
            manifest = run_frame_inspection_pipeline(
                video_path=str(video_path),
                job_id=1,
                beat_id="beat_01",
                asset_id="asset_A",
                cache_root=cache_root,
                allowed_base_dir=tmp_path,
                interval_sec=0.5,
                ffmpeg_runner=ffmpeg_runner,
                hash_fn=hash_fn,
                dedup_max_distance=2,
            )

        # 7 timestamp frames, deduplicated by hash groups:
        # Group 1 (3 near) → 1 kept, Group 2 (3 unique) → 3 kept, Group 3 (2 near) → 1 kept
        # = 5 total
        assert len(manifest.frames) == 5

    def test_persists_manifest_json_in_inspection_dir(self, tmp_path):
        """Pipeline writes manifest JSON to the candidate inspection directory."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"video")
        cache_root = tmp_path / "cache"

        hash_seq = iter(["0000000000000000", "1111111111111111", "2222222222222222"])

        def ffmpeg_runner(cmd, _timeout, _label):
            _write_minimal_jpeg(Path(cmd[-1]), width=640, height=360)
            return "ok"

        def hash_fn(_image_path):
            try:
                return next(hash_seq)
            except StopIteration:
                return "9999999999999999"

        with patch(
            "clipper_agency.core.frame_inspection_pipeline.probe_video",
            return_value=_mock_video_info(str(video_path)),
        ):
            manifest = run_frame_inspection_pipeline(
                video_path=str(video_path),
                job_id=42,
                beat_id="my_beat",
                asset_id="asset_X",
                cache_root=cache_root,
                allowed_base_dir=tmp_path,
                interval_sec=1.0,
                ffmpeg_runner=ffmpeg_runner,
                hash_fn=hash_fn,
                dedup_max_distance=0,
            )

        expected_dir = (
            cache_root / "job_42" / "inspections" / "candidates"
            / "beat_my_beat" / "asset_asset_X"
        )
        manifest_path = expected_dir / "manifest.json"
        assert manifest_path.is_file()

        data = json.loads(manifest_path.read_text())
        assert data["asset_id"] == "asset_X"
        assert data["beat_id"] == "my_beat"
        assert data["source_path"] == str(video_path)
        # 3s at 1.0s interval → 4 timestamps (0.0, 1.0, 2.0, 3.0)
        assert len(data["frames"]) == 4
        assert data["frames"][0]["timestamp_sec"] == 0.0

    def test_raises_when_probe_returns_none(self, tmp_path):
        """Pipeline should raise a clear error when probe_video returns None."""
        cache_root = tmp_path / "cache"

        with patch(
            "clipper_agency.core.frame_inspection_pipeline.probe_video",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="probe"):
                run_frame_inspection_pipeline(
                    video_path="/nonexistent/video.mp4",
                    job_id=1,
                    beat_id="beat_01",
                    asset_id="asset_A",
                    cache_root=cache_root,
                    allowed_base_dir=tmp_path,
                )
