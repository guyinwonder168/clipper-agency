"""RC-9: rendered_scene_manifest persistence + entries/scenes key.

The Reviewer repair loop reconstructs Composer output from the on-disk
``output.json`` (see ``_run_cached_upstream_repair`` ->
``_reconstruct_upstream_outputs`` -> ``_load_agent_output``). If the
manifest is attached to the in-memory dict AFTER the dict is persisted,
the on-disk JSON omits it and the repair loop is blind.

Two regressions are pinned here:

* RC-9a — the audio-first render persist path writes a manifest-bearing
  dict to ``output.json`` (the manifest is attached before, not after,
  the authoritative on-disk write).
* RC-9b — ``get_semantic_review_context`` reads scenes from the
  ``entries`` key, matching the ``RenderedSceneManifest`` serialization.
"""

from __future__ import annotations

import json
from pathlib import Path

from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.core.paths import agent_output_file
from clipper_agency.core.reviewer_context import (
    ReviewContextBundle,
    get_semantic_review_context,
)


def _stub_audio_first_env(mocker, tmp_path: Path) -> None:
    """Stub the FFmpeg/VLM side-effects of the audio-first render path.

    The real ``write_json`` is intentionally NOT mocked — the on-disk
    persist is the contract under test.
    """
    mocker.patch("clipper_agency.agents.composer.run_ffmpeg_streaming")
    mocker.patch.object(ComposerAgent, "_generate_thumbnail")
    mocker.patch.object(
        ComposerAgent,
        "_probe_output_duration",
        return_value=30.0,
    )
    mocker.patch.object(ComposerAgent, "_persist_diagnostics")
    mocker.patch("clipper_agency.agents.composer._persist_visual_coverage")
    mocker.patch(
        "clipper_agency.agents.composer.evaluate_visual_coverage",
        return_value=_PassCoverage(),
    )
    mocker.patch(
        "clipper_agency.agents.composer.detect_black_segments",
        return_value=[],
    )
    mocker.patch(
        "clipper_agency.agents.composer.detect_freeze_segments",
        return_value=[],
    )


class _PassCoverage:
    """Minimal stub mirroring the visual-coverage result shape."""

    def model_dump(self) -> dict:
        return {"status": "pass"}

    @classmethod
    def pass_result(cls) -> _PassCoverage:
        return cls()


def test_audio_first_render_persists_rendered_scene_manifest(mocker, tmp_path):
    """RC-9a: on-disk output.json must contain rendered_scene_manifest."""
    _stub_audio_first_env(mocker, tmp_path)

    assets_cache = str(tmp_path)
    job_id = 1

    agent = ComposerAgent()
    agent._run_audio_first_render(
        job_id=job_id,
        voiceover_path=str(tmp_path / "voice.mp3"),
        timestamps=[
            {"word": "hello", "start": 0.0, "end": 1.0},
            {"word": "world", "start": 1.0, "end": 2.0},
        ],
        assets=[{"beat_id": "b1", "asset_id": "abc123"}],
        beat_durations=[5.0],
        trimmed_clips=[str(tmp_path / "clip0.mp4")],
        card_fallback_scenes=[],
        video_path=str(tmp_path / "video.mp4"),
        thumbnail_path=str(tmp_path / "thumb.png"),
        assets_cache=assets_cache,
        agent_dir=str(tmp_path),
    )

    output_path = Path(agent_output_file(assets_cache, job_id, "composer"))
    assert output_path.exists(), "composer output.json was never persisted"
    persisted = json.loads(output_path.read_text(encoding="utf-8"))

    assert "rendered_scene_manifest" in persisted, (
        "rendered_scene_manifest missing from persisted output.json — "
        "repair loop reconstruction will be blind"
    )


def test_get_semantic_review_context_reads_entries_key():
    """RC-9b: manifest serializes under 'entries', not 'scenes'."""
    manifest = {
        "entries": [
            {
                "scene": "1",
                "scene_index": 0,
                "beat_id": "1",
                "start_sec": 0.0,
                "end_sec": 5.0,
                "source_path": "/tmp/clip0.mp4",
                "source_type": "video",
                "selected_asset_id": "abc123",
                "caption_regions": [],
            }
        ],
        "video_duration_sec": 5.0,
        "video_path": "/tmp/video.mp4",
    }
    bundle = ReviewContextBundle(
        story_beats=[{"beat_id": 1, "text": "hello world"}],
        word_timestamps=[
            {"word": "hello", "start": 0.0, "end": 1.0},
            {"word": "world", "start": 1.0, "end": 2.0},
        ],
        rendered_scene_manifest=manifest,
        audio_duration_sec=5.0,
        video_duration_sec=5.0,
    )

    ctx = get_semantic_review_context(bundle, scene_index=0)

    assert ctx["scene_start_sec"] == 0.0, (
        "scene start not resolved — manifest likely read from wrong key"
    )
    assert ctx["scene_end_sec"] == 5.0, (
        "scene end not resolved — manifest likely read from wrong key"
    )
    assert ctx["word_timestamps"], (
        "no words matched the scene range — manifest entries were invisible"
    )
