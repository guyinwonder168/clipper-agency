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

    script = _job18_uncovered_script_output()
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        orch._enforce_narrative_coverage(
            conn,
            job_id=job_id,
            script_output=script,
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


# ── FIX-8 (cue-anchor contract): G7 derives word_range from start_cue ──


def test_enforce_narrative_coverage_derives_ranges_from_cues(tmp_path, monkeypatch):
    """FIX-8 plan §7 case 7: when beats carry ``start_cue`` (the new contract),
    G7 DERIVES ``word_range`` from the cues and records a pass. The on-disk
    script_output is rewritten with the derived ranges so downstream
    consumers (Voice Producer, build_canonical_timeline) see the field."""
    from clipper_agency.core.beat_timeline import build_canonical_timeline

    orch = _helper_orchestrator(monkeypatch, tmp_path)
    recorded: list[tuple] = []
    monkeypatch.setattr(
        orch, "_record_gate", lambda ac, jid, name, res: recorded.append((name, res))
    )
    monkeypatch.setattr(orch, "_persist_repaired_narrative", lambda *a, **k: None)

    # 3 beats, cues anchor verbatim in the voiceover in spoken order.
    voiceover = (
        "halo guys hari ini gosip terbaru "
        "kemudian anji menikah lagi dengan wina "
        "dan terakhir jangan lupa follow update"
    )
    script_output = {
        "voiceover_text": voiceover,
        # No word_range — only start_cue (the FIX-8 contract).
        "narrative_structure": [
            {"beat_id": 1, "start_cue": "halo guys hari ini"},
            {"beat_id": 2, "start_cue": "kemudian anji menikah lagi"},
            {"beat_id": 3, "start_cue": "dan terakhir jangan lupa"},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=""
    )

    assert abort is None  # pass
    # Derived ranges are written into script_output and fully cover [0, N-1].
    ranges = [b["word_range"] for b in script_output["narrative_structure"]]
    n = len(voiceover.split())
    assert ranges[0][0] == 0
    assert ranges[-1][1] == n - 1
    for i in range(len(ranges) - 1):
        assert ranges[i][1] == ranges[i + 1][0] - 1  # contiguous
    # The G7 gate recorded a pass with cue_derived provenance.
    g7 = [r for name, r in recorded if name == "G7_narrative_coverage"]
    assert len(g7) == 1 and g7[0].passed and g7[0].severity == "pass"

    # Downstream consumer contract: build_canonical_timeline reads the derived
    # word_range and produces one entry per beat (no mega-beat).
    timestamps = [
        {"word": w, "start": i * 1.0, "end": i * 1.0 + 0.5} for i, w in enumerate(voiceover.split())
    ]
    timeline = build_canonical_timeline(script_output["narrative_structure"], timestamps)
    assert len(timeline) == 3


def test_enforce_narrative_coverage_cue_not_found_routes_to_scriptwriter(tmp_path, monkeypatch):
    """FIX-8 plan §3: a start_cue that does not anchor in the voiceover is a
    cue_not_found failure. It surfaces via the stable narrative_not_covered
    routing token (FIX-5 router) with the cue-specific reason in details."""
    from clipper_agency.core.beat_anchor import CUE_NOT_FOUND

    orch = _helper_orchestrator(monkeypatch, tmp_path)
    recorded: list[tuple] = []
    monkeypatch.setattr(
        orch, "_record_gate", lambda ac, jid, name, res: recorded.append((name, res))
    )
    monkeypatch.setattr(orch, "_persist_repaired_narrative", lambda *a, **k: None)
    failed_agents: list[tuple] = []
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine._update_agent_state_inner",
        lambda *a, **k: failed_agents.append(a),
        raising=False,
    )

    voiceover = "satu dua tiga empat lima enam tujuh"
    script_output = {
        "voiceover_text": voiceover,
        "narrative_structure": [
            {"beat_id": 1, "start_cue": "satu dua tiga"},
            # Cue that does NOT appear anywhere in the voiceover.
            {"beat_id": 2, "start_cue": "kosong tidak ada di voiceover"},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=""
    )

    assert abort is not None
    assert abort["status"] == "failed"
    assert abort["failed_at"] == "narrative_coverage"
    # Stable routing token (FIX-5 router keys on this).
    assert abort["gate_reason"] == NARRATIVE_NOT_COVERED
    # Cue-specific reason survives in details for diagnostics.
    g7 = [r for name, r in recorded if name == "G7_narrative_coverage"]
    assert len(g7) == 1
    assert g7[0].data["reason"] == NARRATIVE_NOT_COVERED
    assert g7[0].data["cue_reason"] == CUE_NOT_FOUND
    assert g7[0].data["violation_type"] == "cue_not_matched"
    # G7 hard-fail marks the Scriptwriter failed so job-resume can target it.
    assert len(failed_agents) == 1
    assert failed_agents[0][2] == "scriptwriter"


def test_enforce_narrative_coverage_cue_out_of_order_routes_to_scriptwriter(tmp_path, monkeypatch):
    """FIX-8 plan §3: cues whose best-match positions are not monotonically
    increasing surface as cue_out_of_order (still routes to Scriptwriter
    regen via the stable narrative_not_covered token)."""
    from clipper_agency.core.beat_anchor import CUE_OUT_OF_ORDER

    orch = _helper_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "_record_gate", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_persist_repaired_narrative", lambda *a, **k: None)
    monkeypatch.setattr(
        "clipper_agency.orchestrator.engine._update_agent_state_inner",
        lambda *a, **k: None,
        raising=False,
    )

    # Cue[0] matches at position 2, cue[1] would match at position 0 → OOO.
    voiceover = "alpha beta gamma delta"
    script_output = {
        "voiceover_text": voiceover,
        "narrative_structure": [
            {"beat_id": 1, "start_cue": "gamma delta"},
            {"beat_id": 2, "start_cue": "alpha beta"},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=""
    )
    assert abort is not None
    assert abort["gate_reason"] == NARRATIVE_NOT_COVERED
    # Re-derive to confirm the violation_type is cue_out_of_order (the engine
    # surfaces the same stable cue token via details["cue_reason"]).
    from clipper_agency.core.beat_anchor import derive_word_ranges

    res = derive_word_ranges(voiceover, ["gamma delta", "alpha beta"])
    assert res.ok is False
    assert res.reason == CUE_OUT_OF_ORDER


# ── Review round-1 regression tests (pr-test-analyzer + codex) ──


def test_derived_ranges_ignore_stale_llm_word_range(tmp_path, monkeypatch):
    """job_20 regression (root cause): beats carrying BOTH a deliberately-wrong
    LLM ``word_range=[0,94]`` AND correct ``start_cue``s MUST derive from the
    cues and pass — the stale LLM word_range is ignored. Proves the contract
    shift (LLM no longer authoritative for word indices)."""
    from clipper_agency.core.beat_anchor import count_words

    orch = _helper_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "_record_gate", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_persist_repaired_narrative", lambda *a, **k: None)

    voiceover = (
        "halo guys hari ini gosip terbaru "
        "kemudian anji menikah lagi dengan wina "
        "dan terakhir jangan lupa follow update"
    )
    n = count_words(voiceover)
    bad_end = 94  # job_20-style under-index (claims 0..94 of a shorter voiceover)
    script_output = {
        "voiceover_text": voiceover,
        "narrative_structure": [
            {"beat_id": 1, "start_cue": "halo guys hari ini", "word_range": [0, bad_end]},
            {"beat_id": 2, "start_cue": "kemudian anji menikah lagi", "word_range": [0, bad_end]},
            {"beat_id": 3, "start_cue": "dan terakhir jangan lupa", "word_range": [0, bad_end]},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=""
    )
    assert abort is None  # derived from cues → pass despite stale word_range
    ranges = [b["word_range"] for b in script_output["narrative_structure"]]
    # Derived ranges fully cover [0, n-1] — the bad [0,94] was overwritten.
    assert ranges[0][0] == 0
    assert ranges[-1][1] == n - 1
    assert all(r[1] <= n - 1 for r in ranges)


def test_g7_rejects_voiceover_with_standalone_punctuation(tmp_path, monkeypatch):
    """FIX-8 codex round-4 P1: a voiceover whose whitespace-split count diverges
    from beat_anchor.tokenize (standalone ``...`` / ``—`` tokens) is a CONTRACT
    violation — the Voice Producer timestamps are whitespace-split, so derived
    word_range indices would offset. G7 rejects it (routes to Scriptwriter
    regen) instead of letting the divergent voiceover reach TTS."""
    from clipper_agency.core.beat_anchor import count_words

    orch = _helper_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "_record_gate", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_persist_repaired_narrative", lambda *a, **k: None)

    voiceover = "halo guys ... ternyata anji menikah — lalu raffi punya project besar"
    n = count_words(voiceover)
    # The standalone ``...`` and ``—`` make split() over-count tokenize().
    assert len(voiceover.split()) > n
    script_output = {
        "voiceover_text": voiceover,
        "narrative_structure": [
            {"beat_id": 1, "start_cue": "halo guys ternyata"},
            {"beat_id": 2, "start_cue": "lalu raffi punya"},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=""
    )
    # Rejected pre-derivation as a voiceover-tokenizer divergence.
    assert abort is not None
    assert abort["gate_reason"] == NARRATIVE_NOT_COVERED


def test_g7_accepts_hyphenated_reduplication(tmp_path, monkeypatch):
    """FIX-8 codex round-4 P1 (mirror): Indonesian reduplication (``kata-kata``,
    ``anak-anak``) and possessives (``jang'an``) are valid single tokens — the
    tokenizer preserves INTERNAL hyphens/apostrophes, so split() == tokenize()
    and the contract check passes (no spurious rejection of correct Indonesian)."""
    orch = _helper_orchestrator(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "_record_gate", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_persist_repaired_narrative", lambda *a, **k: None)

    voiceover = "kata-kata ini tentang anak-anak yang jang'an hidup tenang saja"
    # Internal hyphens preserved → split count == tokenize count (no divergence).
    assert len(voiceover.split()) == len(
        __import__("clipper_agency.core.beat_anchor", fromlist=["tokenize"]).tokenize(voiceover)
    )
    script_output = {
        "voiceover_text": voiceover,
        "narrative_structure": [
            {"beat_id": 1, "start_cue": "kata-kata ini tentang"},
            {"beat_id": 2, "start_cue": "yang jang'an hidup"},
        ],
    }

    abort = orch._enforce_narrative_coverage(
        MagicMock(), job_id=1, script_output=script_output, assets_cache=""
    )
    assert abort is None  # contract OK → derivation proceeds


def test_scriptwriter_normalize_through_g7_and_timeline_e2e(tmp_path, monkeypatch):
    """Plan §7 case 7 (full chain): Scriptwriter _normalize_narrative_structure
    derives word_range from start_cue → G7 passes → build_canonical_timeline
    produces one entry per beat (no mega-beat). Exercises the real normalize
    path, not a hand-built script_output."""
    from clipper_agency.agents.scriptwriter import _normalize_narrative_structure
    from clipper_agency.core.beat_anchor import count_words
    from clipper_agency.core.beat_timeline import build_canonical_timeline

    voiceover = (
        "halo guys hari ini gosip terbaru "
        "kemudian anji menikah lagi dengan wina natalia "
        "dan terakhir jangan lupa follow update gosip setiap hari"
    )
    raw_beats = [
        {"beat_id": 1, "section": "hook", "start_cue": "halo guys hari ini"},
        {"beat_id": 2, "section": "story_1", "start_cue": "kemudian anji menikah lagi"},
        {"beat_id": 3, "section": "closing_cta", "start_cue": "dan terakhir jangan lupa"},
    ]
    normalized = _normalize_narrative_structure(raw_beats, voiceover_text=voiceover)

    # Normalize backfilled word_range from cues, fully covering [0, n-1].
    n = count_words(voiceover)
    ranges = [b["word_range"] for b in normalized]
    assert ranges[0][0] == 0
    assert ranges[-1][1] == n - 1

    # build_canonical_timeline (downstream consumer) sees one beat per range.
    timestamps = [
        {"word": w, "start": i * 1.0, "end": i * 1.0 + 0.5} for i, w in enumerate(voiceover.split())
    ]
    timeline = build_canonical_timeline(normalized, timestamps)
    assert len(timeline) == 3  # no mega-beat
