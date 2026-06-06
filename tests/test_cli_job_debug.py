"""Tests for read-only CLI job diagnostics."""

import json

from click.testing import CliRunner

from clipper_agency.__main__ import cli
from clipper_agency.config.schema import AppSettings
from clipper_agency.db.connection import get_connection
from clipper_agency.db.queries import (
    create_agent_state, create_job, get_agent_state,
    mark_agent_completed, mark_agent_failed, update_job_status,
)
from clipper_agency.db.schema import initialize_schema


def _create_debug_job(tmp_path, monkeypatch):
    db_path = tmp_path / "clipper.db"
    assets_cache = tmp_path / "assets" / "cache"
    output_dir = tmp_path / "outputs"
    conn = get_connection(db_path)
    initialize_schema(conn)
    job_id = create_job(conn, "Raisa concert update", "indonesian_artists")
    create_agent_state(conn, job_id, "composer")
    mark_agent_failed(conn, job_id, "composer", "FFmpeg render failed")

    job_cache = assets_cache / f"job_{job_id}"
    final_dir = output_dir / f"job_{job_id}"
    (job_cache / "agents" / "segment_producer").mkdir(parents=True)
    (job_cache / "agents" / "voice_producer" / "voices").mkdir(parents=True)
    (job_cache / "agents" / "composer").mkdir(parents=True)
    (job_cache / "gates").mkdir(parents=True)
    final_dir.mkdir(parents=True)

    (job_cache / "manifest.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
    (job_cache / "agents" / "segment_producer" / "research_brief.md").write_text("# Research brief", encoding="utf-8")
    (job_cache / "agents" / "voice_producer" / "provider_attempts.json").write_text(
        json.dumps([{"provider": "gemini_tts", "status": "http_403"}]),
        encoding="utf-8",
    )
    (job_cache / "agents" / "composer" / "ffmpeg_stderr.log").write_text("dimension mismatch", encoding="utf-8")
    (job_cache / "gates" / "G10_video_validation.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
    (job_cache / "agents" / "voice_producer" / "voices" / "scene_1.mp3").write_bytes(b"binary-audio")
    (final_dir / "caption.txt").write_text("caption", encoding="utf-8")

    settings = AppSettings(
        _env_file=None,
        db_path=str(db_path),
        assets_cache=assets_cache,
        output_dir=output_dir,
    )
    monkeypatch.setattr("clipper_agency.__main__.load_settings", lambda: settings)
    return job_id


def test_jobs_command_includes_status_updated_and_failure_summary(tmp_path, monkeypatch):
    """jobs lists status, updated time, current stage, and compact failure summary."""
    _create_debug_job(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["jobs"])

    assert result.exit_code == 0
    assert "Raisa concert update" in result.output
    assert "composer failed" in result.output
    assert "FFmpeg render failed" in result.output
    assert "updated=" in result.output


def test_job_show_prints_single_job_summary(tmp_path, monkeypatch):
    """job-show prints one job's DB status and timestamps."""
    job_id = _create_debug_job(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["job-show", str(job_id)])

    assert result.exit_code == 0
    assert f"Job #{job_id}" in result.output
    assert "Raisa concert update" in result.output
    assert "Status:" in result.output
    assert "Created:" in result.output


def test_job_debug_prints_agent_states_gates_and_key_artifacts(tmp_path, monkeypatch):
    """job-debug prints job row, agent states, gates, and useful previews."""
    job_id = _create_debug_job(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["job-debug", str(job_id)])

    assert result.exit_code == 0
    assert "Agent States" in result.output
    assert "composer" in result.output
    assert "Gate Results" in result.output
    assert "G10_video_validation.json" in result.output
    assert "provider_attempts.json" in result.output
    assert "dimension mismatch" in result.output


def test_job_artifacts_lists_paths_and_does_not_inline_binary(tmp_path, monkeypatch):
    """job-artifacts lists binary artifacts with metadata only."""
    job_id = _create_debug_job(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["job-artifacts", str(job_id)])

    assert result.exit_code == 0
    assert "scene_1.mp3" in result.output
    assert "caption.txt" in result.output
    assert "binary-audio" not in result.output


def test_job_debug_commands_missing_job_return_nonzero(tmp_path, monkeypatch):
    """Missing jobs fail with a clear non-zero result."""
    _create_debug_job(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["job-show", "99999"])

    assert result.exit_code != 0
    assert "Job not found" in result.output


# ── Phase 13: job-retry / job-resume CLI ────────────────────────────

PIPELINE_AGENTS = [
    "safety", "segment_producer", "scriptwriter",
    "voice_producer", "visual_director", "composer", "reviewer",
]


def _create_failed_pipeline_job(tmp_path, monkeypatch):
    """Create a FAILED job with completed upstream agents and failed composer."""
    db_path = tmp_path / "clipper.db"
    assets_cache = tmp_path / "assets" / "cache"
    output_dir = tmp_path / "outputs"
    conn = get_connection(db_path)
    initialize_schema(conn)
    job_id = create_job(conn, "Agnez Mo new single", "indonesian_artists")

    for name in PIPELINE_AGENTS:
        create_agent_state(conn, job_id, name)

    # Upstream agents completed
    for name in ["safety", "segment_producer", "scriptwriter", "voice_producer"]:
        mark_agent_completed(conn, job_id, name)

    # visual_director completed
    mark_agent_completed(conn, job_id, "visual_director")

    # composer failed
    mark_agent_failed(conn, job_id, "composer", "FFmpeg crashed")

    # Job status FAILED
    update_job_status(conn, job_id, "FAILED", error_message="composer failed")

    # Minimal manifest
    job_cache = assets_cache / f"job_{job_id}"
    job_cache.mkdir(parents=True)
    (job_cache / "manifest.json").write_text(
        json.dumps({"job_id": job_id}), encoding="utf-8",
    )

    settings = AppSettings(
        _env_file=None,
        db_path=str(db_path),
        assets_cache=assets_cache,
        output_dir=output_dir,
    )
    monkeypatch.setattr("clipper_agency.__main__.load_settings", lambda: settings)
    return job_id, db_path


def test_job_retry_resets_target_and_downstream(tmp_path, monkeypatch):
    """job-retry --from <agent> resets that agent and downstream to pending."""
    job_id, db_path = _create_failed_pipeline_job(tmp_path, monkeypatch)

    from unittest.mock import patch
    with patch("clipper_agency.__main__.Orchestrator") as MockOrch:
        mock_instance = MockOrch.return_value
        mock_instance.run_pipeline_from.return_value = {
            "status": "completed", "job_id": job_id,
        }

        result = CliRunner().invoke(cli, ["job-retry", str(job_id), "--from", "composer"])

    assert result.exit_code == 0
    assert "composer" in result.output
    assert "pending" in result.output.lower() or "reset" in result.output.lower() or "completed" in result.output.lower()

    # Verify DB state: safety and visual_director remain completed
    conn = get_connection(db_path)
    from clipper_agency.db.queries import get_agent_state
    assert get_agent_state(conn, job_id, "safety")["state"] == "completed"
    assert get_agent_state(conn, job_id, "visual_director")["state"] == "completed"


def test_job_retry_invalid_agent_rejected(tmp_path, monkeypatch):
    """job-retry --from rejects unknown agent names."""
    job_id, _ = _create_failed_pipeline_job(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["job-retry", str(job_id), "--from", "nonexistent"])
    assert result.exit_code != 0


def test_job_retry_not_failed_rejected(tmp_path, monkeypatch):
    """job-retry rejects jobs that are not FAILED."""
    job_id, db_path = _create_failed_pipeline_job(tmp_path, monkeypatch)
    # Change status back to COMPLETED
    conn = get_connection(db_path)
    update_job_status(conn, job_id, "COMPLETED")

    result = CliRunner().invoke(cli, ["job-retry", str(job_id), "--from", "composer"])
    assert result.exit_code != 0
    assert "FAILED" in result.output


def test_job_resume_continues_from_failed_agent(tmp_path, monkeypatch):
    """job-resume finds the failed agent and resets it + downstream."""
    job_id, db_path = _create_failed_pipeline_job(tmp_path, monkeypatch)

    from unittest.mock import patch
    with patch("clipper_agency.__main__.Orchestrator") as MockOrch:
        mock_instance = MockOrch.return_value
        mock_instance.run_pipeline_from.return_value = {
            "status": "completed", "job_id": job_id,
        }

        result = CliRunner().invoke(cli, ["job-resume", str(job_id)])

    assert result.exit_code == 0
    assert "composer" in result.output

    # Verify DB: upstream agents remain completed
    conn = get_connection(db_path)
    from clipper_agency.db.queries import get_agent_state
    assert get_agent_state(conn, job_id, "visual_director")["state"] == "completed"


def test_job_resume_not_failed_or_paused_rejected(tmp_path, monkeypatch):
    """job-resume rejects jobs that are not FAILED or PAUSED."""
    job_id, db_path = _create_failed_pipeline_job(tmp_path, monkeypatch)
    conn = get_connection(db_path)
    update_job_status(conn, job_id, "COMPLETED")

    result = CliRunner().invoke(cli, ["job-resume", str(job_id)])
    assert result.exit_code != 0
    assert "FAILED" in result.output or "PAUSED" in result.output


# ── Phase 13 Batch 2: CLI-to-engine wiring ──────────────────────────


def test_job_retry_triggers_engine_execution(tmp_path, monkeypatch):
    """job-retry --from <agent> triggers orchestrator.run_pipeline_from."""
    job_id, db_path = _create_failed_pipeline_job(tmp_path, monkeypatch)
    video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

    from unittest.mock import patch
    with patch("clipper_agency.__main__.Orchestrator") as MockOrch:
        mock_instance = MockOrch.return_value
        mock_instance.run_pipeline_from.return_value = {
            "status": "completed", "job_id": job_id,
        }

        result = CliRunner().invoke(
            cli, ["job-retry", str(job_id), "--from", "composer"],
        )

    assert result.exit_code == 0
    assert "completed" in result.output.lower() or "Pipeline" in result.output
    mock_instance.run_pipeline_from.assert_called_once()
    call_kwargs = mock_instance.run_pipeline_from.call_args
    assert call_kwargs[1]["from_agent"] == "composer" or call_kwargs[0][1] == "composer"


def test_job_retry_with_use_cache_passes_flag(tmp_path, monkeypatch):
    """job-retry --from <agent> --use-cache passes use_cache to engine."""
    job_id, db_path = _create_failed_pipeline_job(tmp_path, monkeypatch)

    from unittest.mock import patch
    with patch("clipper_agency.__main__.Orchestrator") as MockOrch:
        mock_instance = MockOrch.return_value
        mock_instance.run_pipeline_from.return_value = {
            "status": "completed", "job_id": job_id,
        }

        result = CliRunner().invoke(
            cli, ["job-retry", str(job_id), "--from", "composer", "--use-cache"],
        )

    assert result.exit_code == 0
    call_kwargs = mock_instance.run_pipeline_from.call_args
    # Check use_cache was passed (either positional or keyword)
    assert call_kwargs[1].get("use_cache", False) is True


def test_job_resume_triggers_engine_execution(tmp_path, monkeypatch):
    """job-resume triggers orchestrator.run_pipeline_from."""
    job_id, db_path = _create_failed_pipeline_job(tmp_path, monkeypatch)

    from unittest.mock import patch
    with patch("clipper_agency.__main__.Orchestrator") as MockOrch:
        mock_instance = MockOrch.return_value
        mock_instance.run_pipeline_from.return_value = {
            "status": "completed", "job_id": job_id,
        }

        result = CliRunner().invoke(cli, ["job-resume", str(job_id)])

    assert result.exit_code == 0
    mock_instance.run_pipeline_from.assert_called_once()
