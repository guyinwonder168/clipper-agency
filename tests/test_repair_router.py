"""Tests for repair router (pure module)."""

import pytest
from clipper_agency.core.repair_router import route_repair, build_repair_plan
from clipper_agency.config.schema import RepairPlan


class TestRepairRouting:
    """Repair routing table tests."""

    def test_routes_wrong_event_to_visual_director(self):
        assert route_repair({"reason": "wrong_event", "action": "replace_visual"}) == "visual_director"

    def test_routes_wrong_event_redo_to_segment_producer(self):
        assert route_repair({"reason": "wrong_event", "action": "redo_research"}) == "segment_producer"

    def test_routes_broken_source_to_visual_director(self):
        assert route_repair({"reason": "broken_source", "action": "replace_visual"}) == "visual_director"

    def test_routes_text_collision_to_visual_director(self):
        assert route_repair({"reason": "text_collision", "action": "fix_text"}) == "visual_director"

    def test_routes_black_frame_to_composer(self):
        assert route_repair({"reason": "black_frame", "action": "rerender"}) == "composer"

    def test_routes_freeze_frame_to_composer(self):
        assert route_repair({"reason": "freeze_frame", "action": "rerender"}) == "composer"

    def test_routes_duration_mismatch_to_composer(self):
        assert route_repair({"reason": "duration_mismatch", "action": "adjust"}) == "composer"

    def test_routes_package_mismatch_to_segment_producer(self):
        assert route_repair({"reason": "package_mismatch", "action": "narrow_topic"}) == "segment_producer"

    def test_routes_script_scope_to_segment_producer_and_scriptwriter(self):
        assert route_repair({"reason": "script_scope_mismatch", "action": "rewrite"}) == "segment_producer_and_scriptwriter"

    def test_routes_unsafe_claim_to_segment_producer_and_scriptwriter(self):
        assert route_repair({"reason": "unsafe_factual_claim", "action": "fix_claim"}) == "segment_producer_and_scriptwriter"

    def test_routes_unknown_to_visual_director_default(self):
        assert route_repair({"reason": "unknown_issue", "action": "something"}) == "visual_director"


class TestBuildRepairPlan:
    """RepairPlan construction tests."""

    def test_builds_valid_repair_plan(self):
        plan = build_repair_plan(
            decision="revise",
            patches=[
                {"beat_id": "B04", "action": "replace_visual", "reason": "wrong_event", "rerun_from": "visual_director"},
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
