"""Planned + predicted-achieved boundary derivation (PR 13).

Mirrors the contract pinned by verifier 2:
  * ``word_range`` is INCLUSIVE — ``timestamps[w1]`` is the last word of the
    beat, so ``beat_word_end = timestamps[w1]['end']`` (NOT ``w1 + 1``).
  * PLANNED = pure cumulative sum of per-beat voiceover spans (no margin, no
    xfade subtraction).
  * PREDICTED ACHIEVED mirrors ``clipper_agency/agents/composer.py`` L297-328
    xfade accumulator: ``cumulative_duration`` starts at ``durs[0]``; for each
    ``i >= 1`` compute ``offset = max(0.0, cum - trans_duration - margin)``
    BEFORE updating ``cum``, then ``cum += durs[i] - trans_duration``.

Reference (verifier 2, empirically confirmed against composer.py):

    def derive_planned_boundaries(beats, timestamps):
        out=[]; cursor=0.0
        for b in beats:
            w0,w1=b['word_range']           # INCLUSIVE
            dur=timestamps[w1]['end']-timestamps[w0]['start']
            out.append((cursor, cursor+dur)); cursor+=dur
        return out

    def predicted_achieved_boundaries(beats, timestamps, trans=0.5, margin=0.1):
        durs=[timestamps[b['word_range'][1]]['end']
              - timestamps[b['word_range'][0]]['start'] for b in beats]
        achieved=[0.0]; cum=float(durs[0])
        for i in range(1,len(beats)):
            achieved.append(max(0.0, cum-trans-margin))
            cum += durs[i]-trans            # mirror composer.py L328
        return achieved
"""

from __future__ import annotations

# Composer defaults (clipper_agency/agents/composer.py L57 = _SAFETY_MARGIN).
TRANSITION_DURATION_DEFAULT = 0.5
SAFETY_MARGIN = 0.1


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


def predicted_achieved_boundaries(
    planned: list[tuple[float, float]],
    transition_duration_sec: float = TRANSITION_DURATION_DEFAULT,
    safety_margin: float = SAFETY_MARGIN,
) -> list[float]:
    """Per-beat predicted achieved start, mirroring composer.py's xfade
    accumulator.

    The accumulator starts at ``durs[0]``; for each ``i >= 1`` it emits
    ``max(0.0, cum - trans_duration - margin)`` then advances
    ``cum += durs[i] - trans_duration``.
    """
    if not planned:
        return []
    durs = [end - start for start, end in planned]
    achieved = [0.0]
    cum = float(durs[0])
    for i in range(1, len(durs)):
        achieved.append(max(0.0, cum - transition_duration_sec - safety_margin))
        cum += durs[i] - transition_duration_sec
    return achieved


def compute_transition_count(narrative_structure: list[dict]) -> int:
    """One junction per adjacent beat pair = ``len(beats) - 1`` (0 for single)."""
    return max(0, len(narrative_structure) - 1)
