"""Assemble the AV-drift table rows (PR 13).

Combines planned boundaries (pure cumulative), measured achieved boundaries
(ffprobe blackdetect), and caption windows into one ``DriftRow`` per beat.
``offset_ms_predicted_margin`` follows the PR-13 Q4 hypothesis
(``beat_index * _SAFETY_MARGIN``) so the achieved column can be tested
against the deterministic ``N * 0.1s`` upper bound.
"""

from __future__ import annotations

from clipper_agency.diagnostics.models import DriftRow, JobSignals
from clipper_agency.diagnostics.planned import _ts

# Upper-bound _SAFETY_MARGIN drift per xfade transition (ms). The PR-13 Q4
# hypothesis tests whether measured achieved drift approaches N * 100ms.
_PREDICTED_MARGIN_PER_TRANSITION_MS = 100.0


def build_drift_table(
    signals: JobSignals,
    achieved: list[tuple[float, float | None] | None],
    caption_windows: dict[int, tuple[float, float]],
    planned: list[tuple[float, float]],
) -> list[DriftRow]:
    """Build one ``DriftRow`` per beat.

    ``achieved`` is a list (possibly with ``None`` entries) of measured
    ``(start, end)`` tuples whose ``end`` may itself be ``None``;
    ``caption_windows`` maps ``beat_id -> (start, end)``; ``planned`` is the
    per-beat ``(planned_start, planned_end)`` list.
    """
    rows: list[DriftRow] = []
    beats = signals.narrative_structure
    for i, beat in enumerate(beats):
        beat_id = beat.get("beat_id", i + 1)
        section = str(beat.get("section", ""))
        w0, w1 = beat.get("word_range", [0, 0])
        beat_word_start = _ts(signals.timestamps, w0, "start")
        beat_word_end = _ts(signals.timestamps, w1, "end")

        planned_start, planned_end = planned[i]

        ach = achieved[i] if i < len(achieved) else None
        ach_start = ach[0] if ach else None
        ach_end = ach[1] if ach else None

        cap = caption_windows.get(beat_id)
        cap_start = cap[0] if cap else None
        cap_end = cap[1] if cap else None

        offset_planned = (planned_start - beat_word_start) * 1000.0
        offset_achieved = (ach_start - beat_word_start) * 1000.0 if ach_start is not None else None
        offset_predicted_margin = i * _PREDICTED_MARGIN_PER_TRANSITION_MS

        rows.append(
            DriftRow(
                beat_id=beat_id,
                section=section,
                beat_word_start=beat_word_start,
                beat_word_end=beat_word_end,
                scene_planned_start=planned_start,
                scene_planned_end=planned_end,
                scene_achieved_start=ach_start,
                scene_achieved_end=ach_end,
                caption_window_start=cap_start,
                caption_window_end=cap_end,
                offset_ms_planned=offset_planned,
                offset_ms_achieved=offset_achieved,
                offset_ms_predicted_margin=offset_predicted_margin,
            )
        )
    return rows
