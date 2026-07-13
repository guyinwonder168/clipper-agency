"""Tests for repair router (pure module)."""

from clipper_agency.config.schema import RepairPlan
from clipper_agency.core.repair_router import (
    GATE_FAILURE_REPAIR_MAP,
    build_gate_failure_repair_plan,
    build_repair_plan,
    route_repair,
)


class TestRepairRouting:
    """Repair routing table tests."""

    def test_routes_wrong_event_to_visual_director(self):
        assert (
            route_repair({"reason": "wrong_event", "action": "replace_visual"}) == "visual_director"
        )

    def test_routes_wrong_event_redo_to_segment_producer(self):
        assert (
            route_repair({"reason": "wrong_event", "action": "redo_research"}) == "segment_producer"
        )

    def test_routes_broken_source_to_visual_director(self):
        assert (
            route_repair({"reason": "broken_source", "action": "replace_visual"})
            == "visual_director"
        )

    def test_routes_text_collision_to_visual_director(self):
        assert route_repair({"reason": "text_collision", "action": "fix_text"}) == "visual_director"

    def test_routes_black_frame_to_composer(self):
        assert route_repair({"reason": "black_frame", "action": "rerender"}) == "composer"

    def test_routes_freeze_frame_to_composer(self):
        assert route_repair({"reason": "freeze_frame", "action": "rerender"}) == "composer"

    def test_routes_duration_mismatch_to_composer(self):
        assert route_repair({"reason": "duration_mismatch", "action": "adjust"}) == "composer"

    def test_routes_package_mismatch_to_segment_producer(self):
        assert (
            route_repair({"reason": "package_mismatch", "action": "narrow_topic"})
            == "segment_producer"
        )

    def test_routes_script_scope_to_segment_producer_and_scriptwriter(self):
        assert (
            route_repair({"reason": "script_scope_mismatch", "action": "rewrite"})
            == "segment_producer_and_scriptwriter"
        )

    def test_routes_unsafe_claim_to_segment_producer_and_scriptwriter(self):
        assert (
            route_repair({"reason": "unsafe_factual_claim", "action": "fix_claim"})
            == "segment_producer_and_scriptwriter"
        )

    def test_routes_unknown_to_visual_director_default(self):
        assert route_repair({"reason": "unknown_issue", "action": "something"}) == "visual_director"


class TestBuildRepairPlan:
    """RepairPlan construction tests."""

    def test_builds_valid_repair_plan(self):
        plan = build_repair_plan(
            decision="revise",
            patches=[
                {
                    "beat_id": "B04",
                    "action": "replace_visual",
                    "reason": "wrong_event",
                    "rerun_from": "visual_director",
                },
            ],
        )
        assert isinstance(plan, RepairPlan)
        assert plan.decision == "revise"
        assert len(plan.patches) == 1
        assert plan.patches[0].beat_id == "B04"

    def test_builds_reject_plan_with_no_patches(self):
        plan = build_repair_plan(decision="reject", patches=[])
        assert plan.decision == "reject"
        assert plan.patches == []

    def test_respects_max_cycles(self):
        plan = build_repair_plan(decision="revise", patches=[], max_cycles=3)
        assert plan.max_repair_cycles == 3


class TestBuildGateFailureRepairPlan:
    """Deterministic gate failure → repair routing tests (Bug 4)."""

    def test_visual_coverage_failure_routes_to_visual_director(self):
        review = {"status": "fail", "reason": "VISUAL_COVERAGE_FAILED"}
        routing = build_gate_failure_repair_plan(review)
        assert routing is not None
        assert routing["target_agent"] == "visual_director"
        assert routing["decision"] == "revise"
        assert len(routing["patches"]) == 1
        assert routing["patches"][0]["reason"] == "broken_source"

    def test_text_collision_failure_routes_to_visual_director(self):
        review = {"status": "fail", "reason": "TEXT_COLLISION_FAILED"}
        routing = build_gate_failure_repair_plan(review)
        assert routing is not None
        assert routing["target_agent"] == "visual_director"
        assert routing["patches"][0]["reason"] == "text_collision"

    def test_safe_area_failure_routes_to_visual_director(self):
        review = {"status": "fail", "reason": "SAFE_AREA_FAILED"}
        routing = build_gate_failure_repair_plan(review)
        assert routing is not None
        assert routing["target_agent"] == "visual_director"
        assert routing["patches"][0]["reason"] == "text_collision"

    def test_package_consistency_failure_routes_to_segment_producer(self):
        review = {"status": "fail", "reason": "PACKAGE_CONSISTENCY_FAILED"}
        routing = build_gate_failure_repair_plan(review)
        assert routing is not None
        assert routing["target_agent"] == "segment_producer"
        assert routing["patches"][0]["reason"] == "wrong_event"
        assert routing["patches"][0]["action"] == "redo_research"

    def test_timestamp_semantic_failure_routes_to_visual_director(self):
        review = {"status": "fail", "reason": "TIMESTAMP_SEMANTIC_FAILED"}
        routing = build_gate_failure_repair_plan(review)
        assert routing is not None
        assert routing["target_agent"] == "visual_director"

    def test_returns_none_for_pass_status(self):
        review = {"status": "pass", "reason": "VISUAL_COVERAGE_FAILED"}
        assert build_gate_failure_repair_plan(review) is None

    def test_returns_none_for_unmapped_reason(self):
        # SEMANTIC_REVIEW_FAILED is not in the map (it has its own repair_plan)
        review = {"status": "fail", "reason": "SEMANTIC_REVIEW_FAILED"}
        assert build_gate_failure_repair_plan(review) is None

    def test_returns_none_for_unknown_reason(self):
        review = {"status": "fail", "reason": "SOMETHING_UNEXPECTED"}
        assert build_gate_failure_repair_plan(review) is None

    def test_returns_none_for_missing_reason(self):
        review = {"status": "fail"}
        assert build_gate_failure_repair_plan(review) is None

    def test_all_gate_failure_reasons_are_mapped(self):
        """Every key in GATE_FAILURE_REPAIR_MAP must produce a valid routing."""
        for reason in GATE_FAILURE_REPAIR_MAP:
            routing = build_gate_failure_repair_plan({"status": "fail", "reason": reason})
            assert routing is not None, f"Reason {reason} returned None"
            assert "target_agent" in routing
            assert "patches" in routing
            assert len(routing["patches"]) >= 1


class TestFix4ReviewerGateRouting:
    """FIX-4 (ADR 0030): the reviewer's per-scene ENTITY_MISMATCH and
    AUDIO_TRUNCATED_REVIEWER reason tokens must route repair to the correct
    agent — wrong entity → Visual Director (replace_visual), truncated audio →
    Composer (redo_compose)."""

    def test_entity_mismatch_routes_to_visual_director(self):
        review = {"status": "fail", "reason": "ENTITY_MISMATCH"}
        routing = build_gate_failure_repair_plan(review)
        assert routing is not None
        assert routing["target_agent"] == "visual_director"
        assert routing["patches"][0]["reason"] == "wrong_entity"
        assert routing["patches"][0]["action"] == "replace_visual"
        assert routing["patches"][0]["rerun_from"] == "visual_director"

    def test_audio_truncated_reviewer_routes_to_composer(self):
        review = {"status": "fail", "reason": "AUDIO_TRUNCATED_REVIEWER"}
        routing = build_gate_failure_repair_plan(review)
        assert routing is not None
        assert routing["target_agent"] == "composer"
        assert routing["patches"][0]["reason"] == "duration_mismatch"
        assert routing["patches"][0]["action"] == "redo_compose"
        assert routing["patches"][0]["rerun_from"] == "composer"

    def test_wrong_entity_reason_routes_to_visual_director(self):
        """The patch reason 'wrong_entity' (distinct from 'wrong_event') routes
        to Visual Director (the wrong-entity asset must be re-selected)."""
        assert (
            route_repair({"reason": "wrong_entity", "action": "replace_visual"})
            == "visual_director"
        )


class TestCoverageTokenRouting:
    """FIX-5 (ADR 0030): the two stable coverage-failure tokens emitted by
    G7 (_enforce_narrative_coverage -> "narrative_not_covered") and FIX-6
    (_enforce_timeline_contract -> "timeline_not_covered") must route repair
    to the ROOT agent (Scriptwriter) so the regen targets the actual defect,
    not a downstream patch."""

    def test_route_narrative_coverage_gap_targets_scriptwriter(self):
        assert (
            route_repair({"reason": "narrative_coverage_gap", "action": "regen_narrative"})
            == "scriptwriter"
        )

    def test_route_timeline_coverage_gap_targets_scriptwriter(self):
        assert (
            route_repair({"reason": "timeline_coverage_gap", "action": "regen_narrative"})
            == "scriptwriter"
        )

    def test_coverage_routing_no_regression_on_existing_reasons(self):
        """Existing reasons keep their original targets."""
        assert (
            route_repair({"reason": "broken_source", "action": "replace_visual"})
            == "visual_director"
        )
        assert (
            route_repair({"reason": "wrong_event", "action": "redo_research"}) == "segment_producer"
        )
        assert route_repair({"reason": "black_frame", "action": "x"}) == "composer"

    def test_build_gate_plan_for_narrative_not_covered(self):
        routing = build_gate_failure_repair_plan(
            {"status": "fail", "reason": "narrative_not_covered"}
        )
        assert routing is not None
        assert routing["decision"] == "revise"
        assert routing["target_agent"] == "scriptwriter"
        patch = routing["patches"][0]
        assert patch["action"] == "regen_narrative"
        assert patch["reason"] == "narrative_coverage_gap"
        assert patch["rerun_from"] == "scriptwriter"
        assert patch["beat_id"] == "global"

    def test_build_gate_plan_for_timeline_not_covered(self):
        routing = build_gate_failure_repair_plan(
            {"status": "fail", "reason": "timeline_not_covered"}
        )
        assert routing is not None
        assert routing["target_agent"] == "scriptwriter"
        patch = routing["patches"][0]
        assert patch["action"] == "regen_narrative"
        assert patch["reason"] == "timeline_coverage_gap"
        assert patch["rerun_from"] == "scriptwriter"
