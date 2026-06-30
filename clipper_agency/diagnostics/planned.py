"""Planned-boundary derivation (PR 13).

PLANNED boundaries are the cumulative sum of the canonical timeline's
RENDERED durations (``timeline_to_duration_list`` — the exact helper the
Composer consumes, ADR 0020). This matches what the Composer actually places
on the timeline, including the ``_MIN_BEAT_DURATION_SEC`` clamp: a beat whose
raw audio span is < 0.5s is still rendered at 0.5s, so the planned boundary
must use the clamped ``duration_sec``, not the raw ``(start_sec, end_sec)``
span.
"""

from __future__ import annotations

from clipper_agency.core.beat_timeline import (
    build_canonical_timeline,
    timeline_to_duration_list,
)


def read_ts(ts: list[dict], idx: int, key: str) -> float:
    """Read a numeric field from a timestamp dict, clamped to bounds."""
    safe = max(0, min(idx, len(ts) - 1))
    return float(ts[safe].get(key, 0.0))


def derive_planned_boundaries(
    narrative_structure: list[dict],
    timestamps: list[dict],
) -> list[tuple[float, float]]:
    """Per-beat ``(planned_start, planned_end)`` as the cumulative sum of the
    canonical timeline's rendered durations (ADR 0020 — what the Composer
    places on the timeline, clamp-inclusive).

    Returns ``[]`` when either input is empty (``build_canonical_timeline``
    returns ``[]``).
    """
    # enforce_contract=False: this is a read-only AV-drift diagnostic that
    # runs on already-produced (possibly job_18-style) historical timelines.
    # It must REPORT what the timeline was, never enforce a contract — raising
    # here would crash the diagnostic on the exact jobs it exists to diagnose
    # (FIX-6 / ADR 0030 RISK-2).
    durations = timeline_to_duration_list(
        build_canonical_timeline(narrative_structure, timestamps, enforce_contract=False)
    )
    out: list[tuple[float, float]] = []
    cursor = 0.0
    for duration in durations:
        out.append((cursor, cursor + duration))
        cursor += duration
    return out


def compute_transition_count(narrative_structure: list[dict]) -> int:
    """One junction per adjacent beat pair = ``len(beats) - 1`` (0 for single)."""
    return max(0, len(narrative_structure) - 1)
