"""Tests for the web dashboard with basic auth and job listing."""

import base64
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from clipper_agency.dashboard.auth import authenticate, check_auth, requires_auth
from clipper_agency.dashboard.app import app as dash_app
from clipper_agency.config.schema import AppSettings
from clipper_agency.db.connection import get_connection
from clipper_agency.db.queries import create_agent_state, create_job, mark_agent_failed
from clipper_agency.db.schema import initialize_schema

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Test credentials
TEST_USER = "admin"
TEST_PASS = "changeme"


class TestAuthFailsClosed:
    """auth fails closed when DASHBOARD_USERNAME or DASHBOARD_PASSWORD is unset."""

    def test_fails_when_username_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert check_auth("admin", "changeme") is False

    def test_fails_when_password_unset(self):
        with patch.dict(os.environ, {"DASHBOARD_USERNAME": "admin"}, clear=True):
            assert check_auth("admin", "any") is False

    def test_fails_when_both_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert check_auth("any", "any") is False


def test_check_auth_valid():
    """check_auth returns True when credentials match env vars."""
    with patch.dict(os.environ, {"DASHBOARD_USERNAME": TEST_USER, "DASHBOARD_PASSWORD": TEST_PASS}):
        assert check_auth(TEST_USER, TEST_PASS) is True


def test_check_auth_invalid_username():
    """check_auth returns False for wrong username."""
    with patch.dict(os.environ, {"DASHBOARD_USERNAME": TEST_USER, "DASHBOARD_PASSWORD": TEST_PASS}):
        assert check_auth("hacker", TEST_PASS) is False


def test_check_auth_invalid_password():
    """check_auth returns False for wrong password."""
    with patch.dict(os.environ, {"DASHBOARD_USERNAME": TEST_USER, "DASHBOARD_PASSWORD": TEST_PASS}):
        assert check_auth(TEST_USER, "wrongpass") is False


def test_check_auth_custom_env():
    """check_auth respects custom env vars."""
    with patch.dict(os.environ, {"DASHBOARD_USERNAME": "user", "DASHBOARD_PASSWORD": "pass"}):
        assert check_auth("user", "pass") is True
        assert check_auth("admin", "changeme") is False


def test_authenticate_returns_401_response():
    """authenticate returns a 401 with WWW-Authenticate header."""
    resp = authenticate()
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def test_requires_auth_decorator_blocks_unauth():
    """requires_auth returns 401 when no auth header provided."""

    @requires_auth
    def protected():
        return "secret"

    with dash_app.test_request_context("/"):
        resp = protected()
        assert resp.status_code == 401


def test_requires_auth_decorator_allows_auth():
    """requires_auth passes through when correct auth provided."""
    with patch.dict(os.environ, {"DASHBOARD_USERNAME": TEST_USER, "DASHBOARD_PASSWORD": TEST_PASS}):

        @requires_auth
        def protected():
            return "secret"

        credentials = base64.b64encode(b"admin:changeme").decode("utf-8")
        with dash_app.test_request_context(
            "/", headers={"Authorization": f"Basic {credentials}"}
        ):
            assert protected() == "secret"


# ── App Route Tests ──


@pytest.fixture(autouse=True)
def _set_auth_env():
    """Set auth env vars for all dashboard route tests."""
    with patch.dict(
        os.environ,
        {
            "DASHBOARD_USERNAME": TEST_USER,
            "DASHBOARD_PASSWORD": TEST_PASS,
            "DASHBOARD_SECRET_KEY": "test-secret",
        },
    ):
        yield


@pytest.fixture
def client():
    """Flask test client."""
    dash_app.testing = True
    dash_app.secret_key = "test-secret"
    dash_app.config.update(WTF_CSRF_ENABLED=True)
    return dash_app.test_client()


def _auth_header():
    credentials = base64.b64encode(b"admin:changeme").decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}


def _csrf_header(client):
    response = client.get("/", headers=_auth_header())
    token_match = re.search(
        r'<meta name="csrf-token" content="([^"]+)">', response.text
    )
    assert token_match is not None
    return {"X-CSRFToken": token_match.group(1)}


def test_index_requires_auth(client):
    """Index route returns 401 without auth."""
    resp = client.get("/")
    assert resp.status_code == 401


def test_index_with_auth(client):
    """Index route returns 200 with valid auth."""
    credentials = base64.b64encode(b"admin:changeme").decode("utf-8")
    resp = client.get("/", headers={"Authorization": f"Basic {credentials}"})
    assert resp.status_code == 200


def test_jobs_page_requires_auth(client):
    """Jobs page returns 401 without auth."""
    resp = client.get("/jobs")
    assert resp.status_code == 401


def test_jobs_page_with_auth(client):
    """Jobs page returns 200 with valid auth."""
    credentials = base64.b64encode(b"admin:changeme").decode("utf-8")
    resp = client.get("/jobs", headers={"Authorization": f"Basic {credentials}"})
    assert resp.status_code == 200


def test_api_jobs_requires_auth(client):
    """API jobs returns 401 without auth."""
    resp = client.get("/api/jobs")
    assert resp.status_code == 401


def test_api_jobs_with_auth_returns_json(client):
    """API jobs returns JSON list with valid auth."""
    credentials = base64.b64encode(b"admin:changeme").decode("utf-8")
    resp = client.get("/api/jobs", headers={"Authorization": f"Basic {credentials}"})
    assert resp.status_code == 200
    assert resp.is_json
    assert isinstance(resp.json, list)


def test_api_job_detail_not_found(client):
    """API job detail returns 404 for non-existent job."""
    credentials = base64.b64encode(b"admin:changeme").decode("utf-8")
    resp = client.get("/api/jobs/99999", headers={"Authorization": f"Basic {credentials}"})
    assert resp.status_code == 404
    assert resp.json["error"] == "Job not found"


def test_api_create_job_missing_topic(client):
    """API create job returns 400 when topic is missing."""
    headers = _auth_header() | _csrf_header(client)
    resp = client.post(
        "/api/jobs",
        json={},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "topic" in resp.json["error"]


def test_api_create_job_requires_csrf_token(client):
    """State-changing API requests require a CSRF token."""
    resp = client.post(
        "/api/jobs",
        json={"topic": "news"},
        headers=_auth_header(),
    )
    assert resp.status_code == 400


def test_api_create_job_fails_when_csrf_secret_missing(client):
    """State-changing API requests fail closed when CSRF config is missing."""
    dash_app.secret_key = None
    resp = client.post(
        "/api/jobs",
        json={"topic": "news"},
        headers=_auth_header() | {"X-CSRFToken": "token"},
    )
    assert resp.status_code == 403


def test_dashboard_get_routes_declare_http_methods():
    """GET-only routes declare methods explicitly for static analysis."""
    source = (PROJECT_ROOT / "clipper_agency/dashboard/app.py").read_text(encoding="utf-8")
    assert '@app.route("/", methods=["GET"])' in source
    assert '@app.route("/jobs", methods=["GET"])' in source
    assert '@app.route("/api/jobs", methods=["GET"])' in source
    assert '@app.route("/api/jobs/<int:job_id>", methods=["GET"])' in source
    assert '@app.route("/jobs/<int:job_id>", methods=["GET"])' in source
    assert '@app.route("/api/jobs/<int:job_id>/debug", methods=["GET"])' in source


def test_dashboard_index_uses_async_await():
    """Index template uses async/await instead of promise chaining."""
    source = (
        PROJECT_ROOT / "clipper_agency/dashboard/templates/index.html"
    ).read_text(encoding="utf-8")
    assert ".then(" not in source
    assert "await fetch" in source


@patch("clipper_agency.dashboard.app.load_settings")
@patch("clipper_agency.orchestrator.engine.Orchestrator.run_pipeline")
def test_api_create_job_passes_settings_to_orchestrator(mock_run, mock_settings, client):
    """Dashboard passes db_path and output_dir from settings to Orchestrator."""
    from clipper_agency.config.schema import AppSettings

    mock_settings.return_value = AppSettings(
        _env_file=None, db_path="test/db.db", output_dir="test/out",
    )
    mock_run.return_value = {"status": "completed", "job_id": 1, "output": {}}

    resp = client.post(
        "/api/jobs",
        json={"topic": "test topic"},
        headers=_auth_header() | _csrf_header(client),
    )
    assert resp.status_code == 200
    mock_run.assert_called_once_with(
        topic="test topic",
        niche="indonesian_artists",
        output_dir="test/out",
    )


def _create_debug_job(tmp_path):
    db_path = tmp_path / "clipper.db"
    assets_cache = tmp_path / "assets" / "cache"
    output_dir = tmp_path / "outputs"
    conn = get_connection(db_path)
    initialize_schema(conn)
    job_id = create_job(conn, "Agnez Mo update", "indonesian_artists")
    create_agent_state(conn, job_id, "voice_producer")
    mark_agent_failed(conn, job_id, "voice_producer", "All TTS providers failed")

    job_cache = assets_cache / f"job_{job_id}"
    (job_cache / "agents" / "segment_producer").mkdir(parents=True)
    (job_cache / "agents" / "voice_producer").mkdir(parents=True)
    (job_cache / "agents" / "composer").mkdir(parents=True)
    (job_cache / "agents" / "voice_producer" / "voices").mkdir(parents=True)
    (job_cache / "gates").mkdir(parents=True)
    (output_dir / f"job_{job_id}").mkdir(parents=True)

    (job_cache / "manifest.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
    (job_cache / "agents" / "segment_producer" / "research_brief.md").write_text("# Brief\nUseful context", encoding="utf-8")
    (job_cache / "agents" / "voice_producer" / "provider_attempts.json").write_text(
        json.dumps([{"provider": "elevenlabs", "status": "missing_key"}]),
        encoding="utf-8",
    )
    (job_cache / "agents" / "composer" / "ffmpeg_stderr.log").write_text("ffmpeg failed", encoding="utf-8")
    (job_cache / "gates" / "G8_audio_validation.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
    (job_cache / "agents" / "voice_producer" / "voices" / "scene_1.mp3").write_bytes(b"binary-audio")
    return job_id, AppSettings(
        _env_file=None,
        db_path=str(db_path),
        assets_cache=assets_cache,
        output_dir=output_dir,
    )


def test_jobs_page_includes_debug_summary_fields(client, tmp_path):
    """Jobs page shows current stage and failure summary fields."""
    _, settings = _create_debug_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings):
        resp = client.get("/jobs", headers=_auth_header())

    assert resp.status_code == 200
    assert "Current Stage" in resp.text
    assert "Failure" in resp.text
    assert "voice_producer failed" in resp.text
    assert "All TTS providers failed" in resp.text


def test_job_detail_page_renders_for_existing_job(client, tmp_path):
    """Job detail page renders debug data for an existing job."""
    job_id, settings = _create_debug_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings):
        resp = client.get(f"/jobs/{job_id}", headers=_auth_header())

    assert resp.status_code == 200
    assert "Pipeline Debug" in resp.text
    assert "Artifact Inventory" in resp.text
    assert "research_brief.md" in resp.text


def test_job_debug_api_returns_db_and_artifact_inventory(client, tmp_path):
    """Debug API returns DB rows, manifest, gates, agents, previews, and inventory."""
    job_id, settings = _create_debug_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings):
        resp = client.get(f"/api/jobs/{job_id}/debug", headers=_auth_header())

    assert resp.status_code == 200
    payload = resp.json
    assert payload["job"]["id"] == job_id
    assert payload["agent_states"][0]["agent_name"] == "voice_producer"
    assert payload["manifest"]["exists"] is True
    assert payload["previews"]["research_brief.md"].startswith("# Brief")
    assert payload["previews"]["provider_attempts.json"][0]["provider"] == "elevenlabs"
    assert payload["previews"]["ffmpeg_stderr.log"] == "ffmpeg failed"
    assert any(item["name"] == "G8_audio_validation.json" for item in payload["gates"])
    binary_items = [item for item in payload["artifacts"] if item["name"] == "scene_1.mp3"]
    assert binary_items
    assert "content" not in binary_items[0]


def test_job_detail_and_debug_api_return_404_for_missing_job(client, tmp_path):
    """Missing job detail and debug endpoints return 404."""
    _, settings = _create_debug_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings):
        page_resp = client.get("/jobs/99999", headers=_auth_header())
        api_resp = client.get("/api/jobs/99999/debug", headers=_auth_header())

    assert page_resp.status_code == 404
    assert api_resp.status_code == 404


# ── Phase 13: Dashboard retry/resume POST routes ────────────────────


def _create_retryable_job(tmp_path):
    """Create a FAILED job suitable for retry/resume testing."""
    from clipper_agency.db.queries import (
        create_agent_state, create_job, mark_agent_completed,
        mark_agent_failed, update_job_status,
    )

    db_path = tmp_path / "clipper.db"
    assets_cache = tmp_path / "assets" / "cache"
    output_dir = tmp_path / "outputs"

    conn = get_connection(str(db_path))
    initialize_schema(conn)
    job_id = create_job(conn, "Retry test topic", "indonesian_artists",
                        config_snapshot={
                            "topic": "Retry test topic",
                            "niche": "indonesian_artists",
                            "output_dir": str(output_dir),
                            "assets_cache": str(assets_cache),
                        })

    for name in ["safety", "segment_producer", "scriptwriter",
                 "voice_producer", "visual_director", "composer", "reviewer"]:
        create_agent_state(conn, job_id, name)

    for name in ["safety", "segment_producer", "scriptwriter",
                 "voice_producer", "visual_director"]:
        mark_agent_completed(conn, job_id, name)

    mark_agent_failed(conn, job_id, "composer", "FFmpeg crashed")
    update_job_status(conn, job_id, "FAILED", "composer failed")

    # Write manifest
    job_cache = assets_cache / f"job_{job_id}"
    job_cache.mkdir(parents=True)
    (job_cache / "manifest.json").write_text(
        json.dumps({"job_id": job_id, "agents": {}, "gates": {},
                     "final_outputs": {}}),
        encoding="utf-8",
    )

    settings = AppSettings(
        _env_file=None,
        db_path=str(db_path),
        assets_cache=str(assets_cache),
        output_dir=str(output_dir),
    )
    return job_id, settings


def test_post_retry_triggers_engine(client, tmp_path):
    """POST /jobs/<id>/retry triggers engine.run_pipeline_from."""
    job_id, settings = _create_retryable_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings), \
         patch("clipper_agency.dashboard.app.Orchestrator") as MockOrch:
        mock_instance = MockOrch.return_value
        mock_instance.run_pipeline_from.return_value = {
            "status": "completed", "job_id": job_id,
        }
        resp = client.post(
            f"/jobs/{job_id}/retry",
            json={"from_agent": "composer", "use_cache": False},
            headers=_auth_header() | _csrf_header(client),
        )

    assert resp.status_code == 200
    data = resp.json
    assert data["status"] == "completed"
    mock_instance.run_pipeline_from.assert_called_once()


def test_post_resume_triggers_engine(client, tmp_path):
    """POST /jobs/<id>/resume triggers engine.run_pipeline_from."""
    job_id, settings = _create_retryable_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings), \
         patch("clipper_agency.dashboard.app.Orchestrator") as MockOrch:
        mock_instance = MockOrch.return_value
        mock_instance.run_pipeline_from.return_value = {
            "status": "completed", "job_id": job_id,
        }
        resp = client.post(
            f"/jobs/{job_id}/resume",
            headers=_auth_header() | _csrf_header(client),
        )

    assert resp.status_code == 200
    data = resp.json
    assert data["status"] == "completed"
    mock_instance.run_pipeline_from.assert_called_once()


def test_post_retry_requires_csrf_token(client, tmp_path):
    """POST /jobs/<id>/retry requires a CSRF token."""
    job_id, settings = _create_retryable_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings):
        resp = client.post(
            f"/jobs/{job_id}/retry",
            json={"from_agent": "composer", "use_cache": False},
            headers=_auth_header(),
        )

    assert resp.status_code == 400


def test_post_resume_requires_csrf_token(client, tmp_path):
    """POST /jobs/<id>/resume requires a CSRF token."""
    job_id, settings = _create_retryable_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings):
        resp = client.post(
            f"/jobs/{job_id}/resume",
            headers=_auth_header(),
        )

    assert resp.status_code == 400


def test_post_retry_requires_from_agent(client, tmp_path):
    """POST /jobs/<id>/retry rejects request without from_agent."""
    job_id, settings = _create_retryable_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings):
        resp = client.post(
            f"/jobs/{job_id}/retry",
            json={"use_cache": False},
            headers=_auth_header() | _csrf_header(client),
        )

    assert resp.status_code == 400


def test_post_retry_missing_job_returns_404(client, tmp_path):
    """POST /jobs/99999/retry returns 404 for missing job."""
    _, settings = _create_retryable_job(tmp_path)
    with patch("clipper_agency.dashboard.app.load_settings", return_value=settings):
        resp = client.post(
            "/jobs/99999/retry",
            json={"from_agent": "composer"},
            headers=_auth_header() | _csrf_header(client),
        )

    assert resp.status_code == 404
