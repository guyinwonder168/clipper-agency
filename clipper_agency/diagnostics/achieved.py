"""Measure achieved scene boundaries from the muxed video (PR 13).

PRIMARY signal: ffmpeg ``blackdetect``. Verifier-1 empirically confirmed that
scene-change ``gt(scene,T)`` fires 0 cuts on job_8 — the xfade-to-black
transitions + Ken-Burns zoompan produce sub-frame motion that SCD does not
register. blackdetect is therefore the only reliable achieved-boundary source.

The achieved scene-start for beat k = the ``black_end`` of the k-th INTERNAL
black gap (the moment the xfade emerges from black into the next scene's
content). Lead-in (start <= LEAD_IN_MAX_SEC) and trailing (end within
TRAILING_TAIL_SEC of the video duration) bookend gaps are excluded, so the
remaining N-1 internal gaps map 1:1 to beat transitions.

We DO NOT reuse the persisted ``visual_coverage.json`` BLACK_FRAME issues
(Codex P2#1): that file is a *filtered gate report* —
``visual_coverage._check_black_segments`` only persists gaps exceeding
``black_frame_max_ms`` (200 ms). Sub-threshold transitions are omitted, so
treating the persisted list as complete would silently shift the remaining
gaps onto the wrong beats. Always run blackdetect fresh on the muxed video.

A blackdetect FAILURE (non-zero rc, timeout, missing binary) is surfaced
explicitly: ``measure_achieved_boundaries`` returns ``(all-None, note)`` so
the report flags "achieved column unavailable" instead of emitting a
misleading hybrid table (the silent-failure mode the reviewer flagged).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from clipper_agency.core.media_probe import probe_video

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
    """Return the muxed video duration via the shared ``probe_video`` helper."""
    info = probe_video(video_path.name, video_path.parent)
    return info.duration if info is not None else None


def _run_blackdetect(video_path: Path, pixel_threshold: float) -> list[tuple[float, float]]:
    """Run the pinned blackdetect command and parse its output.

    Raises ``subprocess.CalledProcessError`` on a non-zero ffmpeg exit so a
    crash / corrupt-video does not masquerade as "zero gaps found".
    """
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
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_BLACKDETECT_TIMEOUT_SEC,
        check=False,
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr
        )
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
) -> tuple[list[tuple[float, float | None] | None], str | None]:
    """Measure per-beat achieved ``(start, end)`` boundaries via blackdetect.

    Returns ``(boundaries, failure_note)``. ``boundaries`` is padded to
    ``expected_count`` with ``None`` for any beat whose end is unknown (e.g. the
    final beat, whose achieved-start is the trailing-black bookend). On a
    blackdetect failure (non-zero rc / timeout / missing binary) returns
    ``(all-None, note)`` so the caller can flag "achieved column unavailable".
    On a missing video returns ``(all-None, None)``.
    """
    n = max(0, expected_count)
    video = Path(video_path)
    if not video.is_file():
        return [None] * n, None

    try:
        gaps = _run_blackdetect(video, pixel_threshold)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return [None] * n, f"blackdetect failed ({type(exc).__name__}); achieved column unavailable"

    duration = _probe_duration(video)
    starts = _internal_boundaries(gaps, duration)

    out: list[tuple[float, float | None] | None] = []
    for i in range(n):
        if i == 0:
            out.append((0.0, starts[0] if starts else None))
        elif i - 1 < len(starts):
            start = starts[i - 1]
            nxt = starts[i] if i < len(starts) else None
            out.append((start, nxt))
        else:
            out.append(None)
    return out, None
