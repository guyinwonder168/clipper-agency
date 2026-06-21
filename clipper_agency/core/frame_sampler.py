"""Frame sampling and deduplication helpers — pure functions, no I/O."""

from __future__ import annotations


def plan_frame_samples(
    duration_sec: float,
    scene_boundaries: list[float],
    interval_sec: float = 0.5,
    max_offset_sec: float | None = None,
) -> list[float]:
    """Plan frame sample timestamps by merging regular intervals with scene boundaries.

    Always includes 0.0 and duration_sec. Timestamps are sorted and deduplicated.
    For zero duration, returns [0.0].

    When *max_offset_sec* is provided, it is an absolute safety upper bound on
    every emitted offset: every offset (including the trailing ``duration_sec``
    and any scene boundary) is clamped to ``[0.0, max_offset_sec]``. This guards
    against a bogus/stale probed ``duration_sec`` (e.g. ffprobe reporting a
    container duration of hundreds of seconds for a short clip) producing
    offsets far beyond the actually-playable media. Offsets above the bound are
    dropped; the bound itself is added as the final offset when at least one
    offset remains.
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

    result = sorted(timestamps)

    # RC-7: clamp every offset to the actual source media bound so a stale/huge
    # probed duration can never push extraction offsets beyond the clip.
    if max_offset_sec is not None and max_offset_sec >= 0:
        clamped = [o for o in result if o <= max_offset_sec]
        if not clamped:
            return [0.0]
        if clamped[-1] < max_offset_sec:
            clamped.append(max_offset_sec)
        return sorted(set(clamped))

    return result


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
