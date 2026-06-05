"""Subtitle engine — converts script text per scene into timed CaptionOverlay objects.

Pure functions on immutable data — no side effects, no I/O.
"""

from __future__ import annotations

from typing import Optional

from clipper_agency.rendering.contracts import CaptionOverlay

_DEFAULT_SCENE_DURATION = 5.0


def build_subtitle_overlays(
    scenes: list[dict],
    words_per_caption: int = 6,
) -> list[CaptionOverlay]:
    """Convert scene texts to timed caption overlays with absolute timestamps.

    Each scene's text is split into chunks of *words_per_caption* words.
    Each chunk gets a start/end time calculated from the scene's duration.
    Returns a flat list of ``CaptionOverlay`` with absolute timestamps.

    Args:
        scenes: Scriptwriter output — list of dicts with ``"text"`` and
            ``"duration"`` keys.
        words_per_caption: Maximum words per caption chunk (default 6,
            TikTok-optimized).

    Returns:
        Flat list of ``CaptionOverlay`` instances with absolute timestamps.
    """
    overlays: list[CaptionOverlay] = []
    scene_start = 0.0

    for scene in scenes:
        text = scene.get("text", "")
        duration = float(scene.get("duration", _DEFAULT_SCENE_DURATION))

        # Skip scenes with empty/whitespace-only text
        words = text.split()
        if not words:
            scene_start += duration
            continue

        # Split into chunks
        chunks: list[str] = []
        for i in range(0, len(words), words_per_caption):
            chunks.append(" ".join(words[i : i + words_per_caption]))

        chunk_duration = duration / len(chunks)

        for idx, chunk in enumerate(chunks):
            overlays.append(
                CaptionOverlay(
                    text=chunk,
                    start_seconds=scene_start + idx * chunk_duration,
                    end_seconds=scene_start + (idx + 1) * chunk_duration,
                )
            )

        scene_start += duration

    return overlays


def build_hook_overlay(
    scenes: list[dict],
    hook_window_seconds: float = 3.0,
) -> Optional[CaptionOverlay]:
    """Create a large hook caption spanning the first few seconds of video.

    Uses the first scene's headline text for an attention-grabbing overlay.

    Args:
        scenes: Scriptwriter output — list of dicts with ``"text"`` and
            ``"duration"`` keys.
        hook_window_seconds: How many seconds the hook overlay spans (default 3.0).

    Returns:
        A ``CaptionOverlay`` with position ``"center"`` and style ``"hook"``,
        or ``None`` if no suitable scene text is available.
    """
    if not scenes:
        return None

    first = scenes[0]
    text = first.get("text", "").strip()
    if not text:
        return None

    duration = float(first.get("duration", _DEFAULT_SCENE_DURATION))
    end = min(hook_window_seconds, duration)

    if end <= 0.0:
        return None

    return CaptionOverlay(
        text=text,
        start_seconds=0.0,
        end_seconds=end,
        position="center",
        style="hook",
    )


def validate_tiktok_output(cmd_args: list[str]) -> dict[str, bool]:
    """Validate that an FFmpeg command list has TikTok-required production flags.

    Args:
        cmd_args: Flat list of FFmpeg CLI arguments (e.g. ``["-c:v", "libx264"]``).

    Returns:
        Dict mapping requirement name to ``True`` (met) or ``False`` (missing).
    """
    result: dict[str, bool] = {}

    def _arg_value(flag: str) -> str | None:
        try:
            idx = cmd_args.index(flag)
            return cmd_args[idx + 1]
        except (ValueError, IndexError):
            return None

    result["pix_fmt_yuv420p"] = _arg_value("-pix_fmt") == "yuv420p"
    result["faststart"] = (
        _arg_value("-movflags") is not None
        and "+faststart" in (_arg_value("-movflags") or "")
    )
    result["codec_h264"] = _arg_value("-c:v") == "libx264"
    result["codec_aac"] = _arg_value("-c:a") == "aac"
    result["audio_bitrate"] = _arg_value("-b:a") is not None
    result["shortest_flag"] = "-shortest" in cmd_args

    return result
