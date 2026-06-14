"""Canonical beat timeline builder (ADR 0020).

Single source of truth for beat durations. Built once by the orchestrator
after Voice Producer completes. Consumed by Visual Director, Composer, and
Reviewer.
"""

from __future__ import annotations

from clipper_agency.config.schema import BeatTimelineEntry

_MIN_BEAT_DURATION_SEC = 0.5


def _ts_value(ts: object, key: str, default: float) -> float:
    """Extract a numeric value from a timestamp dict or pydantic model."""
    if isinstance(ts, dict):
        return ts.get(key, default)
    return getattr(ts, key, default)


def build_canonical_timeline(
    narrative_structure: list[dict],
    timestamps: list[dict],
) -> list[BeatTimelineEntry]:
    """Build canonical beat timeline from narrative structure + word timestamps.

    Each beat spans: current beat's first word start → next beat's first word
    start.  The final beat extends to the last timestamp end, covering trailing
    audio.  Durations are clamped to a 0.5s minimum.

    Args:
        narrative_structure: Scriptwriter beats with ``word_range`` (list of
            ``[first_word_idx, last_word_idx]``).
        timestamps: Voice Producer word-level timestamps (``word``, ``start``,
            ``end``).

    Returns:
        Ordered list of :class:`BeatTimelineEntry` keyed by ``beat_id``.
        Empty list if either input is empty.
    """
    if not narrative_structure or not timestamps:
        return []

    # Build ordered list of (first_word_idx, beat_id) pairs
    beat_starts: list[tuple[int, int]] = []
    for beat in narrative_structure:
        word_range = beat.get("word_range", [])
        first_idx = word_range[0] if word_range else 0
        beat_id = beat.get("beat_id", len(beat_starts) + 1)
        beat_starts.append((first_idx, beat_id))

    # Sort by word index to get chronological order
    beat_starts.sort(key=lambda x: x[0])

    # Final timestamp end for trailing audio
    final_end = _ts_value(timestamps[-1], "end", 0.0)

    entries: list[BeatTimelineEntry] = []
    for pos, (first_idx, beat_id) in enumerate(beat_starts):
        safe_start = max(0, min(first_idx, len(timestamps) - 1))
        start_time = _ts_value(timestamps[safe_start], "start", 0.0)

        if pos + 1 < len(beat_starts):
            next_first = beat_starts[pos + 1][0]
            safe_next = max(0, min(next_first, len(timestamps) - 1))
            end_time = _ts_value(timestamps[safe_next], "start", final_end)
        else:
            end_time = final_end

        duration = max(_MIN_BEAT_DURATION_SEC, end_time - start_time)
        entries.append(BeatTimelineEntry(
            beat_id=beat_id,
            start_sec=start_time,
            end_sec=end_time,
            duration_sec=duration,
        ))

    return entries


def timeline_to_duration_map(
    timeline: list[BeatTimelineEntry],
) -> dict[int, float]:
    """Convert timeline to ``{beat_id: duration_sec}`` for Visual Director."""
    return {e.beat_id: e.duration_sec for e in timeline}


def timeline_to_duration_list(
    timeline: list[BeatTimelineEntry],
) -> list[float]:
    """Convert timeline to ordered ``[duration_sec, ...]`` for Composer."""
    return [e.duration_sec for e in timeline]
