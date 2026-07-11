"""Media probing utilities — ffprobe-based video metadata extraction."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clipper_agency.core.safe_paths import resolve_existing_file_under


@dataclass(frozen=True)
class VideoInfo:
    """Immutable video metadata extracted via ffprobe."""

    path: str
    width: int
    height: int
    codec: str
    pix_fmt: str
    duration: float | None
    has_audio: bool = False
    audio_duration: float | None = None
    file_size: int = 0
    sample_aspect_ratio: str = "1:1"
    fps: float = 30.0


def probe_video(
    path: str | Path,
    allowed_base_dir: str | Path,
) -> VideoInfo | None:
    """Probe a video file with ffprobe and return structured metadata.

    Returns ``None`` if the file does not exist, ffprobe is unavailable,
    or the JSON output cannot be parsed.
    """
    resolved_path = resolve_existing_file_under(allowed_base_dir, path)
    if resolved_path is None:
        return None
    resolved = str(resolved_path)

    try:
        cmd: list[str] = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            resolved,
        ]
        raw = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    try:
        data: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    streams: list[dict[str, Any]] = data.get("streams", [])
    fmt: dict[str, Any] | None = data.get("format")

    # --- video stream ---
    video_stream = _find_stream(streams, "video")
    if video_stream is None:
        return None

    width = video_stream.get("width", 0)
    height = video_stream.get("height", 0)
    codec = video_stream.get("codec_name", "unknown")
    pix_fmt = video_stream.get("pix_fmt", "unknown")

    # --- sample aspect ratio ---
    sar_raw = video_stream.get("sample_aspect_ratio", "1:1")
    if not sar_raw or sar_raw == "0:1":
        sar_raw = "1:1"

    # --- framerate ---
    fps: float = 30.0  # default
    r_frame_rate = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = r_frame_rate.split("/")
        if int(den) > 0:
            fps = round(int(num) / int(den), 2)
    except (ValueError, ZeroDivisionError):
        fps = 30.0

    # --- audio stream ---
    audio_stream = _find_stream(streams, "audio")
    has_audio = audio_stream is not None
    # FIX-2 (audio-as-master): capture the AUDIO-STREAM duration independently of
    # the container `format.duration` (which is -shortest/-t-equalized). This is
    # the source-of-truth the G10 AUDIO_NOT_TRUNCATED check probes.
    audio_duration: float | None = None
    if audio_stream is not None:
        audio_dur_raw = audio_stream.get("duration")
        if audio_dur_raw:
            try:
                audio_duration = float(audio_dur_raw)
            except (ValueError, TypeError):
                audio_duration = None

    # --- duration ---
    duration: float | None = None
    if fmt is not None and fmt.get("duration"):
        try:
            duration = float(fmt["duration"])
        except (ValueError, TypeError):
            duration = None

    # --- file size ---
    try:
        file_size = resolved_path.stat().st_size
    except OSError:
        file_size = 0

    return VideoInfo(
        path=resolved,
        width=width,
        height=height,
        codec=codec,
        pix_fmt=pix_fmt,
        duration=duration,
        has_audio=has_audio,
        audio_duration=audio_duration,
        file_size=file_size,
        sample_aspect_ratio=sar_raw,
        fps=fps,
    )


def _find_stream(
    streams: list[dict[str, Any]],
    codec_type: str,
) -> dict[str, Any] | None:
    """Return the first stream matching *codec_type*, or ``None``."""
    for stream in streams:
        if stream.get("codec_type") == codec_type:
            return stream
    return None
