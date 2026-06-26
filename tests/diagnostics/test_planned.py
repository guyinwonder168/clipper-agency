"""Hermetic unit tests for planned-boundary derivation (PR 13).

Synthetic fixtures only — no real ffmpeg, no network. AAA pattern.
"""

from __future__ import annotations

import pytest

from clipper_agency.diagnostics.planned import (
    SAFETY_MARGIN,
    TRANSITION_DURATION_DEFAULT,
    compute_transition_count,
    derive_planned_boundaries,
    predicted_achieved_boundaries,
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


# ---------------------------------------------------------------------------
# predicted_achieved_boundaries — mirrors composer.py xfade accumulator.
# ---------------------------------------------------------------------------


def test_predicted_achieved_boundaries_mirrors_xfade_accumulator() -> None:
    """Predicted achieved start for beat i = cum - trans_duration - margin.

    durs = [4, 4, 4]; cum starts 4.
      beat2 = max(0, 4 - 0.5 - 0.1) = 3.4; cum = 4 + 4 - 0.5 = 7.5
      beat3 = max(0, 7.5 - 0.5 - 0.1) = 6.9; cum = 7.5 + 4 - 0.5 = 11.0
    """
    # Arrange — three planned beats of 4s each.
    planned = [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0)]
    # Act
    achieved = predicted_achieved_boundaries(
        planned, transition_duration_sec=0.5, safety_margin=0.1
    )
    # Assert
    assert achieved == pytest.approx([0.0, 3.4, 6.9])


def test_predicted_achieved_boundaries_never_negative() -> None:
    """The max(0.0, ...) clamp keeps the first predicted start at 0.0 and
    prevents negative offsets when a beat is shorter than the margin."""
    # Arrange — beat1 is 0.2s long, so cum starts 0.2 and beat2 prediction
    # would be negative without the clamp.
    planned = [(0.0, 0.2), (0.2, 0.6)]
    # Act
    achieved = predicted_achieved_boundaries(planned, transition_duration_sec=0.5)
    # Assert
    assert achieved[0] == 0.0
    assert achieved[1] == 0.0  # clamped, would be 0.2 - 0.5 - 0.1 = -0.4


def test_predicted_achieved_boundaries_respects_trans_duration_override() -> None:
    """Drift is linear in trans_duration — smaller trans ⇒ larger achieved."""
    # Arrange — three planned beats of 4s each.
    planned = [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0)]
    # Act
    achieved_03 = predicted_achieved_boundaries(planned, transition_duration_sec=0.3)
    achieved_07 = predicted_achieved_boundaries(planned, transition_duration_sec=0.7)
    # Assert — larger trans_duration pulls achieved starts earlier.
    assert achieved_07[1] < achieved_03[1]
    assert achieved_07[2] < achieved_03[2]


def test_predicted_achieved_boundaries_default_constants() -> None:
    """Module constants are the composer defaults (0.5 / 0.1)."""
    # Arrange / Act / Assert
    assert TRANSITION_DURATION_DEFAULT == 0.5
    assert SAFETY_MARGIN == 0.1


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
