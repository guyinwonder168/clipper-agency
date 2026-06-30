"""Engine integration tests for the FIX-6 timeline contract gate (ADR 0030).

Asserts that ``_enforce_timeline_contract`` (the backstop for G7 / FIX-1):
- returns ``(timeline, None)`` on a healthy timeline,
- on a MAX_BEAT_EXCEEDED violation atomically writes job=FAILED +
  agent_state(scriptwriter)=failed in ONE transaction (no half-committed
  job=FAILED + scriptwriter=completed — the Codex P2 lesson from G7),
- records the FIX6_timeline_contract gate artifact on disk,
- rolls back + re-raises on a transient DB error,
- and that every engine ``build_canonical_timeline`` call site routes through
  it (normal / repair / cache-repair / review-retry / resume).

Fully offline: no LLM, no real agents, no network.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from clipper_agency.db.connection import close_connection, get_connection
from clipper_agency.db.queries import (
    create_agent_state,
    create_job,
    get_agent_state,
    get_job,
)
from clipper_agency.orchestrator.engine import Orchestrator

# ── Fixtures ──


def _make_orchestrator(tmp_path: Path) -> Orchestrator:
    return Orchestrator(db_path=str(tmp_path / "fix6_engine.db"))


def _seed_job(conn, assets_cache: str) -> int:
    """Create a job + a scriptwriter agent_state row. Returns the job_id."""
    job_id = create_job(conn, topic="t", niche="n")
    create_agent_state(conn, job_id, "scriptwriter")
    return job_id


def _healthy_narrative_and_ts():
    """A well-covered 2-beat timeline (no FIX-6 violation)."""
    ts = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 1.0, "end": 1.5},
        {"word": "c", "start": 2.0, "end": 2.5},
        {"word": "d", "start": 3.0, "end": 3.5},
    ]
    narrative = [
        {"beat_id": 1, "word_range": [0, 1]},
        {"beat_id": 2, "word_range": [2, 3]},
    ]
    return narrative, ts


def _mega_beat_narrative_and_ts():
    """job_18 replay: last beat manufactured > 12s (MAX_BEAT_EXCEEDED)."""
    ts = []
    step = 35.0 / 75
    for i in range(76):
        start = i * step
        ts.append({"word": f"w{i}", "start": start, "end": start + step * 0.5})
    ts[-1]["end"] = 35.0
    narrative = [
        {"beat_id": 1, "word_range": [0, 10]},
        {"beat_id": 2, "word_range": [11, 17]},
        {"beat_id": 3, "word_range": [18, 23]},
    ]
    return narrative, ts


# ── _enforce_timeline_contract unit tests ──


class TestEnforceTimelineContract:
    def test_returns_timeline_none_on_success(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            narrative, ts = _healthy_narrative_and_ts()
            timeline, abort = orch._enforce_timeline_contract(
                conn, job_id, str(tmp_path), narrative, ts
            )
            assert abort is None
            assert len(timeline) == 2
            assert [e.beat_id for e in timeline] == [1, 2]
        finally:
            close_connection(orch.db_path)

    def test_aborts_on_max_beat_with_atomic_db_state(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            narrative, ts = _mega_beat_narrative_and_ts()
            timeline, abort = orch._enforce_timeline_contract(
                conn, job_id, str(tmp_path), narrative, ts
            )
            # Failure path returns ([], abort).
            assert timeline == []
            assert abort is not None
            assert abort["status"] == "failed"
            assert abort["failed_at"] == "timeline_contract"
            # _enforce_gate populates `reason` with the gate message; the
            # STABLE routing token lives in the gate artifact's data.reason
            # (asserted below).
            assert "timeline contract violated" in abort["reason"]
            assert abort["job_id"] == job_id
            # FIX-5 contract surface: the stable "timeline_not_covered" routing
            # token is NOT on the abort top-level (that carries the human gate
            # message); it lives ONLY in the persisted gate artifact's
            # data.reason — the field FIX-5 must route on. Locks the surface so
            # FIX-5 cannot accidentally read abort["reason"].
            assert abort["reason"] != "timeline_not_covered"

            # Atomic DB state: job=FAILED AND scriptwriter=failed, committed
            # together (not half-written).
            job = get_job(conn, job_id)
            assert job["status"] == "FAILED"
            agent = get_agent_state(conn, job_id, "scriptwriter")
            assert agent["state"] == "failed"

            # Gate artifact persisted on disk for ops/debug-dashboard (per-gate
            # JSON file at <job_cache>/gates/FIX6_timeline_contract.json).
            gate_file = tmp_path / f"job_{job_id}" / "gates" / "FIX6_timeline_contract.json"
            assert gate_file.exists()
            record = json.loads(gate_file.read_text())
            assert record["passed"] is False
            assert record["data"]["reason"] == "timeline_not_covered"
            assert record["data"]["kind"] == "MAX_BEAT_EXCEEDED"
        finally:
            close_connection(orch.db_path)

    def test_rollback_on_db_error(self, tmp_path: Path, monkeypatch) -> None:
        """A transient DB error during the agent-state write rolls back and
        re-raises — no half-committed job=FAILED + scriptwriter=completed
        (Codex P2 lesson from G7). Asserted via observable DB state: the
        jobs UPDATE ran (commit=False) inside the same transaction, so a
        rollback must revert BOTH writes — the job row must NOT be left FAILED."""
        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            narrative, ts = _mega_beat_narrative_and_ts()

            # Force the agent-state write (the second DML, after the jobs
            # UPDATE) to fail with a transient sqlite error.
            from clipper_agency.orchestrator import engine as engine_mod

            def boom(*a, **k):
                raise sqlite3.OperationalError("simulated lock")

            monkeypatch.setattr(engine_mod, "_update_agent_state_inner", boom)

            with pytest.raises(sqlite3.OperationalError):
                orch._enforce_timeline_contract(conn, job_id, str(tmp_path), narrative, ts)
            # rollback() reverted the whole transaction: the job row is NOT
            # left in the half-committed FAILED state (the Codex P2 regression).
            job = get_job(conn, job_id)
            assert job["status"] != "FAILED"
        finally:
            close_connection(orch.db_path)

    def test_fix6_not_relaxable_even_when_gate_in_relax_set(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """FIX-6 is non-relaxable (RISK-5): even if FIX6_TIMELINE_CONTRACT is in
        the DEV relax-set, a mega-beat STILL aborts — it must NOT return
        ([], None), which every caller would treat as success with an empty
        timeline (letting reviewer/packaging proceed on an invalid timeline).
        Codex P2 r3497506157."""
        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            # Put FIX6 in the relax-set — the helper must still enforce.
            orch._relax_gates = frozenset({"FIX6_TIMELINE_CONTRACT"})
            narrative, ts = _mega_beat_narrative_and_ts()

            timeline, abort = orch._enforce_timeline_contract(
                conn, job_id, str(tmp_path), narrative, ts
            )
            # Non-relaxable: the abort is returned even with the gate relaxed.
            assert timeline == []
            assert abort is not None
            assert abort["status"] == "failed"
            assert abort["failed_at"] == "timeline_contract"
            # Enforcement was NOT skipped — the job is FAILED.
            assert get_job(conn, job_id)["status"] == "FAILED"
        finally:
            close_connection(orch.db_path)


# ── Blast-radius: every engine call site is gated ──


class TestEngineCallSitesWrapped:
    def test_normal_path_site_wrapped(self, tmp_path: Path, monkeypatch) -> None:
        """_stage_composition (the job_18 load-bearing L1222 site) returns the
        abort dict on a mega-beat fixture instead of composing."""
        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            narrative, ts = _mega_beat_narrative_and_ts()
            script_output = {"narrative_structure": narrative, "script": []}
            voice_output = {"timestamps": ts}

            # If the site is NOT gated, _run_visual_director_phase would be
            # reached; assert it never is by failing if it is called.
            def _no_call(*a, **k):
                raise AssertionError("VD reached — FIX-6 site NOT gated")

            monkeypatch.setattr(orch, "_run_visual_director_phase", _no_call)

            result = orch._stage_composition(
                conn,
                job_id,
                "t",
                research_output={},
                script_output=script_output,
                voice_output=voice_output,
                assets_cache=str(tmp_path),
                output_dir=str(tmp_path),
            )
            assert result["status"] == "failed"
            assert result["failed_at"] == "timeline_contract"
        finally:
            close_connection(orch.db_path)

    def test_resume_path_site_wrapped(self, tmp_path: Path, monkeypatch) -> None:
        """_retry_review_and_package (the L1874 review-retry site — one of the
        5 engine ``build_canonical_timeline`` call sites) returns the abort
        tuple on a mega-beat fixture — proves a second, resume/retry-family
        site is gated (blast-radius). The full run_pipeline_from path requires
        a complete niche config snapshot + live-catalog preflight and is
        covered end-to-end by the integration suite; this isolates the gate
        on the retry path the same way the G7 test isolates _stage_content."""
        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            narrative, ts = _mega_beat_narrative_and_ts()
            script_output = {"narrative_structure": narrative, "script": []}
            voice_output = {"timestamps": ts}

            # If the site is NOT gated, _run_reviewer would be reached.
            def _no_call(*a, **k):
                raise AssertionError("reviewer reached — FIX-6 site NOT gated")

            monkeypatch.setattr(orch, "_run_reviewer", _no_call)

            abort, review_output, pkg_output = orch._retry_review_and_package(
                conn,
                job_id,
                "t",
                script_output=script_output,
                compose_output={"duration_sec": 35.0},
                safety_rules=[],
                niche="n",
                output_dir=str(tmp_path),
                assets_cache=str(tmp_path),
                voice_output=voice_output,
            )
            assert abort is not None
            assert abort["status"] == "failed"
            assert abort["failed_at"] == "timeline_contract"
            assert review_output is None
            assert pkg_output is None
        finally:
            close_connection(orch.db_path)

    def test_reviewer_not_left_running_on_timeline_abort(self, tmp_path: Path, monkeypatch) -> None:
        """The FIX-6 timeline check in _retry_review_and_package runs BEFORE
        mark_agent_running(reviewer), so a mega-beat abort never leaves a stale
        reviewer=running state while the job is FAILED + scriptwriter=failed
        (Codex local-review P2, caught locally ahead of the bot)."""
        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            create_agent_state(conn, job_id, "reviewer")  # pre-existing row
            narrative, ts = _mega_beat_narrative_and_ts()
            script_output = {"narrative_structure": narrative, "script": []}
            voice_output = {"timestamps": ts}

            abort, _review, _pkg = orch._retry_review_and_package(
                conn,
                job_id,
                "t",
                script_output=script_output,
                compose_output={"duration_sec": 35.0},
                safety_rules=[],
                niche="n",
                output_dir=str(tmp_path),
                assets_cache=str(tmp_path),
                voice_output=voice_output,
            )
            assert abort is not None
            assert abort["failed_at"] == "timeline_contract"
            # reviewer is NOT left in a stale "running" state.
            assert get_agent_state(conn, job_id, "reviewer")["state"] != "running"
        finally:
            close_connection(orch.db_path)


# ── Blast-radius: the repair + resume RE-DERIVATION paths are gated ──
# (job_18 root cause = a timeline RE-DERIVED on repair/resume from the same
# broken narrative_structure. These prove FIX-6 fires on those paths — the
# pattern that let FIX-1 P1+P2 slip when a lane was documented but not run.)


def _niche_ctx() -> dict:
    """Minimal niche_ctx for repair/resume helpers (only keys those helpers read)."""
    return {
        "safety_rules": [],
        "channel_description": "",
        "language": "id",
        "tone": "informative",
        "content_angle": "",
    }


class TestEngineRepairAndResumeSitesWrapped:
    def test_cached_repair_path_site_wrapped(self, tmp_path: Path, monkeypatch) -> None:
        """_run_cached_upstream_repair (L719 — rebuilds the timeline from cached
        upstream on a VD/Composer repair) returns the abort tuple on a mega-beat
        before VD runs."""
        from clipper_agency.orchestrator.engine import RepairCycleContext

        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            narrative, ts = _mega_beat_narrative_and_ts()
            script_output = {"narrative_structure": narrative, "script": []}
            voice_output = {"timestamps": ts}

            monkeypatch.setattr(
                orch,
                "_reconstruct_upstream_outputs",
                lambda *a, **k: ({}, script_output, voice_output, {}),
            )
            # G7 passes (stubbed) so FIX-6 is the gate that catches the mega-beat.
            monkeypatch.setattr(orch, "_enforce_narrative_coverage", lambda *a, **k: None)

            def _vd_should_not_run(*a, **k):
                raise AssertionError("VD reached — cached-repair FIX-6 site NOT gated")

            monkeypatch.setattr(orch, "_run_visual_director_phase", _vd_should_not_run)

            ctx = RepairCycleContext(
                cycle=1,
                job_id=job_id,
                topic="t",
                output_dir=str(tmp_path),
                assets_cache=str(tmp_path),
                conn=conn,
                niche_ctx=_niche_ctx(),
                target_agent="visual_director",
                target_idx=5,
            )
            _research, _script, _voice, _compose, beat_timeline, abort = (
                orch._run_cached_upstream_repair(ctx)
            )
            assert abort is not None
            assert abort["status"] == "failed"
            assert abort["failed_at"] == "timeline_contract"
            assert beat_timeline == []
        finally:
            close_connection(orch.db_path)

    def test_cascade_repair_path_site_wrapped(self, tmp_path: Path, monkeypatch) -> None:
        """_rerun_upstream_cascade (L648 — reruns SP→SW→VP then rebuilds the
        timeline) returns the abort dict on a mega-beat before VD runs."""
        from clipper_agency.orchestrator.engine import RepairCycleContext

        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            narrative, ts = _mega_beat_narrative_and_ts()
            script_output = {
                "narrative_structure": narrative,
                "script": [],
                "voiceover_text": "w " * 76,
                "status": "ok",
            }
            voice_output = {"timestamps": ts, "status": "ok"}

            monkeypatch.setattr(orch, "_run_researcher", lambda **k: {"status": "ok"})
            monkeypatch.setattr(orch, "_run_content_scriptwriter", lambda *a, **k: script_output)
            monkeypatch.setattr(orch, "_enforce_narrative_coverage", lambda *a, **k: None)
            monkeypatch.setattr(orch, "_run_voice_producer", lambda **k: voice_output)
            monkeypatch.setattr(orch, "_complete_agent", lambda *a, **k: None)
            monkeypatch.setattr(
                "clipper_agency.orchestrator.engine.mark_agent_running",
                lambda *a, **k: None,
            )

            def _vd_should_not_run(*a, **k):
                raise AssertionError("VD reached — cascade-repair FIX-6 site NOT gated")

            monkeypatch.setattr(orch, "_run_visual_director_phase", _vd_should_not_run)

            ctx = RepairCycleContext(
                cycle=1,
                job_id=job_id,
                topic="t",
                output_dir=str(tmp_path),
                assets_cache=str(tmp_path),
                conn=conn,
                niche_ctx=_niche_ctx(),
                target_agent="visual_director",
                target_idx=5,
            )
            result = orch._rerun_upstream_cascade(ctx)
            assert isinstance(result, dict)
            assert result["status"] == "failed"
            assert result["failed_at"] == "timeline_contract"
        finally:
            close_connection(orch.db_path)

    def test_resume_downstream_path_site_wrapped(self, tmp_path: Path, monkeypatch) -> None:
        """_retry_downstream_stages (L2282 — the resume/retry path inside
        run_pipeline_from) returns the abort dict on a mega-beat before VD runs.
        from_idx = visual_director skips the SW + VP rerun blocks so execution
        lands directly on the FIX-6 timeline-build site."""
        from clipper_agency.orchestrator.engine import PIPELINE_ORDER

        orch = _make_orchestrator(tmp_path)
        conn = get_connection(orch.db_path)
        try:
            job_id = _seed_job(conn, str(tmp_path))
            narrative, ts = _mega_beat_narrative_and_ts()
            script_output = {"narrative_structure": narrative, "script": []}
            voice_output = {"timestamps": ts}

            monkeypatch.setattr(orch, "_enforce_narrative_coverage", lambda *a, **k: None)

            def _vd_should_not_run(*a, **k):
                raise AssertionError("VD reached — resume FIX-6 site NOT gated")

            monkeypatch.setattr(orch, "_run_visual_director_phase", _vd_should_not_run)

            result = orch._retry_downstream_stages(
                conn,
                job_id,
                "t",
                _niche_ctx(),
                "n",
                str(tmp_path),
                str(tmp_path),
                from_idx=PIPELINE_ORDER.index("visual_director"),
                use_cache=False,
                research_output={},
                script_output=script_output,
                voice_output=voice_output,
                visual_output={},
            )
            assert result is not None
            assert result["status"] == "failed"
            assert result["failed_at"] == "timeline_contract"
        finally:
            close_connection(orch.db_path)


# ── Diagnostics consumer stays safe ──


def test_diagnostics_planned_does_not_raise(tmp_path: Path) -> None:
    """derive_planned_boundaries on the job_18 fixture returns a list WITHOUT
    raising — the non-gate diagnostic consumer is safe under
    enforce_contract=False (FIX-6 RISK-2)."""
    from clipper_agency.diagnostics.planned import derive_planned_boundaries

    narrative, ts = _mega_beat_narrative_and_ts()
    boundaries = derive_planned_boundaries(narrative, ts)
    assert isinstance(boundaries, list)
    assert len(boundaries) == 3  # the stretched timeline is reported as-is
