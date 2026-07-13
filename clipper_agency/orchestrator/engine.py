"""Orchestrator Engine — coordinates the full gated agent pipeline."""

import json
import logging
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.agents.reviewer import ReviewerAgent
from clipper_agency.agents.safety import SafetyAgent
from clipper_agency.agents.scriptwriter import ScriptwriterAgent
from clipper_agency.agents.segment_producer import SegmentProducerAgent
from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.agents.voice_producer import VoiceProducerAgent
from clipper_agency.bootstrap import load_env
from clipper_agency.config.loader import (
    build_channel_description,
    get_angle_name,
    get_language_name,
    get_tone_name,
    load_niche,
    load_settings,
    resolve_relax_gates,
)
from clipper_agency.config.preflight import preflight_agent_models
from clipper_agency.config.schema import RepairPatch, RepairPlan
from clipper_agency.core.artifacts import write_json
from clipper_agency.core.beat_timeline import (
    TimelineContractError,
    build_canonical_timeline,
)
from clipper_agency.core.logging import add_job_file_handler, remove_job_file_handler
from clipper_agency.core.manifest import (
    create_manifest,
    update_manifest_agent,
    update_manifest_final,
    update_manifest_gate,
)
from clipper_agency.core.narrative_coverage import validate_narrative_coverage
from clipper_agency.core.paths import gate_result_file
from clipper_agency.core.repair_metrics import (
    compute_repair_cycle_record,
    extract_quality_snapshot,
    is_repair_improved,
    persist_repair_cycle,
)
from clipper_agency.core.repair_router import (
    NARRATIVE_NOT_COVERED,
    REGEN_NARRATIVE_ACTION,
    TIMELINE_NOT_COVERED,
    build_gate_failure_repair_plan,
    route_repair,
)
from clipper_agency.core.safe_paths import resolve_existing_file_under
from clipper_agency.core.validation import validate_agent_cache
from clipper_agency.db.connection import db_write_lock, get_connection
from clipper_agency.db.queries import (
    PIPELINE_ORDER,
    _update_agent_state_inner,
    _update_job_status_inner,
    append_audit_log,
    create_agent_state,
    create_job,
    get_job,
    mark_agent_completed,
    mark_agent_failed,
    mark_agent_running,
    reset_agents_from,
    update_job_artifact_status,
    update_job_publication_status,
    update_job_quality_status,
    update_job_repair_status,
    update_job_status,
)
from clipper_agency.db.schema import initialize_schema
from clipper_agency.observability.llm_trace import LLMTraceWriter
from clipper_agency.orchestrator.duration_gate import (
    DurationBudget,
    check_script_duration_budget,
    estimate_script_duration_sec,
)
from clipper_agency.orchestrator.gates import (
    GateAssetValidation,
    GateAudioValidation,
    GateCostEstimate,
    GateCreativeMemory,
    GateInputPreflight,
    GateNarrativeCoverage,
    GatePostResearchRisk,
    GateResearchCache,
    GateResult,
    GateScriptValidation,
    GateSourceQuality,
    GateVideoValidation,
)
from clipper_agency.orchestrator.validator import validate_content_direction
from clipper_agency.output.packager import OutputPackager

logger = logging.getLogger(__name__)

_LOG_MAX_LEN = 500
_RE_CTRL = re.compile(r"[\r\n\t]")


def _sanitize_for_log(text: str) -> str:
    """Strip control characters to prevent log injection (CWE-117)."""
    return _RE_CTRL.sub(" ", str(text))[:_LOG_MAX_LEN]


def _word_count_for_coverage(text: str) -> int:
    """Whitespace-separated word count for the G7 coverage gate.

    Local twin of ``agents.scriptwriter._word_count`` so the orchestrator
    stays decoupled from the agents layer (no orchestrator->agents import).
    """
    return len((text or "").split())


def _extract_main_entities(research_output: dict[str, Any] | None) -> list[str]:
    """Project Segment Producer ``entities`` to the flat name list the reviewer consumes.

    The Segment Producer emits ``entities`` as a list of ``{"name", "type"}``
    dicts (``segment_producer.py``). The reviewer's FIX-4 per-scene entity
    gate + the package-consistency gate both take a flat ``list[str]`` of names.
    Returns ``[]`` when research_output is missing or carries no entities, so
    the gate degrades to its no-op behavior (safe direction — recall loss only,
    never a bypass; ``derive_expected_entities`` still binds via visual_must_show).
    Used at BOTH ``_run_reviewer`` call sites so the gate fires on the normal
    path AND the repair path (blast-radius: a happy-path-only wire is inert).
    """
    if not research_output:
        return []
    entities = research_output.get("entities") or []
    return [str(e.get("name", "")) for e in entities if isinstance(e, dict) and e.get("name")]


_COMPOSER_FAILED = "Composer failed"
_PACKAGING_FAILED = "Packaging failed"
_VOICE_GEN_FAILED = "Voice generation failed"
_ASSET_SOURCING_FAILED = "Asset sourcing failed"
_SCRIPT_BUDGET_FAILED = "Scriptwriter duration budget exceeded"
_RESEARCH_FAILED = "Research generation failed"
_REPAIR_EXHAUSTED = "Repair cycles exhausted"
_MANUAL_REVIEW_REQUIRED = "Manual review required"
# FIX-5 (SonarCloud S1192): the persisted duplicate-guard filename was
# duplicated 3x as a string literal. Centralize it (DRY) so a future rename
# can't desync the load/save/reset sites.
_PREVIOUS_PATCHES_FILENAME = "previous_patches.json"
_GATE_RELAX_WARN_MSG = "DEV gate-relax: %s hard_fail RELAXED -> continuing. msg=%s"
_SAME_PATCH_REPEATED = "Identical repair patch repeated"
# FIX-5 (ADR 0030): a SINGLE Scriptwriter coverage-regen attempt before the
# job terminally FAILs (never "completes" a garbage uncovered-narrative video).
# Intentionally 1, not N: when a regen attempt STILL fails G7 inside
# ``_rerun_upstream_cascade``, the abort propagates as a coverage failure and
# the job terminally FAILs immediately. Re-prompting the same model that just
# failed the identical coverage gate with the identical "cover ALL words"
# directive is unlikely to fix the gap and burns TTS + LLM credits per retry;
# a model/prompt failure needs human triage, not blind repetition. This is a
# deliberate policy choice (KISS): one shot at repair, then surface failure.
_COVERAGE_MAX_REPAIR_CYCLES = 1
# FIX-5 (ADR 0030, Codex P2): the coverage directive injected into the
# Scriptwriter system prompt on a regen_narrative attempt. Without this the
# regen re-uses the identical first-run prompt and the model can re-emit the
# same under-covered narrative_structure until MAX_REPAIR_CYCLES exhausts.
_COVERAGE_REGEN_DIRECTIVE = (
    "COVERAGE CONTRACT (regeneration): your previous narrative_structure's "
    "word_range indices did NOT cover the full voiceover. You MUST emit "
    "narrative_structure whose word_range union is exactly [0, word_count-1] "
    "- contiguous, in-bounds, no gaps, no overlaps, starting at 0 and ending "
    "at the last word. Every word of voiceover_text must fall inside exactly "
    "one beat's word_range. Re-check the union before returning."
)


@dataclass
class RepairCycleContext:
    """Shared state for repair cycle helpers (AGENTS.md >5 params rule)."""

    cycle: int
    job_id: int
    topic: str
    output_dir: str
    assets_cache: str
    conn: Any
    niche_ctx: dict[str, Any]
    target_agent: str
    target_idx: int
    # FIX-5 (ADR 0030): when set to "regen_narrative", signals that the
    # cascade is a coverage-regen attempt so Scriptwriter gets the "cover
    # ALL words" prompt hint. Defaults to "" so the 8 existing callers
    # (non-coverage repairs) are unaffected.
    repair_hint: str = ""


class Orchestrator:
    """Coordinates the full gated agent pipeline: Topic → Output Package."""

    def __init__(self, db_path: str = "data/clipper.db") -> None:
        # Load .env before any service reads env vars. Orchestrator is the
        # common chokepoint for CLI + dashboard + retry + resume, so this
        # guarantees os.getenv is populated regardless of the entry point.
        load_env()
        self.db_path = db_path
        self._trace_writer = self._build_trace_writer()
        # DEV gate-relax: frozenset of gate IDs whose hard_fail is downgraded
        # to warn+continue. Default empty == today's byte-for-byte behavior.
        # Re-resolved at the start of run_pipeline / run_pipeline_from.
        self._relax_gates: frozenset[str] = frozenset()
        conn = get_connection(db_path)
        initialize_schema(conn)

    def _gate_relaxed(self, gate_name: str) -> bool:
        """True iff ``gate_name`` is in the current DEV relax-set.

        Case-insensitive: ``resolve_relax_gates`` uppercases tokens, so the
        lookup key is uppercased to match — call-sites use canonical names
        like ``"Safety"`` while operators may type ``safety`` / ``SAFETY``.
        """
        return gate_name.upper() in getattr(self, "_relax_gates", frozenset())

    @staticmethod
    def _build_trace_writer() -> LLMTraceWriter | None:
        """Create the shared LLM trace writer when tracing is enabled."""
        settings = load_settings()
        trace_cfg = settings.observability.llm_traces
        if not trace_cfg.enabled:
            return None
        return LLMTraceWriter(
            settings.assets_cache,
            redact_secrets=trace_cfg.redact_secrets,
        )

    def _init_job_statuses(self, conn, job_id: int) -> None:
        """Initialize lifecycle statuses at pipeline start."""
        update_job_quality_status(conn, job_id, "not_reviewed")
        update_job_publication_status(conn, job_id, "blocked")
        update_job_repair_status(conn, job_id, "none")

    def _record_gate(
        self, assets_cache: str, job_id: int, gate_name: str, result: GateResult
    ) -> str:
        """Persist a gate result to the job workspace."""
        path = gate_result_file(assets_cache, job_id, gate_name)
        write_json(path, asdict(result))
        update_manifest_gate(assets_cache, job_id, gate_name, result.passed, result.severity, path)
        return path

    def _complete_agent(self, conn, assets_cache: str, job_id: int, agent_name: str) -> None:
        """Mark agent completed in DB and manifest."""
        mark_agent_completed(conn, job_id, agent_name)
        update_manifest_agent(assets_cache, job_id, agent_name, "completed")

    def _fail_agent(
        self,
        conn: Any,
        job_id: int,
        agent_name: str,
        output: dict[str, Any],
        default_reason: str,
    ) -> dict[str, Any]:
        """Mark agent failed, update job, return failure dict."""
        error = output.get("error", default_reason)
        logger.error(
            "%s FAILED: %s", agent_name.replace("_", " ").title(), _sanitize_for_log(error)
        )
        mark_agent_failed(conn, job_id, agent_name, error)
        update_job_status(conn, job_id, "FAILED", error)
        return {
            "status": "failed",
            "failed_at": agent_name,
            "reason": error,
            "job_id": job_id,
        }

    def _handle_repair_plan(
        self,
        review_output: dict[str, Any],
        assets_cache: str,
        job_id: int,
        current_cycle: int,
    ) -> dict[str, Any] | None:
        """Route a reviewer repair plan to the correct agent.

        Returns a dict with ``decision``, ``target_agent``, and ``patches``
        if a repair plan is present and within cycle limits, or ``None``
        if no repair is needed or cycles are exhausted.
        """
        raw_plan = review_output.get("repair_plan")
        if raw_plan is None:
            return None

        max_cycles = raw_plan.get("max_repair_cycles", 2)
        if current_cycle >= max_cycles:
            logger.warning(
                "Repair cycle limit reached: %d >= %d for job %d",
                current_cycle,
                max_cycles,
                job_id,
            )
            return None

        patches_raw = raw_plan.get("patches", [])
        if not patches_raw:
            return None

        # Build a validated RepairPlan
        validated = [
            RepairPatch(
                beat_id=p["beat_id"],
                action=p["action"],
                reason=p["reason"],
                rerun_from=p["rerun_from"],
                timestamp_start_sec=p.get("timestamp_start_sec", 0.0),
                timestamp_end_sec=p.get("timestamp_end_sec", 0.0),
                required_visual=p.get("required_visual", ""),
            )
            for p in patches_raw
        ]
        plan = RepairPlan(
            decision=raw_plan.get("decision", "revise"),
            max_repair_cycles=max_cycles,
            patches=validated,
        )

        # Persist the plan to reviewer workspace
        plan_dir = Path(assets_cache) / f"job_{job_id}" / "agents" / "reviewer"
        write_json(str(plan_dir / "repair_plan.json"), plan.model_dump())

        # Route first patch to the correct agent
        target = route_repair(patches_raw[0])
        logger.info(
            "Repair plan routed to %s (decision=%s, cycle=%d/%d)",
            target,
            plan.decision,
            current_cycle,
            max_cycles,
        )

        return {
            "decision": plan.decision,
            "target_agent": target,
            "patches": [p.model_dump() for p in validated],
        }

    # ── Bounded repair loop (Task 6.2) ──

    def _are_patches_identical(
        self,
        prev: list[dict],
        curr: list[dict],
    ) -> bool:
        """Check if two patch lists describe the same repair action."""
        if len(prev) != len(curr):
            return False
        for p, c in zip(prev, curr):
            if (
                p.get("beat_id") != c.get("beat_id")
                or p.get("action") != c.get("action")
                or p.get("reason") != c.get("reason")
                or p.get("rerun_from") != c.get("rerun_from")
            ):
                return False
        return True

    def _load_previous_patches(
        self,
        assets_cache: str,
        job_id: int,
    ) -> list[dict]:
        """Load the previous cycle's patch list for repetition check."""
        repair_dir = Path(assets_cache) / f"job_{job_id}" / "repair"
        prev_path = repair_dir / _PREVIOUS_PATCHES_FILENAME
        if prev_path.exists():
            from clipper_agency.core.artifacts import read_json

            # FIX-5 (silent-failure P2): previous_patches.json is internal
            # bookkeeping for the duplicate-guard. A corrupt/partial file
            # (kill mid-write, fs issue) would raise JSONDecodeError and
            # mask the root cause as a generic pipeline exception, AND it
            # would pre-empt the single coverage regen attempt. Treat a
            # corrupt file as "no previous patches" — the guard simply
            # won't fire and the regen proceeds normally.
            try:
                return read_json(str(prev_path))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Corrupt repair patch state at %s, treating as empty (%s)",
                    prev_path,
                    exc,
                )
                return []
        return []

    def _save_previous_patches(
        self,
        assets_cache: str,
        job_id: int,
        patches: list[dict],
    ) -> None:
        """Persist the current patch list for next cycle's repetition check."""
        repair_dir = Path(assets_cache) / f"job_{job_id}" / "repair"
        repair_dir.mkdir(parents=True, exist_ok=True)
        write_json(str(repair_dir / _PREVIOUS_PATCHES_FILENAME), patches)

    def _reset_previous_patches(self, assets_cache: str, job_id: int) -> None:
        """Clear any persisted previous-patch state at the start of a repair run.

        The duplicate-patch guard (``_check_duplicate_patches``) is intended to
        catch a cycle repeating the SAME patch WITHIN one repair loop. The
        coverage-regen patch (``build_gate_failure_repair_plan``) is a CONSTANT
        across every coverage repair, so a stale persisted file from a PRIOR run
        (a retry/resume of a job that previously went through a coverage repair
        cycle) would byte-match cycle 1 of the NEW run and falsely exhaust it
        before any regen is attempted. Clearing here scopes the guard to within
        a single ``_execute_repair_cycle`` invocation (silent-failure P2)."""
        if not assets_cache:
            return
        prev_path = Path(assets_cache) / f"job_{job_id}" / "repair" / _PREVIOUS_PATCHES_FILENAME
        if prev_path.exists():
            try:
                prev_path.unlink()
            except OSError:
                logger.warning("Could not clear stale repair patches at %s", prev_path)

    def _handle_review_outcome(
        self,
        cycle: int,
        job_id: int,
        before_review: dict[str, Any],
        after_review: dict[str, Any],
        conn,
        assets_cache: str,
    ) -> dict[str, Any]:
        """Handle reviewer outcome: pass, continue with patches, or manual review.

        Returns an action dict with ``_action`` key (``"return"`` or ``"continue"``).
        """
        if after_review.get("status") == "pass":
            self._complete_agent(conn, assets_cache, job_id, "reviewer")
            update_job_repair_status(conn, job_id, "completed")
            update_job_quality_status(conn, job_id, "passed")
            update_job_artifact_status(conn, job_id, "approved")
            update_job_publication_status(conn, job_id, "ready")
            logger.info("Repair PASSED at cycle %d for job %d", cycle, job_id)
            return {
                "_action": "return",
                "status": "completed",
                "job_id": job_id,
                "cycle": cycle,
            }

        # Reviewer failed — check for new repair plan
        new_plan = after_review.get("repair_plan")
        if new_plan and new_plan.get("patches"):
            new_patches = new_plan["patches"]
            self._complete_agent(conn, assets_cache, job_id, "reviewer")
            update_job_quality_status(conn, job_id, "failed")
            return {
                "_action": "continue",
                "target_agent": route_repair(new_patches[0]),
                "patches": new_patches,
                "before_review": after_review,
            }

        # No LLM repair plan — try deterministic gate failure synthesis
        # (Codex P2 #2: enables multi-gate sequential repair within budget)

        gate_plan = build_gate_failure_repair_plan(after_review)
        if gate_plan:
            self._complete_agent(conn, assets_cache, job_id, "reviewer")
            update_job_quality_status(conn, job_id, "failed")
            return {
                "_action": "continue",
                "target_agent": gate_plan["target_agent"],
                "patches": gate_plan["patches"],
                "before_review": after_review,
            }

        # Reviewer failed with no repair plan — manual review
        self._complete_agent(conn, assets_cache, job_id, "reviewer")
        update_job_repair_status(conn, job_id, "exhausted")
        update_job_artifact_status(conn, job_id, "manual_review_required")
        update_job_quality_status(conn, job_id, "repair_exhausted")
        logger.warning(
            "Repair cycle %d: no repair plan, job %d needs manual review",
            cycle,
            job_id,
        )
        return {
            "_action": "return",
            "status": "manual_review_required",
            "job_id": job_id,
            "reason": _MANUAL_REVIEW_REQUIRED,
            "cycle": cycle,
        }

    def _check_duplicate_patches(
        self,
        cycle: int,
        job_id: int,
        patches: list[dict],
        assets_cache: str,
        conn,
    ) -> dict[str, Any] | None:
        """Return exhaustion dict if patches are identical to previous cycle, else None."""
        prev_patches = self._load_previous_patches(assets_cache, job_id)
        if not prev_patches or not self._are_patches_identical(prev_patches, patches):
            return None

        logger.warning(
            "Identical repair patch repeated at cycle %d for job %d",
            cycle,
            job_id,
        )
        update_job_repair_status(conn, job_id, "exhausted")
        update_job_artifact_status(conn, job_id, "manual_review_required")
        update_job_quality_status(conn, job_id, "repair_exhausted")
        append_audit_log(
            conn,
            action="repair_exhausted",
            actor="engine",
            resource_type="job",
            resource_id=job_id,
            details=json.dumps(
                {
                    "cycle": cycle,
                    "reason": _SAME_PATCH_REPEATED,
                }
            ),
        )
        return {
            "_action": "return",
            "status": "exhausted",
            "job_id": job_id,
            "reason": _SAME_PATCH_REPEATED,
            "cycle": cycle,
        }

    def _execute_single_repair_cycle(
        self,
        cycle: int,
        max_cycles: int,
        target_agent: str,
        patches: list[dict],
        before_review: dict[str, Any],
        job_id: int,
        assets_cache: str,
        output_dir: str,
        topic: str,
        conn,
    ) -> dict[str, Any]:
        """Execute one iteration of the repair cycle.

        Returns a dict with a ``_action`` key:
        - ``"return"`` — caller should return the dict immediately.
        - ``"continue"`` — caller should update state and continue looping.
          The dict also carries ``target_agent``, ``patches``, ``before_review``.
        """
        logger.info(
            "Repair cycle %d/%d: target=%s job=%d",
            cycle,
            max_cycles,
            target_agent,
            job_id,
        )

        # Check for repeated identical patches
        exhausted = self._check_duplicate_patches(cycle, job_id, patches, assets_cache, conn)
        if exhausted:
            return exhausted

        # Save current patches for next cycle's comparison
        self._save_previous_patches(assets_cache, job_id, patches)

        # Load niche context
        job = get_job(conn, job_id)
        snapshot = json.loads((job.get("config_snapshot") or "{}") if job else "{}")
        niche_ctx = snapshot.get("niche_ctx", {})

        # Determine which agent to rerun based on routing
        target_idx = PIPELINE_ORDER.index(target_agent)
        reset_agents_from(conn, job_id, target_agent)

        # Bundle shared repair state (AGENTS.md >5 params rule)
        ctx = RepairCycleContext(
            cycle=cycle,
            job_id=job_id,
            topic=topic,
            output_dir=output_dir,
            assets_cache=assets_cache,
            conn=conn,
            niche_ctx=niche_ctx,
            target_agent=target_agent,
            target_idx=target_idx,
            # FIX-5: thread the coverage-regen sentinel so the cascade adds
            # the "cover ALL words" prompt hint on the Scriptwriter re-run.
            repair_hint=patches[0].get("action", "") if patches else "",
        )

        if target_agent in ("segment_producer", "scriptwriter"):
            # Full cascade: SP→SW→VP→VD→Composer (Codex P2 #1).
            # FIX-5 (ADR 0030, OQ-1/RISK-5): target="scriptwriter" MUST take
            # this branch too — the ELSE branch (_run_cached_upstream_repair)
            # only RECONSTRUCTS Scriptwriter from cached disk state and would
            # reload the SAME broken narrative_structure (no actual regen).
            # The cascade re-executes _run_content_scriptwriter, regenerating
            # the structure fresh, then re-fires G7 on it.
            cascade = self._rerun_upstream_cascade(ctx)
            if isinstance(cascade, dict):
                cascade["_action"] = "return"
                return cascade
            (research_output, script_output, voice_output, compose_output, beat_timeline) = cascade
        else:
            # VD/Composer repair: reconstruct cached upstream outputs
            (research_output, script_output, voice_output, compose_output, beat_timeline, abort) = (
                self._run_cached_upstream_repair(ctx)
            )
            if abort:
                abort["_action"] = "return"
                return abort

        # Re-run reviewer
        mark_agent_running(conn, job_id, "reviewer")
        after_review = self._run_reviewer(
            job_id=job_id,
            topic=topic,
            script=script_output.get("script", []),
            caption=script_output.get("caption", ""),
            safety_rules=niche_ctx.get("safety_rules", []),
            audio_duration_sec=voice_output.get("voiceover_duration_sec", 0.0),
            visual_duration_sec=compose_output.get("output_duration_sec", 0.0),
            narrative_structure=script_output.get("narrative_structure", []),
            unverified_claims=script_output.get("unverified_claims", []),
            story_beats=research_output.get("story_beats", []),
            word_timestamps=voice_output.get("timestamps", []),
            rendered_scene_manifest=compose_output.get("rendered_scene_manifest"),
            diagnostics=compose_output.get("diagnostics", {}),
            beat_timeline=beat_timeline,
            # FIX-4 (ADR 0030): thread the source voiceover duration so the
            # reviewer's AUDIO_NOT_TRUNCATED re-probe fires on the repair path
            # too (blast-radius: a happy-path-only wire is inert in repair).
            voiceover_duration_sec=voice_output.get("voiceover_duration_sec", 0.0),
            # FIX-4 (ADR 0030): thread topic-level entities so the per-scene
            # entity-binding gate + package-consistency gate fire on the repair
            # path too (was always None → both gates degraded to no-op).
            main_entities=_extract_main_entities(research_output),
        )
        # Persist reviewer output for debugging in repair cycles too.
        self._persist_agent_output(assets_cache, job_id, "reviewer", after_review)

        # Persist repair cycle metrics
        record = compute_repair_cycle_record(
            cycle=cycle,
            source_agent="reviewer",
            target_agent=target_agent,
            before_review=before_review,
            after_review=after_review,
        )
        persist_repair_cycle(assets_cache, job_id, record)
        logger.info(
            "Repair cycle %d: review score %s→%s improved=%s",
            cycle,
            extract_quality_snapshot(before_review).get("reviewer_score", 0),
            extract_quality_snapshot(after_review).get("reviewer_score", 0),
            is_repair_improved(
                extract_quality_snapshot(before_review),
                extract_quality_snapshot(after_review),
            ),
        )

        # Check reviewer outcome
        return self._handle_review_outcome(
            cycle,
            job_id,
            before_review,
            after_review,
            conn,
            assets_cache,
        )

    def _maybe_reuse_cached_voiceover(
        self,
        ctx: RepairCycleContext,
        script_output: dict[str, Any],
    ) -> dict[str, Any] | None:
        """FIX-5 vo-diff skip (claude-auto-tok pattern).

        Return the cached voice_producer output to REUSE when a Scriptwriter
        regen left ``voiceover_text`` byte-identical to the previously
        persisted voiceover AND the cached audio has a valid
        ``voiceover_path`` (cache-integrity guard). Return ``None`` to signal
        the caller must regen via Voice Producer.

        Safe because audio is the master (ADR 0020): if audio is unchanged,
        the canonical timeline is unchanged, so VD/Composer re-decisions are
        deterministic. Only the cascade path (target in segment_producer /
        scriptwriter) re-runs Scriptwriter, so this is the only place the
        skip applies.
        """
        prev_vo = self._load_agent_output(ctx.assets_cache, ctx.job_id, "voice_producer")
        if not prev_vo:
            return None
        # Cache-integrity backstop (Codex P2): the path string being truthy is
        # NOT enough — verify the audio file actually exists on disk. A
        # cross-job cleanup / partial fs / resume-on-different-host can leave
        # the JSON referencing a deleted file; reusing it would feed a missing
        # audio master to Composer/Reviewer.
        vo_path = prev_vo.get("voiceover_path", "")
        # FIX-5 (SonarCloud S6549): vo_path comes from persisted JSON (tainted).
        # Validate existence AND containment under the workspace cache dir
        # before trusting it — an out-of-workspace or missing path aborts to
        # the safe regen fallback (resolve_existing_file_under returns None).
        if not vo_path or not resolve_existing_file_under(ctx.assets_cache, vo_path):
            logger.info(
                "VO-diff skip aborted: cached audio missing on disk (job %d, cycle %d)",
                ctx.job_id,
                ctx.cycle,
            )
            return None
        prev_text = prev_vo.get("voiceover_text", "")
        new_text = script_output.get("voiceover_text", "")
        # Only skip when BOTH sides have a real (non-empty) text AND they match
        # byte-for-byte. An empty new_text (Scriptwriter parse failure ->
        # _empty_output) must NOT reuse stale audio for an empty voiceover.
        if new_text and prev_text and new_text == prev_text:
            # Belt-and-suspenders (silent-failure P2): byte-identical
            # voiceover_text implies identical _word_count_for_coverage(new)
            # == _word_count_for_coverage(prev), so the cached timestamps
            # remain valid BY CONSTRUCTION. If a future change to how word
            # count is derived desyncs that invariant, the cached
            # timestamps length would no longer match the new word count —
            # detect it here and fall through to regen (safe default)
            # rather than reuse stale timestamps.
            expected_words = _word_count_for_coverage(new_text)
            cached_ts = prev_vo.get("timestamps", [])
            if expected_words and len(cached_ts) != expected_words:
                logger.warning(
                    "VO-diff skip aborted: cached timestamps (%d) != word "
                    "count (%d) for byte-identical text (job %d, cycle %d) "
                    "— word_count derivation desync suspected, regenerating",
                    len(cached_ts),
                    expected_words,
                    ctx.job_id,
                    ctx.cycle,
                )
                return None
            logger.info(
                "VO-diff skip: voiceover_text unchanged, reusing cached audio (job %d, cycle %d)",
                ctx.job_id,
                ctx.cycle,
            )
            return prev_vo
        return None

    def _run_research_for_repair(
        self,
        ctx: RepairCycleContext,
    ) -> tuple[dict[str, Any], bool]:
        """Run Segment Producer fresh for a repair cascade (DRY helper).

        Returns ``(research_output, ok)``. On failure ``_fail_agent`` is
        invoked (stamping the abort) and ``ok`` is ``False`` so the caller
        returns the abort immediately; on success ``ok`` is ``True`` and SP
        is marked completed.
        """
        research_output = self._run_researcher(
            job_id=ctx.job_id,
            topic=ctx.topic,
            safety_rules=ctx.niche_ctx.get("safety_rules", []),
            channel_description=ctx.niche_ctx.get("channel_description", ""),
            language=ctx.niche_ctx.get("language", "id"),
            tone=ctx.niche_ctx.get("tone", "informative"),
            content_angle=ctx.niche_ctx.get("content_angle", ""),
            output_dir=ctx.output_dir,
            assets_cache=ctx.assets_cache,
        )
        if research_output.get("status") == "failed":
            return (
                self._fail_agent(
                    ctx.conn, ctx.job_id, "segment_producer", research_output, _RESEARCH_FAILED
                ),
                False,
            )
        self._complete_agent(ctx.conn, ctx.assets_cache, ctx.job_id, "segment_producer")
        return research_output, True

    def _rerun_upstream_cascade(
        self,
        ctx: RepairCycleContext,
    ) -> dict[str, Any] | tuple:
        """Rerun SP→SW→VP→VD→Composer cascade for upstream repair.

        Returns a 5-tuple (research, script, voice, compose,
        beat_timeline) on success, or an abort dict on failure.
        """
        # Rerun Segment Producer — UNLESS this is a Scriptwriter-only
        # coverage repair (FIX-5 / codex P1). reset_agents_from(...,'scriptwriter')
        # left SP's DB state + disk artifacts intact, so re-running paid
        # external research (ScrapeCreators/Firecrawl/Tavily/Brave) is pure
        # waste AND a spurious failure surface (a transient research-provider
        # error would abort before Scriptwriter regen is even attempted). SP
        # output is the master input to Scriptwriter and is already on disk;
        # reuse it. Only a segment_producer-targeted repair needs fresh research.
        if ctx.target_agent == "segment_producer":
            research_output, ok = self._run_research_for_repair(ctx)
            if not ok:
                return research_output
        else:
            # Scriptwriter-targeted coverage repair: reuse persisted SP output.
            # If the cached output is missing/empty (partial fs / pre-SP job),
            # fall back to a fresh research run rather than feed Scriptwriter
            # nothing (safe default; preserves the original behavior).
            research_output = self._load_agent_output(
                ctx.assets_cache, ctx.job_id, "segment_producer"
            )
            if not research_output:
                logger.warning(
                    "Coverage SW-regen for job %d: no cached SP output, "
                    "running Segment Producer fresh",
                    ctx.job_id,
                )
                research_output, ok = self._run_research_for_repair(ctx)
                if not ok:
                    return research_output

        # Rerun Scriptwriter + G7 coverage enforce (FIX-5 threads the
        # coverage-regen sentinel through _run_content_scriptwriter).
        script_output, abort = self._rerun_scriptwriter(ctx, research_output)
        if abort:
            return abort

        # VO-diff skip (claude-auto-tok pattern) + Voice Producer rerun.
        voice_output, abort = self._rerun_voice_producer(ctx, script_output)
        if abort:
            return abort

        # Rebuild canonical timeline from fresh outputs (ADR 0020).
        # FIX-6: enforce the physical-timeline contract (backstop for G7).
        beat_timeline, abort = self._enforce_timeline_contract(
            ctx.conn,
            ctx.job_id,
            ctx.assets_cache,
            script_output.get("narrative_structure", []),
            voice_output.get("timestamps", []),
        )
        if abort:
            return abort

        # Rerun Visual Director
        visual_output = self._run_visual_director_phase(
            ctx.conn,
            ctx.job_id,
            ctx.topic,
            research_output,
            script_output,
            ctx.output_dir,
            ctx.assets_cache,
            voice_output=voice_output,
            beat_timeline=beat_timeline,
        )
        if visual_output.get("status") == "failed":
            return self._fail_agent(
                ctx.conn, ctx.job_id, "visual_director", visual_output, _ASSET_SOURCING_FAILED
            )

        # Rerun Composer
        compose_output, abort = self._retry_composer_stage(
            ctx.conn,
            ctx.job_id,
            visual_output,
            voice_output,
            ctx.output_dir,
            ctx.assets_cache,
            cycle=ctx.cycle,
            beat_timeline=beat_timeline,
        )
        if abort:
            return abort

        return (research_output, script_output, voice_output, compose_output, beat_timeline)

    def _rerun_scriptwriter(
        self,
        ctx: RepairCycleContext,
        research_output: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Rerun Scriptwriter and enforce G7 coverage on the repair path.

        Returns ``(script_output, abort)`` where ``abort`` is ``None`` on
        success, or a failure dict (failed Scriptwriter or G7 gate) the caller
        returns immediately. Mirrors the
        :meth:`_enforce_timeline_contract` / :meth:`_retry_composer_stage`
        convention. Extracted from :meth:`_rerun_upstream_cascade` to drop its
        cognitive complexity below 15 (SonarCloud S3776).
        """
        # Rerun Scriptwriter
        script_output = self._run_content_scriptwriter(
            ctx.conn,
            ctx.job_id,
            ctx.topic,
            ctx.niche_ctx.get("safety_rules", []),
            ctx.niche_ctx.get("channel_description", ""),
            ctx.niche_ctx.get("language", "id"),
            ctx.niche_ctx.get("tone", "informative"),
            ctx.niche_ctx.get("content_angle", ""),
            research_output,
            ctx.assets_cache,
            # FIX-5: thread the coverage-regen sentinel so Scriptwriter gets
            # the "cover ALL words" hint on a coverage-regen attempt.
            repair_hint=ctx.repair_hint,
        )
        if script_output.get("status") == "failed":
            return (
                {},
                self._fail_agent(
                    ctx.conn, ctx.job_id, "scriptwriter", script_output, _SCRIPT_BUDGET_FAILED
                ),
            )

        # G7 (ADR 0030 / FIX-1): enforce coverage on the repair-rerun path too.
        if abort := self._enforce_narrative_coverage(
            ctx.conn, ctx.job_id, script_output, ctx.assets_cache
        ):
            return ({}, abort)
        return (script_output, None)

    def _rerun_voice_producer(
        self,
        ctx: RepairCycleContext,
        script_output: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Rerun Voice Producer with the claude-auto-tok vo-diff skip.

        Audio is the master (ADR 0020); if a coverage-regen leaves
        voiceover_text byte-identical to the previously persisted voiceover,
        reuse the cached audio + timestamps instead of burning a TTS call.
        Returns ``(voice_output, abort)`` where ``abort`` is ``None`` on
        success or a failure dict on a failed Voice Producer. Extracted from
        :meth:`_rerun_upstream_cascade` to drop its cognitive complexity
        below 15 (SonarCloud S3776).
        """
        # Cache integrity guard: only skip when the cached voice has a valid
        # voiceover_path (else fall through to regen).
        voice_output = self._maybe_reuse_cached_voiceover(ctx, script_output)
        if voice_output is None:
            mark_agent_running(ctx.conn, ctx.job_id, "voice_producer")
            voice_output = self._run_voice_producer(
                job_id=ctx.job_id,
                script=script_output.get("script", []),
                voiceover_text=script_output.get("voiceover_text", ""),
                output_dir=ctx.output_dir,
                assets_cache=ctx.assets_cache,
            )
            # _run_voice_producer already stamped + re-persisted voiceover_text
            # onto the output (the contract has no such field) so a later
            # regen's VO-diff skip has real data to compare against.
        if voice_output.get("status") == "failed":
            return (
                {},
                self._fail_agent(
                    ctx.conn, ctx.job_id, "voice_producer", voice_output, _VOICE_GEN_FAILED
                ),
            )
        self._complete_agent(ctx.conn, ctx.assets_cache, ctx.job_id, "voice_producer")
        return (voice_output, None)

    def _run_cached_upstream_repair(
        self,
        ctx: RepairCycleContext,
    ) -> tuple[dict, dict, dict, dict, list, dict | None]:
        """Rerun VD and/or Composer using cached upstream outputs.

        Returns (research, script, voice, compose, beat_timeline, abort).
        ``abort`` is None on success, or a failure dict on abort.
        """
        (research_output, script_output, voice_output, visual_output) = (
            self._reconstruct_upstream_outputs(
                ctx.target_idx,
                ctx.assets_cache,
                ctx.job_id,
            )
        )

        # G7 (ADR 0030 / FIX-1): enforce coverage on the cached-repair path
        # too. A pre-G7 / cached job_18-style word_range must not recreate the
        # mega-beat when a VD/composer repair reloads it (Codex P2).
        g7_abort = self._enforce_narrative_coverage(
            ctx.conn, ctx.job_id, script_output, ctx.assets_cache
        )
        if g7_abort:
            return (research_output, script_output, voice_output, {}, [], g7_abort)

        # Build canonical timeline for repair cycle (ADR 0020).
        # FIX-6: enforce the physical-timeline contract (backstop for G7).
        beat_timeline, tlc_abort = self._enforce_timeline_contract(
            ctx.conn,
            ctx.job_id,
            ctx.assets_cache,
            script_output.get("narrative_structure", []),
            voice_output.get("timestamps", []),
        )
        if tlc_abort:
            return (research_output, script_output, voice_output, {}, [], tlc_abort)

        compose_output: dict[str, Any] = {}
        abort = None
        if ctx.target_agent == "visual_director":
            visual_output = self._run_visual_director_phase(
                ctx.conn,
                ctx.job_id,
                ctx.topic,
                research_output,
                script_output,
                ctx.output_dir,
                ctx.assets_cache,
                voice_output=voice_output,
                beat_timeline=beat_timeline,
            )
            if visual_output.get("status") == "failed":
                abort = self._fail_agent(
                    ctx.conn, ctx.job_id, "visual_director", visual_output, _ASSET_SOURCING_FAILED
                )

        if not abort and ctx.target_agent in ("visual_director", "composer"):
            compose_output, abort = self._retry_composer_stage(
                ctx.conn,
                ctx.job_id,
                visual_output,
                voice_output,
                ctx.output_dir,
                ctx.assets_cache,
                cycle=ctx.cycle,
                beat_timeline=beat_timeline,
            )

        return (research_output, script_output, voice_output, compose_output, beat_timeline, abort)

    def _execute_repair_cycle(
        self,
        repair_plan: dict[str, Any],
        job_id: int,
        assets_cache: str,
        output_dir: str,
        topic: str,
    ) -> dict[str, Any]:
        """Execute the bounded repair loop.

        Loops up to max_repair_cycles, re-running the target agent and
        downstream agents, then re-reviewing. Stops on pass, exhaustion,
        or repeated identical patch.

        Returns a result dict with status: completed, exhausted,
        or manual_review_required.
        """
        conn = get_connection(self.db_path)
        max_cycles = repair_plan.get("max_repair_cycles", 2)
        patches = repair_plan.get("patches", [])

        # FIX-5 (silent-failure P2): scope the duplicate-patch guard to THIS
        # repair run. A stale persisted previous_patches.json from a prior run
        # (retry/resume of a job that already went through a coverage repair)
        # would byte-match the constant coverage-regen patch on cycle 1 and
        # falsely exhaust the loop before any regen is attempted. Clear it so
        # the guard only fires on a repeat WITHIN this loop.
        self._reset_previous_patches(assets_cache, job_id)

        # Set initial repair status
        update_job_repair_status(conn, job_id, "running")
        update_job_publication_status(conn, job_id, "blocked")

        # Route first patch to determine target agent
        target_agent = route_repair(patches[0]) if patches else "visual_director"

        # Capture before-review snapshot for metrics
        before_review = self._load_agent_output(assets_cache, job_id, "reviewer")

        for cycle in range(1, max_cycles + 1):
            result = self._execute_single_repair_cycle(
                cycle,
                max_cycles,
                target_agent,
                patches,
                before_review,
                job_id,
                assets_cache,
                output_dir,
                topic,
                conn,
            )

            if result["_action"] == "return":
                result.pop("_action")
                return result

            # _action == "continue" — update state for next cycle
            target_agent = result["target_agent"]
            patches = result["patches"]
            before_review = result["before_review"]

        # Exhausted all cycles
        update_job_repair_status(conn, job_id, "exhausted")
        update_job_artifact_status(conn, job_id, "manual_review_required")
        update_job_quality_status(conn, job_id, "repair_exhausted")
        logger.warning(
            "Repair EXHAUSTED after %d cycles for job %d",
            max_cycles,
            job_id,
        )
        return {
            "status": "exhausted",
            "job_id": job_id,
            "reason": _REPAIR_EXHAUSTED,
            "cycle": max_cycles,
        }

    def _enforce_gate(
        self,
        conn: Any,
        job_id: int,
        gate_name: str,
        result: GateResult,
        failed_at: str = "",
        commit: bool = True,
        relaxable: bool = True,
    ) -> dict[str, Any] | None:
        """Return a failure response dict if gate hard-failed, or None.

        ``commit`` (default True) writes + commits job=FAILED as a single
        unit — the behavior every G1-G10 caller relies on. ``commit=False``
        runs the no-commit inner UPDATE and leaves the transaction open so
        the caller can batch a second write (the G7 atomic path) and commit
        both together (PR #86).
        """
        if not result.passed and result.severity == "hard_fail":
            if relaxable and self._gate_relaxed(gate_name):
                logger.warning(
                    _GATE_RELAX_WARN_MSG,
                    gate_name,
                    result.message,
                )
                return None
            logger.error("%s FAILED (hard): %s", gate_name, result.message)
            if commit:
                update_job_status(conn, job_id, "FAILED", result.message)
            else:
                _update_job_status_inner(conn, job_id, "FAILED", result.message)
            return {
                "status": "failed",
                "failed_at": failed_at,
                "reason": result.message,
                "job_id": job_id,
            }
        return None

    def _enforce_narrative_coverage(
        self,
        conn,
        job_id: int,
        script_output: dict[str, Any],
        assets_cache: str,
    ) -> dict[str, Any] | None:
        """G7 (ADR 0030 / FIX-1): assert narrative_structure word_range
        covers [0, word_count-1] before any consumer (Voice Producer, the
        canonical timeline, or Visual Director) touches it.

        Applies eligible in-place tail repair to script_output first, records
        the gate, and returns an ``_enforce_gate`` abort dict on hard_fail
        (else None). SHARED across the normal ``_stage_content`` path AND the
        retry / repair rerun paths, so an under-covered word_range can never
        recreate the job_18 mega-beat regardless of entry point (Codex P1:
        the contract must fire on every Scriptwriter -> consumer hop).
        """
        voiceover_text = script_output.get("voiceover_text", "")
        narrative = script_output.get("narrative_structure", [])
        coverage = validate_narrative_coverage(narrative, _word_count_for_coverage(voiceover_text))
        if coverage.repaired_structure is not None:
            script_output["narrative_structure"] = coverage.repaired_structure
            self._persist_repaired_narrative(assets_cache, job_id, script_output)
            logger.info(
                "G7 narrative coverage: %s (tail_words=%s, reordered=%s)",
                coverage.reason,
                coverage.details.get("tail_words", 0),
                coverage.details.get("reordered", False),
            )
        g7_result = GateNarrativeCoverage().evaluate(coverage=coverage)
        self._record_gate(assets_cache, job_id, "G7_narrative_coverage", g7_result)
        abort = None
        # Hold the process-wide write lock across BOTH writes + the single
        # commit. The singleton connection is shared across Flask threads via
        # check_same_thread=False, so under a threaded WSGI deploy a concurrent
        # request's public-helper conn.commit() could otherwise commit this
        # half-open transaction between the jobs and agent writes — then an
        # agent-write raise would leave job=FAILED + scriptwriter=completed
        # (the job_18-residual state) with a rollback that has nothing to undo
        # (Codex P2 r3496171628). The jobs UPDATE runs (commit=False) inside
        # the lock; the agent write + commit run inside the same lock.
        with db_write_lock():
            abort = self._enforce_gate(
                conn,
                job_id,
                "G7_narrative_coverage",
                g7_result,
                failed_at="narrative_coverage",
                commit=False,
            )
            if abort is not None:
                # One transaction, one commit, so a transient DB error (e.g.
                # sqlite "database is locked") can never leave job=FAILED +
                # scriptwriter=completed (Codex P2 r3494109780).
                # _enforce_gate(commit=False) already ran the jobs UPDATE as
                # the first DML (auto-opening the txn under legacy
                # isolation_level), so conn.in_transaction is True here and the
                # BEGIN guard is belt-and-suspenders for any future reordering.
                try:
                    if not conn.in_transaction:
                        conn.execute("BEGIN")
                    _update_agent_state_inner(
                        conn,
                        job_id,
                        "scriptwriter",
                        "failed",
                        error_message=g7_result.message,
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                # FIX-5 (ADR 0030): stamp the stable coverage token so the
                # abort site can route into the bounded Scriptwriter regen loop
                # instead of terminal-hard-failing (Codex P1: without this the
                # GATE_FAILURE_REPAIR_MAP narrative_not_covered entry is
                # unreachable from a real uncovered-narrative run).
                abort["gate_reason"] = NARRATIVE_NOT_COVERED
        return abort

    def _persist_repaired_narrative(
        self, assets_cache: str, job_id: int, script_output: dict[str, Any]
    ) -> None:
        """Re-write the Scriptwriter's on-disk narrative artifacts with the
        G7-repaired structure, so retry/resume paths that reload Scriptwriter
        output from disk (e.g. ``_retry_composer_stage``) see the repaired
        version instead of the stale pre-gate one (Codex P2)."""
        if not assets_cache:
            return
        from clipper_agency.core.paths import agent_dir, agent_output_file

        base = agent_dir(assets_cache, job_id, "scriptwriter")
        repaired = script_output["narrative_structure"]
        write_json(f"{base}/narrative_structure.json", repaired)
        write_json(f"{base}/script.json", {"scenes": repaired})
        write_json(agent_output_file(assets_cache, job_id, "scriptwriter"), script_output)

    def _enforce_timeline_contract(
        self,
        conn,
        job_id: int,
        assets_cache: str,
        narrative_structure: list[dict],
        timestamps: list[dict],
    ) -> tuple[list, dict[str, Any] | None]:
        """FIX-6 (ADR 0030 / SRS FR-79): wrap
        :func:`build_canonical_timeline` and abort the pipeline on a
        physically-impossible timeline (a non-physical beat that G7/FIX-1
        word_range coverage cannot catch — e.g. a manufactured 25s mega-beat).

        Backstop for G7: G7 validates ``word_range`` coverage on the script
        dict; FIX-6 catches a non-physical beat at canonical-timeline build
        time. SUCCESS → ``(timeline, None)`` (caller proceeds as today).
        FAILURE → ``([], abort)`` mirroring the G7 / PR#86 atomic DB pattern:
        under :func:`db_write_lock`, ``_enforce_gate(commit=False)`` runs the
        jobs UPDATE (job=FAILED) as the first DML, then
        ``_update_agent_state_inner(scriptwriter=failed)`` + single
        ``conn.commit()``; any raise → ``conn.rollback()`` + re-raise (no
        half-committed job=FAILED + scriptwriter=completed — Codex P2 lesson
        from G7).

        Deviation from ``_enforce_narrative_coverage``: this helper passes
        ``relaxable=False`` to ``_enforce_gate`` so its relax branch is skipped
        — there is no ``DEV_RELAX_GATES`` bypass for FIX-6. A
        physically-impossible beat is never safe to ship; operators who need to
        force-ship relax G7 upstream (the contract gate), which prevents the bad
        ``word_range`` from reaching the timeline (RISK-5).

        Recovery TODAY = terminal hard-fail. FIX-5 (ships later) will consume
        the stable ``"timeline_not_covered"`` reason token to automate
        scriptwriter regen (YAGNI for FIX-6).
        """
        try:
            timeline = build_canonical_timeline(narrative_structure, timestamps)
        except TimelineContractError as exc:
            msg = (
                f"timeline contract violated ({exc.kind}): "
                f"beat_id={exc.beat_id} tail_seconds={exc.tail_seconds:.2f}"
            )
            gate_result = GateResult(
                passed=False,
                severity="hard_fail",
                message=msg,
                data={
                    "reason": exc.reason,
                    "kind": exc.kind,
                    "beat_id": exc.beat_id,
                    "tail_seconds": exc.tail_seconds,
                },
            )
            self._record_gate(assets_cache, job_id, "FIX6_timeline_contract", gate_result)
            abort: dict[str, Any] | None = None
            with db_write_lock():
                abort = self._enforce_gate(
                    conn,
                    job_id,
                    "FIX6_timeline_contract",
                    gate_result,
                    failed_at="timeline_contract",
                    commit=False,
                    relaxable=False,
                )
                if abort is not None:
                    try:
                        if not conn.in_transaction:
                            conn.execute("BEGIN")
                        _update_agent_state_inner(
                            conn,
                            job_id,
                            "scriptwriter",
                            "failed",
                            error_message=msg,
                        )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
                    # FIX-5 (ADR 0030): stamp the stable coverage token so the
                    # abort site can route into the bounded Scriptwriter regen
                    # loop instead of terminal-hard-failing (Codex P1).
                    abort["gate_reason"] = TIMELINE_NOT_COVERED
            return [], abort
        return timeline, None

    def _evaluate_and_enforce_gate(
        self,
        conn,
        job_id: int,
        assets_cache: str,
        gate_label: str,
        gate_record_key: str,
        gate_instance,
        failed_at: str,
        **evaluate_kwargs: Any,
    ) -> dict[str, Any] | None:
        """Run gate.evaluate(), record result, enforce. Return abort dict or None."""
        g_result = gate_instance.evaluate(**evaluate_kwargs)
        self._record_gate(assets_cache, job_id, gate_record_key, g_result)
        return self._enforce_gate(conn, job_id, gate_label, g_result, failed_at=failed_at)

    def _stage_safety(
        self,
        conn: Any,
        topic: str,
        niche: str,
        assets_cache: str,
        output_dir: str,
        config_snapshot: dict | None = None,
    ) -> tuple[int, GateResult] | dict[str, Any]:
        """Run G1 preflight, create job, G2 cost, safety agent.

        Returns (job_id, cost_result) on success or a failure dict.
        """
        snapshot = config_snapshot or {}

        # G1: Input Preflight
        g1 = GateInputPreflight()
        g1_result = g1.evaluate(topic=topic, niche_config={"name": niche})
        self._record_gate(assets_cache, 0, "G1_input_preflight", g1_result)
        if not g1_result.passed:
            if self._gate_relaxed("G1"):
                logger.warning(
                    _GATE_RELAX_WARN_MSG,
                    "G1",
                    g1_result.message,
                )
            else:
                logger.error("G1 Preflight FAILED: %s", g1_result.message)
                update_job_status(conn, 0, "FAILED", g1_result.message)
                return {
                    "status": "failed",
                    "failed_at": "preflight",
                    "reason": g1_result.message,
                    "job_id": 0,
                }

        # Create job in DB with config snapshot
        job_id = create_job(conn, topic=topic, niche=niche, config_snapshot=snapshot)
        logger.info("Job #%d created", job_id)
        add_job_file_handler(job_id)
        create_manifest(
            assets_cache,
            job_id,
            topic,
            output_dir if output_dir else "outputs",
            config_snapshot=snapshot,
        )
        agent_names = [
            "safety",
            "segment_producer",
            "scriptwriter",
            "voice_producer",
            "visual_director",
            "composer",
            "reviewer",
        ]
        for name in agent_names:
            create_agent_state(conn, job_id, name)
        self._init_job_statuses(conn, job_id)

        # G2: Cost Estimate
        g2 = GateCostEstimate()
        cost_result = g2.evaluate()
        self._record_gate(assets_cache, job_id, "G2_cost_estimate", cost_result)

        # Safety Agent
        logger.info("G2: running Safety agent")
        mark_agent_running(conn, job_id, "safety")
        safety_result = self._run_safety(
            job_id=job_id,
            topic=topic,
            assets_cache=assets_cache,
        )
        if safety_result.get("status") == "hard_fail":
            if self._gate_relaxed("Safety"):
                logger.warning(
                    _GATE_RELAX_WARN_MSG,
                    "Safety",
                    safety_result.get("reason"),
                )
            else:
                logger.error("Safety FAILED: %s", safety_result.get("reason"))
                mark_agent_failed(conn, job_id, "safety", safety_result["reason"])
                update_job_status(conn, job_id, "FAILED", safety_result["reason"])
                return {
                    "status": "failed",
                    "failed_at": "safety",
                    "reason": safety_result["reason"],
                    "job_id": job_id,
                }
        self._complete_agent(conn, assets_cache, job_id, "safety")
        return job_id, cost_result

    def _stage_research(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        safety_rules: list[str],
        channel_description: str,
        language: str,
        tone: str,
        content_angle: str,
        assets_cache: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """Run G3→SegmentProducer→G4→G5.

        Returns research_output dict on success or a failure dict.
        """
        g3 = GateResearchCache()
        self._record_gate(assets_cache, job_id, "G3_research_cache", g3.evaluate())

        logger.info("G3: running Segment Producer agent")
        mark_agent_running(conn, job_id, "segment_producer")
        research_output = self._run_researcher(
            job_id=job_id,
            topic=topic,
            safety_rules=safety_rules,
            channel_description=channel_description,
            language=language,
            tone=tone,
            content_angle=content_angle,
            output_dir=output_dir,
            assets_cache=assets_cache,
        )
        self._complete_agent(conn, assets_cache, job_id, "segment_producer")

        # Format Validator: validate content_direction from Segment Producer
        cp_config = load_settings().content_planning
        if cp_config:
            validated = validate_content_direction(
                research_output.get("content_direction"),
                cp_config,
            )
            research_output["validated_direction"] = validated
            logger.info(
                "Format validator: format=%s stories=%d fallback=%s",
                validated.format,
                validated.story_count,
                validated.fallback,
            )

        g4 = GatePostResearchRisk()
        g4_result = g4.evaluate(
            risk_flags=research_output.get("risk_flags", []),
        )
        self._record_gate(assets_cache, job_id, "G4_post_research_risk", g4_result)
        if not g4_result.passed and g4_result.severity == "hard_fail":
            if self._gate_relaxed("G4"):
                logger.warning(
                    _GATE_RELAX_WARN_MSG,
                    "G4",
                    g4_result.message,
                )
            else:
                update_job_status(conn, job_id, "FAILED", g4_result.message)
                return {
                    "status": "failed",
                    "failed_at": "post_research_risk",
                    "reason": g4_result.message,
                    "job_id": job_id,
                }

        g5 = GateSourceQuality()
        g5_result = g5.evaluate(
            video_sources=research_output.get("sources", []),
        )
        self._record_gate(assets_cache, job_id, "G5_source_quality", g5_result)
        if abort := self._enforce_gate(conn, job_id, "G5", g5_result, failed_at="source_quality"):
            return abort

        return research_output

    def _stage_content(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        safety_rules: list[str],
        channel_description: str,
        language: str,
        tone: str,
        content_angle: str,
        research_output: dict[str, Any],
        assets_cache: str,
        output_dir: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | dict[str, Any]:
        """Run G6→Scriptwriter→G7→Voice→G8.

        Returns (script_output, voice_output) on success
        or a failure dict.
        """
        script_output = self._run_content_scriptwriter(
            conn,
            job_id,
            topic,
            safety_rules,
            channel_description,
            language,
            tone,
            content_angle,
            research_output,
            assets_cache,
        )
        if script_output.get("status") == "failed":
            return self._fail_agent(
                conn, job_id, "scriptwriter", script_output, "Scriptwriter duration exceeded"
            )

        # G7 (active): Narrative coverage contract (ADR 0030 / FIX-1).
        # Shared helper enforces it on this path AND on the retry/repair
        # rerun paths (Codex P1) so the contract fires on every hop.
        if abort := self._enforce_narrative_coverage(conn, job_id, script_output, assets_cache):
            return abort

        logger.info("Voice Producer agent")
        mark_agent_running(conn, job_id, "voice_producer")
        voice_output = self._run_voice_producer(
            job_id=job_id,
            script=script_output.get("script", []),
            voiceover_text=script_output.get("voiceover_text", ""),
            output_dir=output_dir,
            assets_cache=assets_cache,
        )
        if voice_output.get("status") == "failed":
            return self._fail_agent(conn, job_id, "voice_producer", voice_output, _VOICE_GEN_FAILED)
        self._complete_agent(conn, assets_cache, job_id, "voice_producer")

        g8 = GateAudioValidation()
        g8_result = g8.evaluate(audio_path=voice_output.get("voiceover_path"))
        self._record_gate(assets_cache, job_id, "G8_audio_validation", g8_result)
        if abort := self._enforce_gate(conn, job_id, "G8", g8_result, failed_at="audio_validation"):
            return abort

        return script_output, voice_output

    def _stage_composition(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        research_output: dict[str, Any],
        script_output: dict[str, Any],
        voice_output: dict[str, Any],
        assets_cache: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """Run Visual→G9→Composer→G10.

        Returns compose_output dict on success or a failure dict.
        """
        # Build canonical beat timeline once (ADR 0020) — single source of
        # truth for beat durations consumed by VD, Composer, and Reviewer.
        # FIX-6 (ADR 0030): enforce the physical-timeline contract (backstop
        # for G7) — the job_18 mega-beat was manufactured at this site.
        beat_timeline, abort = self._enforce_timeline_contract(
            conn,
            job_id,
            assets_cache,
            script_output.get("narrative_structure", []),
            voice_output.get("timestamps", []),
        )
        if abort:
            return abort

        logger.info("G8: running Visual Director agent")
        visual_output = self._run_visual_director_phase(
            conn,
            job_id,
            topic,
            research_output,
            script_output,
            output_dir,
            assets_cache,
            voice_output=voice_output,
            beat_timeline=beat_timeline,
        )

        if visual_output.get("status") == "failed":
            return self._fail_agent(
                conn, job_id, "visual_director", visual_output, _ASSET_SOURCING_FAILED
            )

        # G9: Asset validation
        abort = self._evaluate_and_enforce_gate(
            conn,
            job_id,
            assets_cache,
            gate_label="G9",
            gate_record_key="G9_asset_validation",
            gate_instance=GateAssetValidation(),
            failed_at="asset_validation",
            asset_paths=[a.get("path", "") for a in visual_output.get("assets", [])],
            assets=visual_output.get("assets", []),
        )
        if abort:
            return abort

        logger.info("G9: running Composer agent")
        mark_agent_running(conn, job_id, "composer")
        compose_output = self._run_composer(
            job_id=job_id,
            assets=visual_output.get("assets", []),
            audio_files=voice_output.get("audio_files", []),
            script_scenes=script_output.get("script", []),
            output_dir=output_dir,
            assets_cache=assets_cache,
            voiceover_path=voice_output.get("voiceover_path", ""),
            timestamps=voice_output.get("timestamps", []),
            narrative_structure=script_output.get("narrative_structure", []),
            beat_timeline=beat_timeline,
            voiceover_duration_sec=voice_output.get("voiceover_duration_sec"),
        )

        if compose_output.get("status") == "failed":
            return self._fail_agent(conn, job_id, "composer", compose_output, _COMPOSER_FAILED)
        self._complete_agent(conn, assets_cache, job_id, "composer")

        # G10: Video validation
        cp_config = load_settings().content_planning
        hard_limit = getattr(cp_config, "hard_limit_sec", 60)
        abort = self._evaluate_and_enforce_gate(
            conn,
            job_id,
            assets_cache,
            gate_label="G10",
            gate_record_key="G10_video_validation",
            gate_instance=GateVideoValidation(),
            failed_at="video_validation",
            video_path=compose_output.get("video_path"),
            hard_limit_sec=hard_limit,
            voiceover_duration_sec=voice_output.get("voiceover_duration_sec"),
        )
        if abort:
            return abort

        return compose_output

    def _is_coverage_repairable_abort(self, abort: dict[str, Any] | None) -> bool:
        """FIX-5 (ADR 0030): True when an abort carries a stable coverage token.

        The G7 (``_enforce_narrative_coverage``) and FIX-6
        (``_enforce_timeline_contract``) helpers stamp ``gate_reason`` on the
        abort dict with the exact token ``GATE_FAILURE_REPAIR_MAP`` keys on.
        Without this check those aborts hard-fail the job before the Reviewer
        runs, leaving the narrative_not_covered / timeline_not_covered routing
        entries unreachable (Codex P1)."""
        if not abort:
            return False
        return abort.get("gate_reason") in (NARRATIVE_NOT_COVERED, TIMELINE_NOT_COVERED)

    def _maybe_route_coverage_abort(
        self,
        abort: dict[str, Any] | None,
        conn: Any,
        job_id: int,
        topic: str,
        niche: str,
        assets_cache: str,
        output_dir: str,
    ) -> dict[str, Any] | None:
        """Route a coverage-repairable abort into the bounded regen loop.

        Returns the repair result dict when ``abort`` is coverage-repairable
        (FIX-5 / ADR 0030), or ``None`` when it is not (caller returns the
        abort as a terminal fail). Encapsulates the repeated
        ``_is_coverage_repairable_abort`` → ``_route_coverage_abort_to_repair``
        decision so :meth:`run_pipeline` stays a linear orchestrator below
        the SonarCloud S3776 cognitive-complexity threshold.
        """
        if not abort or not self._is_coverage_repairable_abort(abort):
            return None
        return self._route_coverage_abort_to_repair(
            abort, conn, job_id, topic, niche, assets_cache, output_dir
        )

    def _route_coverage_abort_to_repair(
        self,
        abort: dict[str, Any],
        conn: Any,
        job_id: int,
        topic: str,
        niche: str,
        assets_cache: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """Route a G7/FIX-6 coverage abort into a single Scriptwriter regen
        attempt instead of returning it as a terminal hard-fail.

        FIX-5 (ADR 0030 / SRS FR-78, Codex P1): the coverage abort already
        committed ``job=FAILED`` + ``scriptwriter=failed`` atomically. The
        regen attempt needs a runnable job, so this marks ``repair_status=
        running``, builds the root-agent regen plan from the stable token, and
        delegates to :meth:`_execute_repair_cycle`. Per
        ``_COVERAGE_MAX_REPAIR_CYCLES`` the regen is a SINGLE attempt: if the
        re-run STILL fails G7 the abort propagates and the job terminally
        FAILs (never "completes" a garbage video — anti-job_18).

        Returns a result dict (``completed`` on a successful regen,
        ``failed`` on exhaustion / coverage re-fail with ``repair_status``
        carrying the underlying cycle status)."""
        token = abort.get("gate_reason", "")
        logger.warning(
            "Coverage gate %s failed for job %d — routing to bounded "
            "Scriptwriter regen (max %d cycles)",
            token,
            job_id,
            _COVERAGE_MAX_REPAIR_CYCLES,
        )
        # The abort already wrote job=FAILED atomically. Mark the repair loop
        # active so operators/dashboard see the regen attempt in progress.
        update_job_repair_status(conn, job_id, "running")
        update_job_publication_status(conn, job_id, "blocked")
        routing = build_gate_failure_repair_plan({"status": "fail", "reason": token})
        # routing is guaranteed non-None for the two coverage tokens (covered by
        # test_build_gate_plan_for_{narrative,timeline}_not_covered), but guard
        # defensively so a future token mis-map degrades to the original abort.
        if routing is None:
            return abort
        repair_plan = {
            "max_repair_cycles": _COVERAGE_MAX_REPAIR_CYCLES,
            "patches": routing["patches"],
        }
        repair_result = self._execute_repair_cycle(
            repair_plan=repair_plan,
            job_id=job_id,
            assets_cache=assets_cache,
            output_dir=output_dir,
            topic=topic,
        )
        if repair_result.get("status") == "completed":
            # Package + promote the regen-repaired output (mirrors
            # _handle_repair_routing's post-repair packaging). Thread `topic`
            # explicitly — the repair-cycle result dict does NOT carry it.
            return self._finalize_coverage_repair(
                conn, job_id, topic, niche, output_dir, assets_cache, repair_result
            )
        # Exhausted / manual review — terminal FAIL (never COMPLETED).
        # FIX-5 (silent-failure P2): the entry announcement (L1604) logs the
        # regen ATTEMPT; this logs the OUTCOME so operators scanning logs see
        # the single most load-bearing failure (job_18's class recurs after
        # regen). Mirrors _execute_repair_cycle's 'EXHAUSTED' log (L983).
        # S5145: log job_id ONLY — token/status/reason trace to gate/user
        # data and are persisted via update_job_status below, so operators
        # already see them in the DB/dashboard. The log just flags WHICH job.
        logger.error("Coverage regen FAILED terminally for job %d", job_id)
        update_job_status(conn, job_id, "FAILED", repair_result.get("reason", _REPAIR_EXHAUSTED))
        # FIX-5 (Codex P2 @line 1702): reset the repair lifecycle state. The
        # regen entry set repair_status='running'; without this reset the
        # job/dashboard stays "repair in-progress" after the API already
        # returned failure. Mirrors the exhausted/manual-review reset used by
        # _execute_repair_cycle (L1024) and _handle_review_outcome (L462).
        update_job_repair_status(conn, job_id, "exhausted")
        update_job_artifact_status(conn, job_id, "manual_review_required")
        update_job_quality_status(conn, job_id, "repair_exhausted")
        remove_job_file_handler()
        return {
            "status": "failed",
            "job_id": job_id,
            "reason": repair_result.get("reason", _REPAIR_EXHAUSTED),
            "repair_status": repair_result["status"],
        }

    def _promote_repaired_job(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        niche: str,
        output_dir: str,
        assets_cache: str,
        repair_cycle: int,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Shared package-or-fail-or-promote sequence for repaired jobs.

        Single source of truth (DRY) for the packaging + promotion +
        COMPLETED/FAILED transition used by both the coverage-regen finalize
        path (:meth:`_finalize_coverage_repair`) and the reviewer-driven repair
        path (:meth:`_handle_repair_routing`).

        Anti-job_18 (ADR 0030 / FIX-5): a repaired output that fails packaging
        OR promotion terminally FAILs the job (``repair_status`` carries the
        stage) — it must NEVER be marked COMPLETED with a missing/garbage
        package or no final/ artifacts. Mirrors the non-repair promotion path
        (L2363) which gates publication on ``_promote_to_final`` succeeding.

        ``extra_fields`` is merged into the success dict so the
        reviewer-driven caller can attach ``cost_estimate``/``review``
        without the coverage caller needing them.
        """
        # FIX-5 (silent-failure P2): assert upstream outputs are non-empty
        # BEFORE packaging. A partial fs / failed persist would otherwise feed
        # empty caption/video strings to _package_output, which may tolerate
        # them and silently produce a garbage package marked COMPLETED.
        script_output = self._load_agent_output(assets_cache, job_id, "scriptwriter")
        compose_output = self._load_agent_output(assets_cache, job_id, "composer")
        if not script_output or not compose_output.get("video_path"):
            update_job_status(conn, job_id, "FAILED", _PACKAGING_FAILED)
            # FIX-5 (Codex P2 @line 1765): reset the lifecycle fields the
            # reviewer-driven path already stamped (repair_status='completed'/
            # artifact_status='approved'/publication_status='ready'). Without
            # this the job stays marked approved/ready despite no valid package.
            update_job_repair_status(conn, job_id, "packaging_failed")
            update_job_artifact_status(conn, job_id, "rejected")
            update_job_publication_status(conn, job_id, "blocked")
            remove_job_file_handler()
            return {
                "status": "failed",
                "job_id": job_id,
                "reason": _PACKAGING_FAILED,
                "repair_status": "packaging_failed",
            }
        pkg_output = self._package_output(
            job_id=job_id,
            video_path=compose_output.get("video_path", ""),
            caption=script_output.get("caption", ""),
            topic=topic,
            niche=niche,
            output_dir=output_dir,
            template_name=compose_output.get("template_name"),
        )
        if pkg_output.get("status") == "failed":
            reason = pkg_output.get("error", _PACKAGING_FAILED)
            update_job_status(conn, job_id, "FAILED", reason)
            # FIX-5 (Codex P2 @line 1765): mirror the lifecycle reset so a
            # packaging failure never leaves the job approved/ready.
            update_job_repair_status(conn, job_id, "packaging_failed")
            update_job_artifact_status(conn, job_id, "rejected")
            update_job_publication_status(conn, job_id, "blocked")
            remove_job_file_handler()
            return {
                "status": "failed",
                "job_id": job_id,
                "reason": reason,
                "repair_status": "packaging_failed",
            }
        # FIX-5 (Codex P2): gate the COMPLETED transition on promotion
        # succeeding. _promote_to_final returns {status:failed} on a missing
        # cycle_{n} source dir or an atomic-rename/copytree exception; without
        # this gate the DB would report COMPLETED with NO final/job_* produced.
        #
        # Promote the PACKAGED dir (output/job_{id}/, written by
        # _package_output above — contains metadata.json + caption.txt +
        # package-time artifacts), NOT the cycle_{n} snapshot. The cycle_{n}
        # dir is an interim copy of only video/thumbnail/caption made by
        # _retry_composer_stage BEFORE packaging, so it lacks metadata.json;
        # promoting it would mark the job COMPLETED with a broken output
        # package contract (anti-job_18, ADR 0030). Mirrors the non-repair
        # promotion path (L2536) which promotes output/job_{id}/ directly.
        promotion = self._promote_to_final(
            output_dir=output_dir,
            job_id=job_id,
        )
        if promotion.get("status") == "failed":
            reason = promotion.get("error", _PACKAGING_FAILED)
            update_job_status(conn, job_id, "FAILED", reason)
            # FIX-5 (Codex P2 @line 1765): reset lifecycle on promotion
            # failure too — the packaged artifacts exist but final/ was not
            # produced, so publication must stay blocked (mirrors the
            # non-repair promotion-fail at L2548: "publication stays blocked").
            update_job_repair_status(conn, job_id, "promotion_failed")
            update_job_publication_status(conn, job_id, "blocked")
            remove_job_file_handler()
            return {
                "status": "failed",
                "job_id": job_id,
                "reason": reason,
                "repair_status": "promotion_failed",
            }
        update_job_status(conn, job_id, "COMPLETED")
        # Codex P2 r3502323050: mirror the normal pass path's manifest update
        # (engine.py ~L2743) so final_outputs is populated for repaired jobs —
        # otherwise manifest.json keeps final_outputs empty even though DB says
        # COMPLETED, and dashboard/manifest consumers can't discover the final
        # video/caption/thumbnail/metadata.
        update_manifest_final(
            assets_cache,
            job_id,
            {
                "video": pkg_output.get("video_path", ""),
                "caption": pkg_output.get("caption_path", ""),
                "thumbnail": pkg_output.get("thumbnail_path", ""),
                "metadata": pkg_output.get("metadata_path", ""),
            },
        )
        # FIX-5 (SonarCloud S5145): cast to int to break the taint chain from
        # persisted gate data (job_id/repair_cycle trace to tainted source).
        logger.info(
            "Pipeline COMPLETED after repair (job #%d, cycle %d)",
            int(job_id),
            int(repair_cycle),
        )
        remove_job_file_handler()
        success: dict[str, Any] = {
            "status": "completed",
            "job_id": job_id,
            "output": pkg_output,
            "repair_cycles": repair_cycle,
        }
        if extra_fields:
            success.update(extra_fields)
        return success

    def _finalize_coverage_repair(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        niche: str,
        output_dir: str,
        assets_cache: str,
        repair_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Package + promote the output after a successful coverage regen.

        ``topic`` is threaded explicitly from the caller — the repair-cycle
        result dict does NOT carry it (anti the empty-metadata.topic bug).

        Delegates to :meth:`_promote_repaired_job` for the package-or-fail-or-
        promote sequence; on packaging OR promotion failure the job terminally
        FAILs (never COMPLETED) with the matching ``repair_status`` —
        anti-job_18."""
        return self._promote_repaired_job(
            conn=conn,
            job_id=job_id,
            topic=topic,
            niche=niche,
            output_dir=output_dir,
            assets_cache=assets_cache,
            repair_cycle=repair_result.get("cycle", 0),
        )

    def _handle_repair_routing(
        self,
        conn: Any,
        job_id: int,
        review_output: dict[str, Any] | None,
        _script_output: dict[str, Any],
        _initial_compose_output: dict[str, Any],
        cost_result: Any,
        assets_cache: str,
        output_dir: str,
        topic: str,
        niche: str,
    ) -> dict[str, Any] | None:
        """Handle repair routing from reviewer, returning result or None."""
        if not review_output or not review_output.get("repair_routing"):
            return None

        routing = review_output["repair_routing"]
        logger.info(
            "Starting repair loop: job #%d → %s",
            job_id,
            routing["target_agent"],
        )
        repair_result = self._execute_repair_cycle(
            repair_plan=routing,
            job_id=job_id,
            assets_cache=assets_cache,
            output_dir=output_dir,
            topic=topic,
        )
        if repair_result.get("status") == "completed":
            # Repair passed — package + promote via the shared helper (DRY:
            # identical sequence to _finalize_coverage_repair). Carries the
            # cost_estimate/review fields only this caller surfaces.
            return self._promote_repaired_job(
                conn=conn,
                job_id=job_id,
                topic=topic,
                niche=niche,
                output_dir=output_dir,
                assets_cache=assets_cache,
                repair_cycle=repair_result.get("cycle", 0),
                extra_fields={
                    "cost_estimate": {
                        "estimate_cents": cost_result.data.get("estimate_cents", 0.0),
                    },
                    "review": {
                        "score": review_output.get("score", 0),
                        "verdict": "pass",
                    },
                },
            )

        # Repair exhausted or manual review needed
        update_job_status(conn, job_id, "FAILED", repair_result.get("reason", _REPAIR_EXHAUSTED))
        remove_job_file_handler()
        return {
            "status": "failed",
            "job_id": job_id,
            "reason": repair_result.get("reason", _REPAIR_EXHAUSTED),
            "repair_status": repair_result["status"],
        }

    def _prepare_pipeline_run(
        self,
        relax_gates: str,
    ) -> tuple[Any, frozenset[str]] | dict[str, Any]:
        """Set up the shared connection + DEV gate-relax set + model preflight.

        Returns ``(conn, relax_set)`` on success, or a failure ``dict`` if
        model preflight raises (the caller returns that dict immediately).
        Extracted from :meth:`run_pipeline` to drop its cognitive complexity
        below 15 (SonarCloud S3776).
        """
        conn = get_connection(self.db_path)
        # Resolve DEV gate-relax set (CLI ∪ env). Empty == today's behavior.
        relax_set = resolve_relax_gates(
            getattr(load_settings(), "relax_gates", ""), relax_gates or ""
        )
        # Preflight: validate resolved agent models against the OpenRouter catalog
        # before billing research credits (PR 7). Placed at this orchestrator
        # chokepoint so the CLI, dashboard create, retry, and resume paths ALL
        # validate (Codex P2#1). Returns a failed status on a bad slug.
        try:
            preflight_agent_models()
        except RuntimeError as exc:
            logger.exception("Model preflight failed")
            return {
                "status": "failed",
                "failed_at": "model_preflight",
                "reason": str(exc),
            }
        return conn, relax_set

    def _load_niche_context(
        self, niche: str
    ) -> dict[str, Any] | tuple[Any, list[str], str, str, str, str]:
        """Load niche configuration and derive the context fields.

        Returns a failed-status dict when the niche config is missing, or the
        ``(niche_config, safety_rules, channel_description, language_name,
        tone_name, angle_name)`` tuple on success. Encapsulates the
        ``try/except FileNotFoundError`` so :meth:`run_pipeline` stays below
        the SonarCloud S3776 cognitive-complexity threshold.
        """
        try:
            niche_config = load_niche(niche)
        except FileNotFoundError:
            logger.error("Niche config not found: %r — aborting pipeline", niche)
            return {"status": "failed", "reason": f"Niche config {niche!r} not found"}
        return (
            niche_config,
            niche_config.safety_rules,
            build_channel_description(niche_config),
            get_language_name(niche_config),
            get_tone_name(niche_config),
            get_angle_name(niche_config),
        )

    def _route_repairable_abort(
        self,
        failed: dict[str, Any],
        conn: Any,
        job_id: int,
        topic: str,
        niche: str,
        assets_cache: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """FIX-5 (ADR 0030): route a coverage-repairable stage abort through
        the bounded Scriptwriter regen loop. Returns the repair result when
        repairable, else the original ``failed`` dict (caller returns it as a
        terminal fail; the job still terminally FAILs on regen-exhaustion — the
        anti-job_18 invariant holds).

        Centralizes the repair-or-return pattern repeated at the three
        coverage-abort sites (``_stage_content`` G7, ``_stage_composition``
        FIX-6, and the reviewer-stage 2nd-hop timeline rebuild) so
        :meth:`_run_pipeline_stages` stays under the Sonar S3776
        cognitive-complexity threshold.
        """
        repair = self._maybe_route_coverage_abort(
            failed, conn, job_id, topic, niche, assets_cache, output_dir
        )
        return repair if repair is not None else failed

    def _run_pipeline_stages(
        self,
        conn: Any,
        job_id: int,
        cost_result: Any,
        topic: str,
        niche: str,
        safety_rules: Any,
        channel_description: str,
        language_name: str,
        tone_name: str,
        angle_name: str,
        assets_cache: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """Execute Stages 2-5 (Research → Content → Composition → Review).

        Encapsulates the ``try/except Exception`` stage body so
        :meth:`run_pipeline` stays a linear orchestrator below the
        SonarCloud S3776 cognitive-complexity threshold. Each coverage-repairable
        abort is routed through :meth:`_maybe_route_coverage_abort` (FIX-5 /
        ADR 0030) before terminal-failing.
        """
        try:
            # Stage 2: Research (G3→G5)
            research_output = self._stage_research(
                conn,
                job_id,
                topic,
                safety_rules,
                channel_description,
                language_name,
                tone_name,
                angle_name,
                assets_cache,
                output_dir,
            )
            if isinstance(research_output, dict) and research_output.get("status") == "failed":
                return research_output

            # Stage 3: Content creation (G6→G8)
            stage3 = self._stage_content(
                conn,
                job_id,
                topic,
                safety_rules,
                channel_description,
                language_name,
                tone_name,
                angle_name,
                research_output,
                assets_cache,
                output_dir,
            )
            if isinstance(stage3, dict) and stage3.get("status") == "failed":
                # FIX-5 (ADR 0030, Codex P1): a G7 narrative_not_covered abort
                # is repairable — route it into the bounded Scriptwriter regen
                # loop instead of terminal-hard-failing on first contact.
                return self._route_repairable_abort(
                    stage3, conn, job_id, topic, niche, assets_cache, output_dir
                )
            if not isinstance(stage3, tuple):  # pragma: no cover
                raise RuntimeError("_stage_content returned non-tuple, non-failed value")
            script_output, voice_output = stage3

            # Stage 4: Composition (Visual→G10)
            compose_output = self._stage_composition(
                conn,
                job_id,
                topic,
                research_output,
                script_output,
                voice_output,
                assets_cache,
                output_dir,
            )
            if isinstance(compose_output, dict) and compose_output.get("status") == "failed":
                # FIX-5 (ADR 0030, Codex P1): a FIX-6 timeline_not_covered
                # abort is repairable — route into the bounded regen loop.
                return self._route_repairable_abort(
                    compose_output, conn, job_id, topic, niche, assets_cache, output_dir
                )

            # Stage 5: Review + Package
            logger.info("G10: running Reviewer agent")
            abort, review_output, pkg_output = self._retry_review_and_package(
                conn,
                job_id,
                topic,
                script_output,
                compose_output,
                safety_rules,
                niche,
                output_dir,
                assets_cache,
                voice_output=voice_output,
                research_output=research_output,
            )
            if abort:
                # FIX-5 (ADR 0030, blast-radius P1): the reviewer-stage
                # timeline rebuild (in _retry_review_and_package) can re-derive
                # a FIX-6 timeline_not_covered abort — the SECOND hop for that
                # token (the first is _stage_composition L1968). Mirror that
                # site: route the same token into the bounded regen loop
                # instead of returning it as a bare terminal fail. The job
                # still terminally FAILs on regen-exhaustion (anti-job_18
                # invariant holds); this only ensures the automatic regen
                # attempt fires consistently on both coverage-abort sites.
                return self._route_repairable_abort(
                    abort, conn, job_id, topic, niche, assets_cache, output_dir
                )

            # Handle repair routing from reviewer
            repair_result = self._handle_repair_routing(
                conn,
                job_id,
                review_output,
                script_output,
                compose_output,
                cost_result,
                assets_cache,
                output_dir,
                topic,
                niche,
            )
            if repair_result is not None:
                return repair_result

            # _retry_review_and_package returns (abort, review_output, pkg_output).
            # abort is falsy here (checked above), so review_output is guaranteed
            # non-None — the only None-review path returns a non-None abort.
            # Use a raise (not assert) so this contract guard survives `python -O`
            # and cannot be silently stripped on the production COMPLETION path.
            if review_output is None:  # pragma: no cover
                raise RuntimeError(
                    "_retry_review_and_package returned falsy abort with None "
                    "review_output — contract violation"
                )
            update_job_status(conn, job_id, "COMPLETED")
            logger.info("Pipeline COMPLETED: job #%d", job_id)
            remove_job_file_handler()
            return {
                "status": "completed",
                "job_id": job_id,
                "output": pkg_output,
                "cost_estimate": {
                    "estimate_cents": cost_result.data.get("estimate_cents", 0.0),
                },
                "review": {
                    "score": review_output.get("score", 0),
                    "verdict": review_output.get("status", "fail"),
                },
            }

        except Exception as e:
            logger.exception("Pipeline FAILED: job #%d — %s", job_id, e)
            update_job_status(conn, job_id, "FAILED", str(e))
            remove_job_file_handler()
            return {"status": "failed", "error": str(e), "job_id": job_id}

    def run_pipeline(
        self,
        topic: str,
        niche: str = "indonesian_artists",
        output_dir: str = "outputs",
        relax_gates: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the full topic-to-output pipeline.

        Gate sequence: G1→G2→Safety→G3→Researcher→G4→G5→G6→
                       Scriptwriter→G7→Voice→G8→Visual→G9→
                       Composer→G10→Reviewer→Package
        """
        prepared = self._prepare_pipeline_run(relax_gates)
        if isinstance(prepared, dict):
            return prepared
        conn, self._relax_gates = prepared
        assets_cache = str(kwargs.get("assets_cache") or load_settings().assets_cache)
        logger.info("Pipeline START: niche='%s'", niche)

        niche_ctx = self._load_niche_context(niche)
        if isinstance(niche_ctx, dict):
            return niche_ctx
        _niche_config, safety_rules, channel_description, language_name, tone_name, angle_name = (
            niche_ctx
        )

        # Build config snapshot for retry/resume determinism
        config_snapshot = {
            "topic": topic,
            "niche": niche,
            "output_dir": output_dir,
            "assets_cache": assets_cache,
            "niche_ctx": {
                "safety_rules": safety_rules,
                "channel_description": channel_description,
                "language": language_name,
                "tone": tone_name,
                "content_angle": angle_name,
            },
        }

        # Stage 1: Preflight + Safety
        stage1 = self._stage_safety(
            conn, topic, niche, assets_cache, output_dir, config_snapshot=config_snapshot
        )
        if isinstance(stage1, dict):
            return stage1
        job_id, cost_result = stage1

        # Stages 2-5: Research → Content → Composition → Review + Package
        return self._run_pipeline_stages(
            conn,
            job_id,
            cost_result,
            topic,
            niche,
            safety_rules,
            channel_description,
            language_name,
            tone_name,
            angle_name,
            assets_cache,
            output_dir,
        )

    def _load_agent_output(self, assets_cache: str, job_id: int, agent_name: str) -> dict[str, Any]:
        """Load a completed agent's output.json from the artifact workspace."""
        from clipper_agency.core.artifacts import read_json
        from clipper_agency.core.paths import agent_output_file

        path = agent_output_file(assets_cache, job_id, agent_name)
        try:
            return read_json(path)
        except (FileNotFoundError, ValueError):
            return {}

    @staticmethod
    def _persist_agent_output(
        assets_cache: str,
        job_id: int,
        agent_name: str,
        output: dict,
    ) -> None:
        """Write an agent's output.json to the artifact workspace."""
        from clipper_agency.core.artifacts import write_json
        from clipper_agency.core.paths import agent_output_file, ensure_agent_dir

        ensure_agent_dir(assets_cache, job_id, agent_name)
        write_json(agent_output_file(assets_cache, job_id, agent_name), output)

    def _try_load_cached(
        self,
        assets_cache: str,
        job_id: int,
        agent_name: str,
    ) -> dict[str, Any]:
        """Validate cached artifacts and return output.json if valid.

        Returns an empty dict when cache is invalid so the caller can
        fall through to re-running the agent.
        """
        vr = validate_agent_cache(assets_cache, job_id, agent_name)
        if not vr.passed:
            logger.info(
                "Cache invalid for %s job #%d: %s", agent_name, job_id, "; ".join(vr.issues)
            )
            return {}
        return self._load_agent_output(assets_cache, job_id, agent_name)

    def _run_cached_or_fresh(
        self,
        agent_name: str,
        use_cache: bool,
        assets_cache: str,
        job_id: int,
        run_fn,
    ) -> dict[str, Any]:
        """Try cached output when use_cache is True; fall back to fresh run."""
        if not use_cache:
            return run_fn()
        cached = self._try_load_cached(assets_cache, job_id, agent_name)
        if cached:
            return cached
        return run_fn()

    def _apply_asset_qualification(
        self,
        research_output: dict[str, Any],
        job_id: int,
        topic: str,
        assets_cache: str,
        window_selector: Any = None,
    ) -> tuple[list[dict], list[dict]]:
        """Pre-Visual-Director asset-qualification boundary (PR 5 / design §6).

        Qualifies each beat's candidates BEFORE Visual Director consumes them and runs
        source recovery BEFORE the text-card fallback (the Job #8 fix). Returns the
        immutably-rewritten ``(qualified_story_beats, qualified_flat)`` pool for VD.

        The per-beat ``asset_candidates`` is rebuilt from each beat's qualified set only,
        so rejected candidates never reach VD's live per-beat surface (design §6 step 4 /
        [V4]); the flat pool is defense-in-depth-filtered by the union of reject_reasons.
        ``qualification_report.json`` is written for observability.

        The inspection cache namespace MUST match VD's (``visual_director``/
        ``inspection_cache``) so VD's re-inspection of a pre-qualified candidate is a
        cache hit → 0 double-VLM (SLICE 1 cache-key parity; design §12 HIGHEST risk).
        Note: design §6 step 1 says "segment_producer" for the agent dir — that is
        incorrect; it must be "visual_director" or the cache namespace forks and VLM is
        re-spent. ADR 0027: inspect via VD's own bound method (byte-identical cached
        output, frame ownership in VD, no double extraction).
        """
        from clipper_agency.core import asset_qualification
        from clipper_agency.core.clip_window import KeywordOverlapWindowSelector
        from clipper_agency.core.paths import ensure_agent_dir, job_cache_dir

        settings = load_settings()
        # PR 6: clip-window selector (default conservative full-clip; injectable for tests).
        selector = window_selector or KeywordOverlapWindowSelector()
        # Same cache + frame dir VD uses, so the pre-VD pass populates VD's cache.
        vd_agent_dir = ensure_agent_dir(assets_cache, job_id, "visual_director")
        cache_dir = f"{vd_agent_dir}/inspection_cache"

        story_beats = research_output.get("story_beats", [])
        sp = SegmentProducerAgent(trace_writer=self._trace_writer)
        discover_fn = asset_qualification._build_sp_discovery_adapter(
            sp, topic, research_output.get("entities", []), settings, beats=story_beats
        )
        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=1, discover_fn=discover_fn
        )
        # Lightweight construct (no API); inspect via VD's own bound method.
        inspector = VisualDirectorAgent(trace_writer=self._trace_writer)._run_multimodal_inspection

        results = asset_qualification.qualify_research_candidates(
            research_output,
            job_id,
            cache_dir,
            vd_agent_dir,
            inspector=inspector,
            recovery=recovery,
        )

        # Immutable rewrite (new dicts per beat — CLAUDE.md immutability rule). Filter the
        # ORIGINAL candidate dicts by each beat's qualified asset_ids so every candidate
        # field VD may read is preserved (model_dump would drop non-schema fields).
        results_by_beat = {r.beat_id: r for r in results}
        qualified_story_beats: list[dict] = []
        for beat_dict in story_beats:
            result = results_by_beat.get(str(beat_dict.get("beat_id", "")))
            if result is None:
                qualified_story_beats.append(beat_dict)
                continue
            qualified_ids = {c["asset_id"] for c in result.qualified}
            kept: list[dict] = []
            for ac in beat_dict.get("asset_candidates", []):
                if f"{ac.get('type', '')}_{ac.get('url', '')[:40]}" not in qualified_ids:
                    continue
                # PR 6: attach the clip window (default full-clip; selector is conservative v1).
                window = selector.select_window(ac, beat_dict, None)
                kept.append(
                    {
                        **ac,
                        "source_start_sec": window.source_start_sec,
                        "source_end_sec": window.source_end_sec,
                    }
                )
            rewritten = {**beat_dict, "asset_candidates": kept}
            if result.verdict == "exhausted_text_card" and result.fallback_card is not None:
                rewritten["qualification_text_card"] = result.fallback_card
            qualified_story_beats.append(rewritten)

        # Flat-pool defense-in-depth filter (design §6 step 4 / [V4]): drop any candidate
        # whose asset_id appears in any beat's reject_reasons.
        rejected_ids: set[str] = set()
        for r in results:
            rejected_ids.update(r.reject_reasons.keys())
        qualified_flat = [
            c
            for c in research_output.get("asset_candidates", [])
            if f"{c.get('type', '')}_{c.get('url', '')[:40]}" not in rejected_ids
        ]

        write_json(
            f"{job_cache_dir(assets_cache, job_id)}/qualification_report.json",
            asset_qualification.build_qualification_report(job_id, results),
        )
        return qualified_story_beats, qualified_flat

    def _run_visual_director_phase(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        research_output: dict[str, Any],
        script_output: dict[str, Any],
        output_dir: str,
        assets_cache: str,
        voice_output: dict[str, Any] | None = None,
        beat_timeline: list | None = None,
    ) -> dict[str, Any]:
        """Run Visual Director agent: sources → visual output → complete."""
        mark_agent_running(conn, job_id, "visual_director")
        vo = voice_output or {}

        # Pass research paths — let Visual Director decide what's useful
        research_contract_path = ""
        research_brief_path = ""
        if assets_cache:
            from clipper_agency.core.paths import agent_dir as get_agent_dir

            rd = get_agent_dir(assets_cache, job_id, "segment_producer")
            cp = Path(rd) / "research_contract.json"
            bp = Path(rd) / "research_brief.md"
            if cp.exists():
                research_contract_path = str(cp)
            if bp.exists():
                research_brief_path = str(bp)

        # PR 5: pre-VD asset qualification (design §6). Qualify candidates before VD
        # consumes them + run source recovery before the text-card fallback.
        qualified_story_beats, qualified_flat = self._apply_asset_qualification(
            research_output, job_id, topic, assets_cache
        )

        visual_output = self._run_visual_director(
            job_id=job_id,
            script=script_output.get("script", []),
            topic=topic,
            output_dir=output_dir,
            assets_cache=assets_cache,
            research_contract_path=research_contract_path,
            research_brief_path=research_brief_path,
            story_beats=qualified_story_beats,
            timestamps=vo.get("timestamps", []),
            do_not_use=research_output.get("do_not_use", []),
            asset_candidates=qualified_flat,
            voiceover_duration_sec=vo.get("voiceover_duration_sec", 0.0),
            beat_timeline=beat_timeline,
        )
        if visual_output.get("status") != "failed":
            self._complete_agent(conn, assets_cache, job_id, "visual_director")
        return visual_output

    def _retry_composer_stage(
        self,
        conn,
        job_id: int,
        visual_output: dict[str, Any],
        voice_output: dict[str, Any],
        output_dir: str,
        assets_cache: str,
        cycle: int = 0,
        beat_timeline: list | None = None,
    ) -> tuple[dict[str, Any], dict | None]:
        """Run composer with error handling and G10 gate enforcement.

        When cycle > 0, writes output to a cycle-specific subdirectory
        to preserve the original (cycle 0) output.

        Returns (compose_output, abort_response). If abort_response is not
        None, it should be returned immediately from run_pipeline_from.
        """
        mark_agent_running(conn, job_id, "composer")
        # Load script scenes from completed scriptwriter for subtitles
        script_output = self._load_agent_output(assets_cache, job_id, "scriptwriter")

        # For repair cycles, prepare a cycle-specific subdirectory
        # but composer always writes to the standard contract path.
        # After compose succeeds, output is copied to the cycle dir.
        composer_output_dir = output_dir
        cycle_dir: Path | None = None
        if cycle > 0:
            cycle_dir = Path(output_dir) / f"job_{job_id}" / f"cycle_{cycle}"
            cycle_dir.mkdir(parents=True, exist_ok=True)

        compose_output = self._run_composer(
            job_id=job_id,
            assets=visual_output.get("assets", []),
            audio_files=voice_output.get("audio_files", []),
            output_dir=composer_output_dir,
            assets_cache=assets_cache,
            script_scenes=script_output.get("script", []),
            voiceover_path=voice_output.get("voiceover_path", ""),
            timestamps=voice_output.get("timestamps", []),
            narrative_structure=script_output.get("narrative_structure", []),
            beat_timeline=beat_timeline,
            voiceover_duration_sec=voice_output.get("voiceover_duration_sec"),
        )

        # After compose succeeds, copy output to cycle dir for _promote_to_final
        if cycle > 0 and compose_output.get("status") != "failed":
            # Structurally guaranteed: cycle_dir is assigned at L2563 inside the
            # `if cycle > 0:` block above. Use a raise (not assert) so the guard
            # survives `python -O` and narrows cycle_dir to Path for pyright.
            if cycle_dir is None:  # pragma: no cover
                raise RuntimeError("cycle_dir unset inside cycle>0 block")
            compose_output["cycle"] = cycle
            try:
                job_dir = Path(output_dir) / f"job_{job_id}"
                for fname in ("video.mp4", "thumbnail.png", "caption.txt"):
                    src_file = job_dir / fname
                    if src_file.exists():
                        shutil.copy2(str(src_file), str(cycle_dir / fname))
                compose_output["cycle_video_path"] = str(cycle_dir / "video.mp4")
            except OSError:
                logger.warning(
                    "Failed to copy cycle %d output to %s", cycle, cycle_dir, exc_info=True
                )
                compose_output["cycle_video_path"] = compose_output.get("video_path", "")

        if compose_output.get("status") == "failed":
            return compose_output, self._fail_agent(
                conn, job_id, "composer", compose_output, _COMPOSER_FAILED
            )
        self._complete_agent(conn, assets_cache, job_id, "composer")

        cp_config = load_settings().content_planning
        hard_limit = cp_config.hard_limit_sec if cp_config else 60
        g10 = GateVideoValidation()
        g10_result = g10.evaluate(
            video_path=compose_output.get("video_path"),
            hard_limit_sec=hard_limit,
            voiceover_duration_sec=voice_output.get("voiceover_duration_sec"),
        )
        self._record_gate(assets_cache, job_id, "G10_video_validation", g10_result)
        abort = self._enforce_gate(
            conn,
            job_id,
            "G10",
            g10_result,
            failed_at="video_validation",
        )
        return compose_output, abort

    def _retry_review_and_package(
        self,
        conn,
        job_id: int,
        topic: str,
        script_output: dict[str, Any],
        compose_output: dict[str, Any],
        safety_rules: list[str],
        niche: str,
        output_dir: str,
        assets_cache: str,
        voice_output: dict[str, Any] | None = None,
        research_output: dict[str, Any] | None = None,
    ) -> tuple[dict | None, dict | None, dict | None]:
        """Run review and packaging stages. Returns (abort, review_output, pkg_output)."""
        vo = voice_output or {}
        rp = research_output or {}
        # Build canonical timeline for reviewer (ADR 0020).
        # FIX-6: enforce the physical-timeline contract (backstop for G7).
        # Run BEFORE mark_agent_running(reviewer) so a timeline abort never
        # leaves a stale reviewer=running state (Codex local-review P2).
        beat_timeline, tlc_abort = self._enforce_timeline_contract(
            conn,
            job_id,
            assets_cache,
            script_output.get("narrative_structure", []),
            vo.get("timestamps", []),
        )
        if tlc_abort:
            return (tlc_abort, None, None)
        mark_agent_running(conn, job_id, "reviewer")
        review_output = self._run_reviewer(
            job_id=job_id,
            topic=topic,
            script=script_output.get("script", []),
            caption=script_output.get("caption", ""),
            safety_rules=safety_rules,
            audio_duration_sec=vo.get("voiceover_duration_sec", 0.0),
            visual_duration_sec=compose_output.get("output_duration_sec", 0.0),
            narrative_structure=script_output.get("narrative_structure", []),
            unverified_claims=script_output.get("unverified_claims", []),
            story_beats=rp.get("story_beats", []),
            word_timestamps=vo.get("timestamps", []),
            rendered_scene_manifest=compose_output.get("rendered_scene_manifest"),
            diagnostics=compose_output.get("diagnostics", {}),
            beat_timeline=beat_timeline,
            # FIX-4 (ADR 0030): thread voiceover_duration_sec so the reviewer's
            # AUDIO_NOT_TRUNCATED re-probe fires on the normal path too
            # (blast-radius: both _run_reviewer call sites must wire it).
            voiceover_duration_sec=vo.get("voiceover_duration_sec", 0.0),
            # FIX-4 (ADR 0030): thread topic-level entities so the per-scene
            # entity-binding (ENTITY_MISMATCH) gate fires on the normal path
            # (was always None → gate degraded to no-op). NOTE: the separate
            # package-consistency gate additionally needs story_mode_decision +
            # thumbnail_text, which remain unthreaded (pre-existing gate
            # inertness, NOT FIX-4 scope) — do not claim it fires here.
            main_entities=_extract_main_entities(rp),
        )
        # Persist reviewer output for debugging (deterministic gate results,
        # scores, and verdicts must be on disk even when gates hard-fail).
        self._persist_agent_output(assets_cache, job_id, "reviewer", review_output)
        # Route repair plan if reviewer requested revisions
        repair_routing = self._handle_repair_plan(
            review_output=review_output,
            assets_cache=assets_cache,
            job_id=job_id,
            current_cycle=1,
        )

        if repair_routing is None:
            # Deterministic gate failures (visual_coverage, text_collision,
            # safe_area, package_consistency, timestamp_semantic) don't
            # include an LLM repair_plan — synthesize one from the gate
            # failure reason so the repair loop can engage (Bug 4).
            from clipper_agency.core.repair_router import (
                build_gate_failure_repair_plan,
            )

            repair_routing = build_gate_failure_repair_plan(review_output)
            if repair_routing:
                logger.info(
                    "Deterministic gate failure '%s' → repair routed to %s for job #%d",
                    review_output.get("reason"),
                    repair_routing["target_agent"],
                    job_id,
                )

        if repair_routing:
            # Reviewer failed with repair plan
            update_job_artifact_status(conn, job_id, "rejected")
            update_job_quality_status(conn, job_id, "failed")
            update_job_publication_status(conn, job_id, "blocked")
            update_job_repair_status(conn, job_id, "pending")
            review_output["repair_routing"] = repair_routing
            logger.info(
                "Reviewer repair plan routed to %s for job #%d",
                repair_routing["target_agent"],
                job_id,
            )
            return None, review_output, None

        self._complete_agent(conn, assets_cache, job_id, "reviewer")

        # Set lifecycle statuses based on reviewer outcome
        if review_output.get("status") == "pass":
            update_job_artifact_status(conn, job_id, "approved")
            update_job_quality_status(conn, job_id, "passed")
            update_job_publication_status(conn, job_id, "ready")
        else:
            # Reviewer failed without a repair plan — block publication,
            # keep artifacts on disk, do NOT package or create final/ dir.
            update_job_artifact_status(conn, job_id, "rejected")
            update_job_quality_status(conn, job_id, "failed")
            update_job_publication_status(conn, job_id, "blocked")
            logger.info(
                "Reviewer failed without repair plan for job #%d — "
                "artifacts kept, publication blocked",
                job_id,
            )
            return None, review_output, None

        # Reviewer passed — package and promote to final/
        pkg_output = self._package_output(
            job_id=job_id,
            video_path=compose_output.get("video_path", ""),
            caption=script_output.get("caption", ""),
            topic=topic,
            niche=niche,
            output_dir=output_dir,
            template_name=compose_output.get("template_name"),
        )

        if pkg_output.get("status") == "failed":
            update_job_status(conn, job_id, "FAILED", pkg_output.get("error", _PACKAGING_FAILED))
            return (
                {
                    "status": "failed",
                    "failed_at": "packaging",
                    "reason": pkg_output.get("error", _PACKAGING_FAILED),
                    "job_id": job_id,
                },
                review_output,
                pkg_output,
            )

        # Promote to final/ directory
        promotion = self._promote_to_final(
            output_dir=output_dir,
            job_id=job_id,
        )
        if promotion.get("status") == "failed":
            logger.warning(
                "Promotion failed for job #%d: %s — "
                "approved artifact stays, publication stays blocked until retry",
                job_id,
                promotion.get("error", "unknown"),
            )

        update_manifest_final(
            assets_cache,
            job_id,
            {
                "video": pkg_output.get("video_path", ""),
                "caption": pkg_output.get("caption_path", ""),
                "thumbnail": pkg_output.get("thumbnail_path", ""),
                "metadata": pkg_output.get("metadata_path", ""),
            },
        )
        return None, review_output, pkg_output

    def _reconstruct_upstream_outputs(
        self,
        from_idx: int,
        assets_cache: str,
        job_id: int,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Load completed upstream agent outputs."""
        loader = self._load_agent_output
        research = (
            loader(assets_cache, job_id, "segment_producer")
            if from_idx > PIPELINE_ORDER.index("segment_producer")
            else {}
        )
        script = (
            loader(assets_cache, job_id, "scriptwriter")
            if from_idx > PIPELINE_ORDER.index("scriptwriter")
            else {}
        )
        voice = (
            loader(assets_cache, job_id, "voice_producer")
            if from_idx > PIPELINE_ORDER.index("voice_producer")
            else {}
        )
        visual = (
            loader(assets_cache, job_id, "visual_director")
            if from_idx > PIPELINE_ORDER.index("visual_director")
            else {}
        )
        return research, script, voice, visual

    def _retry_safety_stage(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        assets_cache: str,
        from_idx: int,
    ) -> dict | None:
        """Run safety if needed during retry. Returns abort on hard_fail."""
        if from_idx > PIPELINE_ORDER.index("safety"):
            return None
        mark_agent_running(conn, job_id, "safety")
        safety_result = self._run_safety(
            job_id=job_id,
            topic=topic,
            assets_cache=assets_cache,
        )
        if safety_result.get("status") == "hard_fail":
            if self._gate_relaxed("Safety"):
                logger.warning(
                    _GATE_RELAX_WARN_MSG,
                    "Safety",
                    safety_result.get("reason"),
                )
            else:
                reason = safety_result.get("reason", "Safety failed")
                mark_agent_failed(conn, job_id, "safety", reason)
                update_job_status(conn, job_id, "FAILED", reason)
                return {
                    "status": "failed",
                    "failed_at": "safety",
                    "reason": reason,
                    "job_id": job_id,
                }
        self._complete_agent(conn, assets_cache, job_id, "safety")
        return None

    def _retry_research_stage(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        safety_rules: list[str],
        channel_description: str,
        language: str,
        tone: str,
        content_angle: str,
        assets_cache: str,
        output_dir: str,
        from_idx: int,
    ) -> tuple[dict[str, Any] | None, dict | None]:
        """Run research if needed. Returns (research_output, abort)."""
        if from_idx > PIPELINE_ORDER.index("segment_producer"):
            return None, None
        research_result = self._stage_research(
            conn,
            job_id,
            topic,
            safety_rules,
            channel_description,
            language,
            tone,
            content_angle,
            assets_cache,
            output_dir,
        )
        if (
            isinstance(research_result, dict)
            and research_result.get(
                "status",
            )
            == "failed"
        ):
            return {}, research_result
        return research_result, None

    def _retry_downstream_stages(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        niche_ctx: dict[str, Any],
        niche: str,
        output_dir: str,
        assets_cache: str,
        from_idx: int,
        use_cache: bool,
        research_output: dict[str, Any],
        script_output: dict[str, Any],
        voice_output: dict[str, Any],
        visual_output: dict[str, Any],
    ) -> dict | None:
        """Run retry stages after research. Returns abort on failure."""
        safety_rules = niche_ctx["safety_rules"]
        channel_description = niche_ctx["channel_description"]
        language = niche_ctx["language"]
        tone = niche_ctx["tone"]
        content_angle = niche_ctx["content_angle"]
        if from_idx <= PIPELINE_ORDER.index("scriptwriter"):
            script_output = self._run_cached_or_fresh(
                "scriptwriter",
                use_cache,
                assets_cache,
                job_id,
                lambda: self._run_content_scriptwriter(
                    conn,
                    job_id,
                    topic,
                    safety_rules,
                    channel_description,
                    language,
                    tone,
                    content_angle,
                    research_output,
                    assets_cache,
                ),
            )
            if script_output.get("status") == "failed":
                return self._fail_agent(
                    conn, job_id, "scriptwriter", script_output, _SCRIPT_BUDGET_FAILED
                )

        # G7 (ADR 0030 / FIX-1): enforce coverage on the retry path too —
        # whether Scriptwriter was rerun or reused from cache. NOTE: the
        # automatic FIX-5 regen routing lives on the run_pipeline stage path
        # (_stage_content / _stage_composition); this manual resume/retry path
        # is operator-initiated re-entry and keeps the terminal abort so the
        # FIX-6 resume contract (failed_at == "timeline_contract") holds and a
        # subsequent retry re-enters regen naturally.
        if abort := self._enforce_narrative_coverage(conn, job_id, script_output, assets_cache):
            return abort

        if from_idx <= PIPELINE_ORDER.index("voice_producer"):
            voice_output = self._run_cached_or_fresh(
                "voice_producer",
                use_cache,
                assets_cache,
                job_id,
                lambda: self._run_content_voice(
                    conn,
                    job_id,
                    script_output,
                    output_dir,
                    assets_cache,
                ),
            )

        # Build canonical timeline for retry (ADR 0020).
        # FIX-6: enforce the physical-timeline contract (backstop for G7).
        beat_timeline, abort = self._enforce_timeline_contract(
            conn,
            job_id,
            assets_cache,
            script_output.get("narrative_structure", []),
            voice_output.get("timestamps", []),
        )
        if abort:
            # Manual resume/retry path: keep the terminal FIX-6 abort (the
            # automatic FIX-5 regen routing is on the run_pipeline stage path;
            # see _stage_composition). Preserves the failed_at ==
            # "timeline_contract" resume contract.
            return abort

        if from_idx <= PIPELINE_ORDER.index("visual_director"):
            visual_output = self._run_visual_director_phase(
                conn,
                job_id,
                topic,
                research_output,
                script_output,
                output_dir,
                assets_cache,
                voice_output=voice_output,
                beat_timeline=beat_timeline,
            )
            if visual_output.get("status") == "failed":
                return self._fail_agent(
                    conn, job_id, "visual_director", visual_output, _ASSET_SOURCING_FAILED
                )

        if from_idx <= PIPELINE_ORDER.index("composer"):
            compose_output, abort = self._retry_composer_stage(
                conn,
                job_id,
                visual_output,
                voice_output,
                output_dir,
                assets_cache,
                beat_timeline=beat_timeline,
            )
            if abort:
                return abort
        else:
            compose_output = self._load_agent_output(assets_cache, job_id, "composer")

        return self._retry_reviewer_stage(
            conn,
            job_id,
            topic,
            script_output,
            compose_output,
            niche_ctx,
            niche,
            output_dir,
            assets_cache,
            voice_output,
            research_output,
            from_idx,
        )

    def _retry_reviewer_stage(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        script_output: dict[str, Any],
        compose_output: dict[str, Any],
        niche_ctx: dict[str, Any],
        niche: str,
        output_dir: str,
        assets_cache: str,
        voice_output: dict[str, Any],
        research_output: dict[str, Any],
        from_idx: int,
    ) -> dict | None:
        """Run the reviewer + packaging retry stage if ``from_idx`` reaches it.

        Extracted from ``_retry_downstream_stages`` to keep that method's
        cognitive complexity under the Sonar S3776 cap after FIX-6 added the
        timeline-contract guard. Behavior is byte-identical."""
        if from_idx <= PIPELINE_ORDER.index("reviewer"):
            abort, _, _ = self._retry_review_and_package(
                conn,
                job_id,
                topic,
                script_output,
                compose_output,
                niche_ctx["safety_rules"],
                niche,
                output_dir,
                assets_cache,
                voice_output=voice_output,
                research_output=research_output,
            )
            if abort:
                return abort
        return None

    def run_pipeline_from(
        self,
        job_id: int,
        from_agent: str,
        use_cache: bool = False,
        relax_gates: str = "",
    ) -> dict[str, Any]:
        """Re-run pipeline from a specific agent, reusing completed outputs.

        Reconstructs intermediate data from persisted agent output.json files
        and skips agents that completed before ``from_agent``.
        """
        conn = get_connection(self.db_path)
        # Resolve DEV gate-relax set (CLI ∪ env). Empty == today's behavior.
        # Retry/resume re-reads env so a CLIPPER_RELAX_GATES override applies.
        self._relax_gates = resolve_relax_gates(
            getattr(load_settings(), "relax_gates", ""), relax_gates or ""
        )
        # Preflight (PR 7 Codex P2#1): validate agent models on retry/resume too,
        # so a changed *_MODEL override can't reach OpenRouter mid-pipeline.
        try:
            preflight_agent_models()
        except RuntimeError as exc:
            logger.exception("Model preflight failed")
            return {
                "status": "failed",
                "failed_at": "model_preflight",
                "reason": str(exc),
                "job_id": job_id,
            }
        job = get_job(conn, job_id)
        if not job:
            return {"status": "failed", "reason": f"Job {job_id} not found", "job_id": job_id}

        # Load config snapshot
        snapshot_raw = job.get("config_snapshot")
        snapshot = json.loads(snapshot_raw or "{}")
        topic = snapshot.get("topic", job.get("topic", ""))
        niche = snapshot.get("niche", job.get("niche", "indonesian_artists"))
        output_dir = snapshot.get("output_dir", "outputs")
        assets_cache = snapshot.get("assets_cache", "") or str(
            load_settings().assets_cache,
        )

        update_job_status(conn, job_id, "RUNNING")
        add_job_file_handler(job_id)
        append_audit_log(
            conn,
            action="pipeline_retry",
            actor="engine",
            resource_type="job",
            resource_id=job_id,
            details=json.dumps({"from_agent": from_agent, "use_cache": use_cache}),
        )

        if from_agent not in PIPELINE_ORDER:
            update_job_status(conn, job_id, "FAILED", f"Unknown agent: {from_agent}")
            return {"status": "failed", "reason": f"Unknown agent: {from_agent}", "job_id": job_id}

        from_idx = PIPELINE_ORDER.index(from_agent)
        (research_output, script_output, voice_output, visual_output) = (
            self._reconstruct_upstream_outputs(
                from_idx,
                assets_cache,
                job_id,
            )
        )

        # Load niche config from snapshot for deterministic retry
        niche_ctx_raw = snapshot.get("niche_ctx", {})
        if niche_ctx_raw:
            niche_ctx = niche_ctx_raw
            safety_rules = niche_ctx["safety_rules"]
            channel_description = niche_ctx["channel_description"]
            language_name = niche_ctx["language"]
            tone_name = niche_ctx["tone"]
            angle_name = niche_ctx["content_angle"]
        else:
            # Fallback for old jobs without niche_ctx in snapshot
            try:
                niche_config = load_niche(niche)
            except FileNotFoundError:
                logger.error(
                    "Niche config not found: %r — aborting retry",
                    niche,
                )
                return {"status": "failed", "reason": f"Niche config {niche!r} not found"}
            safety_rules = niche_config.safety_rules
            channel_description = build_channel_description(niche_config)
            language_name = get_language_name(niche_config)
            tone_name = get_tone_name(niche_config)
            angle_name = get_angle_name(niche_config)
            niche_ctx = {
                "safety_rules": safety_rules,
                "channel_description": channel_description,
                "language": language_name,
                "tone": tone_name,
                "content_angle": angle_name,
            }

        try:
            # Stage: Safety
            abort = self._retry_safety_stage(
                conn,
                job_id,
                topic,
                assets_cache,
                from_idx,
            )
            if abort:
                return abort

            # Stage: Research (segment_producer + gates G3-G5)
            fresh, abort = self._retry_research_stage(
                conn,
                job_id,
                topic,
                safety_rules,
                channel_description,
                language_name,
                tone_name,
                angle_name,
                assets_cache,
                output_dir,
                from_idx,
            )
            if abort:
                return abort
            if fresh is not None:
                research_output = fresh

            abort = self._retry_downstream_stages(
                conn,
                job_id,
                topic,
                niche_ctx,
                niche,
                output_dir,
                assets_cache,
                from_idx,
                use_cache,
                research_output,
                script_output,
                voice_output,
                visual_output,
            )
            if abort:
                return abort

            update_job_status(conn, job_id, "COMPLETED")
            logger.info("Pipeline retry COMPLETED: job #%d", job_id)
            remove_job_file_handler()
            return {"status": "completed", "job_id": job_id}

        except Exception as e:
            logger.exception("Pipeline retry FAILED: job #%d — %s", job_id, e)
            update_job_status(conn, job_id, "FAILED", str(e))
            remove_job_file_handler()
            return {"status": "failed", "error": str(e), "job_id": job_id}

    def _run_content_scriptwriter(
        self,
        conn: Any,
        job_id: int,
        topic: str,
        safety_rules: list[str],
        channel_description: str,
        language: str,
        tone: str,
        content_angle: str,
        research_output: dict[str, Any],
        assets_cache: str,
        repair_hint: str = "",
    ) -> dict[str, Any]:
        """Run scriptwriter stage of content creation.

        ``repair_hint`` (FIX-5 / ADR 0030): when ``"regen_narrative"`` this
        run is a coverage-regen attempt; the sentinel is recorded on the
        output for observability so the regen attempt is distinguishable
        from a normal Scriptwriter run (the "cover ALL words" signal).
        """
        g6 = GateCreativeMemory()
        self._record_gate(assets_cache, job_id, "G6_creative_memory", g6.evaluate())

        if repair_hint == "regen_narrative":
            logger.info(
                "Scriptwriter coverage-regen: forcing narrative_structure "
                "to cover ALL words [0, word_count-1] (job %d)",
                job_id,
            )

        mark_agent_running(conn, job_id, "scriptwriter")

        # Build blueprint from research output for audio-first pipeline
        direction = research_output.get("validated_direction")
        resolved_angle = content_angle
        if direction and direction.content_angle:
            resolved_angle = direction.content_angle

        blueprint = {
            "story_beats": research_output.get("story_beats", []),
            "verified_facts": research_output.get("verified_facts", []),
            "unverified_claims": research_output.get("unverified_claims", []),
            "format_decision": research_output.get("format_decision"),
        }
        # Enrich blueprint with validated direction when available
        if direction:
            blueprint["story_format"] = direction.format
            blueprint["story_count"] = direction.story_count
            blueprint["stories_list"] = direction.stories

        cp_config = load_settings().content_planning
        if cp_config:
            blueprint["target_duration_sec"] = cp_config.target_duration_sec
            blueprint["hard_limit_sec"] = cp_config.hard_limit_sec
            blueprint["estimated_words_per_second"] = cp_config.estimated_words_per_second

        script_output = self._run_scriptwriter(
            job_id=job_id,
            topic=topic,
            research_brief=research_output.get("research_brief", ""),
            safety_rules=safety_rules,
            channel_description=channel_description,
            language=language,
            tone=tone,
            content_angle=resolved_angle,
            assets_cache=assets_cache,
            blueprint=blueprint if blueprint else None,
            # FIX-5 (ADR 0030, Codex P2): thread the "cover ALL words"
            # directive into the LLM call on a regen attempt so the model is
            # actually instructed to fix the coverage gap (not just re-run with
            # the same prompt that produced the broken structure).
            coverage_directive=_COVERAGE_REGEN_DIRECTIVE
            if repair_hint == REGEN_NARRATIVE_ACTION
            else "",
        )
        self._complete_agent(conn, assets_cache, job_id, "scriptwriter")

        g7 = GateScriptValidation()
        script_scenes = script_output.get("script", [])
        script_text = (
            " ".join(s.get("text", "") for s in script_scenes)
            if isinstance(script_scenes, list)
            else str(script_scenes)
        )
        g7_result = g7.evaluate(
            script=script_text,
            caption=script_output.get("caption", ""),
        )
        self._record_gate(assets_cache, job_id, "G7_script_validation", g7_result)

        # Duration Gate: check script fits within time budget
        cp_config = load_settings().content_planning
        if cp_config and isinstance(script_scenes, list) and script_scenes:
            estimated = estimate_script_duration_sec(
                script_scenes,
                words_per_sec=cp_config.estimated_words_per_second,
            )
            budget = DurationBudget(
                target=cp_config.target_duration_sec,
                hard=cp_config.hard_limit_sec,
            )
            budget_check = check_script_duration_budget(estimated, budget)
            script_output["_duration_check"] = budget_check
            logger.info("Duration gate: estimated=%.1fs %s", estimated, budget_check["reason"])
            if not budget_check["pass"]:
                reason = f"Script duration {estimated:.1f}s exceeds hard limit {budget.hard}s"
                mark_agent_failed(conn, job_id, "scriptwriter", reason)
                update_job_status(conn, job_id, "FAILED", reason)
                script_output["status"] = "failed"
                script_output["error"] = reason

        return script_output

    def _run_content_voice(
        self,
        conn: Any,
        job_id: int,
        script_output: dict[str, Any],
        output_dir: str,
        assets_cache: str,
    ) -> dict[str, Any]:
        """Run voice producer stage of content creation."""
        mark_agent_running(conn, job_id, "voice_producer")
        voice_output = self._run_voice_producer(
            job_id=job_id,
            script=script_output.get("script", []),
            voiceover_text=script_output.get("voiceover_text", ""),
            output_dir=output_dir,
            assets_cache=assets_cache,
        )
        self._complete_agent(conn, assets_cache, job_id, "voice_producer")

        g8 = GateAudioValidation()
        g8_result = g8.evaluate(audio_path=voice_output.get("voiceover_path"))
        self._record_gate(assets_cache, job_id, "G8_audio_validation", g8_result)
        return voice_output

    # ── Agent runner methods (extracted for testability) ──

    def _run_safety(self, job_id: int, topic: str, **kwargs: Any) -> dict[str, Any]:
        agent = SafetyAgent(trace_writer=self._trace_writer)
        return agent.execute(job_id=job_id, topic=topic, **kwargs)

    def _run_researcher(
        self,
        job_id: int,
        topic: str,
        safety_rules: list[str] | None = None,
        output_dir: str = "outputs",
        **kwargs: Any,
    ) -> dict[str, Any]:
        agent = SegmentProducerAgent(trace_writer=self._trace_writer)
        return agent.execute(
            job_id=job_id,
            topic=topic,
            safety_rules=safety_rules or [],
            output_dir=output_dir,
            **kwargs,
        )

    def _run_scriptwriter(
        self,
        job_id: int,
        topic: str,
        research_brief: str = "",
        safety_rules: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        agent = ScriptwriterAgent(trace_writer=self._trace_writer)
        return agent.execute(
            job_id=job_id,
            topic=topic,
            research_brief=research_brief,
            safety_rules=safety_rules or [],
            **kwargs,
        )

    def _run_voice_producer(
        self,
        job_id: int,
        script: list[dict] | None = None,
        output_dir: str = "outputs",
        **kwargs: Any,
    ) -> dict[str, Any]:
        agent = VoiceProducerAgent(trace_writer=self._trace_writer)
        result = agent.execute(
            job_id=job_id,
            script=script or [],
            output_dir=output_dir,
            **kwargs,
        )
        # FIX-5 (claude-auto-tok): stamp the input voiceover_text onto the
        # persisted output so a later regen's VO-diff skip has real data to
        # compare against. The VoiceoverOutput contract has no such field, so
        # without this the skip is silently inert in production (Codex P1).
        text = kwargs.get("voiceover_text", "")
        assets_cache = kwargs.get("assets_cache", "")
        if (
            text
            and assets_cache
            and result.get("status") not in ("failed", None)
            and result.get("voiceover_text") != text
        ):
            merged = {**result, "voiceover_text": text}
            self._persist_agent_output(assets_cache, job_id, "voice_producer", merged)
            return merged
        return result

    def _run_visual_director(
        self,
        job_id: int,
        script: list[dict] | None = None,
        topic: str = "",
        source_urls: list[str] | None = None,
        output_dir: str = "outputs",
        **kwargs: Any,
    ) -> dict[str, Any]:
        agent = VisualDirectorAgent(trace_writer=self._trace_writer)
        return agent.execute(
            job_id=job_id,
            script=script or [],
            topic=topic,
            source_urls=source_urls or [],
            output_dir=output_dir,
            **kwargs,
        )

    def _run_composer(
        self,
        job_id: int,
        assets: list[dict] | None = None,
        audio_files: list[str] | None = None,
        output_dir: str = "outputs",
        **kwargs: Any,
    ) -> dict[str, Any]:
        agent = ComposerAgent(trace_writer=self._trace_writer)
        return agent.execute(
            job_id=job_id,
            assets=assets or [],
            audio_files=audio_files or [],
            output_dir=output_dir,
            **kwargs,
        )

    def _run_reviewer(
        self,
        job_id: int,
        topic: str,
        script: list[dict] | None = None,
        caption: str = "",
        safety_rules: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        agent = ReviewerAgent(trace_writer=self._trace_writer)
        return agent.execute(
            job_id=job_id,
            topic=topic,
            script=script or [],
            caption=caption,
            safety_rules=safety_rules or [],
            **kwargs,
        )

    def _package_output(
        self,
        job_id: int,
        video_path: str,
        caption: str,
        topic: str,
        niche: str,
        output_dir: str = "outputs",
        **kwargs: Any,
    ) -> dict[str, Any]:
        packager = OutputPackager()
        from pathlib import Path

        caption_dir = Path(output_dir) / f"job_{job_id}"
        caption_dir.mkdir(parents=True, exist_ok=True)
        caption_path_file = caption_dir / "caption.txt"
        caption_path_file.write_text(caption.strip()[:150])
        # Thumbnail is written directly to the job-owned directory by composer.
        # Packager expects it at the fixed contract path (S6549 safe).
        metadata: dict[str, Any] = {"topic": topic, "niche": niche}
        if "template_name" in kwargs:
            metadata["template_name"] = kwargs["template_name"]
        return packager.package(
            job_id=job_id,
            video_path=video_path,
            metadata=metadata,
            output_dir=output_dir,
        )

    def _promote_to_final(
        self,
        output_dir: str,
        job_id: int,
        cycle: int = 0,
    ) -> dict[str, Any]:
        """Atomically promote cycle artifacts to outputs/final/job_{id}/.

        Only called when quality_status=passed and artifact_status=approved.
        Uses temp directory + os.rename for atomicity on same filesystem.

        Returns {"status": "completed", "final_dir": ...} or
                {"status": "failed", ...}.
        """
        base = Path(output_dir)
        if cycle > 0:
            src = base / f"job_{job_id}" / f"cycle_{cycle}"
        else:
            src = base / f"job_{job_id}"

        if not src.is_dir():
            return {
                "status": "failed",
                "error": f"Source directory {src} does not exist",
            }

        final_dir = base / "final" / f"job_{job_id}"
        tmp_dir = base / "final" / f".tmp_job_{job_id}"

        try:
            # Create parent final/ directory
            (base / "final").mkdir(parents=True, exist_ok=True)

            # Copy to temp directory first
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
            shutil.copytree(src, tmp_dir)

            # Atomic rename (same filesystem)
            if final_dir.exists():
                shutil.rmtree(final_dir)
            os.rename(str(tmp_dir), str(final_dir))

            logger.info("Promoted job #%d (cycle %d) to %s", job_id, cycle, final_dir)
            return {
                "status": "completed",
                "final_dir": str(final_dir),
            }
        except Exception as e:
            # Clean up temp dir on failure (ignore permission errors)
            try:
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir, ignore_errors=True)
            except OSError:
                pass
            logger.exception("Promotion FAILED for job #%d: %s", job_id, e)
            return {
                "status": "failed",
                "error": str(e),
            }
