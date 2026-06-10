"""Tests for runtime frame extraction adapter."""

import logging
import struct
from pathlib import Path

from clipper_agency.core.frame_extractor import extract_frames


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


class TestExtractFrames:
    """Unit tests for extract_frames()."""

    def test_persists_deterministic_jpeg_names_and_reads_dimensions(self, tmp_path):
        """Extracted frames use timestamp filenames and image metadata dimensions."""
        video_path = tmp_path / "source.mp4"
        video_path.write_bytes(b"video")
        output_dir = tmp_path / "frames"
        calls: list[list[str]] = []

        def ffmpeg_runner(cmd, _timeout, _label):
            calls.append(cmd)
            _write_minimal_jpeg(Path(cmd[-1]), width=640, height=360)
            return "ok"

        frames = extract_frames(
            video_path=str(video_path),
            timestamps=[0.0, 0.5],
            output_dir=output_dir,
            ffmpeg_runner=ffmpeg_runner,
        )

        assert [Path(frame.path).name for frame in frames] == [
            "frame_000000ms.jpg",
            "frame_000500ms.jpg",
        ]
        assert [(frame.width, frame.height) for frame in frames] == [
            (640, 360),
            (640, 360),
        ]
        assert [frame.timestamp_sec for frame in frames] == [0.0, 0.5]
        assert [frame.perceptual_hash for frame in frames] == ["", ""]
        assert len(calls) == 2
        assert all("-frames:v" in cmd and "1" in cmd for cmd in calls)

    def test_keeps_successful_frames_when_one_timestamp_fails(self, tmp_path, caplog):
        """One failed FFmpeg extraction is logged and does not drop successes."""
        video_path = tmp_path / "source.mp4"
        video_path.write_bytes(b"video")
        output_dir = tmp_path / "frames"

        def ffmpeg_runner(cmd, _timeout, _label):
            if Path(cmd[-1]).name == "frame_000500ms.jpg":
                raise RuntimeError("ffmpeg failed")
            _write_minimal_jpeg(Path(cmd[-1]), width=1080, height=1920)
            return "ok"

        with caplog.at_level(
            logging.WARNING,
            logger="clipper_agency.core.frame_extractor",
        ):
            frames = extract_frames(
                video_path=str(video_path),
                timestamps=[0.0, 0.5, 1.0],
                output_dir=output_dir,
                ffmpeg_runner=ffmpeg_runner,
            )

        assert [Path(frame.path).name for frame in frames] == [
            "frame_000000ms.jpg",
            "frame_001000ms.jpg",
        ]
        assert "0.500" in caplog.text
        assert "ffmpeg failed" in caplog.text

    def test_skips_frame_when_generated_image_metadata_is_invalid(
        self,
        tmp_path,
        caplog,
    ):
        """Invalid generated image metadata is logged and skipped."""
        video_path = tmp_path / "source.mp4"
        video_path.write_bytes(b"video")
        output_dir = tmp_path / "frames"

        def ffmpeg_runner(cmd, _timeout, _label):
            output_path = Path(cmd[-1])
            if output_path.name == "frame_000500ms.jpg":
                output_path.write_bytes(b"not an image")
            else:
                _write_minimal_jpeg(output_path, width=720, height=1280)
            return "ok"

        with caplog.at_level(
            logging.WARNING,
            logger="clipper_agency.core.frame_extractor",
        ):
            frames = extract_frames(
                video_path=str(video_path),
                timestamps=[0.0, 0.5],
                output_dir=output_dir,
                ffmpeg_runner=ffmpeg_runner,
            )

        assert [Path(frame.path).name for frame in frames] == ["frame_000000ms.jpg"]
        assert frames[0].width == 720
        assert frames[0].height == 1280
        assert "metadata" in caplog.text
