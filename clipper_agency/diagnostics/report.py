"""Render the AV-drift report as Markdown and JSON (PR 13).

Both renderers are pure functions over a frozen :class:`DriftReport`. They
emit the PR-13 columns plus a transition_count row and a notes section.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from clipper_agency.diagnostics.models import DriftReport

_COLUMNS = [
    "beat_id",
    "section",
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
    "offset_ms_predicted_margin",
]


def _fmt(value: Any, precision: int = 3) -> str:
    """Format a cell value; ``None`` renders as ``-``."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return str(value)


def render_markdown(report: DriftReport) -> str:
    """Render a Markdown table with all PR-13 columns + notes + transition_count."""
    lines: list[str] = []
    lines.append(f"# AV-Drift Diagnosis — job_{report.job_id}")
    lines.append("")
    lines.append(f"- provider: `{report.provider}`")
    lines.append(f"- video_duration_sec: {_fmt(report.video_duration_sec)}")
    lines.append(f"- voiceover_duration_sec: {_fmt(report.voiceover_duration_sec)}")
    lines.append(f"- transition_count: {report.transition_count}")
    lines.append("")

    header = "| " + " | ".join(_COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in _COLUMNS) + " |"
    lines.append(header)
    lines.append(sep)

    for row in report.rows:
        cells = [_fmt(getattr(row, col)) for col in _COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(f"**transition_count**: {report.transition_count}")
    lines.append("")
    if report.notes:
        lines.append("## Notes")
        lines.append("")
        for note in report.notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)


def render_json(report: DriftReport) -> str:
    """Render a JSON report matching the DriftReport structure."""
    payload = asdict(report)
    return json.dumps(payload, indent=2)
