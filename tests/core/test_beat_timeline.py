"""Tests for canonical beat timeline builder (ADR 0020)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from clipper_agency.config.schema import BeatTimelineEntry
from clipper_agency.core.beat_timeline import (
    MAX_BEAT_DURATION_SEC,
    UNCOVERED_TAIL_THRESHOLD_SEC,
    TimelineContractError,
    build_canonical_timeline,
    timeline_to_duration_list,
    timeline_to_duration_map,
)

# Touch the tunable constants in the import-time namespace so the ruff F401
# hook sees them as used (the test class below references them at runtime).
assert MAX_BEAT_DURATION_SEC == 12
assert UNCOVERED_TAIL_THRESHOLD_SEC == 2
assert TimelineContractError is not None

# ── Fixtures ──

TIMESTAMPS = [
    {"word": "Hello", "start": 0.0, "end": 0.4},
    {"word": "world", "start": 0.4, "end": 0.8},
    {"word": "this", "start": 0.8, "end": 1.2},
    {"word": "is", "start": 1.2, "end": 1.6},
    {"word": "news", "start": 1.6, "end": 2.0},
    {"word": "today", "start": 2.0, "end": 2.5},
    {"word": "amazing", "start": 2.5, "end": 3.0},
    {"word": "story", "start": 3.0, "end": 3.5},
    {"word": "follow", "start": 3.5, "end": 4.0},
    {"word": "now", "start": 4.0, "end": 4.5},
]

NARRATIVE = [
    {"beat_id": 1, "word_range": [0, 3], "section": "hook"},
    {"beat_id": 2, "word_range": [4, 6], "section": "body"},
    {"beat_id": 3, "word_range": [7, 9], "section": "closing"},
]


# ── build_canonical_timeline ──


class TestBuildCanonicalTimelineEmpty:
    def test_empty_narrative_returns_empty(self) -> None:
        assert build_canonical_timeline([], TIMESTAMPS) == []

    def test_empty_timestamps_returns_empty(self) -> None:
        assert build_canonical_timeline(NARRATIVE, []) == []

    def test_both_empty_returns_empty(self) -> None:
        assert build_canonical_timeline([], []) == []


class TestBuildCanonicalTimelineBasic:
    def test_returns_correct_number_of_entries(self) -> None:
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        assert len(timeline) == 3

    def test_entries_are_beat_timeline_entry(self) -> None:
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        for entry in timeline:
            assert isinstance(entry, BeatTimelineEntry)

    def test_beat_ids_preserved(self) -> None:
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        assert [e.beat_id for e in timeline] == [1, 2, 3]


class TestBuildCanonicalTimelineDurations:
    def test_beat_spans_to_next_beat_start(self) -> None:
        """Beat 1 spans word[0].start → word[4].start (next beat's first word)."""
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        beat1 = timeline[0]
        assert beat1.start_sec == 0.0
        assert beat1.end_sec == 1.6  # timestamps[4].start = 1.6
        assert beat1.duration_sec == 1.6

    def test_final_beat_extends_to_last_timestamp_end(self) -> None:
        """Last beat extends to final timestamp end (trailing audio)."""
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        beat3 = timeline[2]
        assert beat3.start_sec == 3.0  # timestamps[7].start
        assert beat3.end_sec == 4.5  # timestamps[-1].end
        assert beat3.duration_sec == 1.5

    def test_minimum_duration_enforced(self) -> None:
        """Durations are clamped to 0.5s minimum."""
        # Two beats with adjacent first-word indices (beat1 ends where beat2
        # begins → 0.4s raw span, clamped to 0.5s). Beat2's word_range covers
        # through the final word so the FIX-6 uncovered-tail check stays benign
        # (this test targets the _MIN_BEAT_DURATION_SEC clamp, not coverage).
        narrative = [
            {"beat_id": 1, "word_range": [0, 0]},
            {"beat_id": 2, "word_range": [1, 9]},
        ]
        timeline = build_canonical_timeline(narrative, TIMESTAMPS)
        # All durations should be >= 0.5
        for entry in timeline:
            assert entry.duration_sec >= 0.5


class TestBuildCanonicalTimelineWordRangeMissing:
    def test_missing_word_range_defaults_to_zero(self) -> None:
        """Beats without word_range use index 0."""
        narrative = [
            {"beat_id": 1, "section": "hook"},  # no word_range
            {"beat_id": 2, "word_range": [5, 8]},
        ]
        timeline = build_canonical_timeline(narrative, TIMESTAMPS)
        # Beat 1 starts at word[0].start = 0.0
        assert timeline[0].start_sec == 0.0

    def test_empty_word_range_defaults_to_zero(self) -> None:
        """Beats with empty word_range [] use index 0."""
        narrative = [
            {"beat_id": 1, "word_range": []},
            {"beat_id": 2, "word_range": [3, 5]},
        ]
        timeline = build_canonical_timeline(narrative, TIMESTAMPS)
        assert timeline[0].start_sec == 0.0


# ── timeline_to_duration_map ──


class TestTimelineToDurationMap:
    def test_returns_dict_keyed_by_beat_id(self) -> None:
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        dur_map = timeline_to_duration_map(timeline)
        assert isinstance(dur_map, dict)
        assert set(dur_map.keys()) == {1, 2, 3}

    def test_values_match_durations(self) -> None:
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        dur_map = timeline_to_duration_map(timeline)
        for entry in timeline:
            assert dur_map[entry.beat_id] == entry.duration_sec


# ── timeline_to_duration_list ──


class TestTimelineToDurationList:
    def test_returns_list_in_order(self) -> None:
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        dur_list = timeline_to_duration_list(timeline)
        assert isinstance(dur_list, list)
        assert len(dur_list) == 3

    def test_values_match_durations(self) -> None:
        timeline = build_canonical_timeline(NARRATIVE, TIMESTAMPS)
        dur_list = timeline_to_duration_list(timeline)
        for i, entry in enumerate(timeline):
            assert dur_list[i] == entry.duration_sec


# ── Object timestamps (getattr path) ──


class TestObjectTimestamps:
    """Timestamps as objects (SimpleNamespace) exercise the getattr branch."""

    def test_works_with_object_timestamps(self) -> None:
        obj_ts = [SimpleNamespace(**ts) for ts in TIMESTAMPS]
        timeline = build_canonical_timeline(NARRATIVE, obj_ts)
        assert len(timeline) == 3
        # Beat 1 spans words 0→4: start=0.0, next beat word 4 start=1.6
        assert timeline[0].start_sec == 0.0
        assert timeline[0].end_sec == 1.6


# ── Timeline contract (FIX-6 / ADR 0030) ──


def _timestamps_spanning(total_seconds: float, words: int) -> list[dict]:
    """Evenly-spaced word timestamps from 0..total_seconds over `words` words."""
    step = total_seconds / max(words - 1, 1)
    out: list[dict] = []
    for i in range(words):
        start = i * step
        end = start + step * 0.5
        out.append({"word": f"w{i}", "start": start, "end": end})
    # Pin the final end to exactly total_seconds (trailing audio edge).
    out[-1]["end"] = total_seconds
    return out


class TestTimelineContractError:
    """FIX-6: build_canonical_timeline raises TimelineContractError on a
    physically-impossible timeline (job_18 mega-beat backstop for G7)."""

    def test_max_beat_exceeded_raises(self) -> None:
        """job_18 replay: 3 beats whose last word_range ends at word 23 of 76,
        so the last beat is manufactured to ~25s (the trailing audio)."""
        ts = _timestamps_spanning(35.0, 76)  # final_end = 35.0
        narrative = [
            {"beat_id": 1, "word_range": [0, 10]},
            {"beat_id": 2, "word_range": [11, 17]},
            {"beat_id": 3, "word_range": [18, 23]},  # ends at word 23 of 76
        ]
        with pytest.raises(TimelineContractError) as exc_info:
            build_canonical_timeline(narrative, ts, enforce_contract=True)
        err = exc_info.value
        assert err.kind == "MAX_BEAT_EXCEEDED"
        assert err.reason == "timeline_not_covered"
        assert err.beat_id == 3  # the offending (last) beat
        # Manufactured duration is final_end(35) - last beat start; well over 12s.
        assert err.tail_seconds > MAX_BEAT_DURATION_SEC

    def test_uncovered_tail_large_raises(self) -> None:
        """A trailing gap on the last beat larger than max(2.0, nominal_span)
        raises UNCOVERED_TAIL. We construct a 3-beat timeline where the last
        beat's word_range words END well before final_end, so its manufactured
        duration (final_end - last beat start) is large but UNDER the 12s
        MAX_BEAT cap, while the gap between the last beat's INTENDED end (its
        word_range last word's timestamp end) and final_end exceeds the
        threshold.

        Builder reality: the last entry's end_sec is always final_end. So the
        UNCOVERED_TAIL helper measures the gap using the last beat's INTENDED
        end = timestamp[word_range[1]].end (where its words actually stop),
        not entries[-1].end_sec. This is the faithful interpretation of the
        design: 'final_ts_end - last beat intended end'.
        """
        # 12 words at 1.0s each, final_end pinned to 12.0.
        ts = [{"word": f"w{i}", "start": float(i), "end": float(i) + 0.5} for i in range(12)]
        ts[-1]["end"] = 12.0
        # Beat 3 word_range [4, 5]: its words end at ts[5].end = 5.5.
        # Last beat start = ts[4].start = 4.0. Manufactured duration =
        # 12.0 - 4.0 = 8.0s (< 12, so MAX_BEAT does NOT fire).
        # Intended end of last beat = ts[5].end = 5.5. Tail = 12.0 - 5.5 = 6.5s.
        # nominal_span = 12 / 3 = 4.0, threshold = max(2.0, 4.0) = 4.0.
        # 6.5 > 4.0 → UNCOVERED_TAIL fires.
        narrative = [
            {"beat_id": 1, "word_range": [0, 1]},
            {"beat_id": 2, "word_range": [2, 3]},
            {"beat_id": 3, "word_range": [4, 5]},
        ]
        with pytest.raises(TimelineContractError) as exc_info:
            build_canonical_timeline(narrative, ts, enforce_contract=True)
        err = exc_info.value
        assert err.kind == "UNCOVERED_TAIL"
        assert err.reason == "timeline_not_covered"
        assert err.beat_id == 3
        assert err.tail_seconds == pytest.approx(6.5, abs=0.01)

    def test_small_tail_logged_not_raised(self, caplog: pytest.LogCaptureFixture) -> None:
        """Last beat's manufactured stretch is within the threshold → today's
        heuristic is preserved (end_time = final_end), NO raise, one INFO line."""
        # 2 beats, beat1 [0,0] start 0.0, beat2 [3,3] start 3.0, final_end 4.5.
        # nominal_span = 4.5/2 = 2.25, threshold = max(2, 2.25) = 2.25.
        # last beat manufactured duration = 4.5 - 3.0 = 1.5s (< 12, OK).
        # tail (final_end - last.end) = 0 → within threshold → no raise.
        ts = [
            {"word": "a", "start": 0.0, "end": 0.5},
            {"word": "b", "start": 1.0, "end": 1.5},
            {"word": "c", "start": 2.0, "end": 2.5},
            {"word": "d", "start": 3.0, "end": 3.5},
            {"word": "e", "start": 4.0, "end": 4.5},
        ]
        narrative = [
            {"beat_id": 1, "word_range": [0, 0]},
            {"beat_id": 2, "word_range": [3, 3]},
        ]
        with caplog.at_level(logging.INFO, logger="clipper_agency.core.beat_timeline"):
            timeline = build_canonical_timeline(narrative, ts, enforce_contract=True)
        # Today's heuristic preserved: last entry end == final_end.
        assert timeline[-1].end_sec == 4.5
        # Benign case logged a one-line INFO summary (no raise).
        assert any("timeline" in rec.message.lower() for rec in caplog.records)

    def test_empty_input_never_raises(self) -> None:
        """The []-on-degenerate contract holds — raise NEVER fires on []."""
        assert build_canonical_timeline([], TIMESTAMPS) == []
        assert build_canonical_timeline(NARRATIVE, []) == []
        assert build_canonical_timeline([], []) == []

    def test_enforce_contract_false_skips_check(self) -> None:
        """The diagnostics path (enforce_contract=False) returns the stretched
        timeline WITHOUT raising — job_18 fixture stays safe to derive from."""
        ts = _timestamps_spanning(35.0, 76)
        narrative = [
            {"beat_id": 1, "word_range": [0, 10]},
            {"beat_id": 2, "word_range": [11, 17]},
            {"beat_id": 3, "word_range": [18, 23]},
        ]
        # Same fixture that raises under enforce_contract=True:
        timeline = build_canonical_timeline(narrative, ts, enforce_contract=False)
        assert len(timeline) == 3
        # The stretched last beat is preserved (diagnostics sees what was).
        assert timeline[-1].end_sec == 35.0

    def test_max_beat_takes_precedence_over_uncovered_tail(self) -> None:
        """A fixture violating BOTH conditions raises MAX_BEAT_EXCEEDED first
        (the more severe / unambiguous signal)."""
        ts = _timestamps_spanning(35.0, 76)
        narrative = [
            {"beat_id": 1, "word_range": [0, 10]},
            {"beat_id": 2, "word_range": [11, 17]},
            {"beat_id": 3, "word_range": [18, 23]},
        ]
        with pytest.raises(TimelineContractError) as exc_info:
            build_canonical_timeline(narrative, ts, enforce_contract=True)
        assert exc_info.value.kind == "MAX_BEAT_EXCEEDED"

    def test_single_beat_uncovered_tail_suppressed(self) -> None:
        """A single-beat timeline has nominal_span == full duration, so the
        UNCOVERED_TAIL threshold collapses to the full duration and can never
        fire — only MAX_BEAT_EXCEEDED can. Pinned because a future change to
        nominal_span math would silently flip which kind can fire (RISK-4)."""
        ts = [
            {"word": "a", "start": 0.0, "end": 0.5},
            {"word": "b", "start": 1.0, "end": 1.5},
            {"word": "c", "start": 2.0, "end": 2.5},
            {"word": "d", "start": 4.0, "end": 8.0},
        ]
        ts[-1]["end"] = 8.0
        narrative = [{"beat_id": 1, "word_range": [0, 2]}]
        # Beat duration = 8.0s (< 12 → no MAX_BEAT); tail = 8.0 - 2.5 = 5.5s but
        # threshold = max(2.0, nominal_span=8.0) = 8.0 → 5.5 <= 8.0 → no raise.
        timeline = build_canonical_timeline(narrative, ts, enforce_contract=True)
        assert len(timeline) == 1
        assert timeline[0].duration_sec == 8.0

    def test_constants_exposed(self) -> None:
        """Module exposes the tunable constants (FIX-5 / ops rely on these)."""
        assert MAX_BEAT_DURATION_SEC == 12
        assert UNCOVERED_TAIL_THRESHOLD_SEC == 2
