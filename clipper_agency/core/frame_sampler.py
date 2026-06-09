"""Frame sampling and deduplication helpers — pure functions, no I/O."""

from __future__ import annotations


def plan_frame_samples(
    duration_sec: float,
    scene_boundaries: list[float],
    interval_sec: float = 0.5,
) -> list[float]:
    """Plan frame sample timestamps by merging regular intervals with scene boundaries.

    Always includes 0.0 and duration_sec. Timestamps are sorted and deduplicated.
    For zero duration, returns [0.0].
    """
    if duration_sec <= 0:
        return [0.0]

    timestamps: set[float] = {0.0, duration_sec}

    # Regular interval timestamps
    t = interval_sec
    while t < duration_sec:
        timestamps.add(t)
        t += interval_sec

    # Scene boundary timestamps
    timestamps.update(scene_boundaries)

    return sorted(timestamps)


def deduplicate_samples_by_hash(
    samples: list[tuple[float, str]],
) -> list[tuple[float, str]]:
    """Remove consecutive samples with the same hash, keeping the first occurrence."""
    if not samples:
        return []

    result: list[tuple[float, str]] = [samples[0]]
    for ts, h in samples[1:]:
        if h != result[-1][1]:
            result.append((ts, h))
    return result
