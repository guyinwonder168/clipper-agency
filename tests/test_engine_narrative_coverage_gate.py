"""Engine integration test for the G7 narrative coverage gate (ADR 0030 / FIX-1).

Asserts that ``_stage_content`` applies an eligible in-place repair to
``script_output['narrative_structure']`` BEFORE evaluating the gate, and that
a hard-failing structure aborts the pipeline. Fully offline: no LLM, no real
agents, no network.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from clipper_agency.agents.scriptwriter import _word_count as _scriptwriter_word_count
from clipper_agency.core.repair_router import NARRATIVE_NOT_COVERED
from clipper_agency.db.connection import close_connection, get_connection
from clipper_agency.db.queries import (
    create_agent_state,
    create_job,
    get_agent_state,
    get_job,
    mark_agent_completed,
)
from clipper_agency.orchestrator.engine import Orchestrator, _word_count_for_coverage


def _make_orchestrator(tmp_path) -> Orchestrator:
    return Orchestrator(db_path=str(tmp_path / "g7_engine.db"))


def _stage_content_kwargs():
    """Minimal kwargs for _stage_content; only fields touched by the G7
    block and the stubbed scriptwriter/voice paths are populated."""
    return dict(
        topic="t",
        safety_rules=[],
        channel_description="",
        language="id",
        tone="neutral",
        content_angle="",
        research_output={},
        assets_cache="",
        output_dir="",
    )


def test_engine_applies_repair_before_gate_then_passes(tmp_path, monkeypatch):
    """A 2-word uncovered tail under tolerance is repaired in place, so the
    G7 gate records a pass and the pipeline proceeds to Voice Producer."""
    orch = _make_orchestrator(tmp_path)

    # Scriptwriter returns a 100-word voiceover whose last beat ends at 97;
    # tail_words=2 < tolerance_words=5 -> eligible for in-place repair.
    voiceover_text = "word " * 100  # 100 whitespace-separated tokens
    script_output = {
        "status": "ok",
        "voiceover_text": voiceover_text.strip(),
        "narrative_structure": [
            {"beat_id": 1, "word_range": [0, 49]},
            {"beat_id": 2, "word_range": [50, 97]},
        ],
        "script": [],
    }
    monkeypatch.setattr(orch, "_run_content_scriptwriter", lambda *a, **k: script_output)

    # Voice producer is stubbed so we never leave the offline boundary.
    voice_output = {"status": "ok", "voiceover_path": "/dev/null"}
    monkeypatch.setattr(orch, "_run_voice_producer", lambda **k: voice_output)
    monkeypatch.setattr(orch, "_complete_agent", lambda *a, **k: None)

    # DB/workspace side-effects stubbed out.
    conn = MagicMock()
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine.mark_agent_running", lambda *a, **k: None
    )
    recorded: list[tuple] = []
    monkeypatch.setattr(
        orch,
        "_record_gate",
        lambda assets_cache, job_id, gate_name, result: recorded.append((gate_name, result)),
    )
    # G8 (audio) would abort on the stubbed /dev/null path; this test targets
    # G7 in isolation, so no-op the downstream gate enforcement. G7's own pass
    # is verified via the recorded result above.
    monkeypatch.setattr(orch, "_enforce_gate", lambda *a, **k: None)

    result = orch._stage_content(conn, job_id=1, **_stage_content_kwargs())

    # Repair was applied to script_output before the gate evaluated it.
    assert script_output["narrative_structure"][-1]["word_range"] == [50, 99]

    # The G7 gate was recorded as a pass.
    g7 = [r for name, r in recorded if name == "G7_narrative_coverage"]
    assert len(g7) == 1
    assert g7[0].passed is True
    assert g7[0].severity == "pass"

    # Pipeline continued past G7 to Voice Producer and returned the pair.
    assert isinstance(result, tuple)
    assert result[1] is voice_output


def test_engine_hard_fails_on_uncovered_tail(tmp_path, monkeypatch):
    """A large uncovered tail (job_18 shape) hard-fails at G7 and returns a
    failure dict instead of invoking the Voice Producer."""
    orch = _make_orchestrator(tmp_path)

    voiceover_text = "word " * 76  # 76 words
    job18_structure = [
        {"beat_id": 1, "word_range": [0, 2]},
        {"beat_id": 2, "word_range": [3, 8]},
        {"beat_id": 3, "word_range": [9, 12]},
        {"beat_id": 4, "word_range": [13, 15]},
        {"beat_id": 5, "word_range": [16, 19]},
        {"beat_id": 6, "word_range": [20, 23]},
    ]
    script_output = {
        "status": "ok",
        "voiceover_text": voiceover_text.strip(),
        "narrative_structure": job18_structure,
        "script": [],
    }
    monkeypatch.setattr(orch, "_run_content_scriptwriter", lambda *a, **k: script_output)

    voice_called = []
    monkeypatch.setattr(
        orch, "_run_voice_producer", lambda **k: voice_called.append(k) or {"status": "ok"}
    )

    conn = MagicMock()
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine.mark_agent_running", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine.update_job_status", lambda *a, **k: None
    )

    result = orch._stage_content(conn, job_id=1, **_stage_content_kwargs())

    # Hard-failed: failure dict returned, narrative_structure unchanged,
    # Voice Producer never reached.
    assert isinstance(result, dict)
    assert result["status"] == "failed"
    assert result["failed_at"] == "narrative_coverage"
    # Stable FIX-5 routing token must survive the _enforce_gate round-trip
    # (it propagates result.message == coverage.reason == 'narrative_not_covered').
    assert result["reason"] == "narrative_not_covered"
    assert script_output["narrative_structure"] == job18_structure
    assert voice_called == []


def test_engine_hard_fails_on_empty_narrative_with_text(tmp_path, monkeypatch):
    """status='completed' + non-empty voiceover_text + EMPTY narrative_structure
    (a silent LLM parse-fallback, per the PR #82 JSON-robustness lesson) must
    hard-fail at G7 with violation_type='empty', not reach Voice Producer."""
    orch = _make_orchestrator(tmp_path)

    script_output = {
        "status": "ok",
        "voiceover_text": "word " * 20,  # 20 words, but no beats
        "narrative_structure": [],
        "script": [],
    }
    monkeypatch.setattr(orch, "_run_content_scriptwriter", lambda *a, **k: script_output)

    voice_called = []
    monkeypatch.setattr(
        orch, "_run_voice_producer", lambda **k: voice_called.append(k) or {"status": "ok"}
    )

    conn = MagicMock()
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine.mark_agent_running", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine.update_job_status", lambda *a, **k: None
    )

    result = orch._stage_content(conn, job_id=1, **_stage_content_kwargs())

    assert isinstance(result, dict)
    assert result["status"] == "failed"
    assert result["failed_at"] == "narrative_coverage"
    assert result["reason"] == "narrative_not_covered"
    assert voice_called == []


def test_g7_word_count_agrees_with_scriptwriter_tokenizer():
    """The G7 gate and the ScriptwriterAgent MUST count words identically,
    else the gate validates coverage against a different ruler than the one
    the LLM used to emit word_range indices. Pins the two twins stay in sync.
    """
    cases = ["", "a", "a b c", "  multiple   spaces  ", "word " * 76, " trailing "]
    for text in cases:
        assert _word_count_for_coverage(text) == _scriptwriter_word_count(text), (
            f"word-count divergence on {text!r}"
        )


# ── shared helper (called from _stage_content AND retry/repair paths) ──


def _helper_orchestrator(monkeypatch, tmp_path) -> Orchestrator:
    """Orchestrator with DB side-effects stubbed for direct helper tests."""
    from clipper_agency.orchestrator.engine import update_job_status  # noqa: F401

    orch = Orchestrator(db_path=str(tmp_path / "g7_helper.db"))
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine.update_job_status", lambda *a, **k: None
    )
    return orch


def test_enforce_narrative_coverage_helper_hard_fails_job18(tmp_path, monkeypatch):
    """The shared _enforce_narrative_coverage helper — called from
    _stage_content AND the retry (_retry_downstream_stages) / repair
    (_rerun_upstream_cascade) rerun paths (Codex P1) — hard-fails the job_18
    fixture, proving the contract fires identically regardless of caller."""
    orch = _helper_orchestrator(monkeypatch, tmp_path)
    recorded: list[tuple] = []
    monkeypatch.setattr(
        orch, "_record_gate", lambda ac, jid, name, res: recorded.append((name, res))
    )
    failed_agents: list[tuple] = []
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine._update_agent_state_inner",
        lambda *a, **k: failed_agents.append(a),
        raising=False,
    )

    script_output = {
        "voiceover_text": "word " * 76,  # 76 words
        "narrative_structure": [
            {"beat_id": 1, "word_range": [0, 2]},
            {"beat_id": 2, "word_range": [3, 8]},
            {"beat_id": 3, "word_range": [9, 12]},
            {"beat_id": 4, "word_range": [13, 15]},
            {"beat_id": 5, "word_range": [16, 19]},
            {"beat_id": 6, "word_range": [20, 23]},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=""
    )

    # Hard-failed with the stable routing token; structure unchanged.
    assert abort is not None
    assert abort["status"] == "failed"
    assert abort["failed_at"] == "narrative_coverage"
    assert abort["reason"] == "narrative_not_covered"
    # FIX-5 producer-side contract (pr-test-analyzer P1): the REAL helper
    # stamps the stable routing token on the abort so _is_coverage_repairable_abort
    # can route into the bounded Scriptwriter regen. Pinning the producer half
    # of the contract the existing consumer tests already pin.
    assert abort["gate_reason"] == NARRATIVE_NOT_COVERED
    assert script_output["narrative_structure"][-1]["word_range"] == [20, 23]
    # G7 recorded as a hard_fail.
    g7 = [r for name, r in recorded if name == "G7_narrative_coverage"]
    assert len(g7) == 1 and not g7[0].passed and g7[0].severity == "hard_fail"
    # G7 hard-fail marks the Scriptwriter agent failed so job-resume can
    # target/regenerate it (Codex P2 r3494109780).
    assert len(failed_agents) == 1
    assert failed_agents[0][2] == "scriptwriter"  # mark_agent_failed(conn, job_id, agent_name, ...)


def test_enforce_narrative_coverage_helper_repairs_and_passes(tmp_path, monkeypatch):
    """The shared helper applies in-place tail repair and returns None (pass)."""
    orch = _helper_orchestrator(monkeypatch, tmp_path)
    recorded: list[tuple] = []
    monkeypatch.setattr(
        orch, "_record_gate", lambda ac, jid, name, res: recorded.append((name, res))
    )

    script_output = {
        "voiceover_text": "word " * 100,  # 100 words
        "narrative_structure": [
            {"beat_id": 1, "word_range": [0, 49]},
            {"beat_id": 2, "word_range": [50, 97]},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=""
    )

    assert abort is None  # pass
    # Repair applied in place before the gate evaluated it.
    assert script_output["narrative_structure"][-1]["word_range"] == [50, 99]
    g7 = [r for name, r in recorded if name == "G7_narrative_coverage"]
    assert len(g7) == 1 and g7[0].passed and g7[0].severity == "pass"


def test_enforce_narrative_coverage_persists_repaired_to_disk(tmp_path, monkeypatch):
    """When the gate repairs/reorders, the repaired structure is re-written to
    the Scriptwriter's on-disk artifacts, so reload paths (e.g.
    _retry_composer_stage) don't resurrect the stale pre-gate version (Codex P2)."""
    import json
    from pathlib import Path

    from clipper_agency.core.paths import agent_dir

    orch = _helper_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "_record_gate", lambda *a, **k: None)

    assets_cache = str(tmp_path / "cache")
    base = Path(agent_dir(assets_cache, 1, "scriptwriter"))
    base.mkdir(parents=True, exist_ok=True)
    # Stale pre-gate on-disk structure (last beat ends at 97, not 99).
    (base / "narrative_structure.json").write_text(
        json.dumps([{"beat_id": 1, "word_range": [0, 49]}, {"beat_id": 2, "word_range": [50, 97]}])
    )

    script_output = {
        "voiceover_text": "word " * 100,  # 100 words; tail=2 < 5% -> repaired
        "narrative_structure": [
            {"beat_id": 1, "word_range": [0, 49]},
            {"beat_id": 2, "word_range": [50, 97]},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=assets_cache
    )

    assert abort is None  # repaired + passed
    # The on-disk artifact now reflects the repaired [50, 99].
    on_disk = json.loads((base / "narrative_structure.json").read_text())
    assert on_disk[-1]["word_range"] == [50, 99]
    # And the full output.json was re-persisted with the repaired structure.
    from clipper_agency.core.paths import agent_output_file

    out = json.loads(Path(agent_output_file(assets_cache, 1, "scriptwriter")).read_text())
    assert out["narrative_structure"][-1]["word_range"] == [50, 99]


# ── Option A: atomic transaction on G7 hard-fail (PR #86) ──


def _seeded_real_db(tmp_path):
    """A real file-based DB + Orchestrator with a job whose scriptwriter agent
    is already ``completed`` — the job_18-residual state the atomic fix must
    either commit alongside job=FAILED or roll back together, never leave
    hanging."""
    db_path = str(tmp_path / "g7_atomic.db")
    orch = Orchestrator(db_path=db_path)
    conn = get_connection(db_path)
    job_id = create_job(conn, "topic", "niche")
    create_agent_state(conn, job_id, "scriptwriter")
    mark_agent_completed(conn, job_id, "scriptwriter")
    return orch, conn, job_id


def _job18_uncovered_script_output() -> dict:
    """A narrative_structure whose word_range union covers only 0-23 of 76
    words — the job_18 fixture that hard-fails G7."""
    return {
        "voiceover_text": "word " * 76,  # 76 words
        "narrative_structure": [{"beat_id": 1, "word_range": [0, 23]}],
    }


def test_enforce_narrative_coverage_hard_fail_commits_both_writes(tmp_path, monkeypatch):
    """Happy path of the atomic fix: on a G7 hard-fail BOTH the job=FAILED and
    scriptwriter=failed writes commit together in one transaction."""
    orch, conn, job_id = _seeded_real_db(tmp_path)
    monkeypatch.setattr(orch, "_record_gate", lambda *a, **k: None)

    abort = orch._enforce_narrative_coverage(
        conn, job_id=job_id, script_output=_job18_uncovered_script_output(), assets_cache=""
    )

    assert abort is not None
    assert abort["failed_at"] == "narrative_coverage"
    # Both writes committed atomically.
    assert get_job(conn, job_id)["status"] == "FAILED"
    assert get_agent_state(conn, job_id, "scriptwriter")["state"] == "failed"
    close_connection()


def test_enforce_narrative_coverage_atomic_rollback_on_agent_write_failure(tmp_path, monkeypatch):
    """If the agent_states write raises after the jobs write ran (e.g. sqlite
    ``database is locked`` under concurrent dashboard retry/resume), the whole
    transaction rolls back — the jobs write is NOT left committed alone. This
    is the exact job_18-residual state (job=FAILED + scriptwriter=completed)
    the atomic fix exists to prevent (Codex P2 r3494109780 follow-up)."""
    orch, conn, job_id = _seeded_real_db(tmp_path)
    monkeypatch.setattr(orch, "_record_gate", lambda *a, **k: None)

    # Force the no-commit agent_states write to raise AFTER _enforce_gate
    # (commit=False) already ran the jobs UPDATE.
    def _raise_on_agent_write(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine._update_agent_state_inner",
        _raise_on_agent_write,
        raising=False,
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        orch._enforce_narrative_coverage(
            conn,
            job_id=job_id,
            script_output=_job18_uncovered_script_output(),
            assets_cache="",
        )

    # Atomicity invariant: jobs write rolled back (NOT left FAILED), and the
    # scriptwriter agent_state is unchanged from its seeded 'completed'.
    assert get_job(conn, job_id)["status"] != "FAILED"
    assert get_agent_state(conn, job_id, "scriptwriter")["state"] == "completed"
    close_connection()


def test_enforce_narrative_coverage_g7_hard_fail_holds_write_lock(tmp_path, monkeypatch):
    """The G7 atomic block holds the process-wide write lock across BOTH the
    jobs write AND the agent write + commit, so a concurrent Flask thread
    cannot interleave a public-helper commit into the half-open transaction
    (Codex P2 r3496171628).

    Asserts the load-bearing invariant directly: each of the two no-commit
    ``_inner`` writes must observe the lock as HELD at the moment it runs.
    A regression that moves the ``with`` block to wrap only one write would
    fail here (the other write would see the lock released)."""
    import clipper_agency.orchestrator.engine as engine_mod

    orch, conn, job_id = _seeded_real_db(tmp_path)
    monkeypatch.setattr(orch, "_record_gate", lambda *a, **k: None)

    held = {"now": False}

    class _Recorder:
        def __enter__(self):
            held["now"] = True
            return self

        def __exit__(self, *exc):
            held["now"] = False

    monkeypatch.setattr(engine_mod, "db_write_lock", lambda: _Recorder())

    write_observed: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        engine_mod,
        "_update_job_status_inner",
        lambda *a, **k: write_observed.append(("job", held["now"])),
    )
    monkeypatch.setattr(
        engine_mod,
        "_update_agent_state_inner",
        lambda *a, **k: write_observed.append(("agent", held["now"])),
    )

    abort = orch._enforce_narrative_coverage(
        conn,
        job_id=job_id,
        script_output=_job18_uncovered_script_output(),
        assets_cache="",
    )

    assert abort is not None
    assert abort["failed_at"] == "narrative_coverage"
    # BOTH writes fired while the lock was held.
    assert write_observed == [("job", True), ("agent", True)]
    close_connection()
