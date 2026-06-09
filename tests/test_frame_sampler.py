"""Tests for core.frame_sampler — frame sampling and deduplication."""

from clipper_agency.core.frame_sampler import (
    deduplicate_samples_by_hash,
    plan_frame_samples,
)


class TestPlanFrameSamples:
    """Tests for plan_frame_samples()."""

    def test_merge_intervals_with_scene_boundaries(self):
        """Intervals and scene boundaries merge, sorted, deduplicated."""
        samples = plan_frame_samples(
            duration_sec=2.0,
            scene_boundaries=[0.0, 1.25],
            interval_sec=0.5,
        )
        assert samples == [0.0, 0.5, 1.0, 1.25, 1.5, 2.0]

    def test_empty_duration_returns_start_only(self):
        """Zero-length clip produces just the start timestamp."""
        samples = plan_frame_samples(
            duration_sec=0.0,
            scene_boundaries=[],
            interval_sec=0.5,
        )
        assert samples == [0.0]

    def test_no_scene_boundaries_regular_intervals(self):
        """Without scene boundaries only regular interval timestamps appear."""
        samples = plan_frame_samples(
            duration_sec=1.5,
            scene_boundaries=[],
            interval_sec=0.5,
        )
        assert samples == [0.0, 0.5, 1.0, 1.5]

    def test_includes_zero_and_duration(self):
        """Start (0.0) and end (duration_sec) are always present."""
        samples = plan_frame_samples(
            duration_sec=3.0,
            scene_boundaries=[1.0, 2.0],
            interval_sec=1.0,
        )
        assert samples[0] == 0.0
        assert samples[-1] == 3.0

    def test_deduplicates_close_timestamps(self):
        """Duplicate timestamps from merged sets are removed."""
        samples = plan_frame_samples(
            duration_sec=2.0,
            scene_boundaries=[1.0],
            interval_sec=1.0,
        )
        # 1.0 appears in both intervals and boundaries — must not duplicate
        assert samples == [0.0, 1.0, 2.0]

    def test_single_interval(self):
        """Duration shorter than interval still yields start and end."""
        samples = plan_frame_samples(
            duration_sec=0.3,
            scene_boundaries=[],
            interval_sec=0.5,
        )
        assert samples == [0.0, 0.3]


class TestDeduplicateSamplesByHash:
    """Tests for deduplicate_samples_by_hash()."""

    def test_removes_repeated_hashes(self):
        """Consecutive samples with the same hash keep only the first."""
        samples = [(0.0, "aaa"), (0.5, "aaa"), (1.0, "bbb")]
        assert deduplicate_samples_by_hash(samples) == [
            (0.0, "aaa"),
            (1.0, "bbb"),
        ]

    def test_empty_list_returns_empty(self):
        """No samples → no output."""
        assert deduplicate_samples_by_hash([]) == []

    def test_all_unique_returns_same(self):
        """All unique hashes → list unchanged."""
        samples = [(0.0, "a"), (0.5, "b"), (1.0, "c")]
        assert deduplicate_samples_by_hash(samples) == samples

    def test_all_same_hash_keeps_first(self):
        """All identical hashes collapse to a single entry."""
        samples = [(0.0, "x"), (0.5, "x"), (1.0, "x")]
        assert deduplicate_samples_by_hash(samples) == [(0.0, "x")]

    def test_single_element(self):
        """Single-element list passes through unchanged."""
        samples = [(1.5, "abc")]
        assert deduplicate_samples_by_hash(samples) == samples
