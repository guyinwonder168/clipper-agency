"""Runtime frame extraction adapter using an injected FFmpeg runner."""

from collections.abc import Callable, Iterable
import logging
from pathlib import Path
import struct
import subprocess

from clipper_agency.config.schema import ExtractedFrame


logger = logging.getLogger(__name__)

FFMPEG_TIMEOUT_SEC = 30
JPEG_EXTENSION = ".jpg"
JPEG_SIZE_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}

FfmpegRunner = Callable[[list[str], int, str], str]


def extract_frames(
    video_path: str | Path,
    timestamps: Iterable[float],
    output_dir: str | Path,
    ffmpeg_runner: FfmpegRunner,
) -> list[ExtractedFrame]:
    """Extract one JPEG frame for each timestamp and return successful frames."""
    frame_dir = Path(output_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)

    frames: list[ExtractedFrame] = []
    for timestamp_sec in timestamps:
        output_path = frame_dir / _frame_filename(timestamp_sec)
        frame = _extract_one_frame(video_path, timestamp_sec, output_path, ffmpeg_runner)
        if frame is not None:
            frames.append(frame)
    return frames


def _extract_one_frame(
    video_path: str | Path,
    timestamp_sec: float,
    output_path: Path,
    ffmpeg_runner: FfmpegRunner,
) -> ExtractedFrame | None:
    cmd = _build_ffmpeg_command(video_path, timestamp_sec, output_path)
    try:
        ffmpeg_runner(
            cmd,
            FFMPEG_TIMEOUT_SEC,
            f"extract_frame_{_timestamp_ms(timestamp_sec)}ms",
        )
        width, height = _read_image_size(output_path)
    except (
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ):
        logger.warning(
            "Failed to extract frame metadata at %.3fs to %s",
            timestamp_sec,
            output_path,
            exc_info=True,
        )
        return None

    return ExtractedFrame(
        timestamp_sec=timestamp_sec,
        path=str(output_path),
        perceptual_hash="",
        width=width,
        height=height,
    )


def _build_ffmpeg_command(
    video_path: str | Path,
    timestamp_sec: float,
    output_path: Path,
) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp_sec:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]


def _frame_filename(timestamp_sec: float) -> str:
    return f"frame_{_timestamp_ms(timestamp_sec):06d}ms{JPEG_EXTENSION}"


def _timestamp_ms(timestamp_sec: float) -> int:
    return int(round(timestamp_sec * 1000))


def _read_image_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _read_png_size(data)
    if data.startswith(b"\xff\xd8"):
        return _read_jpeg_size(data)
    raise ValueError("unsupported image metadata")


def _read_png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24:
        raise ValueError("incomplete PNG metadata")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _read_jpeg_size(data: bytes) -> tuple[int, int]:
    index = 2
    while index + 3 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in JPEG_SIZE_MARKERS and index + 8 < len(data):
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return width, height
        if marker in {0xD9, 0xDA}:
            break
        segment_length = struct.unpack(">H", data[index + 2:index + 4])[0]
        index += 2 + segment_length
    raise ValueError("missing JPEG size metadata")
