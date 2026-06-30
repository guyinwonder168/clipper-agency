"""Canonical beat timeline builder (ADR 0020).

Single source of truth for beat durations. Built once by the orchestrator
after Voice Producer completes. Consumed by Visual Director, Composer, and
Reviewer.

FIX-6 (ADR 0030 / SRS FR-79 / PRD PR-42): ``build_canonical_timeline`` raises
:class:`TimelineContractError` on a physically-impossible timeline instead of
silently stretching the final beat (the job_18 25.17s mega-beat maker). This
is a backstop for G7 (FIX-1): G7 validates ``word_range`` coverage on the
script dict; FIX-6 catches a non-physical beat at canonical-timeline build
time even when ``word_range`` passes.
"""

from __future__ import annotations

import logging

from clipper_agency.config.schema import BeatTimelineEntry

logger = logging.getLogger(__name__)

_MIN_BEAT_DURATION_SEC = 0.5

# FIX-6 (ADR 0030): timeline contract constants.
MAX_BEAT_DURATION_SEC = 12
"""A single manufactured beat longer than this is physically impossible for a
TikTok short (job_18 mega-beat was 25.17s). Triggers
``TimelineContractError(kind=MAX_BEAT_EXCEEDED)``."""

UNCOVERED_TAIL_THRESHOLD_SEC = 2
"""Floor of the uncovered-tail tolerance band. A trailing gap
``<= max(UNCOVERED_TAIL_THRESHOLD_SEC, one nominal beat span)`` is the SMALL
benign case = LOGGED gated extension (today's heuristic preserved, NO raise).
A gap above it triggers ``TimelineContractError(kind=UNCOVERED_TAIL)``."""

# STABLE reason token — FIX-5 (repair_router) routes automated scriptwriter
# regen on this string. Do NOT rename without updating repair_router.
_TIMELINE_NOT_COVERED = "timeline_not_covered"


class TimelineContractError(Exception):
    """Raised by :func:`build_canonical_timeline` when the manufactured timeline
    is physically impossible (FIX-6 / ADR 0030).

    Attributes:
        kind: ``"MAX_BEAT_EXCEEDED"`` (a single beat > ``MAX_BEAT_DURATION_SEC``)
            or ``"UNCOVERED_TAIL"`` (trailing gap above the tolerance band).
        tail_seconds: For ``MAX_BEAT_EXCEEDED`` = the offending beat's
            manufactured ``duration_sec``; for ``UNCOVERED_TAIL`` =
            ``final_ts_end - last beat intended end``.
        beat_id: The offending beat's ``beat_id``. For ``MAX_BEAT_EXCEEDED``
            the over-long beat; for ``UNCOVERED_TAIL`` the LAST beat whose
            intended end is below ``final_end``.
        reason: Stable token ``"timeline_not_covered"`` (FIX-5 routes on this).
    """

    def __init__(
        self,
        kind: str,
        tail_seconds: float,
        beat_id: int,
        reason: str = _TIMELINE_NOT_COVERED,
    ) -> None:
        super().__init__(
            f"timeline contract violated ({kind}): beat_id={beat_id} "
            f"tail_seconds={tail_seconds:.2f}"
        )
        self.kind = kind
        self.tail_seconds = tail_seconds
        self.beat_id = beat_id
        self.reason = reason


def _ts_value(ts: object, key: str, default: float) -> float:
    """Extract a numeric value from a timestamp dict or pydantic model."""
    if isinstance(ts, dict):
        return ts.get(key, default)
    return getattr(ts, key, default)


def _check_max_beat(entries: list[BeatTimelineEntry]) -> BeatTimelineEntry | None:
    """Return the first entry whose manufactured duration exceeds
    ``MAX_BEAT_DURATION_SEC``, else ``None``."""
    for entry in entries:
        if entry.duration_sec > MAX_BEAT_DURATION_SEC:
            return entry
    return None


def _check_uncovered_tail(
    entries: list[BeatTimelineEntry],
    final_end: float,
    last_intended_end: float,
    nominal_span: float,
) -> tuple[BeatTimelineEntry, float] | None:
    """Return ``(last_entry, tail_seconds)`` if the trailing gap between
    ``final_end`` and the last beat's INTENDED end exceeds
    ``max(UNCOVERED_TAIL_THRESHOLD_SEC, nominal_span)``, else ``None``.

    ``last_intended_end`` is where the last beat's ``word_range`` words
    actually stop in the timestamps (``timestamp[word_range[1]].end``) — i.e.
    where the beat's spoken content ends, before the manufactured stretch to
    trailing audio. The manufactured stretch is ``final_end -
    last_intended_end``. A single-beat timeline has ``nominal_span == full
    duration`` so its threshold collapses to the full duration and it can
    never trigger UNCOVERED_TAIL (only MAX_BEAT_EXCEEDED can fire for
    single-beat — documented edge case).
    """
    last = entries[-1]
    tail = final_end - last_intended_end
    threshold = max(UNCOVERED_TAIL_THRESHOLD_SEC, nominal_span)
    if tail > threshold:
        return last, tail
    return None


def build_canonical_timeline(
    narrative_structure: list[dict],
    timestamps: list[dict],
    *,
    enforce_contract: bool = True,
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
        enforce_contract: When ``True`` (default), raise
            :class:`TimelineContractError` on a physically-impossible timeline
            (FIX-6). When ``False``, skip the check — used by the read-only
            diagnostics path (:func:`clipper_agency.diagnostics.planned.derive_planned_boundaries`)
            which must never crash on a historical (possibly job_18-style)
            timeline.

    Returns:
        Ordered list of :class:`BeatTimelineEntry` keyed by ``beat_id``.
        Empty list if either input is empty.

    Raises:
        TimelineContractError: If ``enforce_contract`` is ``True`` AND the
            manufactured timeline is non-physical (a single beat >
            ``MAX_BEAT_DURATION_SEC``, or a trailing gap above the tolerance
            band). Never raised on empty input.
    """
    if not narrative_structure or not timestamps:
        return []

    # Build ordered list of (first_word_idx, last_word_idx, beat_id) pairs.
    # last_word_idx is retained for the UNCOVERED_TAIL intended-end calc.
    beat_starts: list[tuple[int, int, int]] = []
    for beat in narrative_structure:
        word_range = beat.get("word_range", [])
        first_idx = word_range[0] if word_range else 0
        last_idx = word_range[1] if len(word_range) > 1 else first_idx
        beat_id = beat.get("beat_id", len(beat_starts) + 1)
        beat_starts.append((first_idx, last_idx, beat_id))

    # Sort by word index to get chronological order.
    beat_starts.sort(key=lambda x: x[0])

    # Final timestamp end for trailing audio.
    final_end = _ts_value(timestamps[-1], "end", 0.0)

    entries: list[BeatTimelineEntry] = []
    # Last beat's INTENDED end = timestamp[word_range[1]].end (where its spoken
    # content actually stops). Captured during the loop for UNCOVERED_TAIL.
    last_intended_end = final_end
    for pos, (first_idx, last_idx, beat_id) in enumerate(beat_starts):
        safe_start = max(0, min(first_idx, len(timestamps) - 1))
        start_time = _ts_value(timestamps[safe_start], "start", 0.0)

        if pos + 1 < len(beat_starts):
            next_first = beat_starts[pos + 1][0]
            safe_next = max(0, min(next_first, len(timestamps) - 1))
            end_time = _ts_value(timestamps[safe_next], "start", final_end)
        else:
            end_time = final_end
            # FIX-6: capture the last beat's intended end (its last word's
            # timestamp end) for the UNCOVERED_TAIL check.
            safe_last = max(0, min(last_idx, len(timestamps) - 1))
            last_intended_end = _ts_value(timestamps[safe_last], "end", final_end)

        duration = max(_MIN_BEAT_DURATION_SEC, end_time - start_time)
        entries.append(
            BeatTimelineEntry(
                beat_id=beat_id,
                start_sec=start_time,
                end_sec=end_time,
                duration_sec=duration,
            )
        )

    if enforce_contract and entries:
        _enforce_physical_contract(entries, final_end, last_intended_end)

    return entries


def _enforce_physical_contract(
    entries: list[BeatTimelineEntry], final_end: float, last_intended_end: float
) -> None:
    """Run the FIX-6 physical-possibility checks and raise on violation.

    MAX_BEAT_EXCEEDED is checked FIRST (more severe / unambiguous), then
    UNCOVERED_TAIL. A SMALL tail (within threshold) is a benign logged
    extension — today's stretch heuristic is preserved (no raise).
    """
    nominal_span = (final_end - entries[0].start_sec) / len(entries)
    over = _check_max_beat(entries)
    if over is not None:
        raise TimelineContractError(
            kind="MAX_BEAT_EXCEEDED",
            tail_seconds=over.duration_sec,
            beat_id=over.beat_id,
        )
    tail = _check_uncovered_tail(entries, final_end, last_intended_end, nominal_span)
    if tail is not None:
        last_entry, tail_seconds = tail
        raise TimelineContractError(
            kind="UNCOVERED_TAIL",
            tail_seconds=tail_seconds,
            beat_id=last_entry.beat_id,
        )
    # SMALL benign tail: today's heuristic (end_time = final_end) is preserved.
    logger.info(
        "timeline contract ok: %d beats, %.2fs span (last beat stretched to "
        "trailing audio within tolerance)",
        len(entries),
        final_end,
    )


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
