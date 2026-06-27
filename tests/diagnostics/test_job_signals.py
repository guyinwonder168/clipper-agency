"""Hermetic unit tests for JobSignals loading (PR 13).

Uses tmp_path fixtures — writes synthetic persisted artifacts and asserts the
loader resolves them. No real ffmpeg, no network. AAA pattern.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipper_agency.diagnostics.job_signals import load_job_signals


def _write_job_artifacts(cache_root: Path, job_id: int, *, video: bool = True) -> Path:
    """Create synthetic narrative_structure.json + output.json for a job."""
    job_cache = cache_root / f"job_{job_id}"
    sw = job_cache / "agents" / "scriptwriter"
    vp = job_cache / "agents" / "voice_producer"
    sw.mkdir(parents=True)
    vp.mkdir(parents=True)
    (sw / "narrative_structure.json").write_text(
        json.dumps([{"beat_id": 1, "section": "hook", "word_range": [0, 0]}])
    )
    (vp / "output.json").write_text(
        json.dumps(
            {
                "status": "success",
                "provider": "gemini_tts",
                "voiceover_duration_sec": 34.09,
                "timestamps": [{"word": "halo", "start": 0.0, "end": 0.42}],
            }
        )
    )
    if video:
        out_dir = cache_root.parent.parent  # sibling of data/assets
        job_out = out_dir / f"job_{job_id}"
        job_out.mkdir(parents=True, exist_ok=True)
        (job_out / "video.mp4").write_bytes(b"fake")
    return job_cache


def test_load_job_signals_parses_job_id_and_provider(tmp_path: Path) -> None:
    # Arrange — assets_cache = tmp/cache, job_dir = tmp/job_42
    cache = tmp_path / "cache"
    out_dir = tmp_path / "outputs"
    job_dir = out_dir / "job_42"
    job_dir.mkdir(parents=True)
    _write_job_artifacts(cache, 42, video=False)
    (job_dir / "video.mp4").write_bytes(b"fake")
    # Act
    signals = load_job_signals(job_dir, assets_cache=cache)
    # Assert
    assert signals.job_id == 42
    assert signals.provider == "gemini_tts"
    assert signals.voiceover_duration_sec == pytest.approx(34.09)
    assert signals.narrative_structure[0]["section"] == "hook"
    assert signals.timestamps[0]["word"] == "halo"
    assert signals.video_path.endswith("video.mp4")
    assert signals.hook_duration_sec == pytest.approx(0.42)


def test_load_job_signals_missing_narrative_raises_filenotfound(tmp_path: Path) -> None:
    # Arrange — cache exists but the narrative file is absent.
    cache = tmp_path / "cache"
    job_dir = tmp_path / "outputs" / "job_8"
    job_dir.mkdir(parents=True)
    (job_dir / "video.mp4").write_bytes(b"fake")
    (cache / "job_8" / "agents" / "voice_producer").mkdir(parents=True)
    (cache / "job_8" / "agents" / "voice_producer" / "output.json").write_text("{}")
    # Act / Assert
    with pytest.raises(FileNotFoundError):
        load_job_signals(job_dir, assets_cache=cache)


def test_load_job_signals_missing_video_raises_filenotfound(tmp_path: Path) -> None:
    # Arrange — narrative + voice present but no video.mp4 in job_dir.
    cache = tmp_path / "cache"
    job_dir = tmp_path / "outputs" / "job_8"
    job_dir.mkdir(parents=True)
    _write_job_artifacts(cache, 8, video=False)
    # Act / Assert
    with pytest.raises(FileNotFoundError):
        load_job_signals(job_dir, assets_cache=cache)


def test_load_job_signals_rejects_non_job_basename(tmp_path: Path) -> None:
    # Arrange — basename is not job_<N>.
    job_dir = tmp_path / "outputs" / "notajob"
    job_dir.mkdir(parents=True)
    cache = tmp_path / "cache"
    # Act / Assert
    with pytest.raises((ValueError, FileNotFoundError)):
        load_job_signals(job_dir, assets_cache=cache)


def test_resolve_assets_cache_walks_up_to_sibling_data_cache(tmp_path: Path) -> None:
    """Default resolution (assets_cache=None) finds sibling data/assets/cache
    by walking the job_dir's ancestors — works for an absolute job_dir
    regardless of CWD (Codex P2#2)."""
    # Arrange — repo layout: <tmp>/data/{assets/cache, outputs}/job_7
    cache = tmp_path / "data" / "assets" / "cache"
    out_dir = tmp_path / "data" / "outputs"
    job_dir = out_dir / "job_7"
    job_dir.mkdir(parents=True)
    _write_job_artifacts(cache, 7, video=False)
    (job_dir / "video.mp4").write_bytes(b"fake")
    # Act — absolute job_dir, no --assets-cache override.
    signals = load_job_signals(job_dir, assets_cache=None)
    # Assert — walked up from job_7 to <tmp> and found data/assets/cache.
    assert signals.job_id == 7
    assert signals.provider == "gemini_tts"


def test_load_job_signals_rejects_non_list_narrative(tmp_path: Path) -> None:
    """A narrative_structure.json that is not a JSON array raises ValueError
    at the boundary (isinstance narrowing), not a silent TypeError later."""
    # Arrange
    cache = tmp_path / "cache"
    job_dir = tmp_path / "outputs" / "job_8"
    job_dir.mkdir(parents=True)
    (job_dir / "video.mp4").write_bytes(b"fake")
    sw = cache / "job_8" / "agents" / "scriptwriter"
    vp = cache / "job_8" / "agents" / "voice_producer"
    sw.mkdir(parents=True)
    vp.mkdir(parents=True)
    (sw / "narrative_structure.json").write_text(json.dumps({"not": "a list"}))
    (vp / "output.json").write_text(json.dumps({"provider": "x", "timestamps": []}))
    # Act / Assert
    with pytest.raises(ValueError):
        load_job_signals(job_dir, assets_cache=cache)


def test_load_job_signals_rejects_non_dict_narrative_entry(tmp_path: Path) -> None:
    """A non-dict entry inside the narrative array raises ValueError (reject)
    rather than being silently dropped — a diagnosis tool must surface malformed
    beats (Codex P3)."""
    # Arrange — a valid array but one entry is a bare string.
    cache = tmp_path / "cache"
    job_dir = tmp_path / "outputs" / "job_8"
    job_dir.mkdir(parents=True)
    (job_dir / "video.mp4").write_bytes(b"fake")
    sw = cache / "job_8" / "agents" / "scriptwriter"
    vp = cache / "job_8" / "agents" / "voice_producer"
    sw.mkdir(parents=True)
    vp.mkdir(parents=True)
    (sw / "narrative_structure.json").write_text(
        json.dumps([{"beat_id": 1, "word_range": [0, 0]}, "not_a_dict"])
    )
    (vp / "output.json").write_text(
        json.dumps({"provider": "x", "timestamps": [{"word": "a", "start": 0.0, "end": 1.0}]})
    )
    # Act / Assert
    with pytest.raises(ValueError):
        load_job_signals(job_dir, assets_cache=cache)


def test_load_job_signals_rejects_non_list_timestamps(tmp_path: Path) -> None:
    """A voice_producer/output.json whose 'timestamps' is not a JSON array
    raises ValueError at the boundary (Codex P2 — PR #78 thread PRRT_kwDOSepZ-M6Mrw_F)
    instead of an uncaught TypeError/IndexError later in build_drift_table."""
    # Arrange — valid narrative; timestamps is a string, not an array.
    cache = tmp_path / "cache"
    job_dir = tmp_path / "outputs" / "job_8"
    job_dir.mkdir(parents=True)
    (job_dir / "video.mp4").write_bytes(b"fake")
    sw = cache / "job_8" / "agents" / "scriptwriter"
    vp = cache / "job_8" / "agents" / "voice_producer"
    sw.mkdir(parents=True)
    vp.mkdir(parents=True)
    (sw / "narrative_structure.json").write_text(json.dumps([{"beat_id": 1, "word_range": [0, 0]}]))
    (vp / "output.json").write_text(json.dumps({"provider": "x", "timestamps": "nope"}))
    # Act / Assert
    with pytest.raises(ValueError, match="timestamps"):
        load_job_signals(job_dir, assets_cache=cache)


def test_load_job_signals_rejects_non_dict_timestamp_entry(tmp_path: Path) -> None:
    """A non-dict entry inside the timestamps array raises ValueError (reject)
    rather than being silently dropped — mirrors narrative_structure validation."""
    # Arrange — valid narrative; timestamps array contains a bare string.
    cache = tmp_path / "cache"
    job_dir = tmp_path / "outputs" / "job_8"
    job_dir.mkdir(parents=True)
    (job_dir / "video.mp4").write_bytes(b"fake")
    sw = cache / "job_8" / "agents" / "scriptwriter"
    vp = cache / "job_8" / "agents" / "voice_producer"
    sw.mkdir(parents=True)
    vp.mkdir(parents=True)
    (sw / "narrative_structure.json").write_text(json.dumps([{"beat_id": 1, "word_range": [0, 0]}]))
    (vp / "output.json").write_text(
        json.dumps(
            {"provider": "x", "timestamps": [{"word": "a", "start": 0.0, "end": 1.0}, "bad"]}
        )
    )
    # Act / Assert
    with pytest.raises(ValueError, match="timestamps"):
        load_job_signals(job_dir, assets_cache=cache)


def test_load_job_signals_rejects_empty_timestamps_with_non_empty_narrative(
    tmp_path: Path,
) -> None:
    """Empty timestamps with a non-empty narrative raises ValueError —
    derive_planned_boundaries would return [] and build_drift_table's
    planned[i] would otherwise IndexError."""
    # Arrange — narrative has 1 beat; timestamps is an empty array.
    cache = tmp_path / "cache"
    job_dir = tmp_path / "outputs" / "job_8"
    job_dir.mkdir(parents=True)
    (job_dir / "video.mp4").write_bytes(b"fake")
    sw = cache / "job_8" / "agents" / "scriptwriter"
    vp = cache / "job_8" / "agents" / "voice_producer"
    sw.mkdir(parents=True)
    vp.mkdir(parents=True)
    (sw / "narrative_structure.json").write_text(
        json.dumps(
            [
                {"beat_id": 1, "word_range": [0, 0]},
                {"beat_id": 2, "word_range": [0, 0]},
            ]
        )
    )
    (vp / "output.json").write_text(json.dumps({"provider": "x", "timestamps": []}))
    # Act / Assert
    with pytest.raises(ValueError, match="empty"):
        load_job_signals(job_dir, assets_cache=cache)
