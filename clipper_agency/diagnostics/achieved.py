"""Measure achieved scene boundaries from the muxed video (PR 13).

PRIMARY signal: ffmpeg ``blackdetect`` (verifier 1 empirically confirmed that
scene-change ``gt(scene,T)`` fires 0 cuts on job_8 — the xfade-to-black
transitions + Ken-Burns zoompan produce sub-frame motion that SCD does not
register; blackdetect is the repo's already-trusted signal, byte-matching the
BLACK_FRAME issues persisted in ``visual_coverage.json``).

The achieved scene-start for beat k = the ``black_end`` of the k-th INTERNAL
black gap (the moment the xfade emerges from black into the next scene's
content). Lead-in (start <= LEAD_IN_MAX_SEC) and trailing (end within
TRAILING_TAIL_SEC of the video duration) bookend gaps are excluded, so the
remaining N-1 internal gaps map 1:1 to beat transitions.

DRY reuse: when ``visual_coverage.json`` is persisted in the job output dir,
we read its BLACK_FRAME issues instead of re-running ffmpeg (avoiding a
subprocess and divergence). Otherwise we run the pinned blackdetect command.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# Verifier-1 pinned stable blackdetect params (stable across pix_th 0.10/0.20,
# d 0.05/0.1/0.2; do NOT use pix_th=0.05 which collapses to 1 gap).
PIXEL_THRESHOLD_DEFAULT = 0.10
MIN_BLACK_DURATION_SEC = 0.1

# Bookend exclusion windows.
LEAD_IN_MAX_SEC = 0.3
TRAILING_TAIL_SEC = 0.5

# The pinned blackdetect regex (verifier 1).
_BLACK_RE = re.compile(
    r"black_start:(?P<start>[0-9.]+)\s+black_end:(?P<end>[0-9.]+)"
    r"(?:\s+black_duration:(?P<dur>[0-9.]+))?"
)
_BLACKDETECT_TIMEOUT_SEC = 120


def _probe_duration(video_path: Path) -> float | None:
    """Return the muxed video duration via ffprobe, or None on any failure."""
    try:
        raw = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(video_path),
            ],
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        return float(json.loads(raw).get("format", {}).get("duration", 0.0))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _black_gaps_from_visual_coverage(job_dir: Path) -> list[tuple[float, float]] | None:
    """Read persisted BLACK_FRAME issues from visual_coverage.json if present."""
    coverage_path = job_dir / "visual_coverage.json"
    if not coverage_path.is_file():
        return None
    try:
        data = json.loads(coverage_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    gaps: list[tuple[float, float]] = []
    for issue in data.get("issues", []):
        if issue.get("type") != "BLACK_FRAME":
            continue
        start = issue.get("start_sec")
        end = issue.get("end_sec")
        if start is None or end is None:
            continue
        gaps.append((float(start), float(end)))
    return gaps


def _run_blackdetect(video_path: Path, pixel_threshold: float) -> list[tuple[float, float]]:
    """Run the pinned blackdetect command and parse its output."""
    filter_expr = f"blackdetect=d={MIN_BLACK_DURATION_SEC}:pix_th={pixel_threshold}"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(video_path),
        "-vf",
        filter_expr,
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_BLACKDETECT_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    stderr = proc.stderr or ""
    return [(float(m.group("start")), float(m.group("end"))) for m in _BLACK_RE.finditer(stderr)]


def _internal_boundaries(gaps: list[tuple[float, float]], duration: float | None) -> list[float]:
    """Drop bookend gaps; return the black_end of each internal gap.

    - Lead-in gap: ``start <= LEAD_IN_MAX_SEC``.
    - Trailing gap: ``duration`` known and ``end`` within ``TRAILING_TAIL_SEC``
      of it.
    """
    trailing_end = (duration - TRAILING_TAIL_SEC) if duration is not None else None
    achieved: list[float] = []
    for start, end in gaps:
        if start <= LEAD_IN_MAX_SEC:
            continue
        if trailing_end is not None and end >= trailing_end:
            continue
        achieved.append(end)
    return achieved


def measure_achieved_boundaries(
    video_path: str | Path,
    expected_count: int,
    pixel_threshold: float = PIXEL_THRESHOLD_DEFAULT,
    allowed_base_dir: str | Path | None = None,
) -> list[tuple[float, float | None] | None]:
    """Measure per-beat achieved ``(start, end)`` boundaries via blackdetect.

    Returns a list padded to ``expected_count`` with ``None`` for any beat
    whose boundary could not be measured (e.g. the final beat, whose
    achieved-start is the trailing-black bookend). Returns an all-``None`` list
    if the video is missing.
    """
    video = Path(video_path)
    if not video.is_file():
        return [None] * max(0, expected_count)

    # Reuse persisted BLACK_FRAME issues when present (DRY, avoids subprocess).
    gaps: list[tuple[float, float]] | None = None
    if allowed_base_dir is not None:
        gaps = _black_gaps_from_visual_coverage(Path(allowed_base_dir))
    if gaps is None or len(gaps) == 0:
        gaps = _run_blackdetect(video, pixel_threshold)

    duration = _probe_duration(video)
    starts = _internal_boundaries(gaps, duration)

    out: list[tuple[float, float | None] | None] = []
    for i in range(max(0, expected_count)):
        if i == 0:
            out.append((0.0, starts[0] if starts else None))
        elif i - 1 < len(starts):
            start = starts[i - 1]
            nxt = starts[i] if i < len(starts) else None
            out.append((start, nxt))
        else:
            out.append(None)
    return out
