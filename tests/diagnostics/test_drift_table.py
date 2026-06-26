"""Hermetic unit tests for DriftRow table assembly (PR 13).

Synthetic fixtures only — no real ffmpeg, no network. AAA pattern.
"""

from __future__ import annotations

import pytest

from clipper_agency.diagnostics.drift_table import build_drift_table
from clipper_agency.diagnostics.models import DriftRow, JobSignals


def _signals(beats: list[dict], timestamps: list[dict]) -> JobSignals:
    return JobSignals(
        job_id=1,
        narrative_structure=beats,
        timestamps=timestamps,
        video_path="/tmp/video.mp4",
        provider="gemini_tts",
        voiceover_duration_sec=12.0,
        hook_duration_sec=4.0,
    )


def test_build_drift_table_assembles_all_columns() -> None:
    """Each DriftRow carries planned, achieved, caption, and offset fields."""
    # Arrange — two beats; planned, achieved, caption windows given.
    beats = [
        {"beat_id": 1, "section": "hook", "word_range": [0, 1]},
        {"beat_id": 2, "section": "story", "word_range": [2, 3]},
    ]
    timestamps = [
        {"word": "a", "start": 0.0, "end": 2.0},
        {"word": "b", "start": 2.0, "end": 4.0},
        {"word": "c", "start": 4.0, "end": 6.0},
        {"word": "d", "start": 6.0, "end": 8.0},
    ]
    signals = _signals(beats, timestamps)
    planned = [(0.0, 4.0), (4.0, 8.0)]
    achieved = [(0.0, 4.0), (3.5, 8.0)]
    caption_windows = {1: (0.0, 4.0), 2: (4.0, 8.0)}
    # Act
    rows = build_drift_table(signals, achieved, caption_windows, planned)
    # Assert
    assert len(rows) == 2
    r1 = rows[0]
    assert r1.beat_id == 1
    assert r1.section == "hook"
    assert r1.beat_word_start == 0.0
    assert r1.beat_word_end == 4.0
    assert r1.scene_planned_start == 0.0
    assert r1.scene_planned_end == 4.0
    assert r1.scene_achieved_start == 0.0
    assert r1.scene_achieved_end == 4.0
    assert r1.caption_window_start == 0.0
    assert r1.caption_window_end == 4.0
    assert r1.offset_ms_planned == 0.0
    assert r1.offset_ms_achieved == 0.0  # achieved_start - beat_word_start


def test_build_drift_table_offset_ms_achieved_is_signed() -> None:
    """offset_ms_achieved = (achieved_start - beat_word_start) * 1000."""
    # Arrange
    beats = [{"beat_id": 2, "section": "story", "word_range": [0, 0]}]
    timestamps = [{"word": "x", "start": 4.0, "end": 8.0}]
    signals = _signals(beats, timestamps)
    planned = [(4.0, 8.0)]
    achieved = [(3.5, None)]
    caption_windows = {2: (4.0, 8.0)}
    # Act
    rows = build_drift_table(signals, achieved, caption_windows, planned)
    # Assert — achieved_start 3.5 minus beat_word_start 4.0 = -0.5s = -500ms.
    assert rows[0].offset_ms_achieved == pytest.approx(-500.0)


def test_build_drift_table_predicted_margin_is_index_times_100() -> None:
    """offset_ms_predicted_margin = beat_index * 100 (xfade-transition-index)."""
    # Arrange — three beats; expected margins [0, 100, 200] ms.
    beats = [
        {"beat_id": 1, "section": "hook", "word_range": [0, 0]},
        {"beat_id": 2, "section": "s1", "word_range": [1, 1]},
        {"beat_id": 3, "section": "s2", "word_range": [2, 2]},
    ]
    timestamps = [
        {"word": "a", "start": 0.0, "end": 4.0},
        {"word": "b", "start": 4.0, "end": 8.0},
        {"word": "c", "start": 8.0, "end": 12.0},
    ]
    signals = _signals(beats, timestamps)
    planned = [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0)]
    achieved = [None] * 3
    caption_windows = {1: (0.0, 4.0), 2: (4.0, 8.0), 3: (8.0, 12.0)}
    # Act
    rows = build_drift_table(signals, achieved, caption_windows, planned)
    # Assert
    assert [r.offset_ms_predicted_margin for r in rows] == [0.0, 100.0, 200.0]
    assert all(r.offset_ms_achieved is None for r in rows)
    assert all(r.scene_achieved_start is None for r in rows)


def test_build_drift_table_returns_driftrow_type() -> None:
    # Arrange
    beats = [{"beat_id": 1, "section": "hook", "word_range": [0, 0]}]
    timestamps = [{"word": "a", "start": 0.0, "end": 1.0}]
    signals = _signals(beats, timestamps)
    # Act
    rows = build_drift_table(signals, [None], {}, [(0.0, 1.0)])
    # Assert
    assert isinstance(rows[0], DriftRow)
    assert rows[0].caption_window_start is None  # no caption window for beat 1
