"""Planned-boundary derivation (PR 13).

PLANNED boundaries reuse the canonical timeline
(:func:`clipper_agency.core.beat_timeline.build_canonical_timeline`) — the
ADR-0020 single source of truth that Visual Director, Composer, and Reviewer
all consume. This guarantees the harness measures drift against the SAME
planned layout the Composer actually rendered, rather than a re-derivation
that could diverge (the canonical builder spans each beat from its first-word
start to the NEXT beat's first-word start, extends the final beat to the last
timestamp end, and clamps durations to a 0.5s minimum).
"""

from __future__ import annotations

from clipper_agency.core.beat_timeline import build_canonical_timeline


def read_ts(ts: list[dict], idx: int, key: str) -> float:
    """Read a numeric field from a timestamp dict, clamped to bounds."""
    safe = max(0, min(idx, len(ts) - 1))
    return float(ts[safe].get(key, 0.0))


def derive_planned_boundaries(
    narrative_structure: list[dict],
    timestamps: list[dict],
) -> list[tuple[float, float]]:
    """Per-beat ``(planned_start, planned_end)`` straight from the canonical
    timeline (ADR 0020) — the layout the Composer renders against.

    Returns ``[]`` when either input is empty (``build_canonical_timeline``
    returns ``[]``).
    """
    entries = build_canonical_timeline(narrative_structure, timestamps)
    return [(entry.start_sec, entry.end_sec) for entry in entries]


def compute_transition_count(narrative_structure: list[dict]) -> int:
    """One junction per adjacent beat pair = ``len(beats) - 1`` (0 for single)."""
    return max(0, len(narrative_structure) - 1)
