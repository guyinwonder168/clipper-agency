"""Characterization tests for Job #8 — frozen golden regression fixture.

These tests assert the CURRENT BROKEN behavior of Job #8 on master (v2.3.0).
They PASS today because they document what IS broken, not what SHOULD work.

As PRs 1-3 fix each bug, the corresponding test is updated from
asserting-broken → asserting-correct. The fixture data stays frozen; only
the expected values change, making each fix visible in the diff.

Bugs documented:
    Bug 1: Rejected candidates remain rendered in the visual plan
    Bug 2: Beat durations are absurdly wrong (hook=33s, reaction=29s)
    Bug 3: fade_to_black uses st=0.0 (fade at clip start, not end)
    Bug 4: Hard-failed gates don't reach the repair loop
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.rendering.treatment_config import TreatmentConfig
from clipper_agency.rendering.treatment_filters import TreatmentFilterBuilder

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "job8"
TEMPLATES_PATH = Path("templates/treatments.yaml")


def _load(name: str) -> Any:
    """Load a frozen JSON fixture."""
    return json.loads((FIXTURE_DIR / name).read_text())


def _make_beat(beat_id: int = 1, overlay_text: str = "Opening Hook") -> MagicMock:
    """Create a minimal beat mock for _apply_best_candidate tests."""
    beat = MagicMock()
    beat.beat_id = beat_id
    beat.overlay_text = overlay_text
    return beat


# ---------------------------------------------------------------------------
# Bug 1: Rejected candidates remain rendered in the visual plan
#
# Root cause: visual_director.py _apply_best_candidate only updated
# plan_item["action"] when best.decision == "accept". Rejected beats kept
# their original LLM-assigned action and still got rendered.
#
# FIX (PR 1): Added else branch — rejected → use plan_item["fallback"]
# or construct minimal text_card.
#
# Tests below exercise _apply_best_candidate directly (converted from
# fixture-based characterization per code review).
# ---------------------------------------------------------------------------


class TestBug1RejectedCandidatesUseFallback:
    """FIXED: rejected inspection decisions now trigger fallback actions."""

    def test_rejected_candidates_trigger_fallback_action(self) -> None:
        """When all candidates are rejected, action is replaced with fallback."""
        agent = VisualDirectorAgent.__new__(VisualDirectorAgent)
        plan_item = {
            "action": {"type": "tiktok_clip", "source": "rejected.mp4"},
            "fallback": {"type": "text_card", "headline": "Beat 1", "style": "news_card"},
        }
        beat = _make_beat(beat_id=1, overlay_text="Opening Hook")

        with patch(
            "clipper_agency.agents.visual_director.rank_candidates",
            return_value=[],
        ), patch(
            "clipper_agency.agents.visual_director.select_best_candidate",
            return_value=None,
        ):
            agent._apply_best_candidate(plan_item, beat, [{"asset_id": "a1"}])

        assert plan_item["action"]["type"] == "text_card"
        assert plan_item["action"]["headline"] == "Beat 1"

    def test_no_fallback_constructs_minimal_text_card(self) -> None:
        """Without a fallback, a minimal text_card is constructed from beat text."""
        agent = VisualDirectorAgent.__new__(VisualDirectorAgent)
        plan_item: dict[str, Any] = {
            "action": {"type": "tiktok_clip", "source": "rejected.mp4"},
        }
        beat = _make_beat(beat_id=3, overlay_text="Reaction")

        with patch(
            "clipper_agency.agents.visual_director.rank_candidates",
            return_value=[],
        ), patch(
            "clipper_agency.agents.visual_director.select_best_candidate",
            return_value=None,
        ):
            agent._apply_best_candidate(plan_item, beat, [{"asset_id": "a1"}])

        assert plan_item["action"]["type"] == "text_card"
        assert plan_item["action"]["headline"] == "Reaction"

    def test_majority_of_beats_were_rejected(self) -> None:
        """Historical observation: 7 of 8 Job #8 beats were rejected."""
        vd_output = _load("vd_output.json")
        inspections = vd_output["candidate_inspections"]
        rejected = [i for i in inspections if i["decision"] == "reject"]
        accepted = [i for i in inspections if i["decision"] == "accept"]

        assert len(rejected) == 7
        assert len(accepted) == 1
        assert accepted[0]["beat_id"] == 6


# ---------------------------------------------------------------------------
# Bug 2: Beat durations are absurdly wrong
#
# Root cause: visual_director._calculate_beat_durations and
# composer._compute_beat_durations derive timelines independently.
# The VD version searches voice timestamps and produces absurd values
# for some beats (hook=33s, reaction=29s for a 4-word beat).
# ---------------------------------------------------------------------------


class TestBug2AbsurdBeatDurations:
    """CHARACTERIZATION: beat durations are wildly incorrect."""

    def test_hook_duration_is_33_seconds(self) -> None:
        """Hook beat has 33.173s target — absurd for a 15-word opening."""
        vd_output = _load("vd_output.json")
        hook = next(a for a in vd_output["assets"] if a["beat_id"] == 1)

        # BROKEN: hook should be ~4-5s, not 33s
        assert hook["target_duration"] == 33.173

    def test_reaction_duration_is_29_seconds(self) -> None:
        """Reaction beat has 29.681s target — absurd for 4 words (word_range 51-55)."""
        vd_output = _load("vd_output.json")
        reaction = next(a for a in vd_output["assets"] if a["beat_id"] == 7)

        # BROKEN: reaction should be ~3-5s, not 29s
        assert reaction["target_duration"] == 29.681

    def test_reaction_beat_has_only_4_words(self) -> None:
        """Context: beat 7 has word_range [51, 55] — only 4 words for 29.681s."""
        narrative = _load("narrative_structure.json")
        beat7 = next(b for b in narrative if b["beat_id"] == 7)

        assert beat7["word_range"] == [51, 55]
        assert beat7["word_range"][1] - beat7["word_range"][0] == 4


# ---------------------------------------------------------------------------
# Bug 3: fade_to_black uses st=0.0 (fade at clip start, not end)
#
# Root cause: TreatmentFilterBuilder.build() defaults start_time=0.0.
# Composer calls builder.build(asset) without passing start_time.
# The fade_to_black template is "fade=t=out:st={start_time}:d=0.5"
# so every fade-out starts at t=0.0 (beginning of clip) instead of
# near the end (duration - 0.5).
# ---------------------------------------------------------------------------


class TestBug3FadeToBlackStartsAtEnd:
    """FIXED: fade_to_black now uses st=duration-0.5 (fade in last 0.5s)."""

    @pytest.fixture
    def builder(self) -> TreatmentFilterBuilder:
        config = TreatmentConfig(TEMPLATES_PATH)
        return TreatmentFilterBuilder(config)

    def test_fade_to_black_uses_duration_minus_half(self, builder: TreatmentFilterBuilder) -> None:
        """fade_to_black st is computed as duration - 0.5."""
        asset = {
            "treatment": "fade_to_black",
            "target_duration": 5.0,
            "type": "video",
        }

        result = builder.build(asset)

        assert "st=4.5" in result  # 5.0 - 0.5 = 4.5
        assert "st=0.0" not in result  # must NOT be at clip start


class TestBug3BlackFramesInOutput:
    """CHARACTERIZATION: visual_coverage shows 3 BLACK_FRAME hard failures."""

    def test_three_black_frame_issues(self) -> None:
        """visual_coverage reports 3 BLACK_FRAME issues — all hard_fail."""
        coverage = _load("visual_coverage.json")

        black_frames = [
            i for i in coverage["issues"] if i["type"] == "BLACK_FRAME"
        ]

        assert len(black_frames) == 3
        assert all(i["severity"] == "hard_fail" for i in black_frames)

    def test_worst_black_tail_is_13_seconds(self) -> None:
        """The largest black segment is 13533ms — nearly the entire video tail."""
        coverage = _load("visual_coverage.json")

        black_frames = [
            i for i in coverage["issues"] if i["type"] == "BLACK_FRAME"
        ]
        worst = max(black_frames, key=lambda i: i["end_sec"] - i["start_sec"])

        assert worst["detail"] == "Black segment 13533ms > 200ms"

    def test_coverage_status_is_fail(self) -> None:
        """visual_coverage overall status is 'fail'."""
        coverage = _load("visual_coverage.json")
        assert coverage["status"] == "fail"


# ---------------------------------------------------------------------------
# Bug 4: Hard-failed gates don't reach the repair loop
#
# Root cause: engine.py _handle_review_outcome only enters repair if
# review_output["repair_plan"] exists. Deterministic gate failures
# (G3/G6/G7) don't auto-generate repair plans, so the pipeline
# "completes" with hard failures and empty final_outputs.
#
# Manifestation: manifest shows reviewer "completed" despite 3 hard_fail
# gates and final_outputs is empty.
# ---------------------------------------------------------------------------


class TestBug4PipelineCompletesDespiteHardFailures:
    """CHARACTERIZATION: pipeline reports completion despite hard-failed gates."""

    def test_three_gates_hard_failed(self) -> None:
        """Gates G3, G6, G7 all hard_fail."""
        manifest = _load("manifest.json")

        hard_fails = {
            name: gate
            for name, gate in manifest["gates"].items()
            if gate["severity"] == "hard_fail"
        }

        assert set(hard_fails) == {"G3_research_cache", "G6_creative_memory", "G7_script_validation"}

    def test_all_agents_report_completed(self) -> None:
        """All 7 agents (including reviewer) report status=completed."""
        manifest = _load("manifest.json")

        for agent_name, agent in manifest["agents"].items():
            assert agent["status"] == "completed", (
                f"{agent_name} status is {agent['status']}, expected 'completed'"
            )

    def test_reviewer_completed_despite_hard_failures(self) -> None:
        """Reviewer reports 'completed' even though 3 gates hard_failed."""
        manifest = _load("manifest.json")

        assert manifest["agents"]["reviewer"]["status"] == "completed"

        hard_fails = [
            name for name, gate in manifest["gates"].items()
            if gate["severity"] == "hard_fail"
        ]
        assert len(hard_fails) == 3

    def test_final_outputs_is_empty(self) -> None:
        """final_outputs is an empty dict — nothing was published."""
        manifest = _load("manifest.json")
        assert manifest["final_outputs"] == {}


# ---------------------------------------------------------------------------
# Composer status: reports "completed" despite black frames
# (cross-cutting symptom — Bug 1 + Bug 3 combined)
# ---------------------------------------------------------------------------


class TestComposerCompletedDespiteBlackFrames:
    """CHARACTERIZATION: composer marks output 'completed' with known black frames."""

    def test_composer_status_completed(self) -> None:
        """Composer reports status=completed."""
        composer_output = _load("composer_output.json")
        assert composer_output["status"] == "completed"

    def test_composer_output_duration_matches(self) -> None:
        """Output duration is 34.902s — matches the broken video."""
        composer_output = _load("composer_output.json")
        coverage = _load("visual_coverage.json")

        assert composer_output["output_duration_sec"] == coverage["output_duration_sec"]
