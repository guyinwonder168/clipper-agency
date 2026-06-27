"""Hermetic unit tests for per-beat caption-window derivation (PR 13).

Synthetic fixtures only — no real ffmpeg, no network. AAA pattern.
"""

from __future__ import annotations

from clipper_agency.diagnostics.captions import derive_caption_windows


def test_derive_caption_windows_returns_per_beat_window() -> None:
    """Each beat maps to (first_word.start, last_word.end) of its word_range."""
    # Arrange — two beats; beat1 = words[0..1], beat2 = words[2..3].
    beats = [
        {"beat_id": 1, "section": "hook", "word_range": [0, 1]},
        {"beat_id": 2, "section": "story", "word_range": [2, 3]},
    ]
    timestamps = [
        {"word": "a", "start": 0.0, "end": 1.0},
        {"word": "b", "start": 1.0, "end": 2.5},
        {"word": "c", "start": 2.5, "end": 3.5},
        {"word": "d", "start": 3.5, "end": 5.0},
    ]
    # Act
    windows = derive_caption_windows(beats, timestamps)
    # Assert — beat1 caption window spans its own first..last word.
    assert windows == {1: (0.0, 2.5), 2: (2.5, 5.0)}


def test_derive_caption_windows_single_beat() -> None:
    # Arrange
    beats = [{"beat_id": 1, "section": "hook", "word_range": [0, 2]}]
    timestamps = [
        {"word": "a", "start": 0.0, "end": 1.0},
        {"word": "b", "start": 1.0, "end": 2.0},
        {"word": "c", "start": 2.0, "end": 3.0},
    ]
    # Act
    windows = derive_caption_windows(beats, timestamps)
    # Assert
    assert windows == {1: (0.0, 3.0)}


def test_derive_caption_windows_empty_inputs() -> None:
    # Arrange / Act / Assert
    assert derive_caption_windows([], []) == {}


def test_derive_caption_windows_uses_inclusive_end_word() -> None:
    """word_range is INCLUSIVE — end index is the LAST word, not past it."""
    # Arrange — beat covers words[0..0] (single word).
    beats = [{"beat_id": 7, "section": "reaction", "word_range": [0, 0]}]
    timestamps = [
        {"word": "only", "start": 1.0, "end": 1.5},
        {"word": "unused", "start": 1.5, "end": 2.0},
    ]
    # Act
    windows = derive_caption_windows(beats, timestamps)
    # Assert — end is timestamps[0].end (1.5), NOT timestamps[1].end (2.0).
    assert windows == {7: (1.0, 1.5)}
