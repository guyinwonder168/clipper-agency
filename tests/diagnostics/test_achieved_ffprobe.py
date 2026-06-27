"""Integration test for achieved-boundary measurement via ffprobe/ffmpeg (PR 13).

Marked ``@pytest.mark.integration`` — requires real ffmpeg/ffprobe. Skipped
under the offline gate (``-m "not external and not integration"``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from clipper_agency.diagnostics.achieved import measure_achieved_boundaries

_JOB8_DIR = Path("/media/eddy/hdd/Project/clipper agency/data/outputs/job_8")
_JOB8_VIDEO = _JOB8_DIR / "video.mp4"

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _require_ffmpeg() -> None:
    """Skip every test in this module if ffmpeg/ffprobe or the job_8 fixture
    is absent (the offline gate runs with neither)."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    if not _JOB8_VIDEO.is_file():
        pytest.skip(f"job_8 video not present: {_JOB8_VIDEO}")


def test_measure_achieved_boundaries_returns_internal_black_edges() -> None:
    """job_8 has 8 beats => 7 internal black gaps; each black_end is an
    achieved scene start. We expect ~7 achieved boundaries, and the first
    internal black_end should be ~7.6s (matches verifier 1 measurement)."""
    # Arrange — job_8 muxed video, 8 expected beats.
    # Act
    achieved, note = measure_achieved_boundaries(str(_JOB8_VIDEO), expected_count=8)
    # Assert — no failure note; beat 1 starts at 0.0; beat 2's achieved start is
    # the first internal black_end (~7.6s, matches verifier 1). Padded to 8.
    assert note is None
    assert len(achieved) == 8
    assert achieved[0] is not None and achieved[0][0] == 0.0
    assert achieved[1] is not None
    beat2_start = achieved[1][0]
    assert 7.0 <= beat2_start <= 8.2, f"first internal black_end ~7.6s expected, got {beat2_start}"


def test_measure_achieved_boundaries_missing_video_returns_none_padding(
    tmp_path: Path,
) -> None:
    """A non-existent video yields a None-padded list (no raise)."""
    # Arrange
    missing = tmp_path / "nope.mp4"
    # Act
    achieved, note = measure_achieved_boundaries(str(missing), expected_count=3)
    # Assert
    assert achieved == [None, None, None]
    assert note is None


def test_ffprobe_duration_command_returns_zero_rc() -> None:
    """Sanity: the pinned ffprobe duration command exits 0 and parses."""
    # Arrange / Act
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(_JOB8_VIDEO),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # Assert
    assert result.returncode == 0
    assert '"duration"' in result.stdout
