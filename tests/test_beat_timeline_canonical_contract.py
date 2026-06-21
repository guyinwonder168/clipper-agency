"""Canonical beat-timeline contract enforcement (ADR 0020, RC-5).

Defense-in-depth regression tests: a *present-but-empty* canonical timeline
(``beat_timeline=[]``) must still be honored as the single source of truth.
The orchestrator's :func:`build_canonical_timeline` returns ``[]`` on
degenerate/empty input, and the falsy guard ``if beat_timeline:`` treated
that identical to a missing timeline — silently falling through to each
agent's PRIVATE divergent recompute (``_calculate_beat_durations`` /
``_compute_beat_durations``), violating the ADR 0020 single-source-of-truth
contract that PR #52 intended.

These tests assert the canonical path is taken even when the timeline is
empty: the private recompute must NOT be invoked. They FAIL before the
guard is changed to ``is not None`` and PASS afterward.

See: docs/adr/0020-*.md, plan section 1.1 (RC-5).
"""

from __future__ import annotations

import pytest

from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.config.schema import StoryBeat, WordTimestamp

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _vd_beats() -> list[dict]:
    """Story beat dicts (non-empty) that would otherwise drive VD recompute."""
    return [
        {
            "beat_id": 1,
            "role": "hook",
            "narration_goal": "Open the video",
            "spoken_point": "Artist X just released a new album",
            "safe_wording": "Artist X just released a new album",
            "visual_must_show": "Album cover",
            "visual_must_not_show": "",
            "overlay_text": "NEW ALBUM",
            "caption_keywords": ["album"],
            "asset_candidates": [],
            "fallback": {
                "type": "text_card",
                "headline": "Beat 1",
                "image_search": "album",
            },
            "risk_note": "",
        },
    ]


def _vd_timestamps() -> list[dict]:
    """Non-empty word timestamps (would otherwise drive VD recompute)."""
    return [
        {"word": "Artist", "start": 0.0, "end": 0.4},
        {"word": "X", "start": 0.4, "end": 0.6},
        {"word": "released", "start": 0.6, "end": 1.2},
        {"word": "an", "start": 1.2, "end": 1.3},
        {"word": "album", "start": 1.3, "end": 1.8},
    ]


def _composer_narrative() -> list[dict]:
    """Non-empty narrative structure (would otherwise drive Composer recompute)."""
    return [
        {"beat_id": 1, "word_range": [0, 3]},
    ]


def _composer_timestamps() -> list[dict]:
    """Non-empty word timestamps (would otherwise drive Composer recompute)."""
    return [
        {"word": "w0", "start": 0.0, "end": 0.5},
        {"word": "w1", "start": 0.5, "end": 1.0},
        {"word": "w2", "start": 1.0, "end": 1.5},
    ]


# ---------------------------------------------------------------------------
# Visual Director: empty canonical timeline must NOT trigger private recompute
# ---------------------------------------------------------------------------


class TestVisualDirectorEmptyTimelineHonorsCanonicalContract:
    """VD must take the canonical-timeline branch when beat_timeline=[] (RC-5)."""

    def test_empty_timeline_does_not_call_private_recompute(self, mocker):
        """Given beat_timeline=[], VD must not call _calculate_beat_durations.

        The private recompute is the ADR 0020-violating fallback. We spy on it
        to raise if invoked, and stub the rest of _run_beat_driven_planning so
        the guard branch is the only thing under test.
        """
        agent = VisualDirectorAgent()

        # Spy: private recompute must NEVER run when the canonical timeline is
        # present (even if empty).
        mocker.patch.object(
            agent,
            "_calculate_beat_durations",
            side_effect=AssertionError(
                "_calculate_beat_durations must not run when beat_timeline is "
                "present (even empty) — ADR 0020 / RC-5"
            ),
        )

        # Stub downstream planning so we isolate the guard branch. The LLM
        # plan is short-circuited to None so the fallback planner path runs,
        # but the guard already decided the duration source before that.
        mocker.patch.object(
            agent,
            "_plan_beats_with_llm",
            return_value=None,
        )
        mocker.patch.object(agent, "_plan_beats_fallback", return_value=[])
        mocker.patch.object(agent, "_normalize_beat_plan", return_value=[])
        mocker.patch.object(agent, "_deduplicate_llm_plan_urls", return_value=[])
        mocker.patch.object(
            agent,
            "_inspect_and_select_candidates",
            return_value=([], []),
        )
        mocker.patch.object(
            agent,
            "_attach_candidate_windows",
            return_value=[],
        )
        mocker.patch.object(
            agent,
            "_execute_beat_plan",
            return_value=[],
        )

        # Empty canonical timeline — the falsy `if beat_timeline:` bug would
        # route this to _calculate_beat_durations (raising AssertionError).
        parsed_beats = [StoryBeat(**b) for b in _vd_beats()]
        parsed_ts = [WordTimestamp(**t) for t in _vd_timestamps()]

        plan, assets = agent._run_beat_driven_planning(
            story_beats=_vd_beats(),
            timestamps=_vd_timestamps(),
            do_not_use=[],
            voiceover_duration_sec=1.8,
            job_id=1,
            output_dir="",
            agent_dir="",
            beat_timeline=[],  # present but empty — canonical contract
        )

        # If we got here, the guard took the canonical branch and the spy was
        # never invoked. Sanity-check the return shape.
        assert plan == []
        assert assets == []

        # Touch parsed objects to silence unused-variable linters while
        # documenting that construction itself does not exercise the guard.
        assert len(parsed_beats) == 1
        assert len(parsed_ts) == 5


# ---------------------------------------------------------------------------
# Composer: empty canonical timeline must NOT trigger private recompute
# ---------------------------------------------------------------------------


class TestComposerEmptyTimelineHonorsCanonicalContract:
    """Composer must take the canonical-timeline branch when beat_timeline=[] (RC-5)."""

    def test_empty_timeline_does_not_call_private_recompute(self, mocker, tmp_path):
        """Given beat_timeline=[], Composer must not call _compute_beat_durations.

        We invoke _try_audio_first_assemble directly (where the guard lives at
        composer.py:1657) with an empty canonical timeline and assert the
        private recompute is never reached. Downstream clip collection/render
        is stubbed so the guard branch is the only thing under test.
        """
        agent = ComposerAgent()

        # Spy: private recompute must NEVER run when the canonical timeline is
        # present (even empty).
        mocker.patch.object(
            agent,
            "_compute_beat_durations",
            side_effect=AssertionError(
                "_compute_beat_durations must not run when beat_timeline is "
                "present (even empty) — ADR 0020 / RC-5"
            ),
        )

        # Stub the rest of _try_audio_first_assemble so the empty timeline
        # (→ empty beat_durations → no trimmed clips) flows through cleanly
        # without touching FFmpeg.
        mocker.patch.object(
            agent,
            "_align_assets_to_narrative_beats",
            return_value=[],
        )

        # With beat_durations=[] (from timeline_to_duration_list([])) and no
        # aligned assets, _collect_beat_clips produces no clips and the method
        # returns the "No visual assets to compose" failure dict before any
        # render. We still stub render to be safe against env differences.
        mocker.patch.object(agent, "_run_audio_first_render")

        result = agent._try_audio_first_assemble(
            job_id=1,
            voiceover_path=str(tmp_path / "voice.mp4"),
            timestamps=_composer_timestamps(),
            narrative_structure=_composer_narrative(),
            assets=[],
            video_path=str(tmp_path / "job_1" / "video.mp4"),
            thumbnail_path=str(tmp_path / "job_1" / "thumbnail.png"),
            assets_cache="",
            agent_dir="",
            beat_timeline=[],  # present but empty — canonical contract
        )

        # The empty timeline yields beat_durations=[] → no trimmed clips →
        # the "No visual assets to compose" failure path. The point of the
        # test is that we reached it via the CANONICAL branch, not the
        # private recompute (which would have raised AssertionError).
        assert result["status"] == "failed"
        assert result["error"] == "No visual assets to compose"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
