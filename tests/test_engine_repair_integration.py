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


class TestCoverageRegenScriptwriter:
    """FIX-5 (ADR 0030): a coverage hard-fail (G7/FIX-6) routes a bounded
    regen loop to the ROOT agent (Scriptwriter), not the cached-upstream /
    visual_director path. Re-used fixtures/mocking style from
    TestUpstreamCascadeRepair."""

    def _covered_structure(self, word_count=4):
        """A narrative_structure whose word_range union fully covers
        [0, word_count-1] (passes G7)."""
        return [
            {"beat_id": 1, "word_range": [0, 1]},
            {"beat_id": 2, "word_range": [2, word_count - 1]},
        ]

    def test_coverage_fail_routes_to_scriptwriter_regen_not_visual_director(
        self, db_initialized, tmp_path
    ):
        """target_agent='scriptwriter' triggers the full cascade (SW re-run),
        not the cached _run_cached_upstream_repair path."""
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

        covered = self._covered_structure()

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
                        "voiceover_text": "one two three four",
                        "narrative_structure": covered,
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
                    "_run_visual_director_phase", {"status": "completed", "assets": []}
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
                target_agent="scriptwriter",
                patches=[
                    {
                        "beat_id": "global",
                        "action": "regen_narrative",
                        "reason": "narrative_coverage_gap",
                        "rerun_from": "scriptwriter",
                    }
                ],
                before_review={"status": "fail", "reason": "narrative_not_covered"},
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
                conn=conn,
            )

        # The full cascade re-ran (SW regen happened, not a cached reload).
        assert "_run_content_scriptwriter" in call_log
        assert result.get("status") == "completed"
        conn.close()

    def test_coverage_refail_aborts_cascade_on_first_attempt(self, db_initialized, tmp_path):
        """G7 mid-cascade abort propagates as a terminal failure on the FIRST
        regen attempt. This pins the G7-abort-propagation contract, NOT the
        max_repair_cycles bound (the abort short-circuits the loop before the
        cycle count matters — the test would pass identically with
        max_repair_cycles=100). The genuine cycle-count bound is pinned by
        test_coverage_repair_cycle_bound_pinned_end_to_end below."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)

        # Always-broken structure: word_range covers only [0,0] of N words.
        broken = [{"beat_id": 1, "word_range": [0, 0]}]

        repair_plan = {
            "max_repair_cycles": 3,
            "patches": [
                {
                    "beat_id": "global",
                    "action": "regen_narrative",
                    "reason": "narrative_coverage_gap",
                    "rerun_from": "scriptwriter",
                }
            ],
        }

        sw_calls = []

        def sw_mock(*args, **kwargs):
            sw_calls.append(kwargs)
            return {
                "status": "completed",
                "script": [],
                "caption": "c",
                "voiceover_text": "one two three four",
                "narrative_structure": broken,
                "unverified_claims": [],
            }

        with (
            patch.object(
                orch,
                "_run_researcher",
                return_value={
                    "status": "completed",
                    "story_beats": [],
                    "research_brief": "x",
                    "sources": [],
                    "risk_flags": [],
                },
            ),
            patch.object(orch, "_run_content_scriptwriter", side_effect=sw_mock),
            patch.object(
                orch,
                "_run_voice_producer",
                return_value={
                    "status": "completed",
                    "timestamps": [],
                    "voiceover_duration_sec": 5.0,
                },
            ),
            patch.object(
                orch,
                "_run_visual_director_phase",
                return_value={"status": "completed", "assets": []},
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=({"status": "completed", "duration_sec": 5.0}, None),
            ),
        ):
            result = orch._execute_repair_cycle(
                repair_plan=repair_plan,
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
            )

        # The G7 abort propagates as a failure on the FIRST regen attempt.
        # The loop terminates immediately — one shot, not max_repair_cycles=3.
        assert len(sw_calls) == 1
        assert result.get("status") != "completed"
        conn = get_connection(db_initialized)
        from clipper_agency.db.queries import get_job

        job = get_job(conn, job_id)
        # Job must NEVER be COMPLETED with an uncovered narrative.
        assert job["status"] != "COMPLETED"
        conn.close()

    def test_regen_threads_cover_all_words_hint_into_scriptwriter(self, db_initialized, tmp_path):
        """The 'cover ALL words' directive is threaded into the actual LLM
        call (coverage_directive kwarg on _run_scriptwriter), not just the
        sentinel plumbing at _run_content_scriptwriter. Mocks one layer BELOW
        _run_content_scriptwriter so a regression that dropped the
        coverage_directive= threading at engine.py would fail here."""
        from clipper_agency.orchestrator.engine import _COVERAGE_REGEN_DIRECTIVE

        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        captured = {}

        def fake_scriptwriter(*args, **kwargs):
            # Capture the directive that actually reaches the LLM seam.
            captured["coverage_directive"] = kwargs.get("coverage_directive", "")
            return {
                "status": "completed",
                "script": [],
                "caption": "c",
                "voiceover_text": "one two three four",
                "narrative_structure": self._covered_structure(),
                "unverified_claims": [],
            }

        with (
            patch.object(
                orch,
                "_run_researcher",
                return_value={
                    "status": "completed",
                    "story_beats": [],
                    "research_brief": "x",
                    "sources": [],
                    "risk_flags": [],
                },
            ),
            # _run_content_scriptwriter stays REAL so its coverage_directive=
            # threading (engine.py ~2843) is exercised; only _run_scriptwriter
            # (the LLM seam one layer below) is mocked.
            patch.object(orch, "_run_scriptwriter", side_effect=fake_scriptwriter),
            patch.object(
                orch,
                "_run_voice_producer",
                return_value={
                    "status": "completed",
                    "timestamps": [],
                    "voiceover_duration_sec": 5.0,
                },
            ),
            patch.object(
                orch,
                "_run_visual_director_phase",
                return_value={
                    "status": "completed",
                    "assets": [],
                },
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=(
                    {"status": "completed", "duration_sec": 5.0},
                    None,
                ),
            ),
            patch.object(orch, "_run_reviewer", return_value={"status": "pass", "score": 85}),
        ):
            orch._execute_single_repair_cycle(
                cycle=1,
                max_cycles=3,
                target_agent="scriptwriter",
                patches=[
                    {
                        "beat_id": "global",
                        "action": "regen_narrative",
                        "reason": "narrative_coverage_gap",
                        "rerun_from": "scriptwriter",
                    }
                ],
                before_review={"status": "fail", "reason": "narrative_not_covered"},
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
                conn=conn,
            )

        # The "cover ALL words" directive must reach the LLM call verbatim.
        assert captured.get("coverage_directive") == _COVERAGE_REGEN_DIRECTIVE
        conn.close()


class TestCoverageAbortEntryPath:
    """FIX-5 (ADR 0030, pr-test-analyzer P1): the REAL entry path —
    _is_coverage_repairable_abort → _route_coverage_abort_to_repair →
    _finalize_coverage_repair — was previously untested (the existing
    TestCoverageRegenScriptwriter tests bypassed it by calling
    _execute_single_repair_cycle / _execute_repair_cycle directly). These
    tests drive the entry point with a real G7/FIX-6 abort dict."""

    def _g7_abort(self, job_id):
        """A G7 narrative_not_covered abort dict (mirrors engine.py ~1026)."""
        return {
            "status": "failed",
            "failed_at": "narrative_coverage",
            "reason": "narrative coverage gap",
            "job_id": job_id,
            "gate_reason": "narrative_not_covered",
        }

    def _timeline_abort(self, job_id):
        """A FIX-6 timeline_not_covered abort dict."""
        return {
            "status": "failed",
            "failed_at": "timeline_contract",
            "reason": "timeline contract violated",
            "job_id": job_id,
            "gate_reason": "timeline_not_covered",
        }

    def test_is_coverage_repairable_abort_classifies_tokens(self):
        orch = Orchestrator(db_path=":memory:")
        assert orch._is_coverage_repairable_abort(self._g7_abort(1)) is True
        assert orch._is_coverage_repairable_abort(self._timeline_abort(1)) is True
        # Non-coverage aborts + None are NOT repairable via the regen loop.
        assert orch._is_coverage_repairable_abort(None) is False
        assert (
            orch._is_coverage_repairable_abort({"status": "failed", "reason": "other_failure"})
            is False
        )

    def test_g7_abort_routes_to_repair_not_terminal_hardfail_on_success(
        self, db_initialized, tmp_path
    ):
        """End-to-end: a G7 abort enters _route_coverage_abort_to_repair; when
        the regen succeeds + packaging passes, _finalize_coverage_repair
        promotes the job to COMPLETED with the REAL topic threaded through
        (not empty)."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)
        # Seed a composer output so _finalize_coverage_repair can package.
        video_path = tmp_path / "final.mp4"
        video_path.write_bytes(b"fake-mp4")
        compose_out = {
            "status": "completed",
            "video_path": str(video_path),
            "duration_sec": 5.0,
            "template_name": None,
        }
        Path(ac, f"job_{job_id}", "agents", "composer", "output.json").parent.mkdir(
            parents=True, exist_ok=True
        )
        Path(ac, f"job_{job_id}", "agents", "composer", "output.json").write_text(
            json.dumps(compose_out), encoding="utf-8"
        )
        Path(ac, f"job_{job_id}", "agents", "scriptwriter", "output.json").parent.mkdir(
            parents=True, exist_ok=True
        )
        Path(ac, f"job_{job_id}", "agents", "scriptwriter", "output.json").write_text(
            json.dumps({"caption": "c"}), encoding="utf-8"
        )

        with (
            patch.object(
                orch,
                "_execute_repair_cycle",
                return_value={"status": "completed", "cycle": 1},
            ),
            patch.object(orch, "_package_output") as pkg,
            patch.object(orch, "_promote_to_final") as promote,
        ):
            pkg.return_value = {"status": "completed", "video_path": str(video_path)}
            result = orch._route_coverage_abort_to_repair(
                self._g7_abort(job_id),
                conn,
                job_id,
                topic="REAL TOPIC",
                niche="test_niche",
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
            )

        # topic threaded through to _package_output (not "").
        assert pkg.call_args.kwargs["topic"] == "REAL TOPIC"
        assert result["status"] == "completed"
        promote.assert_called_once()
        from clipper_agency.db.queries import get_job

        assert get_job(conn, job_id)["status"] == "COMPLETED"
        conn.close()

    def test_g7_abort_terminally_fails_on_coverage_refail(self, db_initialized, tmp_path):
        """End-to-end: a G7 abort whose regen STILL fails coverage must end
        with job.status == 'FAILED' (the FIX-5 anti-job_18 guarantee at the
        REAL entry path, not the generic exhaustion != COMPLETED check)."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        with patch.object(
            orch,
            "_execute_repair_cycle",
            return_value={"status": "exhausted", "reason": "Repair cycles exhausted"},
        ):
            result = orch._route_coverage_abort_to_repair(
                self._g7_abort(job_id),
                conn,
                job_id,
                topic="T",
                niche="test_niche",
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
            )

        # Terminal FAILED — NOT 'running' / 'repair_running' limbo.
        assert result["status"] == "failed"
        assert result["repair_status"] == "exhausted"
        from clipper_agency.db.queries import get_job

        assert get_job(conn, job_id)["status"] == "FAILED"
        conn.close()

    def test_timeline_abort_routes_to_repair_terminally_fails(self, db_initialized, tmp_path):
        """FIX-6 timeline_not_covered abort takes the same entry path and
        terminally FAILs when the regen cannot produce a physical timeline."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        with patch.object(
            orch,
            "_execute_repair_cycle",
            return_value={"status": "failed", "reason": "still uncovered"},
        ):
            result = orch._route_coverage_abort_to_repair(
                self._timeline_abort(job_id),
                conn,
                job_id,
                topic="T",
                niche="test_niche",
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
            )

        assert result["status"] == "failed"
        from clipper_agency.db.queries import get_job

        assert get_job(conn, job_id)["status"] == "FAILED"
        conn.close()

    def test_finalize_coverage_repair_fails_on_packaging_failure(self, db_initialized, tmp_path):
        """FIX-5 (Codex P2): a packaging failure MUST NOT mark the job
        COMPLETED — terminal FAIL with repair_status=packaging_failed."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        with patch.object(
            orch,
            "_package_output",
            return_value={"status": "failed", "error": "missing video"},
        ):
            result = orch._finalize_coverage_repair(
                conn,
                job_id,
                topic="T",
                niche="test_niche",
                output_dir=str(tmp_path / "outputs"),
                assets_cache=ac,
                repair_result={"status": "completed", "cycle": 1},
            )

        assert result["status"] == "failed"
        assert result["repair_status"] == "packaging_failed"
        from clipper_agency.db.queries import get_job

        assert get_job(conn, job_id)["status"] == "FAILED"
        conn.close()

    def test_finalize_coverage_repair_fails_on_promotion_failure(self, db_initialized, tmp_path):
        """FIX-5 (Codex P2): a _promote_to_final failure MUST NOT mark the job
        COMPLETED — terminal FAIL with repair_status=promotion_failed. Mirrors
        the non-repair promotion path which gates publication on promotion
        succeeding. Without this gate a missing cycle_{n} source dir or an
        atomic-rename exception would leave the DB reporting COMPLETED with NO
        final/job_* artifacts produced (silent-complete-garbage, anti-job_18)."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)
        # Seed a composer output so packaging succeeds (promotion is the
        # failing stage under test, not packaging).
        video_path = tmp_path / "final.mp4"
        video_path.write_bytes(b"fake-mp4")
        compose_out = {
            "status": "completed",
            "video_path": str(video_path),
            "duration_sec": 5.0,
            "template_name": None,
        }
        Path(ac, f"job_{job_id}", "agents", "composer", "output.json").parent.mkdir(
            parents=True, exist_ok=True
        )
        Path(ac, f"job_{job_id}", "agents", "composer", "output.json").write_text(
            json.dumps(compose_out), encoding="utf-8"
        )
        Path(ac, f"job_{job_id}", "agents", "scriptwriter", "output.json").parent.mkdir(
            parents=True, exist_ok=True
        )
        Path(ac, f"job_{job_id}", "agents", "scriptwriter", "output.json").write_text(
            json.dumps({"caption": "c"}), encoding="utf-8"
        )

        with (
            patch.object(
                orch,
                "_package_output",
                return_value={"status": "completed", "video_path": str(video_path)},
            ),
            patch.object(
                orch,
                "_promote_to_final",
                return_value={"status": "failed", "error": "source dir missing"},
            ),
        ):
            result = orch._finalize_coverage_repair(
                conn,
                job_id,
                topic="T",
                niche="test_niche",
                output_dir=str(tmp_path / "outputs"),
                assets_cache=ac,
                repair_result={"status": "completed", "cycle": 1},
            )

        assert result["status"] == "failed"
        assert result["repair_status"] == "promotion_failed"
        from clipper_agency.db.queries import get_job

        assert get_job(conn, job_id)["status"] == "FAILED"
        conn.close()

    def test_coverage_repair_cycle_bound_pinned_end_to_end(self, db_initialized, tmp_path):
        """pr-test-analyzer finding: pin the anti-job_18 bounded-regen
        constant _COVERAGE_MAX_REPAIR_CYCLES (=1) at the REAL entry path
        (_route_coverage_abort_to_repair → _execute_repair_cycle), WITHOUT
        mocking _execute_repair_cycle. A Scriptwriter that always returns an
        UNCOVERED narrative_structure must result in exactly
        _COVERAGE_MAX_REPAIR_CYCLES Scriptwriter regen attempts (not N, not
        unbounded) and a terminal FAILED job. If someone changed the constant
        from 1 to e.g. 5, this test fails."""
        from clipper_agency.orchestrator.engine import _COVERAGE_MAX_REPAIR_CYCLES

        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        # Always-broken structure: word_range covers only [0,0] of N words.
        broken = [{"beat_id": 1, "word_range": [0, 0]}]
        sw_calls = []

        def sw_mock(*args, **kwargs):
            sw_calls.append(kwargs)
            return {
                "status": "completed",
                "script": [],
                "caption": "c",
                "voiceover_text": "one two three four",
                "narrative_structure": broken,
                "unverified_claims": [],
            }

        with (
            patch.object(
                orch,
                "_run_researcher",
                return_value={
                    "status": "completed",
                    "story_beats": [],
                    "research_brief": "x",
                    "sources": [],
                    "risk_flags": [],
                },
            ),
            patch.object(orch, "_run_content_scriptwriter", side_effect=sw_mock),
            patch.object(
                orch,
                "_run_voice_producer",
                return_value={
                    "status": "completed",
                    "timestamps": [],
                    "voiceover_duration_sec": 5.0,
                },
            ),
            patch.object(
                orch,
                "_run_visual_director_phase",
                return_value={"status": "completed", "assets": []},
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=({"status": "completed", "duration_sec": 5.0}, None),
            ),
            # _execute_repair_cycle is NOT mocked — the real loop runs.
        ):
            result = orch._route_coverage_abort_to_repair(
                self._g7_abort(job_id),
                conn,
                job_id,
                topic="T",
                niche="test_niche",
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
            )

        # The bound is pinned directly: regen attempts == the constant.
        assert len(sw_calls) == _COVERAGE_MAX_REPAIR_CYCLES
        # G7 abort on the regen propagates as terminal FAILED (never COMPLETED).
        assert result["status"] == "failed"
        from clipper_agency.db.queries import get_job

        assert get_job(conn, job_id)["status"] == "FAILED"
        conn.close()


class TestDuplicatePatchGuard:
    """FIX-5 (pr-test-analyzer): unit coverage for the SECONDARY termination
    mechanism — _check_duplicate_patches. This bounds coverage-regen when a
    regen passes G7 in the cascade but re-fails downstream (the only way to
    reach cycle 2). Verified independently of the cycle-count primary bound."""

    def test_identical_patches_on_cycle_two_returns_exhausted(self, db_initialized, tmp_path):
        """When cycle>=2 sees a patch identical to cycle 1's, the guard fires:
        returns an 'exhausted' dict with _action='return' (caller stops)."""
        from clipper_agency.db.connection import get_connection

        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        patch = [
            {
                "beat_id": "global",
                "action": "regen_narrative",
                "reason": "narrative_coverage_gap",
                "rerun_from": "scriptwriter",
            }
        ]
        # Seed cycle 1's persisted patches.
        orch._save_previous_patches(ac, job_id, patch)

        result = orch._check_duplicate_patches(
            cycle=2, job_id=job_id, patches=patch, assets_cache=ac, conn=conn
        )

        assert result is not None
        assert result["_action"] == "return"
        assert result["status"] == "exhausted"
        conn.close()

    def test_non_identical_patches_returns_none(self, db_initialized, tmp_path):
        """When the patch differs from the previous cycle's (different action
        / reason / beat_id / rerun_from), the guard does NOT fire — returns
        None so the cycle proceeds."""
        from clipper_agency.db.connection import get_connection

        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        prev_patch = [
            {
                "beat_id": "global",
                "action": "regen_narrative",
                "reason": "narrative_coverage_gap",
                "rerun_from": "scriptwriter",
            }
        ]
        # Different action → not identical.
        curr_patch = [
            {
                "beat_id": "global",
                "action": "revise_visuals",
                "reason": "visual_coverage_failed",
                "rerun_from": "visual_director",
            }
        ]
        orch._save_previous_patches(ac, job_id, prev_patch)

        result = orch._check_duplicate_patches(
            cycle=2, job_id=job_id, patches=curr_patch, assets_cache=ac, conn=conn
        )

        assert result is None
        conn.close()

    def test_no_previous_patches_returns_none(self, db_initialized, tmp_path):
        """Cycle 1 (no persisted previous patches) never trips the guard."""
        from clipper_agency.db.connection import get_connection

        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        patch = [{"beat_id": "global", "action": "regen_narrative"}]
        result = orch._check_duplicate_patches(
            cycle=1, job_id=job_id, patches=patch, assets_cache=ac, conn=conn
        )

        assert result is None
        conn.close()

    def test_reset_previous_patches_clears_cross_run_stale_state(self, db_initialized, tmp_path):
        """FIX-5 (silent-failure P2): _execute_repair_cycle clears any persisted
        previous_patches.json at the start of a run so a retry/resume of a job
        that previously went through a coverage repair cycle does NOT falsely
        exhaust cycle 1 of the new run. The coverage-regen patch is a CONSTANT
        (build_gate_failure_repair_plan), so without the reset a stale
        persisted file byte-matches cycle 1 and bypasses the regen attempt."""
        from pathlib import Path

        from clipper_agency.db.connection import get_connection

        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        # Seed a stale persisted file from a PRIOR run (cross-run state).
        patch = [
            {
                "beat_id": "global",
                "action": "regen_narrative",
                "reason": "narrative_coverage_gap",
                "rerun_from": "scriptwriter",
            }
        ]
        orch._save_previous_patches(ac, job_id, patch)
        prev_path = Path(ac) / f"job_{job_id}" / "repair" / "previous_patches.json"
        assert prev_path.exists()

        orch._reset_previous_patches(ac, job_id)

        # Stale state cleared — cycle 1 of a new run would now proceed.
        assert not prev_path.exists()
        conn.close()


class TestVoDiffSkip:
    """FIX-5 (claude-auto-tok pattern): skip Voice Producer TTS when a
    Scriptwriter regen leaves voiceover_text byte-identical to the cached
    previous voiceover. Reuses cached audio + timestamps (audio is master)."""

    def _write_cached_voiceover(
        self, assets_cache, job_id, voiceover_text, path=None, create_file=True
    ):
        """Mirror the REAL Voice Producer output: write output.json and create
        the referenced audio file on disk so the cache-integrity guard
        (Path.is_file()) passes. Pass ``create_file=False`` to simulate a
        dangling reference (file deleted from disk)."""
        if path is None:
            path = str(
                Path(assets_cache) / f"job_{job_id}" / "agents" / "voice_producer" / "audio.mp4"
            )
        out_path = (
            Path(assets_cache) / f"job_{job_id}" / "agents" / "voice_producer" / "output.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if create_file:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"fake-audio")
        import json as _json

        out_path.write_text(
            _json.dumps(
                {
                    "status": "completed",
                    "voiceover_text": voiceover_text,
                    "voiceover_path": path,
                    # One timestamp per word (mirrors real Voice Producer) so
                    # the cache is internally consistent: byte-identical text
                    # => identical word_count => cached timestamps stay valid.
                    "timestamps": [
                        {"word": w, "start": float(i), "end": float(i + 1)}
                        for i, w in enumerate(voiceover_text.split())
                    ],
                    "voiceover_duration_sec": 5.0,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_vo_diff_skip_reuses_cached_audio_when_voiceover_unchanged(
        self, db_initialized, tmp_path
    ):
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        same_text = "one two three four"
        self._write_cached_voiceover(ac, job_id, same_text)

        voice_calls = []

        def voice_mock(**kwargs):
            voice_calls.append(kwargs)
            return {"status": "completed", "timestamps": [], "voiceover_duration_sec": 5.0}

        with (
            patch.object(
                orch,
                "_run_researcher",
                return_value={
                    "status": "completed",
                    "story_beats": [],
                    "research_brief": "x",
                    "sources": [],
                    "risk_flags": [],
                },
            ),
            patch.object(
                orch,
                "_run_content_scriptwriter",
                return_value={
                    "status": "completed",
                    "script": [],
                    "caption": "c",
                    "voiceover_text": same_text,
                    "narrative_structure": [{"beat_id": 1, "word_range": [0, 3]}],
                    "unverified_claims": [],
                },
            ),
            patch.object(orch, "_run_voice_producer", side_effect=voice_mock),
            patch.object(
                orch,
                "_run_visual_director_phase",
                return_value={
                    "status": "completed",
                    "assets": [],
                },
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=(
                    {"status": "completed", "duration_sec": 5.0},
                    None,
                ),
            ),
            patch.object(orch, "_run_reviewer", return_value={"status": "pass", "score": 85}),
        ):
            orch._execute_single_repair_cycle(
                cycle=1,
                max_cycles=3,
                target_agent="scriptwriter",
                patches=[
                    {
                        "beat_id": "global",
                        "action": "regen_narrative",
                        "reason": "narrative_coverage_gap",
                        "rerun_from": "scriptwriter",
                    }
                ],
                before_review={"status": "fail"},
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
                conn=conn,
            )

        # voiceover_text unchanged → Voice Producer MUST NOT be re-invoked.
        assert voice_calls == []
        conn.close()

    def test_vo_diff_skip_regens_when_voiceover_text_changed(self, db_initialized, tmp_path):
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        self._write_cached_voiceover(ac, job_id, "old narration text")
        new_text = "completely different narration"

        voice_calls = []

        def voice_mock(**kwargs):
            voice_calls.append(kwargs)
            return {"status": "completed", "timestamps": [], "voiceover_duration_sec": 5.0}

        with (
            patch.object(
                orch,
                "_run_researcher",
                return_value={
                    "status": "completed",
                    "story_beats": [],
                    "research_brief": "x",
                    "sources": [],
                    "risk_flags": [],
                },
            ),
            patch.object(
                orch,
                "_run_content_scriptwriter",
                return_value={
                    "status": "completed",
                    "script": [],
                    "caption": "c",
                    "voiceover_text": new_text,
                    "narrative_structure": [{"beat_id": 1, "word_range": [0, 2]}],
                    "unverified_claims": [],
                },
            ),
            patch.object(orch, "_run_voice_producer", side_effect=voice_mock),
            patch.object(
                orch,
                "_run_visual_director_phase",
                return_value={
                    "status": "completed",
                    "assets": [],
                },
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=(
                    {"status": "completed", "duration_sec": 5.0},
                    None,
                ),
            ),
            patch.object(orch, "_run_reviewer", return_value={"status": "pass", "score": 85}),
        ):
            orch._execute_single_repair_cycle(
                cycle=1,
                max_cycles=3,
                target_agent="scriptwriter",
                patches=[
                    {
                        "beat_id": "global",
                        "action": "regen_narrative",
                        "reason": "narrative_coverage_gap",
                        "rerun_from": "scriptwriter",
                    }
                ],
                before_review={"status": "fail"},
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
                conn=conn,
            )

        # voiceover_text CHANGED → Voice Producer runs once.
        assert len(voice_calls) == 1
        conn.close()

    def test_vo_diff_skip_falls_through_when_cache_missing_path(self, db_initialized, tmp_path):
        """Cache-integrity guard: no valid voiceover_path → regen even if
        text matches."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        same_text = "one two three four"
        # Cached voiceover has NO voiceover_path (corrupt/incomplete cache).
        out_path = Path(ac) / f"job_{job_id}" / "agents" / "voice_producer" / "output.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"status": "completed", "voiceover_text": same_text, "voiceover_path": ""}),
            encoding="utf-8",
        )

        voice_calls = []

        def voice_mock(**kwargs):
            voice_calls.append(kwargs)
            return {"status": "completed", "timestamps": [], "voiceover_duration_sec": 5.0}

        with (
            patch.object(
                orch,
                "_run_researcher",
                return_value={
                    "status": "completed",
                    "story_beats": [],
                    "research_brief": "x",
                    "sources": [],
                    "risk_flags": [],
                },
            ),
            patch.object(
                orch,
                "_run_content_scriptwriter",
                return_value={
                    "status": "completed",
                    "script": [],
                    "caption": "c",
                    "voiceover_text": same_text,
                    "narrative_structure": [{"beat_id": 1, "word_range": [0, 3]}],
                    "unverified_claims": [],
                },
            ),
            patch.object(orch, "_run_voice_producer", side_effect=voice_mock),
            patch.object(
                orch,
                "_run_visual_director_phase",
                return_value={
                    "status": "completed",
                    "assets": [],
                },
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=(
                    {"status": "completed", "duration_sec": 5.0},
                    None,
                ),
            ),
            patch.object(orch, "_run_reviewer", return_value={"status": "pass", "score": 85}),
        ):
            orch._execute_single_repair_cycle(
                cycle=1,
                max_cycles=3,
                target_agent="scriptwriter",
                patches=[
                    {
                        "beat_id": "global",
                        "action": "regen_narrative",
                        "reason": "narrative_coverage_gap",
                        "rerun_from": "scriptwriter",
                    }
                ],
                before_review={"status": "fail"},
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
                conn=conn,
            )

        # Cache invalid → regen even though text matched.
        assert len(voice_calls) == 1
        conn.close()

    def test_vo_diff_skip_does_not_fire_when_cache_has_no_voiceover_text(
        self, db_initialized, tmp_path
    ):
        """Production-divergence regression: the REAL Voice Producer contract
        (config/schema.VoiceoverOutput) has no voiceover_text field. Before
        FIX-5 round-2 the orchestrator stamped the text onto the persisted
        output, so a real cache had no text and the skip NEVER fired. This
        test seeds the cache WITHOUT voiceover_text (mirroring the pre-fix
        agent output) and asserts Voice Producer is invoked (no skip)."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        same_text = "one two three four"
        # Cache mirrors real agent output: NO voiceover_text key.
        audio_path = str(Path(ac) / f"job_{job_id}" / "agents" / "voice_producer" / "audio.mp4")
        out_path = Path(ac) / f"job_{job_id}" / "agents" / "voice_producer" / "output.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).write_bytes(b"fake-audio")
        out_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "voiceover_path": audio_path,
                    "timestamps": [{"word": "hello", "start": 0.0, "end": 1.0}],
                    "voiceover_duration_sec": 5.0,
                }
            ),
            encoding="utf-8",
        )

        voice_calls = []

        def voice_mock(**kwargs):
            voice_calls.append(kwargs)
            return {"status": "completed", "timestamps": [], "voiceover_duration_sec": 5.0}

        with (
            patch.object(
                orch,
                "_run_researcher",
                return_value={
                    "status": "completed",
                    "story_beats": [],
                    "research_brief": "x",
                    "sources": [],
                    "risk_flags": [],
                },
            ),
            patch.object(
                orch,
                "_run_content_scriptwriter",
                return_value={
                    "status": "completed",
                    "script": [],
                    "caption": "c",
                    "voiceover_text": same_text,
                    "narrative_structure": [{"beat_id": 1, "word_range": [0, 3]}],
                    "unverified_claims": [],
                },
            ),
            patch.object(orch, "_run_voice_producer", side_effect=voice_mock),
            patch.object(
                orch,
                "_run_visual_director_phase",
                return_value={"status": "completed", "assets": []},
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=({"status": "completed", "duration_sec": 5.0}, None),
            ),
            patch.object(orch, "_run_reviewer", return_value={"status": "pass", "score": 85}),
        ):
            orch._execute_single_repair_cycle(
                cycle=1,
                max_cycles=3,
                target_agent="scriptwriter",
                patches=[
                    {
                        "beat_id": "global",
                        "action": "regen_narrative",
                        "reason": "narrative_coverage_gap",
                        "rerun_from": "scriptwriter",
                    }
                ],
                before_review={"status": "fail"},
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
                conn=conn,
            )

        # No comparable cached text → Voice Producer runs (no skip).
        assert len(voice_calls) == 1
        conn.close()

    def test_vo_diff_skip_does_not_reuse_when_new_voiceover_is_empty(
        self, db_initialized, tmp_path
    ):
        """Latent empty-reuse bug (direct unit test of the skip guard): if the
        new run's voiceover_text is empty (Scriptwriter parse failure), the
        skip MUST return None even when cached text exists — reusing stale
        audio for an empty new voiceover would desync the timeline.

        Tested at the _maybe_reuse_cached_voiceover seam directly: via the
        real cascade an empty voiceover_text fails G7 (word_count=0) before
        reaching Voice Producer, so the guard is unreachable end-to-end — but
        the guard's own correctness (empty != reuse) must still be pinned."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)

        # Seed a valid cached voiceover (file on disk + non-empty text).
        self._write_cached_voiceover(ac, job_id, "old narration")
        from clipper_agency.orchestrator.engine import RepairCycleContext

        ctx = RepairCycleContext(
            cycle=1,
            job_id=job_id,
            topic="T",
            output_dir=str(tmp_path / "outputs"),
            assets_cache=ac,
            conn=None,
            niche_ctx={},
            target_agent="scriptwriter",
            target_idx=2,
            repair_hint="regen_narrative",
        )
        # Empty new text → skip returns None (no reuse) despite matching cache.
        result = orch._maybe_reuse_cached_voiceover(ctx, {"voiceover_text": ""})
        assert result is None

    def test_vo_diff_skip_regens_when_cached_audio_file_missing_from_disk(
        self, db_initialized, tmp_path
    ):
        """Cache-integrity backstop: the JSON references an audio path but the
        file was deleted from disk (cross-job cleanup / partial fs). The skip
        MUST NOT fire — Voice Producer must regenerate."""
        ac = str(tmp_path / "cache")
        job_id = _setup_job(db_initialized, ac, tmp_path)
        orch = Orchestrator(db_path=db_initialized)
        conn = get_connection(db_initialized)

        same_text = "one two three four"
        # create_file=False → path string truthy but file absent on disk.
        self._write_cached_voiceover(ac, job_id, same_text, create_file=False)

        voice_calls = []

        def voice_mock(**kwargs):
            voice_calls.append(kwargs)
            return {"status": "completed", "timestamps": [], "voiceover_duration_sec": 5.0}

        with (
            patch.object(
                orch,
                "_run_researcher",
                return_value={
                    "status": "completed",
                    "story_beats": [],
                    "research_brief": "x",
                    "sources": [],
                    "risk_flags": [],
                },
            ),
            patch.object(
                orch,
                "_run_content_scriptwriter",
                return_value={
                    "status": "completed",
                    "script": [],
                    "caption": "c",
                    "voiceover_text": same_text,
                    "narrative_structure": [{"beat_id": 1, "word_range": [0, 3]}],
                    "unverified_claims": [],
                },
            ),
            patch.object(orch, "_run_voice_producer", side_effect=voice_mock),
            patch.object(
                orch,
                "_run_visual_director_phase",
                return_value={"status": "completed", "assets": []},
            ),
            patch.object(
                orch,
                "_retry_composer_stage",
                return_value=({"status": "completed", "duration_sec": 5.0}, None),
            ),
            patch.object(orch, "_run_reviewer", return_value={"status": "pass", "score": 85}),
        ):
            orch._execute_single_repair_cycle(
                cycle=1,
                max_cycles=3,
                target_agent="scriptwriter",
                patches=[
                    {
                        "beat_id": "global",
                        "action": "regen_narrative",
                        "reason": "narrative_coverage_gap",
                        "rerun_from": "scriptwriter",
                    }
                ],
                before_review={"status": "fail"},
                job_id=job_id,
                assets_cache=ac,
                output_dir=str(tmp_path / "outputs"),
                topic="Test",
                conn=conn,
            )

        # Audio file missing from disk → regen despite matching text.
        assert len(voice_calls) == 1
        conn.close()


class TestTopologyUnchanged:
    """RISK-1 regression: FIX-5 only added routing entries + a loop
    intercept + a vo-diff guard. Topology + audio-first sequence preserved."""

    def test_pipeline_order_unchanged_audio_first(self):
        from clipper_agency.orchestrator.engine import PIPELINE_ORDER

        assert PIPELINE_ORDER == [
            "safety",
            "segment_producer",
            "scriptwriter",
            "voice_producer",
            "visual_director",
            "composer",
            "reviewer",
        ]

    def test_seven_agents_ten_gates_audio_master(self):
        from clipper_agency.orchestrator.engine import PIPELINE_ORDER

        # 7 agents in PIPELINE_ORDER (reviewer is the 7th).
        agents = [a for a in PIPELINE_ORDER if a != "reviewer"]
        assert len(agents) == 6  # 6 production agents + 1 reviewer = 7
        # Voice Producer runs BEFORE Visual Director (audio-first, ADR 0020).
        assert PIPELINE_ORDER.index("voice_producer") < PIPELINE_ORDER.index("visual_director")
