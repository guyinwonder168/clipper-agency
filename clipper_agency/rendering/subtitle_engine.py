"""Subtitle engine — converts script text per scene into timed CaptionOverlay objects.

Pure functions on immutable data — no side effects, no I/O.
"""

from __future__ import annotations

from typing import Optional

from clipper_agency.rendering.contracts import CaptionOverlay

_DEFAULT_SCENE_DURATION = 5.0
_MAX_KEYWORD_WORDS = 6


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


def build_keyword_captions(
    narrative_structure: list[dict],
    timestamps: list[dict],
    width: int = 1080,
    height: int = 1920,
    hook_duration: float = 0.0,
) -> list[CaptionOverlay]:
    """Build keyword captions from narrative structure aligned to audio timestamps.

    Each beat produces one keyword caption using ``caption_keywords``,
    with timing derived from word-level timestamps via ``word_range``.

    Args:
        narrative_structure: List of NarrativeBeat-like dicts with
            ``beat_id``, ``word_range`` [start_idx, end_idx], ``caption_keywords``.
        timestamps: List of WordTimestamp-like dicts with ``word``, ``start``, ``end``.
        width: Video width for positioning (reserved for future use).
        height: Video height for positioning (reserved for future use).
        hook_duration: Skip captions starting before this time (seconds).
            Used to avoid duplicating text already rendered on the hook card.

    Returns:
        Flat list of ``CaptionOverlay`` with ``position="bottom"`` and
        ``style="keyword"``.  Returns empty list on missing/empty inputs.
    """
    if not narrative_structure:
        return []

    # Fallback: estimate timing from word ranges when timestamps unavailable
    if not timestamps:
        words_per_sec = 2.0
        overlays: list[CaptionOverlay] = []
        for beat in narrative_structure:
            keywords = beat.get("caption_keywords", [])
            word_range = beat.get("word_range", [])
            if not keywords or len(word_range) < 2:
                continue
            caption_text = " ".join(keywords[:_MAX_KEYWORD_WORDS])
            if not caption_text:
                continue
            start_time = word_range[0] / words_per_sec
            end_time = word_range[1] / words_per_sec
            if end_time <= start_time:
                continue
            if start_time < hook_duration:
                continue
            overlays.append(CaptionOverlay(
                text=caption_text,
                start_seconds=start_time,
                end_seconds=end_time,
                position="bottom",
                style="keyword",
            ))
        return overlays

    overlays: list[CaptionOverlay] = []

    for beat in narrative_structure:
        keywords = beat.get("caption_keywords", [])
        word_range = beat.get("word_range", [])

        if not keywords or len(word_range) < 2:
            continue

        # Truncate to max words per caption
        caption_text = " ".join(keywords[:_MAX_KEYWORD_WORDS])
        if not caption_text:
            continue

        # Resolve timing from word-level timestamps
        start_idx = max(0, min(word_range[0], len(timestamps) - 1))
        end_idx = max(start_idx + 1, min(word_range[1], len(timestamps)))

        ts_start = timestamps[start_idx]
        ts_end = timestamps[end_idx - 1]

        start_time = (
            ts_start.get("start", 0.0) if isinstance(ts_start, dict)
            else getattr(ts_start, "start", 0.0)
        )
        end_time = (
            ts_end.get("end", start_time + 1.0) if isinstance(ts_end, dict)
            else getattr(ts_end, "end", start_time + 1.0)
        )

        if end_time <= start_time:
            continue
        if start_time < hook_duration:
            continue

        overlays.append(
            CaptionOverlay(
                text=caption_text,
                start_seconds=start_time,
                end_seconds=end_time,
                position="bottom",
                style="keyword",
            )
        )

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
