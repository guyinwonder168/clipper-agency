"""Clipper Agency — automated short-form video content production."""

import json
import os

import click
from dotenv import load_dotenv

from clipper_agency import __version__
from clipper_agency.config.loader import get_agent_config, load_niche, load_settings
from clipper_agency.config.preflight import preflight_agent_models
from clipper_agency.core.logging import get_logger, setup_logging
from clipper_agency.db.queries import PIPELINE_ORDER
from clipper_agency.orchestrator.engine import Orchestrator

# Load .env into os.environ before any service reads env vars.
load_dotenv()

logger = get_logger(__name__)

_NONE = "- none"


def _print_version(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"Clipper Agency v{__version__}")
    ctx.exit()


def _db_path() -> str:
    """Read database path from settings (env/.env) with fallback."""
    settings = load_settings()
    return str(settings.db_path)


def _output_dir() -> str:
    """Read output directory from settings (env/.env) with fallback."""
    settings = load_settings()
    return str(settings.output_dir)


def _assets_cache() -> str:
    """Read assets cache directory from settings (env/.env) with fallback."""
    settings = load_settings()
    return str(settings.assets_cache)


def _log_startup_info() -> None:
    """Log key configuration on startup for debugging."""
    settings = load_settings()
    logger.info("Clipper Agency v%s starting", __version__)
    logger.info("DB path: %s", settings.db_path)
    logger.info("Output dir: %s", settings.output_dir)
    agent_names = ["safety", "segment_producer", "scriptwriter", "visual_director", "reviewer"]
    agent_models = []
    for name in agent_names:
        cfg = get_agent_config(name)
        agent_models.append(cfg["model"] or "none")
    logger.info(
        "Agent models: safety=%s segment_producer=%s scriptwriter=%s visual_director=%s reviewer=%s",
        *agent_models,
    )
    # API key status (presence only — no values leaked)
    for key in [
        "OPENROUTER_API_KEY",
        "ELEVENLABS_API_KEY",
        "FISHAUDIO_API_KEY",
        "PEXELS_API_KEY",
        "SCRAPECREATORS_API_KEY",
        "FIRECRAWL_API_KEY",
        "GEMINI_API_KEY",
        "TAVILY_API_KEY",
        "BRAVE_API_KEY",
    ]:
        status = "CONFIGURED" if os.getenv(key) else "MISSING"
        logger.info("API key %s: %s", key, status)


@click.group()
@click.option(
    "--version",
    is_flag=True,
    callback=_print_version,
    expose_value=False,
    is_eager=True,
    help="Show version and exit",
)
@click.option("--log-level", default=None, help="Logging level (DEBUG, INFO, WARNING, ERROR)")
def cli(log_level: str | None) -> None:
    """Clipper Agency — automated video content production."""
    if log_level is None:
        settings = load_settings()
        log_level = settings.log_level
    setup_logging(log_level)
    # Only log startup info if this is a non-trivial command (not just --version)
    if not any(a == "--version" for a in (click.get_current_context().args or [])):
        _log_startup_info()


@cli.command()
@click.option("--topic", "-t", required=True, help="Topic for video generation")
@click.option("--niche", "-n", default="indonesian_artists", help="Niche profile")
@click.option("--db", default=None, help="Database path (default: from .env or data/clipper.db)")
@click.option(
    "--output-dir", "-o", default=None, help="Output directory (default: from .env or outputs)"
)
@click.option("--dry-run", is_flag=True, help="Validate input without running pipeline")
def run(topic: str, niche: str, db: str | None, output_dir: str | None, dry_run: bool) -> None:
    """Run the full pipeline for a topic."""
    click.echo(f"Clipper Agency — Topic: {topic}")
    click.echo(f"Niche: {niche}")

    # Validate niche exists before starting pipeline
    try:
        load_niche(niche)
    except FileNotFoundError:
        click.echo(
            f"Error: Niche '{niche}' not found. Check available niches in niches/ directory."
        )
        raise SystemExit(1)

    # Preflight: validate resolved agent models against the OpenRouter catalog
    # before billing any research credits (job_9/job_11 root cause: bad slugs
    # surfaced as mid-pipeline 404s). Runs on dry-run too — it is input validation.
    try:
        preflight_agent_models()
    except RuntimeError as exc:
        click.echo(f"Error: Model preflight failed: {exc}")
        raise SystemExit(1)

    if dry_run:
        click.echo("Dry run: input valid. Pipeline execution coming soon...")
        return

    resolved_db = db or _db_path()
    resolved_output = output_dir or _output_dir()

    click.echo("Starting pipeline...")
    orch = Orchestrator(db_path=resolved_db)
    result = orch.run_pipeline(topic=topic, niche=niche, output_dir=resolved_output)

    if result["status"] == "completed":
        click.echo(f"\N{CHECK MARK} Pipeline completed! Job ID: {result['job_id']}")
        out = result.get("output", {})
        if out.get("video_path"):
            click.echo(f"  Video: {out['video_path']}")
    else:
        reason = result.get("reason") or result.get("error") or "Unknown error"
        failed_at = result.get("failed_at", "")
        loc = f" at {failed_at}" if failed_at else ""
        click.echo(f"\N{CROSS MARK} Pipeline failed{loc}: {reason}")


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind")
@click.option("--port", default=5000, help="Port to bind")
def dashboard(host: str, port: int) -> None:
    """Start the web dashboard."""
    from clipper_agency.dashboard.app import run_dashboard

    click.echo(f"Dashboard starting at http://{host}:{port}")
    run_dashboard(host=host, port=port)


@cli.command()
def jobs() -> None:
    """List recent jobs."""
    from clipper_agency.core.job_debug import summarize_jobs
    from clipper_agency.db.connection import get_connection
    from clipper_agency.db.queries import list_jobs

    conn = get_connection(_db_path())
    raw_jobs = list_jobs(conn, limit=10)
    try:
        job_rows = summarize_jobs(conn, raw_jobs)
    except Exception:
        job_rows = [
            job
            | {
                "current_stage": job.get("status", "unknown"),
                "failure_summary": job.get("error_message", ""),
            }
            for job in raw_jobs
        ]
    for job in job_rows:
        if job["status"] == "COMPLETED":
            status_icon = "\N{CHECK MARK}"
        elif job["status"] == "FAILED":
            status_icon = "\N{CROSS MARK}"
        else:
            status_icon = "\N{HOURGLASS}"
        updated_at = job.get("updated_at") or job.get("created_at") or "unknown"
        failure = job.get("failure_summary") or ""
        failure_text = f" failure={failure}" if failure else ""
        click.echo(
            f"{status_icon} #{job['id']}: {job['topic']} — {job['status']} "
            f"stage={job.get('current_stage', job['status'])} updated={updated_at}{failure_text}"
        )


def _load_job_debug(job_id: int) -> dict:
    """Load debug payload or raise a ClickException."""
    from clipper_agency.core.job_debug import collect_job_debug
    from clipper_agency.db.connection import get_connection

    conn = get_connection(_db_path())
    debug = collect_job_debug(conn, job_id, _assets_cache(), _output_dir())
    if not debug:
        raise click.ClickException(f"Job not found: {job_id}")
    return debug


def _echo_job_summary(debug: dict) -> None:
    """Print a compact job summary."""
    job = debug["job"]
    summary = debug["summary"]
    click.echo(f"Job #{job['id']}")
    click.echo(f"Topic: {job['topic']}")
    click.echo(f"Niche: {job['niche']}")
    click.echo(f"Status: {job['status']}")
    click.echo(f"Current Stage: {summary['current_stage']}")
    click.echo(f"Error: {summary['failure_summary']}")
    click.echo(f"Created: {job.get('created_at')}")
    click.echo(f"Updated: {job.get('updated_at')}")
    click.echo(f"Completed: {job.get('completed_at')}")


@cli.command("job-show")
@click.argument("job_id", type=int)
def job_show(job_id: int) -> None:
    """Show one job's DB status and timestamps."""
    _echo_job_summary(_load_job_debug(job_id))


@cli.command("job-debug")
@click.argument("job_id", type=int)
def job_debug(job_id: int) -> None:
    """Show DB state, gate summaries, manifest status, and useful previews."""
    import json

    debug = _load_job_debug(job_id)
    _echo_job_summary(debug)

    click.echo("\nAgent States")
    for state in debug["agent_states"]:
        click.echo(
            f"- {state['agent_name']}: {state['state']} "
            f"started={state.get('started_at')} completed={state.get('completed_at')} "
            f"error={state.get('error_message') or ''}"
        )

    click.echo("\nGate Results")
    for gate in debug["gates"]:
        click.echo(f"- {gate['relative_path']} ({gate['size']} bytes)")
    if not debug["gates"]:
        click.echo(_NONE)

    manifest = debug["manifest"]
    click.echo(f"\nManifest: {manifest['path']} ({'found' if manifest['exists'] else 'missing'})")

    click.echo("\nUseful Previews")
    for name, preview in debug["previews"].items():
        click.echo(f"--- {name} ---")
        if isinstance(preview, str):
            click.echo(preview)
        else:
            click.echo(json.dumps(preview, indent=2, default=str))
    if not debug["previews"]:
        click.echo(_NONE)


@cli.command("job-artifacts")
@click.argument("job_id", type=int)
def job_artifacts(job_id: int) -> None:
    """List job artifact files without inlining binary content."""
    debug = _load_job_debug(job_id)
    click.echo(f"Artifacts for job #{job_id}")
    for artifact in debug["artifacts"]:
        binary = " binary" if artifact["binary"] else ""
        click.echo(
            f"- {artifact['path']} type={artifact['type']} size={artifact['size']} bytes{binary}"
        )
    if not debug["artifacts"]:
        click.echo(_NONE)


# ── Phase 13: job-retry / job-resume ────────────────────────────────

_RETRY_AGENTS = click.Choice(PIPELINE_ORDER)


@cli.command("job-retry")
@click.argument("job_id", type=int)
@click.option(
    "--from",
    "from_agent",
    type=_RETRY_AGENTS,
    required=True,
    help="Agent to retry from (resets this agent + downstream)",
)
@click.option(
    "--use-cache", is_flag=True, default=False, help="Reuse cached artifacts when available"
)
def job_retry(job_id: int, from_agent: str, use_cache: bool) -> None:
    """Retry a FAILED job from a specific agent.

    Resets the target agent and all downstream agents to pending.
    Earlier successful agent outputs are preserved.

    \b
    Examples:
      python -m clipper_agency job-retry 125 --from composer
      python -m clipper_agency job-retry 125 --from voice_producer --use-cache
    """
    from clipper_agency.db.connection import get_connection
    from clipper_agency.db.queries import (
        append_audit_log,
        get_job,
        reset_agents_from,
    )

    conn = get_connection(_db_path())
    job = get_job(conn, job_id)
    if not job:
        raise click.ClickException(f"Job not found: {job_id}")
    if job["status"] != "FAILED":
        raise click.ClickException(
            f"Job #{job_id} is {job['status']}, not FAILED. Only FAILED jobs can be retried."
        )

    cache_flag = " --use-cache" if use_cache else ""
    reset_names = reset_agents_from(conn, job_id, from_agent)
    append_audit_log(
        conn,
        action="job_retry",
        actor="cli",
        resource_type="job",
        resource_id=job_id,
        details=json.dumps(
            {"from_agent": from_agent, "use_cache": use_cache, "reset_agents": reset_names}
        ),
    )

    click.echo(f"Job #{job_id}: reset agents {reset_names} to pending.")
    click.echo(f"  Retry from: {from_agent}{cache_flag}")

    # Execute the pipeline from the target agent
    orch = Orchestrator(db_path=_db_path())
    result = orch.run_pipeline_from(job_id, from_agent=from_agent, use_cache=use_cache)

    if result.get("status") == "completed":
        click.echo(f"\N{CHECK MARK} Retry completed! Job #{job_id}")
    else:
        reason = result.get("reason") or result.get("error") or "Unknown"
        click.echo(f"\N{CROSS MARK} Retry failed: {reason}")


@cli.command("job-resume")
@click.argument("job_id", type=int)
def job_resume(job_id: int) -> None:
    """Resume a FAILED or PAUSED job from the failed/paused agent.

    For FAILED jobs: resets the failed agent and downstream to pending.
    For PAUSED jobs: resets the paused agent and downstream to pending.

    \b
    Examples:
      python -m clipper_agency job-resume 125
    """
    from clipper_agency.db.connection import get_connection
    from clipper_agency.db.queries import (
        append_audit_log,
        get_agent_state,
        get_job,
        reset_agents_from,
    )

    conn = get_connection(_db_path())
    job = get_job(conn, job_id)
    if not job:
        raise click.ClickException(f"Job not found: {job_id}")
    if job["status"] not in ("FAILED", "PAUSED"):
        raise click.ClickException(
            f"Job #{job_id} is {job['status']}. Only FAILED or PAUSED jobs can be resumed."
        )

    # Find the failed or first pending agent
    target_agent = None
    for name in PIPELINE_ORDER:
        state = get_agent_state(conn, job_id, name)
        if not state:
            continue
        if state["state"] == "failed":
            target_agent = name
            break
        if state["state"] == "pending" and job["status"] == "PAUSED":
            target_agent = name
            break

    if not target_agent:
        raise click.ClickException(
            f"Could not determine resume point for job #{job_id}. "
            f"Use job-retry --from <agent> to specify."
        )

    reset_names = reset_agents_from(conn, job_id, target_agent)
    append_audit_log(
        conn,
        action="job_resume",
        actor="cli",
        resource_type="job",
        resource_id=job_id,
        details=json.dumps({"from_agent": target_agent, "reset_agents": reset_names}),
    )

    click.echo(f"Job #{job_id}: resumed from {target_agent}.")
    click.echo(f"  Reset agents: {reset_names}")

    # Execute the pipeline from the resume point
    orch = Orchestrator(db_path=_db_path())
    result = orch.run_pipeline_from(job_id, from_agent=target_agent, use_cache=True)

    if result.get("status") == "completed":
        click.echo(f"\N{CHECK MARK} Resume completed! Job #{job_id}")
    else:
        reason = result.get("reason") or result.get("error") or "Unknown"
        click.echo(f"\N{CROSS MARK} Resume failed: {reason}")


# ── test-agent subcommand ──────────────────────────────────────────────────

AGENT_NAMES = [
    "safety",
    "segment_producer",
    "scriptwriter",
    "voice",
    "visual",
    "composer",
    "reviewer",
]


def _parse_script(script: str | None, fallback: list[dict]) -> list[dict]:
    """Parse JSON script string or return fallback."""
    import json

    return json.loads(script) if script else fallback


def _run_safety(instance: object, topic: str, rules: list[str]) -> dict:
    return instance.execute(job_id=0, topic=topic, safety_rules=rules)


def _run_segment_producer(
    instance: object, topic: str, rules: list[str], max_results: int, output_dir: str
) -> dict:
    return instance.execute(
        job_id=0, topic=topic, safety_rules=rules, max_results=max_results, output_dir=output_dir
    )


def _run_scriptwriter(instance: object, topic: str, rules: list[str], brief: str) -> dict:
    return instance.execute(job_id=0, topic=topic, research_brief=brief, safety_rules=rules)


def _run_voice(instance: object, script: str | None, output_dir: str) -> dict:
    parsed = _parse_script(script, [{"scene": 1, "text": "Test voice output.", "duration": 5}])
    return instance.execute(job_id=0, script=parsed, output_dir=output_dir)


def _run_visual(
    instance: object, topic: str, script: str | None, auto_research_output: dict, output_dir: str
) -> dict:
    parsed = _parse_script(script, [{"scene": 1, "duration": 5}])
    source_urls = auto_research_output.get("sources", {}).get("sources", [])
    urls = [s.get("share_url", "") for s in source_urls if isinstance(s, dict)]
    return instance.execute(
        job_id=0, script=parsed, topic=topic, source_urls=urls, output_dir=output_dir
    )


def _run_composer(instance: object, script: str | None, output_dir: str) -> dict:
    parsed = _parse_script(script, [{"scene": 1, "duration": 5}])
    return instance.execute(job_id=0, assets=parsed, audio_files=[], output_dir=output_dir)


def _run_reviewer(
    instance: object, topic: str, script: str | None, caption: str, rules: list[str]
) -> dict:
    parsed = _parse_script(script, [{"scene": 1, "text": "Test review content.", "duration": 5}])
    return instance.execute(
        job_id=0, topic=topic, script=parsed, caption=caption, safety_rules=rules
    )


def _dispatch_test_agent(
    agent: str,
    instance: object,
    topic: str,
    rules: list[str],
    max_results: int,
    research_brief: str | None,
    auto_research_output: dict,
    script: str | None,
    caption: str,
    output_dir: str,
) -> dict:
    """Execute the selected agent and return its result dict."""
    brief = research_brief or auto_research_output.get(
        "research_brief", "No research brief provided."
    )

    dispatch = {
        "safety": lambda: _run_safety(instance, topic, rules),
        "segment_producer": lambda: _run_segment_producer(
            instance, topic, rules, max_results, output_dir
        ),
        "scriptwriter": lambda: _run_scriptwriter(instance, topic, rules, brief),
        "voice": lambda: _run_voice(instance, script, output_dir),
        "visual": lambda: _run_visual(instance, topic, script, auto_research_output, output_dir),
        "composer": lambda: _run_composer(instance, script, output_dir),
        "reviewer": lambda: _run_reviewer(instance, topic, script, caption, rules),
    }

    handler = dispatch.get(agent)
    if handler:
        return handler()

    click.echo(f"Unknown agent: {agent}")
    return {}


@cli.command("test-agent")
@click.argument("agent", type=click.Choice(AGENT_NAMES))
@click.option("--topic", "-t", default="Test topic", help="Topic for the agent")
@click.option(
    "--safety-rules",
    default="no_defamation,mark_rumors_as_unconfirmed",
    help="Comma-separated safety rules",
)
@click.option("--max-results", default=3, help="Max search results (segment_producer only)")
@click.option("--research-brief", default=None, help="Research brief text (scriptwriter only)")
@click.option(
    "--auto-research", is_flag=True, help="Run researcher first to feed scriptwriter/visual"
)
@click.option("--script", default=None, help="Script JSON string (voice/visual/reviewer/composer)")
@click.option("--caption", default="Test caption", help="Caption text (reviewer only)")
@click.option("--output-dir", "-o", default=None, help="Output directory (default: test_outputs)")
def test_agent(
    agent: str,
    topic: str,
    safety_rules: str,
    max_results: int,
    research_brief: str | None,
    auto_research: bool,
    script: str | None,
    caption: str,
    output_dir: str | None,
) -> None:
    """Run a single agent independently for testing/debugging.

    AGENT is one of: safety, segment_producer, scriptwriter, voice,
    visual, composer, reviewer.

    \b
    Examples:
      python -m clipper_agency test-agent safety -t "Agnez Mo"
      python -m clipper_agency test-agent segment_producer -t "Agnez Mo" --max-results 2
      python -m clipper_agency test-agent scriptwriter -t "Agnez Mo" --auto-research
    """
    import json
    import time

    from clipper_agency.agents.composer import ComposerAgent
    from clipper_agency.agents.reviewer import ReviewerAgent
    from clipper_agency.agents.safety import SafetyAgent
    from clipper_agency.agents.scriptwriter import ScriptwriterAgent
    from clipper_agency.agents.segment_producer import SegmentProducerAgent
    from clipper_agency.agents.visual_director import VisualDirectorAgent
    from clipper_agency.agents.voice_producer import VoiceProducerAgent

    resolved_output = output_dir or _output_dir()
    rules = [r.strip() for r in safety_rules.split(",") if r.strip()]

    agent_map = {
        "safety": SafetyAgent,
        "segment_producer": SegmentProducerAgent,
        "scriptwriter": ScriptwriterAgent,
        "voice": VoiceProducerAgent,
        "visual": VisualDirectorAgent,
        "composer": ComposerAgent,
        "reviewer": ReviewerAgent,
    }

    instance = agent_map[agent]()
    click.echo(f"\n--- Testing {agent.upper()} agent ---")
    click.echo(f"Topic: {topic}")
    click.echo(f"Output dir: {resolved_output}")

    start = time.monotonic()

    # ── Auto-research: run segment_producer first to feed downstream ──────
    auto_research_output: dict = {}
    if auto_research and agent in ("scriptwriter", "visual"):
        click.echo("\n[auto-research] Running segment_producer first...")
        researcher = SegmentProducerAgent()
        auto_research_output = researcher.execute(
            job_id=0,
            topic=topic,
            safety_rules=rules,
            max_results=max_results,
            output_dir=resolved_output,
        )
        click.echo(
            f"[auto-research] Research brief: {len(auto_research_output.get('research_brief', ''))} chars"
        )

    result = _dispatch_test_agent(
        agent,
        instance,
        topic,
        rules,
        max_results,
        research_brief,
        auto_research_output,
        script,
        caption,
        resolved_output,
    )

    elapsed = time.monotonic() - start
    click.echo(f"\n--- Result (in {elapsed:.1f}s) ---")
    click.echo(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    cli()
