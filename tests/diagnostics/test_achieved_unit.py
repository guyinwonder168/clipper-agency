"""Hermetic unit tests for achieved-boundary pure logic (PR 13).

Exercises the bookend filter, the persisted-coverage parser, the
missing-video early return, and the ffmpeg I/O parse paths (via mocked
subprocess) WITHOUT real ffmpeg — the real-ffmpeg end-to-end lives in the
integration-marked ``test_achieved_ffprobe.py``. AAA pattern.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from clipper_agency.diagnostics import achieved as achieved_mod
from clipper_agency.diagnostics.achieved import (
    LEAD_IN_MAX_SEC,
    _black_gaps_from_visual_coverage,
    _internal_boundaries,
    measure_achieved_boundaries,
)

# ---------------------------------------------------------------------------
# _internal_boundaries — drops lead-in + trailing bookends, returns black_end.
# ---------------------------------------------------------------------------


def test_internal_boundaries_drops_lead_in_and_trailing() -> None:
    """Only internal gaps survive; their ``black_end`` is the achieved start."""
    # Arrange — lead-in at 0s, two internal gaps, a trailing gap at the end.
    gaps = [(0.0, 6.0), (6.6, 7.6), (10.3, 11.5), (18.3, 30.5)]
    # Act
    result = _internal_boundaries(gaps, duration=30.5)
    # Assert — lead-in (start 0 <= LEAD_IN_MAX_SEC) and trailing (end >= 30.0)
    # are dropped; the two internal black_end values remain.
    assert result == [7.6, 11.5]


def test_internal_boundaries_keeps_all_when_duration_unknown() -> None:
    """Without a duration the trailing filter is skipped (no False drop)."""
    # Arrange — no trailing bookend can be inferred.
    gaps = [(0.0, 1.0), (5.0, 6.0)]
    # Act
    result = _internal_boundaries(gaps, duration=None)
    # Assert — lead-in still dropped; second gap kept even though it is last.
    assert result == [6.0]


def test_internal_boundaries_empty_returns_empty() -> None:
    # Arrange / Act / Assert
    assert _internal_boundaries([], duration=10.0) == []


def test_lead_in_constant_is_small() -> None:
    """Sanity guard: the lead-in window is sub-second so real beats are kept."""
    assert 0.0 < LEAD_IN_MAX_SEC <= 0.5


# ---------------------------------------------------------------------------
# _black_gaps_from_visual_coverage — parses persisted BLACK_FRAME issues.
# ---------------------------------------------------------------------------


def test_black_gaps_from_visual_coverage_filters_black_frames(tmp_path: Path) -> None:
    """Only BLACK_FRAME issues with numeric start/end become gaps."""
    # Arrange
    coverage = {
        "issues": [
            {"type": "BLACK_FRAME", "start_sec": 1.0, "end_sec": 2.0},
            {"type": "FREEZE_FRAME", "start_sec": 3.0, "end_sec": 4.0},
            {"type": "BLACK_FRAME", "start_sec": None, "end_sec": 5.0},
            {"type": "BLACK_FRAME", "start_sec": 6.0, "end_sec": 7.0},
        ]
    }
    (tmp_path / "visual_coverage.json").write_text(json.dumps(coverage))
    # Act
    gaps = _black_gaps_from_visual_coverage(tmp_path)
    # Assert — FREEZE + the None-start BLACK_FRAME are skipped.
    assert gaps == [(1.0, 2.0), (6.0, 7.0)]


def test_black_gaps_from_visual_coverage_missing_file_returns_none(tmp_path: Path) -> None:
    # Arrange — no visual_coverage.json in the dir.
    # Act / Assert
    assert _black_gaps_from_visual_coverage(tmp_path) is None


def test_black_gaps_from_visual_coverage_corrupt_json_returns_none(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "visual_coverage.json").write_text("{not valid json")
    # Act / Assert
    assert _black_gaps_from_visual_coverage(tmp_path) is None


# ---------------------------------------------------------------------------
# measure_achieved_boundaries — missing-video early return (no ffmpeg needed).
# ---------------------------------------------------------------------------


def test_measure_achieved_boundaries_missing_video_pads_none(tmp_path: Path) -> None:
    """A non-existent video returns a None-padded list without raising."""
    # Arrange — no video, no persisted coverage in tmp_path.
    missing = tmp_path / "absent.mp4"
    # Act
    result = measure_achieved_boundaries(
        str(missing), expected_count=4, allowed_base_dir=str(tmp_path)
    )
    # Assert — padded to expected_count, all None, no subprocess invoked.
    assert result == [None, None, None, None]


# ---------------------------------------------------------------------------
# ffmpeg I/O parse paths — mocked subprocess (no real ffmpeg dependency).
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Stub ffmpeg/ffprobe so the parse + assembly logic runs hermetically."""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"")

    def fake_blackdetect(video_path: Path, pixel_threshold: float) -> list[tuple[float, float]]:
        return [(0.0, 6.0), (6.6, 7.6), (10.3, 11.5), (18.3, 30.5)]

    def fake_probe_duration(video_path: Path) -> float:
        return 30.5

    monkeypatch.setattr(achieved_mod, "_run_blackdetect", fake_blackdetect)
    monkeypatch.setattr(achieved_mod, "_probe_duration", fake_probe_duration)
    return video


def test_measure_assembles_boundaries_from_mocked_gaps(patched_ffmpeg: Path) -> None:
    """The orchestration assembles (start, end) pairs + None padding from gaps."""
    # Arrange — patched_ffmpeg provides a video + stubbed detection.
    # Act — allowed_base_dir has no visual_coverage.json so the stubbed
    # blackdetect runs; duration is stubbed to 30.5 so the trailing gap drops.
    result = measure_achieved_boundaries(
        str(patched_ffmpeg), expected_count=4, allowed_base_dir=str(patched_ffmpeg.parent)
    )
    # Assert — beat1 (0.0, 7.6); beat2 (7.6, 11.5); beat3 (11.5, None); beat4 None.
    assert result[0] == (0.0, 7.6)
    assert result[1] == (7.6, 11.5)
    assert result[2] == (11.5, None)
    assert result[3] is None


def test_probe_duration_parses_ffprobe_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """_probe_duration reads format.duration from ffprobe JSON output."""
    # Arrange
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *a, **k: json.dumps({"format": {"duration": "12.5"}}).encode(),
    )
    # Act
    dur = achieved_mod._probe_duration(video)
    # Assert
    assert dur == 12.5


def test_probe_duration_returns_none_on_subprocess_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Any ffprobe failure degrades to None (no crash)."""
    # Arrange
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")

    def boom(*a: object, **k: object) -> object:
        raise subprocess.CalledProcessError(1, ["ffprobe"])

    monkeypatch.setattr(subprocess, "check_output", boom)
    # Act / Assert
    assert achieved_mod._probe_duration(video) is None


def test_run_blackdetect_parses_stderr_gaps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """_run_blackdetect extracts (start, end) pairs from blackdetect stderr."""
    # Arrange — a fake CompletedProcess whose stderr carries two black gaps.
    fake_stderr = (
        "[blackdetect @ 0x1] black_start:6.63333 black_end:7.60000 black_duration:0.96667\n"
        "[blackdetect @ 0x1] black_start:10.33333 black_end:11.46667 black_duration:1.13334\n"
    )

    class _FakeProc:
        stderr = fake_stderr

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
    # Act
    gaps = achieved_mod._run_blackdetect(tmp_path / "v.mp4", pixel_threshold=0.1)
    # Assert
    assert gaps == [(6.63333, 7.6), (10.33333, 11.46667)]


def test_run_blackdetect_returns_empty_on_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ffmpeg timeout degrades to an empty gap list (no crash)."""
    # Arrange
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(["ffmpeg"], 1)),
    )
    # Act / Assert
    assert achieved_mod._run_blackdetect(tmp_path / "v.mp4", pixel_threshold=0.1) == []
