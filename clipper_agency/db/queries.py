"""CRUD query functions for jobs and agent states."""

import json
import sqlite3
from typing import Any

# Pipeline agent order — used for retry/resume reset logic.
PIPELINE_ORDER = [
    "safety", "segment_producer", "scriptwriter",
    "voice_producer", "visual_director", "composer", "reviewer",
]


def create_job(conn: sqlite3.Connection, topic: str, niche: str,
               account_id: int | None = None, template: str | None = None,
               config_snapshot: dict | None = None) -> int:
    """Insert a new job and return its ID."""
    cursor = conn.execute(
        """INSERT INTO jobs (topic, niche, account_id, template, config_snapshot)
           VALUES (?, ?, ?, ?, ?)""",
        (topic, niche, account_id, template,
         json.dumps(config_snapshot) if config_snapshot is not None else None),
    )
    conn.commit()
    return cursor.lastrowid


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    """Retrieve a job by ID."""
    cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def update_job_status(conn: sqlite3.Connection, job_id: int,
                      status: str, error_message: str | None = None) -> None:
    """Update a job's status."""
    conn.execute(
        """UPDATE jobs
           SET status = ?, updated_at = datetime('now'),
               error_message = COALESCE(?, error_message)
           WHERE id = ?""",
        (status, error_message, job_id),
    )
    conn.commit()


def list_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    """List jobs ordered by created_at descending."""
    cursor = conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
    )
    return [dict(row) for row in cursor.fetchall()]


def create_agent_state(conn: sqlite3.Connection, job_id: int,
                       agent_name: str) -> int:
    """Insert a new agent state and return its ID."""
    cursor = conn.execute(
        "INSERT INTO agent_states (job_id, agent_name) VALUES (?, ?)",
        (job_id, agent_name),
    )
    conn.commit()
    return cursor.lastrowid


def get_agent_state(conn: sqlite3.Connection, job_id: int,
                    agent_name: str) -> dict[str, Any] | None:
    """Retrieve an agent state by job_id and agent_name."""
    cursor = conn.execute(
        "SELECT * FROM agent_states WHERE job_id = ? AND agent_name = ?",
        (job_id, agent_name),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def update_agent_state(conn: sqlite3.Connection, job_id: int,
                       agent_name: str, state: str,
                       output_data: str | None = None,
                       error_message: str | None = None) -> None:
    """Update an agent state's status and optional output."""
    if state == "running":
        started_sql = "COALESCE(started_at, datetime('now'))"
        completed_sql = "NULL"
    elif state in ("completed", "failed"):
        started_sql = "started_at"
        completed_sql = "datetime('now')"
    else:
        started_sql = "started_at"
        completed_sql = "NULL"
    conn.execute(
        f"""UPDATE agent_states
            SET state = ?, output_data = COALESCE(?, output_data),
                error_message = COALESCE(?, error_message),
                started_at = {started_sql},
                completed_at = {completed_sql}
            WHERE job_id = ? AND agent_name = ?""",
        (state, output_data, error_message, job_id, agent_name),
    )
    conn.commit()


def mark_agent_running(conn: sqlite3.Connection, job_id: int,
                       agent_name: str, input_data: str | None = None) -> None:
    """Mark an agent as running and optionally store input_data."""
    update_agent_state(conn, job_id, agent_name, "running",
                       output_data=input_data)


def mark_agent_completed(conn: sqlite3.Connection, job_id: int,
                         agent_name: str,
                         output_data: str | None = None) -> None:
    """Mark an agent as completed and optionally store output_data."""
    update_agent_state(conn, job_id, agent_name, "completed",
                       output_data=output_data)


def mark_agent_failed(conn: sqlite3.Connection, job_id: int,
                      agent_name: str, error_message: str,
                      output_data: str | None = None) -> None:
    """Mark an agent as failed with error message."""
    update_agent_state(conn, job_id, agent_name, "failed",
                       output_data=output_data,
                       error_message=error_message)


def append_audit_log(conn: sqlite3.Connection, action: str,
                     actor: str | None = None,
                     resource_type: str | None = None,
                     resource_id: int | None = None,
                     details: str | None = None) -> None:
    """Insert a row into the audit_log table."""
    conn.execute(
        """INSERT INTO audit_log (action, actor, resource_type, resource_id, details)
           VALUES (?, ?, ?, ?, ?)""",
        (action, actor, resource_type, resource_id, details),
    )
    conn.commit()


def update_job_quality_status(conn: sqlite3.Connection,
                              job_id: int, quality_status: str) -> None:
    """Update the quality_status column on a job."""
    conn.execute(
        "UPDATE jobs SET quality_status = ?, updated_at = datetime('now') WHERE id = ?",
        (quality_status, job_id),
    )
    conn.commit()


def update_job_publication_status(conn: sqlite3.Connection,
                                  job_id: int, publication_status: str) -> None:
    """Update the publication_status column on a job."""
    conn.execute(
        "UPDATE jobs SET publication_status = ?, updated_at = datetime('now') WHERE id = ?",
        (publication_status, job_id),
    )
    conn.commit()


def update_job_artifact_status(conn: sqlite3.Connection,
                               job_id: int, artifact_status: str) -> None:
    """Update the artifact_status column on a job."""
    conn.execute(
        "UPDATE jobs SET artifact_status = ?, updated_at = datetime('now') WHERE id = ?",
        (artifact_status, job_id),
    )
    conn.commit()


def update_job_repair_status(conn: sqlite3.Connection,
                             job_id: int, repair_status: str) -> None:
    """Update the repair_status column on a job."""
    conn.execute(
        "UPDATE jobs SET repair_status = ?, updated_at = datetime('now') WHERE id = ?",
        (repair_status, job_id),
    )
    conn.commit()


def reset_agents_from(conn: sqlite3.Connection, job_id: int,
                       from_agent: str) -> list[str]:
    """Reset target agent and all downstream agents to pending.

    Clears completed_at and error_message for reset agents.
    Returns the list of agent names that were reset.

    Raises ValueError if from_agent is not a known pipeline agent.
    """
    if from_agent not in PIPELINE_ORDER:
        raise ValueError(f"Unknown agent: {from_agent}")

    start_idx = PIPELINE_ORDER.index(from_agent)
    reset_names = PIPELINE_ORDER[start_idx:]

    for name in reset_names:
        conn.execute(
            """UPDATE agent_states
               SET state = 'pending',
                   error_message = NULL,
                   completed_at = NULL
               WHERE job_id = ? AND agent_name = ?""",
            (job_id, name),
        )
    conn.commit()
    return reset_names
