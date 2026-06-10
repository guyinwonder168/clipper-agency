"""FFmpeg-backed media quality detectors for black and frozen video segments."""

import re
import subprocess
from pathlib import Path

from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming


DETECTOR_TIMEOUT_SEC = 120
_BLACK_SEGMENT_RE = re.compile(
    r"black_start:(?P<start>\d+(?:\.\d+)?)\s+"
    r"black_end:(?P<end>\d+(?:\.\d+)?)",
)
_FREEZE_START_RE = re.compile(
    r"lavfi\.freezedetect\.freeze_start:\s*(?P<start>\d+(?:\.\d+)?)",
)
_FREEZE_END_RE = re.compile(
    r"lavfi\.freezedetect\.freeze_end:\s*(?P<end>\d+(?:\.\d+)?)",
)


class MediaDetectionError(RuntimeError):
    """Raised when an FFmpeg media detector command fails."""


def detect_black_segments(
    video_path: str | Path,
    min_duration_sec: float,
    pixel_threshold: float,
) -> list[tuple[float, float]]:
    """Return black video intervals detected by FFmpeg blackdetect."""
    filter_expr = f"blackdetect=d={min_duration_sec}:pix_th={pixel_threshold}"
    stderr = _run_detector(video_path, filter_expr, "blackdetect")
    return _parse_black_segments(stderr)


def detect_freeze_segments(
    video_path: str | Path,
    min_duration_sec: float,
    noise_threshold: float,
) -> list[tuple[float, float]]:
    """Return frozen video intervals detected by FFmpeg freezedetect."""
    filter_expr = f"freezedetect=n={noise_threshold}:d={min_duration_sec}"
    stderr = _run_detector(video_path, filter_expr, "freezedetect")
    return _parse_freeze_segments(stderr)


def _run_detector(video_path: str | Path, filter_expr: str, label: str) -> str:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(video_path),
        "-vf",
        filter_expr,
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        return run_ffmpeg_streaming(cmd, timeout=DETECTOR_TIMEOUT_SEC, label=label)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = _detector_failure_detail(exc)
        raise MediaDetectionError(f"FFmpeg {label} failed: {detail}") from exc


def _parse_black_segments(stderr: str) -> list[tuple[float, float]]:
    return [
        (float(match.group("start")), float(match.group("end")))
        for match in _BLACK_SEGMENT_RE.finditer(stderr)
    ]


def _parse_freeze_segments(stderr: str) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    current_start: float | None = None

    for line in stderr.splitlines():
        start_match = _FREEZE_START_RE.search(line)
        if start_match is not None:
            current_start = float(start_match.group("start"))
            continue

        end_match = _FREEZE_END_RE.search(line)
        if end_match is not None and current_start is not None:
            intervals.append((current_start, float(end_match.group("end"))))
            current_start = None

    return intervals


def _detector_failure_detail(exc: BaseException) -> str:
    stderr = getattr(exc, "stderr", None)
    if stderr:
        return str(stderr)
    return str(exc)
