#!/usr/bin/env python3
"""Thin CLI entry for the AV-drift diagnosis harness (PR 13).

READ-ONLY: reads persisted artifacts + probes the muxed video with ffprobe.
Does NOT alter any pipeline behavior (ADR-0026 compliance).

usage:
  diagnose_av_drift.py <job_dir> [--assets-cache DIR]
      [--pixel-threshold FLOAT] [--out PATH] [--json PATH]

Exit codes:
  0 — report produced (drift may be large; this is a measurement tool).
  2 — a required input is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Standalone script (not a ``python -m`` invocation): ensure the repo root is
# importable so ``clipper_agency.*`` resolves when run directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from clipper_agency.core.media_probe import probe_video  # noqa: E402
from clipper_agency.diagnostics.achieved import (  # noqa: E402
    PIXEL_THRESHOLD_DEFAULT,
    measure_achieved_boundaries,
)
from clipper_agency.diagnostics.captions import derive_caption_windows  # noqa: E402
from clipper_agency.diagnostics.drift_table import build_drift_table  # noqa: E402
from clipper_agency.diagnostics.job_signals import load_job_signals  # noqa: E402
from clipper_agency.diagnostics.models import DriftReport  # noqa: E402
from clipper_agency.diagnostics.planned import (  # noqa: E402
    compute_transition_count,
    derive_planned_boundaries,
)
from clipper_agency.diagnostics.report import render_json, render_markdown  # noqa: E402


def _probe_video_duration(video_path: str) -> float | None:
    """Probe the muxed video duration via the shared ``probe_video`` helper.

    ``probe_video`` resolves a name under a base dir (S6549 safe-path
    contract); split the already-validated ``signals.video_path`` into
    name + parent so we probe exactly that file. Returns ``None`` on any
    probe failure so the achieved-boundary table is still emitted.
    """
    resolved = Path(video_path)
    info = probe_video(resolved.name, resolved.parent)
    return info.duration if info is not None else None


def _build_report(job_dir: str, assets_cache: str | None, pixel_threshold: float) -> DriftReport:
    signals = load_job_signals(job_dir, assets_cache=assets_cache)
    planned = derive_planned_boundaries(signals.narrative_structure, signals.timestamps)
    achieved, achieved_note = measure_achieved_boundaries(
        signals.video_path,
        expected_count=len(signals.narrative_structure),
        pixel_threshold=pixel_threshold,
    )
    caption_windows = derive_caption_windows(signals.narrative_structure, signals.timestamps)
    transition_count = compute_transition_count(signals.narrative_structure)
    rows = build_drift_table(signals, achieved, caption_windows, planned)

    notes: list[str] = []
    if achieved_note is not None:
        notes.append(achieved_note)
    if signals.provider != "elevenlabs":
        notes.append(
            f"provider is {signals.provider}; measured fallback-TTS path "
            "(no ElevenLabs job available)"
        )
    notes.append(
        "rendered_scene_manifest not persisted; PLANNED via canonical timeline "
        "(build_canonical_timeline, ADR 0020)"
    )
    tail_audio = signals.voiceover_duration_sec - (planned[-1][1] if planned else 0.0)
    if tail_audio > 1.0:
        notes.append(
            f"uncovered tail audio: {tail_audio:.3f}s after last planned beat end "
            "(timestamps beyond the final beat's word_range)"
        )

    return DriftReport(
        job_id=signals.job_id,
        provider=signals.provider,
        video_duration_sec=_probe_video_duration(signals.video_path),
        voiceover_duration_sec=signals.voiceover_duration_sec,
        transition_count=transition_count,
        rows=rows,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose audio/visual drift for a finished job (READ-ONLY)."
    )
    parser.add_argument("job_dir", help="job output dir (job_<N>) containing video.mp4")
    parser.add_argument("--assets-cache", default=None, help="assets cache root override")
    parser.add_argument(
        "--pixel-threshold",
        dest="pixel_threshold",
        type=float,
        default=PIXEL_THRESHOLD_DEFAULT,
        help=f"blackdetect pix_th (default {PIXEL_THRESHOLD_DEFAULT})",
    )
    parser.add_argument("--out", default=None, help="write markdown report to PATH")
    parser.add_argument("--json", dest="json_path", default=None, help="write JSON report to PATH")
    args = parser.parse_args(argv)

    try:
        report = _build_report(args.job_dir, args.assets_cache, args.pixel_threshold)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    markdown = render_markdown(report)
    if args.out:
        Path(args.out).write_text(markdown)
    else:
        print(markdown)
    if args.json_path:
        Path(args.json_path).write_text(render_json(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
