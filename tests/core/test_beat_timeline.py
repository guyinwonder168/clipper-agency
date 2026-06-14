"""Tests for canonical beat timeline builder (ADR 0020)."""

from __future__ import annotations

from types import SimpleNamespace

from clipper_agency.config.schema import BeatTimelineEntry
from clipper_agency.core.beat_timeline import (
    build_canonical_timeline,
    timeline_to_duration_list,
    timeline_to_duration_map,
)


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
        assert beat3.start_sec == 3.0   # timestamps[7].start
        assert beat3.end_sec == 4.5     # timestamps[-1].end
        assert beat3.duration_sec == 1.5

    def test_minimum_duration_enforced(self) -> None:
        """Durations are clamped to 0.5s minimum."""
        # Two beats with adjacent word ranges (0 duration gap)
        narrative = [
            {"beat_id": 1, "word_range": [0, 0]},
            {"beat_id": 2, "word_range": [1, 1]},
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
