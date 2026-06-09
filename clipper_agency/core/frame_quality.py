"""Frame quality helpers for detecting empty or uniform sampled frames."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


DEFAULT_UNIFORM_VARIANCE_THRESHOLD = 1.0


def compute_frame_variance(image: object) -> float:
    """Return pixel-value variance for an OpenCV-compatible image array.

    The implementation deliberately avoids importing NumPy so tests and callers
    without OpenCV/NumPy installed can still use plain nested pixel sequences.
    """
    values = tuple(_flatten_numeric_values(image))
    if not values:
        return 0.0

    mean = sum(values) / len(values)
    squared_diffs = ((value - mean) ** 2 for value in values)
    return sum(squared_diffs) / len(values)


def is_empty_or_uniform_frame(image: object, threshold: float) -> bool:
    """Return True when frame variance is at or below the uniform threshold."""
    return compute_frame_variance(image) <= threshold


def detect_empty_segments(
    sampled_frames: Sequence[tuple[float, object]],
    max_gap_sec: float,
) -> list[tuple[float, float]]:
    """Merge nearby empty sampled frames into timestamp intervals."""
    intervals: list[tuple[float, float]] = []
    current_start: float | None = None
    current_end: float | None = None

    for timestamp, image in sorted(sampled_frames, key=lambda frame: frame[0]):
        if not is_empty_or_uniform_frame(image, DEFAULT_UNIFORM_VARIANCE_THRESHOLD):
            if current_start is not None and current_end is not None:
                intervals.append((current_start, current_end))
                current_start = None
                current_end = None
            continue

        if current_start is None or current_end is None:
            current_start = timestamp
            current_end = timestamp
            continue

        if timestamp - current_end <= max_gap_sec:
            current_end = timestamp
        else:
            intervals.append((current_start, current_end))
            current_start = timestamp
            current_end = timestamp

    if current_start is not None and current_end is not None:
        intervals.append((current_start, current_end))

    return intervals


def _flatten_numeric_values(value: object) -> Iterable[float]:
    """Yield numeric scalar values from nested arrays without NumPy imports."""
    if isinstance(value, (str, bytes)):
        return

    try:
        iterator = iter(value)  # type: ignore[arg-type]
    except TypeError:
        yield float(value)  # type: ignore[arg-type]
        return

    for item in iterator:
        yield from _flatten_numeric_values(item)
