"""Flask dashboard app with basic auth and job listing."""

import os

from flask import Flask, abort, jsonify, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect

from clipper_agency import __version__
from clipper_agency.bootstrap import load_env
from clipper_agency.config.loader import load_settings
from clipper_agency.core.job_debug import collect_job_debug, summarize_jobs
from clipper_agency.dashboard.auth import requires_auth
from clipper_agency.db.connection import get_connection
from clipper_agency.db.queries import PIPELINE_ORDER, get_agent_state, get_job, list_jobs
from clipper_agency.db.schema import initialize_schema
from clipper_agency.orchestrator.engine import Orchestrator

# Load .env BEFORE reading any env var (e.g. DASHBOARD_SECRET_KEY below) and
# before services are constructed. The dashboard/retry/resume paths previously
# skipped this, leaving every os.getenv service misconfigured.
load_env()

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY")


@app.before_request
def require_csrf_secret():
    """Fail closed for state-changing requests when CSRF config is missing."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not app.secret_key:
        abort(403)


csrf = CSRFProtect(app)

_JOB_NOT_FOUND = "Job not found"


@app.errorhandler(CSRFError)
def handle_csrf_error(error: CSRFError):
    """Return JSON for CSRF validation failures."""
    return jsonify({"error": error.description}), 400


def _get_db():
    """Get a database connection with schema initialization."""
    settings = load_settings()
    conn = get_connection(str(settings.db_path))
    initialize_schema(conn)
    return conn


@app.route("/", methods=["GET"])
@requires_auth
def index():
    """Dashboard home page."""
    return render_template("index.html", version=__version__)


@app.route("/jobs", methods=["GET"])
@requires_auth
def jobs_page():
    """Jobs listing page."""
    conn = _get_db()
    jobs = summarize_jobs(conn, list_jobs(conn, limit=50))
    return render_template("jobs.html", jobs=jobs, version=__version__)


@app.route("/jobs/<int:job_id>", methods=["GET"])
@requires_auth
def job_detail_page(job_id: int):
    """Render a read-only debug detail page for a job."""
    settings = load_settings()
    conn = _get_db()
    debug = collect_job_debug(conn, job_id, settings.assets_cache, settings.output_dir)
    if not debug:
        abort(404)
    return render_template("job_detail.html", debug=debug, version=__version__)


@app.route("/api/jobs", methods=["GET"])
@requires_auth
def api_jobs():
    """JSON API: list recent jobs."""
    conn = _get_db()
    return jsonify(list_jobs(conn, limit=50))


@app.route("/api/jobs/<int:job_id>", methods=["GET"])
@requires_auth
def api_job_detail(job_id: int):
    """JSON API: get a specific job."""
    conn = _get_db()
    job = get_job(conn, job_id)
    if not job:
        return jsonify({"error": _JOB_NOT_FOUND}), 404
    return jsonify(dict(job))


@app.route("/api/jobs/<int:job_id>/debug", methods=["GET"])
@requires_auth
def api_job_debug(job_id: int):
    """JSON API: get read-only job debug data."""
    settings = load_settings()
    conn = _get_db()
    debug = collect_job_debug(conn, job_id, settings.assets_cache, settings.output_dir)
    if not debug:
        return jsonify({"error": _JOB_NOT_FOUND}), 404
    return jsonify(debug)


@app.route("/api/jobs", methods=["POST"])
@requires_auth
def api_create_job():
    """JSON API: create and run a new job."""
    data = request.get_json(silent=True)
    if not data or "topic" not in data:
        return jsonify({"error": "topic is required"}), 400

    from clipper_agency.orchestrator.engine import Orchestrator

    settings = load_settings()
    orch = Orchestrator(db_path=str(settings.db_path))
    result = orch.run_pipeline(
        topic=data["topic"],
        niche=data.get("niche", "indonesian_artists"),
        output_dir=str(settings.output_dir),
    )
    return jsonify(result)


@app.route("/jobs/<int:job_id>/retry", methods=["POST"])
@requires_auth
def retry_job(job_id: int):
    """Retry a job from a specified agent.

    Expects JSON body with ``from_agent`` (required) and ``use_cache`` (optional).
    """
    data = request.get_json(silent=True) or {}
    from_agent = data.get("from_agent")
    if not from_agent:
        return jsonify({"error": "from_agent is required"}), 400

    settings = load_settings()
    conn = _get_db()
    job = get_job(conn, job_id)
    if not job:
        return jsonify({"error": _JOB_NOT_FOUND}), 404

    use_cache = data.get("use_cache", False)
    orch = Orchestrator(db_path=str(settings.db_path))
    result = orch.run_pipeline_from(job_id, from_agent=from_agent, use_cache=use_cache)
    return jsonify(result)


@app.route("/jobs/<int:job_id>/resume", methods=["POST"])
@requires_auth
def resume_job(job_id: int):
    """Resume a FAILED or PAUSED job from the failed/paused agent."""
    settings = load_settings()
    conn = _get_db()
    job = get_job(conn, job_id)
    if not job:
        return jsonify({"error": _JOB_NOT_FOUND}), 404

    # Find the failed agent to determine resume point
    target_agent = None
    for name in PIPELINE_ORDER:
        state = get_agent_state(conn, job_id, name)
        if state and state["state"] == "failed":
            target_agent = name
            break

    if not target_agent:
        return jsonify({"error": "Could not determine resume point"}), 400

    orch = Orchestrator(db_path=str(settings.db_path))
    result = orch.run_pipeline_from(job_id, from_agent=target_agent, use_cache=True)
    return jsonify(result)


def run_dashboard(host: str = "0.0.0.0", port: int = 5000) -> None:
    """Start the dashboard server (development only — use WSGI server in production)."""
    from werkzeug.serving import run_simple

    run_simple(host, port, app, use_debugger=False, use_reloader=False)
