"""Hermetic unit tests for planned-boundary derivation (PR 13).

Synthetic fixtures only — no real ffmpeg, no network. AAA pattern.
"""

from __future__ import annotations

import pytest

from clipper_agency.diagnostics.planned import (
    compute_transition_count,
    derive_planned_boundaries,
)

# ---------------------------------------------------------------------------
# Synthetic fixtures — word_range is INCLUSIVE; durations are clean integers.
# ---------------------------------------------------------------------------


@pytest.fixture
def beats_three() -> list[dict]:
    """Three beats with inclusive word_ranges covering 6 words."""
    return [
        {"beat_id": 1, "word_range": [0, 1]},
        {"beat_id": 2, "word_range": [2, 3]},
        {"beat_id": 3, "word_range": [4, 5]},
    ]


@pytest.fixture
def timestamps_six() -> list[dict]:
    """Six words: each is 2s long, contiguous (end == next start)."""
    return [
        {"word": "a", "start": 0.0, "end": 2.0},
        {"word": "b", "start": 2.0, "end": 4.0},
        {"word": "c", "start": 4.0, "end": 6.0},
        {"word": "d", "start": 6.0, "end": 8.0},
        {"word": "e", "start": 8.0, "end": 10.0},
        {"word": "f", "start": 10.0, "end": 12.0},
    ]


# ---------------------------------------------------------------------------
# derive_planned_boundaries
# ---------------------------------------------------------------------------


def test_derive_planned_boundaries_returns_cumulative_durations(
    beats_three: list[dict], timestamps_six: list[dict]
) -> None:
    """PLANNED = pure cumulative sum of per-beat voiceover spans."""
    # Arrange — beat1 = words[0..1] = 0.0..4.0 = 4s; beat2 = 4.0..8.0 = 4s;
    #           beat3 = 8.0..12.0 = 4s.
    # Act
    planned = derive_planned_boundaries(beats_three, timestamps_six)
    # Assert
    assert planned == [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0)]


def test_derive_planned_boundaries_handles_uneven_beats() -> None:
    """Word durations vary; planned sums the actual spans, not word counts."""
    # Arrange
    beats = [{"beat_id": 1, "word_range": [0, 0]}, {"beat_id": 2, "word_range": [1, 2]}]
    timestamps = [
        {"word": "x", "start": 0.0, "end": 1.5},
        {"word": "y", "start": 1.5, "end": 2.0},
        {"word": "z", "start": 2.0, "end": 5.0},
    ]
    # Act — beat1 = 0.0..1.5 (1.5s); beat2 = 1.5..5.0 (3.5s).
    planned = derive_planned_boundaries(beats, timestamps)
    # Assert
    assert planned == [(0.0, 1.5), (1.5, 5.0)]


def test_derive_planned_boundaries_empty_returns_empty() -> None:
    # Arrange / Act
    planned = derive_planned_boundaries([], [])
    # Assert
    assert planned == []


def test_derive_planned_boundaries_final_beat_absorbs_trailing_audio() -> None:
    """The canonical timeline extends the final beat to the last timestamp end
    (ADR 0020) — so PLANNED matches the layout the Composer renders, including
    trailing audio beyond the last beat's own word_range."""
    # Arrange — one beat covering only word 0, but timestamps run to 10s.
    beats = [{"beat_id": 1, "word_range": [0, 0]}]
    timestamps = [
        {"word": "a", "start": 0.0, "end": 1.0},
        {"word": "b", "start": 1.0, "end": 2.0},
        {"word": "c", "start": 2.0, "end": 10.0},
    ]
    # Act
    planned = derive_planned_boundaries(beats, timestamps)
    # Assert — beat 1 spans 0.0 -> final timestamp end (10.0), NOT 0.0 -> 1.0.
    assert planned == [(0.0, 10.0)]


# ---------------------------------------------------------------------------
# compute_transition_count
# ---------------------------------------------------------------------------


def test_compute_transition_count_is_beats_minus_one(
    beats_three: list[dict],
) -> None:
    # Arrange / Act
    count = compute_transition_count(beats_three)
    # Assert
    assert count == 2


def test_compute_transition_count_single_beat_is_zero() -> None:
    # Arrange
    beats = [{"beat_id": 1, "word_range": [0, 0]}]
    # Act
    count = compute_transition_count(beats)
    # Assert
    assert count == 0


def test_compute_transition_count_empty_is_zero() -> None:
    # Arrange / Act / Assert
    assert compute_transition_count([]) == 0
