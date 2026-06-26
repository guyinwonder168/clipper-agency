"""Hermetic unit tests for achieved-boundary pure logic (PR 13).

Exercises the bookend filter, the missing-video early return, and the
ffmpeg I/O paths (via mocked ``_run_blackdetect`` / ``probe_video``) WITHOUT
real ffmpeg — the real-ffmpeg end-to-end lives in the integration-marked
``test_achieved_ffprobe.py``. AAA pattern.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_agency.diagnostics import achieved as achieved_mod
from clipper_agency.diagnostics.achieved import (
    LEAD_IN_MAX_SEC,
    _internal_boundaries,
    _probe_duration,
    _run_blackdetect,
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
    """Without a duration the trailing filter is skipped (no false drop)."""
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
# _probe_duration — delegates to the shared probe_video helper.
# ---------------------------------------------------------------------------


def test_probe_duration_reads_probe_video_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_probe_duration returns probe_video's reported duration."""
    # Arrange — a stub VideoInfo carrying duration 12.5s.
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    monkeypatch.setattr(
        achieved_mod, "probe_video", lambda name, base: SimpleNamespace(duration=12.5)
    )
    # Act
    dur = _probe_duration(video)
    # Assert
    assert dur == 12.5


def test_probe_duration_returns_none_when_probe_video_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe_video None (missing file / ffprobe failure) degrades to None."""
    # Arrange
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    monkeypatch.setattr(achieved_mod, "probe_video", lambda name, base: None)
    # Act / Assert
    assert _probe_duration(video) is None


# ---------------------------------------------------------------------------
# _run_blackdetect — parses stderr gaps; raises on non-zero rc / timeout.
# ---------------------------------------------------------------------------


def test_run_blackdetect_parses_stderr_gaps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """_run_blackdetect extracts (start, end) pairs from blackdetect stderr."""
    # Arrange — a fake CompletedProcess whose stderr carries two black gaps.

    class _FakeProc:
        returncode = 0
        stderr = (
            "[blackdetect @ 0x1] black_start:6.63333 black_end:7.60000 black_duration:0.96667\n"
            "[blackdetect @ 0x1] black_start:10.33333 black_end:11.46667 black_duration:1.13334\n"
        )

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
    # Act
    gaps = _run_blackdetect(tmp_path / "v.mp4", pixel_threshold=0.1)
    # Assert
    assert gaps == [(6.63333, 7.6), (10.33333, 11.46667)]


def test_run_blackdetect_raises_on_nonzero_rc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-zero ffmpeg exit raises CalledProcessError (no silent empty list)."""
    # Arrange

    class _FakeProc:
        returncode = 1
        stdout = ""
        stderr = "Error: corrupt video"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
    # Act / Assert — the silent-failure fix: ffmpeg failure must surface.
    with pytest.raises(subprocess.CalledProcessError):
        _run_blackdetect(tmp_path / "v.mp4", pixel_threshold=0.1)


def test_run_blackdetect_raises_on_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A ffmpeg timeout propagates (no silent empty list)."""
    # Arrange
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(["ffmpeg"], 1)),
    )
    # Act / Assert
    with pytest.raises(subprocess.TimeoutExpired):
        _run_blackdetect(tmp_path / "v.mp4", pixel_threshold=0.1)


# ---------------------------------------------------------------------------
# measure_achieved_boundaries — orchestration + failure sentinel.
# ---------------------------------------------------------------------------


def test_measure_achieved_boundaries_missing_video_pads_none(tmp_path: Path) -> None:
    """A non-existent video returns (all-None, None) without raising."""
    # Arrange — no video.
    missing = tmp_path / "absent.mp4"
    # Act
    boundaries, note = measure_achieved_boundaries(str(missing), expected_count=4)
    # Assert — padded to expected_count, all None, no failure note.
    assert boundaries == [None, None, None, None]
    assert note is None


@pytest.fixture
def patched_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Stub blackdetect + probe so the assembly logic runs hermetically."""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"")

    def fake_blackdetect(video_path: Path, pixel_threshold: float) -> list[tuple[float, float]]:
        return [(0.0, 6.0), (6.6, 7.6), (10.3, 11.5), (18.3, 30.5)]

    monkeypatch.setattr(achieved_mod, "_run_blackdetect", fake_blackdetect)
    monkeypatch.setattr(
        achieved_mod, "probe_video", lambda name, base: SimpleNamespace(duration=30.5)
    )
    return video


def test_measure_assembles_boundaries_from_mocked_gaps(patched_ffmpeg: Path) -> None:
    """The orchestration assembles (start, end) pairs + None padding from gaps."""
    # Arrange — patched_ffmpeg provides a video + stubbed detection.
    # Act — duration stubbed to 30.5 so the trailing gap (end 30.5) drops.
    boundaries, note = measure_achieved_boundaries(str(patched_ffmpeg), expected_count=4)
    # Assert — beat1 (0.0, 7.6); beat2 (7.6, 11.5); beat3 (11.5, None); beat4 None.
    assert note is None
    assert boundaries[0] == (0.0, 7.6)
    assert boundaries[1] == (7.6, 11.5)
    assert boundaries[2] == (11.5, None)
    assert boundaries[3] is None


def test_measure_returns_failure_note_when_blackdetect_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A blackdetect failure surfaces as (all-None, note) — not a silent empty result."""
    # Arrange — a real video file but blackdetect raises.
    video = tmp_path / "video.mp4"
    video.write_bytes(b"")

    def boom(video_path: Path, pixel_threshold: float) -> list[tuple[float, float]]:
        raise subprocess.CalledProcessError(1, ["ffmpeg"])

    monkeypatch.setattr(achieved_mod, "_run_blackdetect", boom)
    # Act
    boundaries, note = measure_achieved_boundaries(str(video), expected_count=3)
    # Assert — all-None + a descriptive note (the silent-failure fix).
    assert boundaries == [None, None, None]
    assert note is not None
    assert "blackdetect failed" in note
