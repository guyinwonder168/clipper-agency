"""Frozen dataclasses for the AV-drift diagnosis harness (PR 13).

All models are immutable (``frozen=True``) per repo rule. These are the
contracts the harness emits; no pipeline state machine reads them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JobSignals:
    """All read-only signals loaded for a single job under diagnosis.

    ``narrative_structure`` and ``timestamps`` are the raw persisted dicts
    (untouched). ``hook_duration_sec`` is the duration of the first beat
    (the hook section) — a convenience used by caption derivation.
    """

    job_id: int
    narrative_structure: list[dict]
    timestamps: list[dict]
    video_path: str
    provider: str
    voiceover_duration_sec: float
    hook_duration_sec: float


@dataclass(frozen=True)
class DriftRow:
    """One row of the AV-drift table, comparing planned vs achieved timing."""

    beat_id: int
    section: str
    beat_word_start: float
    beat_word_end: float
    scene_planned_start: float
    scene_planned_end: float
    scene_achieved_start: float | None
    scene_achieved_end: float | None
    caption_window_start: float | None
    caption_window_end: float | None
    offset_ms_planned: float
    offset_ms_achieved: float | None
    offset_ms_predicted_margin: float


@dataclass(frozen=True)
class DriftReport:
    """Aggregate AV-drift report emitted by the harness for one job."""

    job_id: int
    provider: str
    video_duration_sec: float | None
    voiceover_duration_sec: float
    transition_count: int
    rows: list[DriftRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
