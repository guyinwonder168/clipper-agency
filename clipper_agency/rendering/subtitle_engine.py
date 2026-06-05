"""Subtitle engine — converts script text per scene into timed CaptionOverlay objects.

Pure functions on immutable data — no side effects, no I/O.
"""

from __future__ import annotations

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
