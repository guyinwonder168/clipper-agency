"""Tests for database CRUD queries."""

from clipper_agency.db.connection import close_connection, get_connection
from clipper_agency.db.queries import (
    append_audit_log,
    create_agent_state,
    create_job,
    get_agent_state,
    get_job,
    list_jobs,
    reset_agents_from,
    update_agent_state,
    update_job_status,
)
from clipper_agency.db.schema import initialize_schema


def test_create_and_get_job(temp_db_path):
    """Create a job and retrieve it by ID."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test topic", niche="indonesian_artists")
    assert job_id > 0
    job = get_job(conn, job_id)
    assert job["topic"] == "Test topic"
    assert job["niche"] == "indonesian_artists"
    assert job["status"] == "CREATED"
    close_connection()


def test_update_job_status(temp_db_path):
    """Update job status and verify the change."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="indonesian_artists")
    update_job_status(conn, job_id, "SAFETY_CHECKED")
    job = get_job(conn, job_id)
    assert job["status"] == "SAFETY_CHECKED"
    close_connection()


def test_completed_transition_clears_stale_error_message(temp_db_path):
    """FIX-5 (Codex P2): a repaired job transitioning FAILED -> COMPLETED
    must NOT retain the stale coverage-failure error_message.

    _update_job_status_inner force-clears error_message=NULL on a COMPLETED
    transition (COALESCE would otherwise preserve the old value for an empty
    arg). Anti-job_18: a successfully-repaired COMPLETED job must not surface
    narrative/timeline coverage-failure text in the DB, dashboard, or any
    error_message consumer."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="indonesian_artists")
    # FAIL with a coverage message (mirrors G7/FIX-6 abort).
    update_job_status(conn, job_id, "FAILED", "narrative_not_covered: gap")
    job = get_job(conn, job_id)
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["error_message"] == "narrative_not_covered: gap"
    # Repair succeeds -> COMPLETED must clear the stale text.
    update_job_status(conn, job_id, "COMPLETED")
    job = get_job(conn, job_id)
    assert job is not None
    assert job["status"] == "COMPLETED"
    assert job["error_message"] is None
    close_connection()


def test_create_and_get_agent_state(temp_db_path):
    """Create an agent state and retrieve it."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="indonesian_artists")
    create_agent_state(conn, job_id=job_id, agent_name="safety")
    state = get_agent_state(conn, job_id, "safety")
    assert state["state"] == "pending"
    assert state["agent_name"] == "safety"
    close_connection()


def test_update_agent_state(temp_db_path):
    """Update agent state and verify output_data is stored."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="indonesian_artists")
    create_agent_state(conn, job_id, "safety")
    update_agent_state(conn, job_id, "safety", "completed", output_data='{"result": "pass"}')
    state = get_agent_state(conn, job_id, "safety")
    assert state["state"] == "completed"
    close_connection()


def test_create_job_with_empty_config_snapshot(temp_db_path):
    """Empty dict config_snapshot is stored as '{}', not NULL."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test", config_snapshot={})
    job = get_job(conn, job_id)
    assert job["config_snapshot"] == "{}"
    close_connection()


def test_update_agent_state_clears_completed_at_on_retry(temp_db_path):
    """Transition from terminal to non-terminal clears completed_at."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test")
    create_agent_state(conn, job_id, "safety")
    update_agent_state(conn, job_id, "safety", "completed")
    state = get_agent_state(conn, job_id, "safety")
    assert state["completed_at"] is not None

    update_agent_state(conn, job_id, "safety", "running")
    state = get_agent_state(conn, job_id, "safety")
    assert state["state"] == "running"
    assert state["completed_at"] is None
    close_connection()


def test_list_jobs_returns_ordered(temp_db_path):
    """list_jobs returns jobs ordered by created_at DESC."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    create_job(conn, topic="A", niche="test")
    create_job(conn, topic="B", niche="test")
    jobs = list_jobs(conn)
    assert len(jobs) >= 2
    assert jobs[0]["id"] >= jobs[1]["id"]  # Most recent first
    close_connection()


# ── Task 11: Agent state transition helpers ──────────────────────


def test_mark_agent_running_sets_state_and_timestamps(temp_db_path):
    """mark_agent_running should set state to running and started_at."""
    from clipper_agency.db.queries import mark_agent_running

    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test")
    create_agent_state(conn, job_id, "safety")

    mark_agent_running(conn, job_id, "safety", input_data='{"topic":"X"}')

    state = get_agent_state(conn, job_id, "safety")
    assert state["state"] == "running"
    assert state["started_at"] is not None
    close_connection()


def test_mark_agent_completed_sets_state_and_output(temp_db_path):
    """mark_agent_completed should set state to completed, output, completed_at."""
    from clipper_agency.db.queries import mark_agent_completed

    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test")
    create_agent_state(conn, job_id, "segment_producer")

    mark_agent_completed(conn, job_id, "segment_producer", output_data='{"status":"completed"}')

    state = get_agent_state(conn, job_id, "segment_producer")
    assert state["state"] == "completed"
    assert state["output_data"] == '{"status":"completed"}'
    assert state["completed_at"] is not None
    close_connection()


def test_mark_agent_failed_sets_state_and_error(temp_db_path):
    """mark_agent_failed should set state to failed with error message."""
    from clipper_agency.db.queries import mark_agent_failed

    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test")
    create_agent_state(conn, job_id, "composer")

    mark_agent_failed(
        conn, job_id, "composer", "FFmpeg not found", output_data='{"status":"failed"}'
    )

    state = get_agent_state(conn, job_id, "composer")
    assert state["state"] == "failed"
    assert state["error_message"] == "FFmpeg not found"
    assert state["completed_at"] is not None
    close_connection()


def test_agent_state_transitions_in_order(temp_db_path):
    """Agent should go pending → running → completed in sequence."""
    from clipper_agency.db.queries import (
        mark_agent_completed,
        mark_agent_running,
    )

    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test")
    create_agent_state(conn, job_id, "safety")

    s1 = get_agent_state(conn, job_id, "safety")
    assert s1["state"] == "pending"

    mark_agent_running(conn, job_id, "safety")
    s2 = get_agent_state(conn, job_id, "safety")
    assert s2["state"] == "running"

    mark_agent_completed(conn, job_id, "safety")
    s3 = get_agent_state(conn, job_id, "safety")
    assert s3["state"] == "completed"
    close_connection()


# ── Phase 13: Audit log and retry helpers ──────────────────────────


def test_append_audit_log_inserts_row(temp_db_path):
    """append_audit_log inserts a row with all fields."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)

    append_audit_log(
        conn,
        action="job_retry",
        actor="cli",
        resource_type="job",
        resource_id=42,
        details='{"from_agent": "composer"}',
    )

    rows = conn.execute("SELECT * FROM audit_log").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["action"] == "job_retry"
    assert row["actor"] == "cli"
    assert row["resource_type"] == "job"
    assert row["resource_id"] == 42
    assert row["details"] == '{"from_agent": "composer"}'
    assert row["created_at"] is not None
    close_connection()


def test_reset_agents_from_resets_target_and_downstream(temp_db_path):
    """reset_agents_from resets the target agent and all downstream to pending."""
    from clipper_agency.db.queries import mark_agent_completed, mark_agent_failed

    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test")

    # Create full pipeline agents
    for name in [
        "safety",
        "segment_producer",
        "scriptwriter",
        "voice_producer",
        "visual_director",
        "composer",
        "reviewer",
    ]:
        create_agent_state(conn, job_id, name)

    # Mark early agents completed, composer failed
    mark_agent_completed(conn, job_id, "safety")
    mark_agent_completed(conn, job_id, "segment_producer")
    mark_agent_completed(conn, job_id, "scriptwriter")
    mark_agent_completed(conn, job_id, "voice_producer")
    mark_agent_failed(conn, job_id, "composer", "render error")

    # Reset from visual_director onward
    reset_agents_from(conn, job_id, "visual_director")

    # Upstream agents untouched
    assert get_agent_state(conn, job_id, "safety")["state"] == "completed"
    assert get_agent_state(conn, job_id, "segment_producer")["state"] == "completed"
    assert get_agent_state(conn, job_id, "scriptwriter")["state"] == "completed"
    assert get_agent_state(conn, job_id, "voice_producer")["state"] == "completed"

    # Target and downstream reset to pending
    assert get_agent_state(conn, job_id, "visual_director")["state"] == "pending"
    assert get_agent_state(conn, job_id, "composer")["state"] == "pending"
    assert get_agent_state(conn, job_id, "reviewer")["state"] == "pending"

    # Cleared timestamps and errors
    composer = get_agent_state(conn, job_id, "composer")
    assert composer["error_message"] is None
    assert composer["completed_at"] is None
    close_connection()


def test_reset_agents_from_invalid_agent_raises(temp_db_path):
    """reset_agents_from raises ValueError for unknown agent name."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    job_id = create_job(conn, topic="Test", niche="test")

    import pytest

    with pytest.raises(ValueError, match="Unknown agent"):
        reset_agents_from(conn, job_id, "nonexistent_agent")
    close_connection()


# ── Fail-fast contract guards: lastrowid is None ──────────────────


def test_create_job_raises_when_lastrowid_none():
    """create_job raises RuntimeError when cursor.lastrowid is None.

    Locks the fail-fast contract guard that replaced the old silent-None
    corruption (which would have returned None as a job_id). Fully hermetic: a
    MagicMock connection stands in for sqlite3 — its execute() returns a cursor
    whose lastrowid is None, so no real DB / INSERT row is needed. The happy
    path (lastrowid set) is covered by every other create_job test in this
    module."""
    from unittest.mock import MagicMock

    import pytest

    conn = MagicMock()
    conn.execute.return_value.lastrowid = None
    with pytest.raises(RuntimeError, match="create_job: INSERT returned no lastrowid"):
        create_job(conn, topic="Test", niche="test")


def test_create_agent_state_raises_when_lastrowid_none():
    """create_agent_state raises RuntimeError when cursor.lastrowid is None.

    Mirrors test_create_job_raises_when_lastrowid_none for the agent-state
    insert path. No real DB needed: the INSERT is fully mocked, so job_id=1
    never hits a FK constraint."""
    from unittest.mock import MagicMock

    import pytest

    conn = MagicMock()
    conn.execute.return_value.lastrowid = None
    with pytest.raises(RuntimeError, match="create_agent_state: INSERT returned no lastrowid"):
        create_agent_state(conn, job_id=1, agent_name="safety")
