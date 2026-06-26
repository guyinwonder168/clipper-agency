"""Hermetic unit tests for report rendering (PR 13).

No real ffmpeg, no network. AAA pattern.
"""

from __future__ import annotations

import json

from clipper_agency.diagnostics.models import DriftReport, DriftRow
from clipper_agency.diagnostics.report import render_json, render_markdown


def _sample_report() -> DriftReport:
    rows = [
        DriftRow(
            beat_id=1,
            section="hook",
            beat_word_start=0.0,
            beat_word_end=6.734,
            scene_planned_start=0.0,
            scene_planned_end=6.734,
            scene_achieved_start=0.0,
            scene_achieved_end=6.0,
            caption_window_start=0.0,
            caption_window_end=6.734,
            offset_ms_planned=0.0,
            offset_ms_achieved=0.0,
            offset_ms_predicted_margin=0.0,
        ),
        DriftRow(
            beat_id=2,
            section="story_1",
            beat_word_start=6.734,
            beat_word_end=10.943,
            scene_planned_start=6.734,
            scene_planned_end=10.943,
            scene_achieved_start=7.6,
            scene_achieved_end=None,
            caption_window_start=6.734,
            caption_window_end=10.943,
            offset_ms_planned=0.0,
            offset_ms_achieved=866.0,
            offset_ms_predicted_margin=100.0,
        ),
    ]
    return DriftReport(
        job_id=8,
        provider="gemini_tts",
        video_duration_sec=30.55,
        voiceover_duration_sec=34.09,
        transition_count=7,
        rows=rows,
        notes=["manifest not persisted; PLANNED derived from narrative_structure+timestamps"],
    )


def test_render_markdown_includes_table_header_and_columns() -> None:
    # Arrange
    report = _sample_report()
    # Act
    md = render_markdown(report)
    # Assert
    assert "# AV-Drift Diagnosis" in md
    for col in (
        "beat_id",
        "beat_word_start",
        "beat_word_end",
        "scene_planned_start",
        "scene_planned_end",
        "scene_achieved_start",
        "scene_achieved_end",
        "caption_window_start",
        "caption_window_end",
        "offset_ms_planned",
        "offset_ms_achieved",
    ):
        assert col in md


def test_render_markdown_includes_transition_count_and_notes() -> None:
    # Arrange
    report = _sample_report()
    # Act
    md = render_markdown(report)
    # Assert
    assert "transition_count" in md
    assert "7" in md
    assert "PLANNED derived" in md  # a note surfaced


def test_render_markdown_shows_dash_for_none_values() -> None:
    # Arrange — beat2 achieved_end is None.
    report = _sample_report()
    # Act
    md = render_markdown(report)
    # Assert — the markdown table is present and beat 2 row is rendered.
    assert "story_1" in md
    assert "10.943" in md


def test_render_json_roundtrips_to_dict() -> None:
    # Arrange
    report = _sample_report()
    # Act
    payload = json.loads(render_json(report))
    # Assert
    assert payload["job_id"] == 8
    assert payload["provider"] == "gemini_tts"
    assert payload["transition_count"] == 7
    assert payload["video_duration_sec"] == 30.55
    assert len(payload["rows"]) == 2
    assert payload["rows"][0]["beat_id"] == 1
    assert payload["rows"][1]["scene_achieved_end"] is None
    assert payload["rows"][1]["offset_ms_achieved"] == 866.0
    assert "PLANNED derived" in payload["notes"][0]


def test_render_json_handles_none_video_duration() -> None:
    # Arrange — video duration unknown (ffprobe failed).
    report = DriftReport(
        job_id=1,
        provider="unknown",
        video_duration_sec=None,
        voiceover_duration_sec=0.0,
        transition_count=0,
        rows=[],
        notes=[],
    )
    # Act
    payload = json.loads(render_json(report))
    # Assert
    assert payload["video_duration_sec"] is None
