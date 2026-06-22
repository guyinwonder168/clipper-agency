"""Tests for DEV gate-relax (CLIPPER_RELAX_GATES / --relax-gates).

Spec: additive — an empty relax-set means today's behavior byte-for-byte.
Relaxing a gate downgrades its hard_fail from abort to warn+continue, and
never affects non-relaxed gates.
"""

import logging
from unittest.mock import MagicMock

from clipper_agency.orchestrator.engine import Orchestrator
from clipper_agency.orchestrator.gates import GateResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(tmp_path) -> Orchestrator:
    """Build an Orchestrator against a throwaway SQLite DB."""
    return Orchestrator(db_path=str(tmp_path / "gate_relax.db"))


def _hard_fail(message: str = "boom") -> GateResult:
    return GateResult(passed=False, severity="hard_fail", message=message)


# ---------------------------------------------------------------------------
# _gate_relaxed
# ---------------------------------------------------------------------------


class TestGateRelaxed:
    def test_truthy_when_gate_in_relax_set(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"G4", "G5"})
        assert orch._gate_relaxed("G4") is True
        assert orch._gate_relaxed("G5") is True

    def test_falsy_when_gate_not_in_relax_set(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"G4"})
        assert orch._gate_relaxed("G5") is False

    def test_falsy_when_relax_set_empty_default(self, tmp_path):
        """Default frozenset() == today's behavior (nothing relaxed)."""
        orch = _make_orchestrator(tmp_path)
        # Fresh orchestrator should not have relaxed anything.
        for gate in ("G1", "G4", "G5", "G8", "G9", "G10", "Safety"):
            assert orch._gate_relaxed(gate) is False

    def test_falsy_when_attr_missing(self, tmp_path):
        """Defensive: missing attr must not relax."""
        orch = _make_orchestrator(tmp_path)
        # Simulate an orchestrator constructed before the attr was set.
        if hasattr(orch, "_relax_gates"):
            del orch._relax_gates
        assert orch._gate_relaxed("G4") is False


# ---------------------------------------------------------------------------
# _enforce_gate (G5 / G8 path) — covers the regression contract too
# ---------------------------------------------------------------------------


class TestEnforceGateRelax:
    def test_relaxed_hard_fail_returns_none_and_warns(self, tmp_path, caplog):
        """G5 hard_fail + 'G5' in relax-set -> None (continue) + WARNING log."""
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"G5"})
        # A fake conn — on the relaxed path update_job_status must NOT run.
        fake_conn = MagicMock(name="conn")

        result = orch._enforce_gate(fake_conn, job_id=1, gate_name="G5", result=_hard_fail("nope"))

        assert result is None
        fake_conn.execute.assert_not_called()
        assert any(
            "G5" in rec.getMessage() and "RELAXED" in rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
        )

    def test_non_relaxed_hard_fail_returns_abort_dict(self, tmp_path):
        """Regression guard: without relax, hard_fail aborts exactly as today."""
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset()  # empty == today's behavior

        # Use a real in-memory-ish conn via the orchestrator's own DB so
        # update_job_status doesn't blow up; we only assert the returned dict.
        conn = orch.__dict__.get("conn")  # not stored; build fresh
        # The orchestrator opens its own connection; re-open one for the test.
        from clipper_agency.db.connection import get_connection
        from clipper_agency.db.schema import initialize_schema

        conn = get_connection(orch.db_path)
        initialize_schema(conn)
        # Need a job row so update_job_status(conn, job_id, ...) succeeds.
        from clipper_agency.db.queries import create_job

        job_id = create_job(conn, topic="t", niche="n", config_snapshot={})

        abort = orch._enforce_gate(conn, job_id=job_id, gate_name="G8", result=_hard_fail("bad"))

        assert abort is not None
        assert abort["status"] == "failed"
        assert abort["job_id"] == job_id
        assert abort["reason"] == "bad"

    def test_passed_gate_returns_none_regardless_of_relax(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"G5"})
        fake_conn = MagicMock()
        passing = GateResult(passed=True, severity="pass", message="ok")
        assert orch._enforce_gate(fake_conn, 1, "G5", passing) is None

    def test_soft_fail_returns_none_regardless_of_relax(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"G5"})
        fake_conn = MagicMock()
        soft = GateResult(passed=False, severity="soft_fail", message="meh")
        assert orch._enforce_gate(fake_conn, 1, "G5", soft) is None


# ---------------------------------------------------------------------------
# _evaluate_and_enforce_gate (G9 / G10 path)
# ---------------------------------------------------------------------------


class TestEvaluateAndEnforceGateRelax:
    def test_relaxed_hard_fail_returns_none(self, tmp_path, caplog):
        """G9 path: when gate is relaxed, evaluate+record runs but abort is None."""
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"G9"})

        fake_gate = MagicMock()
        fake_gate.evaluate.return_value = _hard_fail("assets bad")
        fake_conn = MagicMock()

        abort = orch._evaluate_and_enforce_gate(
            fake_conn,
            job_id=1,
            assets_cache=str(tmp_path / "cache"),
            gate_label="G9",
            gate_record_key="G9_asset_validation",
            gate_instance=fake_gate,
            failed_at="asset_validation",
            asset_paths=[],
        )

        assert abort is None
        fake_gate.evaluate.assert_called_once()
        assert any(
            "G9" in rec.getMessage() and "RELAXED" in rec.getMessage()
            for rec in caplog.records
            if rec.levelno == logging.WARNING
        )


# ---------------------------------------------------------------------------
# _stage_research-style scenario: G4 inline hard_fail
# ---------------------------------------------------------------------------


class TestStageResearchG4Relax:
    """Drive _stage_research with G4 hard_fail under relax vs no-relax.

    We stub the Segment Producer and the G4 gate so we can isolate the G4
    inline-enforcement branch. A fake conn records FAILED-status writes so we
    can assert whether the stage aborted.
    """

    def _build_fake_conn(self) -> MagicMock:
        conn = MagicMock(name="conn")
        status_writes: list[tuple] = []

        def _update_job_status(c, job_id, status, reason=""):
            status_writes.append((job_id, status, reason))

        conn.status_writes = status_writes  # type: ignore[attr-defined]
        return conn

    def test_g4_relaxed_does_not_return_failed(self, tmp_path, mocker):
        from clipper_agency.orchestrator import engine as engine_mod

        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"G4"})

        # Segment Producer returns benign research output.
        mocker.patch.object(
            orch, "_run_researcher", return_value={"risk_flags": ["x"], "sources": []}
        )
        mocker.patch.object(orch, "_complete_agent", return_value=None)
        # Format validator path: return a config-free walk-through.
        mocker.patch.object(
            engine_mod, "load_settings", return_value=MagicMock(content_planning=None)
        )
        # G4 evaluates to hard_fail.
        fake_g4 = MagicMock()
        fake_g4.evaluate.return_value = _hard_fail("risky")
        mocker.patch.object(engine_mod, "GatePostResearchRisk", return_value=fake_g4)
        # G5 passes so we don't abort downstream.
        fake_g5 = MagicMock()
        fake_g5.evaluate.return_value = GateResult(passed=True, severity="pass", message="ok")
        mocker.patch.object(engine_mod, "GateSourceQuality", return_value=fake_g5)
        mocker.patch.object(orch, "_record_gate", return_value="path")
        # G3 cache gate also must be patched (constructed in-stage).
        mocker.patch.object(engine_mod, "GateResearchCache", return_value=MagicMock())
        fake_conn = self._build_fake_conn()

        out = orch._stage_research(
            conn=fake_conn,
            job_id=1,
            topic="t",
            safety_rules=[],
            channel_description="d",
            language="id",
            tone="casual",
            content_angle="a",
            assets_cache=str(tmp_path / "cache"),
            output_dir=str(tmp_path / "out"),
        )

        # Relaxed -> returns the research dict (NOT a failed dict).
        assert isinstance(out, dict)
        assert out.get("status") != "failed"
        assert out.get("risk_flags") == ["x"]

    def test_g4_not_relaxed_returns_failed(self, tmp_path, mocker):
        """Regression: without relax, G4 hard_fail aborts the stage."""
        from clipper_agency.orchestrator import engine as engine_mod

        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset()  # empty == today's behavior

        mocker.patch.object(
            orch, "_run_researcher", return_value={"risk_flags": ["x"], "sources": []}
        )
        mocker.patch.object(orch, "_complete_agent", return_value=None)
        mocker.patch.object(
            engine_mod, "load_settings", return_value=MagicMock(content_planning=None)
        )
        fake_g4 = MagicMock()
        fake_g4.evaluate.return_value = _hard_fail("risky")
        mocker.patch.object(engine_mod, "GatePostResearchRisk", return_value=fake_g4)
        mocker.patch.object(orch, "_record_gate", return_value="path")
        mocker.patch.object(engine_mod, "GateResearchCache", return_value=MagicMock())

        def _fake_update_job_status(c, job_id, status, reason=""):
            pass

        mocker.patch.object(engine_mod, "update_job_status", side_effect=_fake_update_job_status)
        fake_conn = self._build_fake_conn()

        out = orch._stage_research(
            conn=fake_conn,
            job_id=1,
            topic="t",
            safety_rules=[],
            channel_description="d",
            language="id",
            tone="casual",
            content_angle="a",
            assets_cache=str(tmp_path / "cache"),
            output_dir=str(tmp_path / "out"),
        )

        assert out.get("status") == "failed"
        assert out.get("failed_at") == "post_research_risk"
        assert out.get("reason") == "risky"


# ---------------------------------------------------------------------------
# _retry_safety_stage (retry/resume Safety) — must honor relax like the fresh path
# ---------------------------------------------------------------------------


class TestRetrySafetyStageRelax:
    """The retry/resume Safety path must honor ``_gate_relaxed('Safety')`` the
    same way the fresh ``_stage_safety`` path does. Regression for the
    retry-path gap (the retry path previously always aborted on Safety
    hard_fail, ignoring the relax-set)."""

    def test_safety_relaxed_continues(self, tmp_path, caplog, mocker):
        from clipper_agency.orchestrator import engine as engine_mod

        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"Safety"})
        mocker.patch.object(engine_mod, "mark_agent_running", return_value=None)
        mocker.patch.object(
            orch, "_run_safety", return_value={"status": "hard_fail", "reason": "risky"}
        )
        mocker.patch.object(orch, "_complete_agent", return_value=None)

        out = orch._retry_safety_stage(
            MagicMock(), job_id=1, topic="t", assets_cache=str(tmp_path / "c"), from_idx=0
        )

        assert out is None  # relaxed -> continue (NOT an abort dict)
        assert any(
            "Safety" in r.getMessage() and "RELAXED" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
        )

    def test_safety_not_relaxed_aborts(self, tmp_path, mocker):
        """Regression: without relax, retry-path Safety hard_fail aborts."""
        from clipper_agency.orchestrator import engine as engine_mod

        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset()
        mocker.patch.object(engine_mod, "mark_agent_running", return_value=None)
        mocker.patch.object(
            orch, "_run_safety", return_value={"status": "hard_fail", "reason": "risky"}
        )
        mocker.patch.object(orch, "_complete_agent", return_value=None)
        mocker.patch.object(engine_mod, "mark_agent_failed", return_value=None)
        mocker.patch.object(engine_mod, "update_job_status", return_value=None)

        out = orch._retry_safety_stage(
            MagicMock(), job_id=1, topic="t", assets_cache=str(tmp_path / "c"), from_idx=0
        )

        assert out is not None
        assert out["status"] == "failed"
        assert out["failed_at"] == "safety"


# ---------------------------------------------------------------------------
# _stage_safety G1 + Safety inline relax — coverage for the two inline points
# ---------------------------------------------------------------------------


class TestStageSafetyInlineRelax:
    """``_stage_safety`` G1 and Safety inline relax branches — coverage for the
    two inline enforcement points not exercised by the ``_enforce_gate`` /
    ``_stage_research`` tests above."""

    def _stubs(self, orch, mocker, g1_result, safety_result) -> None:
        from clipper_agency.orchestrator import engine as engine_mod

        fake_g1 = MagicMock()
        fake_g1.evaluate.return_value = g1_result
        mocker.patch.object(engine_mod, "GateInputPreflight", return_value=fake_g1)
        fake_g2 = MagicMock()
        fake_g2.evaluate.return_value = GateResult(passed=True, severity="pass", message="ok")
        mocker.patch.object(engine_mod, "GateCostEstimate", return_value=fake_g2)
        mocker.patch.object(orch, "_record_gate", return_value="path")
        mocker.patch.object(engine_mod, "create_job", return_value=42)
        mocker.patch.object(engine_mod, "add_job_file_handler", return_value=None)
        mocker.patch.object(engine_mod, "create_manifest", return_value=None)
        mocker.patch.object(engine_mod, "create_agent_state", return_value=None)
        mocker.patch.object(orch, "_init_job_statuses", return_value=None)
        mocker.patch.object(engine_mod, "mark_agent_running", return_value=None)
        mocker.patch.object(orch, "_run_safety", return_value=safety_result)
        mocker.patch.object(orch, "_complete_agent", return_value=None)
        mocker.patch.object(engine_mod, "mark_agent_failed", return_value=None)
        mocker.patch.object(engine_mod, "update_job_status", return_value=None)

    def test_g1_relaxed_continues(self, tmp_path, mocker):
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"G1"})
        self._stubs(orch, mocker, _hard_fail("bad topic"), {"status": "completed"})

        out = orch._stage_safety(
            MagicMock(),
            topic="t",
            niche="n",
            assets_cache=str(tmp_path / "c"),
            output_dir=str(tmp_path / "o"),
        )

        assert isinstance(out, tuple)  # (job_id, cost_result) — G1 relaxed, continued
        assert out[0] == 42

    def test_safety_relaxed_continues(self, tmp_path, mocker):
        orch = _make_orchestrator(tmp_path)
        orch._relax_gates = frozenset({"Safety"})
        passing = GateResult(passed=True, severity="pass", message="ok")
        self._stubs(orch, mocker, passing, {"status": "hard_fail", "reason": "risky"})

        out = orch._stage_safety(
            MagicMock(),
            topic="t",
            niche="n",
            assets_cache=str(tmp_path / "c"),
            output_dir=str(tmp_path / "o"),
        )

        assert isinstance(out, tuple)  # Safety relaxed, continued
        assert out[0] == 42
