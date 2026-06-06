"""Read-only job debugging helpers for dashboard and CLI."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from clipper_agency.core.paths import job_cache_dir, job_final_output_dir
from clipper_agency.db.queries import get_job

BINARY_SUFFIXES = {".mp3", ".wav", ".mp4", ".png", ".jpg", ".jpeg", ".webp"}
SECRET_TERMS = ("secret", "token", "password", "api_key", "apikey", "authorization")
_REDACTED = "[redacted]"


def summarize_jobs(conn: sqlite3.Connection, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach compact current-stage and failure summaries to job rows."""
    return [_summarize_job(conn, job) for job in jobs]


def collect_job_debug(
    conn: sqlite3.Connection,
    job_id: int,
    assets_cache: str | Path,
    output_dir: str | Path,
) -> dict[str, Any] | None:
    """Collect read-only DB and filesystem debug data for one job."""
    job = get_job(conn, job_id)
    if not job:
        return None

    cache_root = Path(job_cache_dir(assets_cache, job_id))
    final_root = Path(job_final_output_dir(output_dir, job_id))
    agent_states = _agent_states(conn, job_id)
    job_output = _job_output(conn, job_id)
    artifacts = _inventory_roots([cache_root, final_root])

    return {
        "job": job,
        "summary": _summary_from_states(job, agent_states),
        "agent_states": agent_states,
        "job_output": job_output,
        "manifest": _read_json_status(cache_root / "manifest.json"),
        "gates": _inventory_roots([cache_root / "gates"]),
        "agents": _inventory_roots([cache_root / "agents"]),
        "artifacts": artifacts,
        "previews": _previews(cache_root),
        "roots": {
            "assets_cache_job": str(cache_root),
            "output_dir_job": str(final_root),
        },
    }


def _summarize_job(conn: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    states = _agent_states(conn, int(job["id"]))
    return job | _summary_from_states(job, states)


def _summary_from_states(job: dict[str, Any], states: list[dict[str, Any]]) -> dict[str, str]:
    failed = next((state for state in states if state.get("state") == "failed"), None)
    running = next((state for state in states if state.get("state") == "running"), None)
    if failed:
        return {
            "current_stage": f"{failed['agent_name']} failed",
            "failure_summary": failed.get("error_message") or job.get("error_message") or "failed",
        }
    if running:
        return {"current_stage": f"{running['agent_name']} running", "failure_summary": ""}
    return {"current_stage": str(job.get("status", "unknown")), "failure_summary": job.get("error_message") or ""}


def _agent_states(conn: sqlite3.Connection, job_id: int) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """SELECT * FROM agent_states
           WHERE job_id = ?
           ORDER BY id ASC""",
        (job_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _job_output(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    cursor = conn.execute(
        "SELECT * FROM job_outputs WHERE job_id = ? ORDER BY id DESC LIMIT 1",
        (job_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _inventory_roots(roots: list[Path]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if _is_forbidden(path):
                continue
            stat = path.stat()
            items.append(
                {
                    "path": str(path),
                    "relative_path": str(path.relative_to(root)),
                    "name": path.name,
                    "type": _file_type(path),
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "binary": path.suffix.lower() in BINARY_SUFFIXES,
                }
            )
    return items


def _previews(cache_root: Path) -> dict[str, Any]:
    preview_paths = {
        "research_brief.md": cache_root / "agents" / "segment_producer" / "research_brief.md",
        "provider_attempts.json": cache_root / "agents" / "voice_producer" / "provider_attempts.json",
        "ffmpeg_stderr.log": cache_root / "agents" / "composer" / "ffmpeg_stderr.log",
    }
    previews: dict[str, Any] = {}
    for name, path in preview_paths.items():
        if not path.exists() or _is_forbidden(path) or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if path.suffix == ".json":
            previews[name] = _sanitize(_read_json(path))
        else:
            previews[name] = _sanitize_text(path.read_text(encoding="utf-8", errors="replace")[:4096])
    return previews


def _read_json_status(path: Path) -> dict[str, Any]:
    if not path.exists() or _is_forbidden(path):
        return {"exists": False, "path": str(path)}
    return {"exists": True, "path": str(path), "data": _sanitize(_read_json(path))}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (_REDACTED if _looks_secret(key) else _sanitize(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: str) -> str:
    redacted = value
    for term in SECRET_TERMS:
        redacted = redacted.replace(term.upper(), _REDACTED).replace(term, _REDACTED)
    return redacted


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(term in lowered for term in SECRET_TERMS)


def _is_forbidden(path: Path) -> bool:
    return path.name.startswith(".env") or _looks_secret(path.name)


def _file_type(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "file"
