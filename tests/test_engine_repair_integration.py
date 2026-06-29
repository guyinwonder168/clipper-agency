"""Integration tests for deterministic gate failure → repair routing (Bug 4).

When the reviewer's deterministic gates (visual_coverage, text_collision,
safe_area, package_consistency, timestamp_semantic) hard-fail, they don't
include an LLM-generated repair_plan. The engine must synthesize a repair
routing dict from the gate failure reason so the repair loop can engage.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from clipper_agency.db.connection import close_connection, get_connection
from clipper_agency.db.queries import (
    create_agent_state,
    create_job,
    mark_agent_completed,
)
from clipper_agency.db.schema import initialize_schema
from clipper_agency.orchestrator.engine import Orchestrator


@pytest.fixture
def db_initialized(tmp_path):
    """Create a fresh DB with schema initialized."""
    db_path = str(tmp_path / "test.db")
    conn = get_connection(db_path)
    initialize_schema(conn)
    conn.close()
    close_connection(db_path)
    yield db_path
    close_connection(db_path)


def _setup_job(db_path, assets_cache, tmp_path):
    """Create a job with all agents completed, ready for review."""
    conn = get_connection(db_path)
    snapshot = {
        "topic": "Gate failure test",
        "niche": "test_niche",
        "output_dir": str(tmp_path / "outputs"),
        "assets_cache": assets_cache,
        "niche_ctx": {
            "safety_rules": ["no_defamation"],
            "channel_description": "Test channel",
            "language": "id",
            "tone": "informal_investigative",
            "content_angle": "Test angle",
        },
    }
    job_id = create_job(conn, "Gate failure test", "test_niche", config_snapshot=snapshot)
    all_agents = [
        "safety",
        "segment_producer",
        "scriptwriter",
        "voice_producer",
        "visual_director",
        "composer",
        "reviewer",
    ]
    for name in all_agents:
        create_agent_state(conn, job_id, name)
        mark_agent_completed(conn, job_id, name)

    # Write output.json for upstream agents
    agent_outputs = {
        "segment_producer": {
            "status": "completed",
            "research_brief": "Brief",
            "sources": [{"url": "https://example.com"}],
            "story_beats": [],
            "risk_flags": [],
        },
        "scriptwriter": {
            "status": "completed",
            "script": [{"scene": 1, "text": "Hello!", "duration": 5}],
            "caption": "Test caption",
            "voiceover_text": "Hello!",
            "hashtags": [],
            "narrative_structure": [],
            "estimated_duration": 5,
        },
        "voice_producer": {
            "status": "completed",
            "audio_files": [],
            "voiceover_path": "",
            "timestamps": [],
            "voiceover_duration_sec": 5.0,
        },
        "visual_director": {
            "status": "completed",
            "assets": [{"scene": 1, "source": "pexels", "path": "v.mp4"}],
        },
        "composer": {
            "status": "completed",
            "video_path": str(tmp_path / "out.mp4"),
            "thumbnail_path": "",
            "duration_sec": 5.0,
        },
    }
    for agent_name, output in agent_outputs.items():
        out_path = Path(assets_cache) / f"job_{job_id}" / "agents" / agent_name / "output.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output), encoding="utf-8")

    close_connection(db_path)
    return job_id


class TestGateFailureRepairRouting:
    """Engine wires deterministic gate failures into the repair loop."""

    def test_visual_coverage_gate_failure_routes_to_visual_director(
        self,
        db_initialized,
        tmp_path,
    ):
        """VISUAL_COVERAGE_FAILED without repair_plan → repair routing to VD."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)

        gate_failure_review = {
            "status": "fail",
            "reason": "VISUAL_COVERAGE_FAILED",
            "score": 0,
            "feedback": "Hard gate: visual coverage failed",
        }

        with patch.object(
            Orchestrator,
            "_run_reviewer",
            return_value=gate_failure_review,
        ):
            abort, review_output, pkg = orch._retry_review_and_package(
                conn=get_connection(db_initialized),
                job_id=job_id,
                topic="Gate failure test",
                script_output={
                    "script": [],
                    "caption": "",
                    "narrative_structure": [],
                    "unverified_claims": [],
                },
                compose_output={
                    "video_path": str(tmp_path / "out.mp4"),
                    "duration_sec": 5.0,
                    "rendered_scene_manifest": [],
                    "diagnostics": {},
                },
                safety_rules=["no_defamation"],
                niche="test_niche",
                output_dir=str(tmp_path / "outputs"),
                assets_cache=ac,
            )

        assert review_output is not None
        assert "repair_routing" in review_output
        routing = review_output["repair_routing"]
        assert routing["target_agent"] == "visual_director"
        assert routing["decision"] == "revise"
        assert len(routing["patches"]) == 1

    def test_package_consistency_gate_failure_routes_to_segment_producer(
        self,
        db_initialized,
        tmp_path,
    ):
        """PACKAGE_CONSISTENCY_FAILED → repair routing to segment_producer."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)

        gate_failure_review = {
            "status": "fail",
            "reason": "PACKAGE_CONSISTENCY_FAILED",
            "score": 0,
            "feedback": "Hard gate: package consistency failed",
        }

        with patch.object(
            Orchestrator,
            "_run_reviewer",
            return_value=gate_failure_review,
        ):
            _, review_output, _ = orch._retry_review_and_package(
                conn=get_connection(db_initialized),
                job_id=job_id,
                topic="Gate failure test",
                script_output={
                    "script": [],
                    "caption": "",
                    "narrative_structure": [],
                    "unverified_claims": [],
                },
                compose_output={
                    "video_path": str(tmp_path / "out.mp4"),
                    "duration_sec": 5.0,
                    "rendered_scene_manifest": [],
                    "diagnostics": {},
                },
                safety_rules=["no_defamation"],
                niche="test_niche",
                output_dir=str(tmp_path / "outputs"),
                assets_cache=ac,
            )

        assert review_output is not None
        routing = review_output["repair_routing"]
        assert routing["target_agent"] == "segment_producer"

    def test_unmapped_failure_still_blocks_without_repair(
        self,
        db_initialized,
        tmp_path,
    ):
        """Unknown failure reason (not in GATE_FAILURE_REPAIR_MAP) → no routing."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)

        unknown_failure_review = {
            "status": "fail",
            "reason": "SOME_UNRECOGNIZED_REASON",
            "score": 0,
        }

        with patch.object(
            Orchestrator,
            "_run_reviewer",
            return_value=unknown_failure_review,
        ):
            _, review_output, _ = orch._retry_review_and_package(
                conn=get_connection(db_initialized),
                job_id=job_id,
                topic="Gate failure test",
                script_output={
                    "script": [],
                    "caption": "",
                    "narrative_structure": [],
                    "unverified_claims": [],
                },
                compose_output={
                    "video_path": str(tmp_path / "out.mp4"),
                    "duration_sec": 5.0,
                    "rendered_scene_manifest": [],
                    "diagnostics": {},
                },
                safety_rules=["no_defamation"],
                niche="test_niche",
                output_dir=str(tmp_path / "outputs"),
                assets_cache=ac,
            )

        assert review_output is not None
        # Unknown reason → no repair routing → stays blocked
        assert "repair_routing" not in review_output


class TestUpstreamCascadeRepair:
    """P2 #1: SP repair triggers full SP→SW→VP→VD→Composer cascade."""

    def test_segment_producer_repair_reruns_full_cascade(
        self,
        db_initialized,
        tmp_path,
    ):
        """SP target_agent reruns all 5 agents, not just cached outputs."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        call_log = []

        def track(name, return_value):
            def _mock(*args, **kwargs):
                call_log.append(name)
                return return_value

            return _mock

        with (
            patch.object(
                orch,
                "_run_researcher",
                side_effect=track(
                    "_run_researcher",
                    {
                        "status": "completed",
                        "story_beats": [],
                        "research_brief": "x",
                        "sources": [],
                        "risk_flags": [],
                    },
                ),
            ),
            patch.object(
                orch,
                "_run_content_scriptwriter",
                side_effect=track(
                    "_run_content_scriptwriter",
                    {
                        "status": "completed",
                        "script": [],
                        "caption": "c",
                        "voiceover_text": "Hello!",
                        "narrative_structure": [{"beat_id": 1, "word_range": [0, 0]}],
                        "unverified_claims": [],
                    },
                ),
            ),
            patch.object(
                orch,
                "_run_voice_producer",
                side_effect=track(
                    "_run_voice_producer",
                    {
                        "status": "completed",
                        "timestamps": [],
                        "voiceover_duration_sec": 5.0,
                    },
                ),
            ),
            patch.object(
                orch,
                "_run_visual_director_phase",
                side_effect=track(
                    "_run_visual_director_phase",
                    {
                        "status": "completed",
                        "assets": [],
                    },
                ),
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=({"status": "completed", "duration_sec": 5.0}, None),
            ),
            patch.object(orch, "_run_reviewer", return_value={"status": "pass", "score": 85}),
        ):
            result = orch._execute_single_repair_cycle(
                cycle=1,
                max_cycles=3,
                target_agent="segment_producer",
                patches=[{"beat_id": "all", "action": "redo_research", "reason": "wrong_event"}],
                before_review={"status": "fail", "reason": "PACKAGE_CONSISTENCY_FAILED"},
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
                conn=conn,
            )

        # All 5 agents rerun in order
        assert call_log == [
            "_run_researcher",
            "_run_content_scriptwriter",
            "_run_voice_producer",
            "_run_visual_director_phase",
        ]
        assert result.get("status") == "completed"
        conn.close()


class TestMultiGateSequentialRepair:
    """P2 #2: After repair, a different gate failure triggers new patches."""

    def test_gate_failure_after_repair_continues_with_new_patches(
        self,
        db_initialized,
        tmp_path,
    ):
        """Post-repair review fails with different gate → continue."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        after_review = {
            "status": "fail",
            "reason": "TEXT_COLLISION_FAILED",
            "score": 0,
        }

        result = orch._handle_review_outcome(
            cycle=1,
            job_id=job_id,
            before_review={"status": "fail", "reason": "VISUAL_COVERAGE_FAILED"},
            after_review=after_review,
            conn=conn,
            assets_cache=ac,
        )

        assert result["_action"] == "continue"
        assert result["target_agent"] == "visual_director"
        assert len(result["patches"]) == 1
        conn.close()

    def test_no_repair_plan_and_no_gate_failure_goes_manual(
        self,
        db_initialized,
        tmp_path,
    ):
        """Neither repair_plan nor gate failure → manual review."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        after_review = {
            "status": "fail",
            "reason": "UNKNOWN_REASON",
            "score": 0,
        }

        result = orch._handle_review_outcome(
            cycle=1,
            job_id=job_id,
            before_review={"status": "fail"},
            after_review=after_review,
            conn=conn,
            assets_cache=ac,
        )

        assert result["_action"] == "return"
        assert result["status"] == "manual_review_required"
        conn.close()
