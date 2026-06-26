"""Planned-boundary derivation (PR 13).

Mirrors the contract pinned by verifier 2:
  * ``word_range`` is INCLUSIVE — ``timestamps[w1]`` is the last word of the
    beat, so ``beat_word_end = timestamps[w1]['end']`` (NOT ``w1 + 1``).
  * PLANNED = pure cumulative sum of per-beat voiceover spans (no margin, no
    xfade subtraction).

Reference (verifier 2, empirically confirmed against composer.py):

    def derive_planned_boundaries(beats, timestamps):
        out=[]; cursor=0.0
        for b in beats:
            w0,w1=b['word_range']           # INCLUSIVE
            dur=timestamps[w1]['end']-timestamps[w0]['start']
            out.append((cursor, cursor+dur)); cursor+=dur
        return out
"""

from __future__ import annotations


def _ts(ts: list[dict], idx: int, key: str) -> float:
    """Read a numeric field from a timestamp dict, clamped to bounds."""
    safe = max(0, min(idx, len(ts) - 1))
    return float(ts[safe].get(key, 0.0))


def derive_planned_boundaries(
    narrative_structure: list[dict],
    timestamps: list[dict],
) -> list[tuple[float, float]]:
    """Per-beat ``(planned_start, planned_end)`` as a pure cumulative sum.

    Each beat's planned span is ``timestamps[w0].start -> timestamps[w1].end``
    where ``[w0, w1]`` is the beat's INCLUSIVE ``word_range``.
    """
    if not narrative_structure or not timestamps:
        return []

    out: list[tuple[float, float]] = []
    cursor = 0.0
    for beat in narrative_structure:
        w0, w1 = beat["word_range"]
        dur = _ts(timestamps, w1, "end") - _ts(timestamps, w0, "start")
        out.append((cursor, cursor + dur))
        cursor += dur
    return out


def compute_transition_count(narrative_structure: list[dict]) -> int:
    """One junction per adjacent beat pair = ``len(beats) - 1`` (0 for single)."""
    return max(0, len(narrative_structure) - 1)
