"""Orchestrator Engine — coordinates the full gated agent pipeline."""

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.agents.segment_producer import SegmentProducerAgent
from clipper_agency.agents.reviewer import ReviewerAgent
from clipper_agency.agents.safety import SafetyAgent
from clipper_agency.agents.scriptwriter import ScriptwriterAgent
from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.agents.voice_producer import VoiceProducerAgent
from clipper_agency.config.loader import (
    load_settings, load_niche, build_channel_description,
    get_language_name, get_tone_name, get_angle_name,
)
from clipper_agency.core.artifacts import write_json
from clipper_agency.core.logging import add_job_file_handler, remove_job_file_handler
from clipper_agency.core.manifest import (
    create_manifest,
    update_manifest_agent,
    update_manifest_final,
    update_manifest_gate,
)
from clipper_agency.core.paths import gate_result_file
from clipper_agency.core.validation import validate_agent_cache
from clipper_agency.db.connection import get_connection
from clipper_agency.db.queries import (
    PIPELINE_ORDER,
    append_audit_log,
    create_agent_state,
    create_job,
    get_agent_state,
    get_job,
    mark_agent_completed,
    mark_agent_failed,
    mark_agent_running,
    update_job_status,
)
from clipper_agency.db.schema import initialize_schema
from clipper_agency.orchestrator.duration_gate import (
    DurationBudget,
    check_script_duration_budget,
    estimate_script_duration_sec,
)
from clipper_agency.orchestrator.gates import (
    GateResult,
    GateCostEstimate,
    GateInputPreflight,
    GatePostResearchRisk,
    GateResearchCache,
    GateSourceQuality,
    GateCreativeMemory,
    GateScriptValidation,
    GateAudioValidation,
    GateAssetValidation,
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


_COMPOSER_FAILED = "Composer failed"
_PACKAGING_FAILED = "Packaging failed"
_VOICE_GEN_FAILED = "Voice generation failed"
_ASSET_SOURCING_FAILED = "Asset sourcing failed"
_SCRIPT_BUDGET_FAILED = "Scriptwriter duration budget exceeded"


class Orchestrator:
    """Coordinates the full gated agent pipeline: Topic → Output Package."""

    def __init__(self, db_path: str = "data/clipper.db") -> None:
        self.db_path = db_path
        conn = get_connection(db_path)
        initialize_schema(conn)

    def _record_gate(self, assets_cache: str, job_id: int,
                     gate_name: str, result: GateResult) -> str:
        """Persist a gate result to the job workspace."""
        path = gate_result_file(assets_cache, job_id, gate_name)
        write_json(path, asdict(result))
        update_manifest_gate(assets_cache, job_id, gate_name,
                            result.passed, result.severity, path)
        return path

    def _complete_agent(self, conn, assets_cache: str, job_id: int,
                        agent_name: str) -> None:
        """Mark agent completed in DB and manifest."""
        mark_agent_completed(conn, job_id, agent_name)
        update_manifest_agent(assets_cache, job_id, agent_name, "completed")

    def _fail_agent(
        self, conn: Any, job_id: int, agent_name: str,
        output: dict[str, Any], default_reason: str,
    ) -> dict[str, Any]:
        """Mark agent failed, update job, return failure dict."""
        error = output.get("error", default_reason)
        logger.error("%s FAILED: %s",
                     agent_name.replace("_", " ").title(),
                     _sanitize_for_log(error))
        mark_agent_failed(conn, job_id, agent_name, error)
        update_job_status(conn, job_id, "FAILED", error)
        return {
            "status": "failed",
            "failed_at": agent_name,
            "reason": error,
            "job_id": job_id,
        }

    def _enforce_gate(self, conn, job_id: int, gate_name: str,
                      result: GateResult,
                      failed_at: str = "") -> dict[str, Any] | None:
        """Return a failure response dict if gate hard-failed, or None."""
        if not result.passed and result.severity == "hard_fail":
            logger.error("%s FAILED (hard): %s", gate_name, result.message)
            update_job_status(conn, job_id, "FAILED", result.message)
            return {
                "status": "failed",
                "failed_at": failed_at,
                "reason": result.message,
                "job_id": job_id,
            }
        return None

    def _stage_safety(
        self, conn: Any, topic: str, niche: str,
        assets_cache: str, output_dir: str,
        config_snapshot: dict | None = None,
    ) -> tuple[int, dict[str, Any]] | dict[str, Any]:
        """Run G1 preflight, create job, G2 cost, safety agent.

        Returns (job_id, cost_result) on success or a failure dict.
        """
        snapshot = config_snapshot or {}

        # G1: Input Preflight
        g1 = GateInputPreflight()
        g1_result = g1.evaluate(topic=topic, niche_config={"name": niche})
        self._record_gate(assets_cache, 0, "G1_input_preflight", g1_result)
        if not g1_result.passed:
            logger.error("G1 Preflight FAILED: %s", g1_result.message)
            update_job_status(conn, 0, "FAILED", g1_result.message)
            return {"status": "failed", "failed_at": "preflight",
                    "reason": g1_result.message, "job_id": 0}

        # Create job in DB with config snapshot
        job_id = create_job(conn, topic=topic, niche=niche,
                            config_snapshot=snapshot)
        logger.info("Job #%d created", job_id)
        add_job_file_handler(job_id)
        create_manifest(assets_cache, job_id, topic,
                        output_dir if output_dir else "outputs",
                        config_snapshot=snapshot)
        agent_names = [
            "safety", "segment_producer", "scriptwriter",
            "voice_producer", "visual_director", "composer", "reviewer",
        ]
        for name in agent_names:
            create_agent_state(conn, job_id, name)

        # G2: Cost Estimate
        g2 = GateCostEstimate()
        cost_result = g2.evaluate()
        self._record_gate(assets_cache, job_id, "G2_cost_estimate", cost_result)

        # Safety Agent
        logger.info("G2: running Safety agent")
        mark_agent_running(conn, job_id, "safety")
        safety_result = self._run_safety(
            job_id=job_id, topic=topic, assets_cache=assets_cache,
        )
        if safety_result.get("status") == "hard_fail":
            logger.error("Safety FAILED: %s", safety_result.get("reason"))
            mark_agent_failed(conn, job_id, "safety", safety_result["reason"])
            update_job_status(conn, job_id, "FAILED", safety_result["reason"])
            return {
                "status": "failed", "failed_at": "safety",
                "reason": safety_result["reason"], "job_id": job_id,
            }
        self._complete_agent(conn, assets_cache, job_id, "safety")
        return job_id, cost_result

    def _stage_research(
        self, conn: Any, job_id: int, topic: str,
        safety_rules: list[str], channel_description: str,
        language: str, tone: str, content_angle: str,
        assets_cache: str, output_dir: str,
    ) -> dict[str, Any]:
        """Run G3→SegmentProducer→G4→G5.

        Returns research_output dict on success or a failure dict.
        """
        g3 = GateResearchCache()
        self._record_gate(assets_cache, job_id, "G3_research_cache", g3.evaluate())

        logger.info("G3: running Segment Producer agent")
        mark_agent_running(conn, job_id, "segment_producer")
        research_output = self._run_researcher(
            job_id=job_id, topic=topic, safety_rules=safety_rules,
            channel_description=channel_description,
            language=language, tone=tone, content_angle=content_angle,
            output_dir=output_dir, assets_cache=assets_cache,
        )
        self._complete_agent(conn, assets_cache, job_id, "segment_producer")

        # Format Validator: validate content_direction from Segment Producer
        cp_config = load_settings().content_planning
        if cp_config:
            validated = validate_content_direction(
                research_output.get("content_direction"), cp_config,
            )
            research_output["validated_direction"] = validated
            logger.info("Format validator: format=%s stories=%d fallback=%s",
                        validated.format, validated.story_count,
                        validated.fallback)

        g4 = GatePostResearchRisk()
        g4_result = g4.evaluate(
            risk_flags=research_output.get("risk_flags", []),
        )
        self._record_gate(assets_cache, job_id, "G4_post_research_risk", g4_result)
        if not g4_result.passed and g4_result.severity == "hard_fail":
            update_job_status(conn, job_id, "FAILED", g4_result.message)
            return {
                "status": "failed", "failed_at": "post_research_risk",
                "reason": g4_result.message, "job_id": job_id,
            }

        g5 = GateSourceQuality()
        g5_result = g5.evaluate(
            video_sources=research_output.get("sources", []),
        )
        self._record_gate(assets_cache, job_id, "G5_source_quality", g5_result)
        if abort := self._enforce_gate(conn, job_id, "G5", g5_result,
                                        failed_at="source_quality"):
            return abort

        return research_output

    def _stage_content(
        self, conn: Any, job_id: int, topic: str,
        safety_rules: list[str], channel_description: str,
        language: str, tone: str, content_angle: str,
        research_output: dict[str, Any],
        assets_cache: str, output_dir: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | dict[str, Any]:
        """Run G6→Scriptwriter→G7→Voice→G8.

        Returns (script_output, voice_output) on success
        or a failure dict.
        """
        script_output = self._run_content_scriptwriter(
            conn, job_id, topic, safety_rules, channel_description,
            language, tone, content_angle,
            research_output, assets_cache,
        )
        if script_output.get("status") == "failed":
            return self._fail_agent(conn, job_id, "scriptwriter",
                                    script_output,
                                    "Scriptwriter duration exceeded")

        logger.info("G7: running Voice Producer agent")
        mark_agent_running(conn, job_id, "voice_producer")
        voice_output = self._run_voice_producer(
            job_id=job_id,
            script=script_output.get("script", []),
            voiceover_text=script_output.get("voiceover_text", ""),
            output_dir=output_dir, assets_cache=assets_cache,
        )
        if voice_output.get("status") == "failed":
            return self._fail_agent(conn, job_id, "voice_producer",
                                    voice_output, _VOICE_GEN_FAILED)
        self._complete_agent(conn, assets_cache, job_id, "voice_producer")

        g8 = GateAudioValidation()
        g8_result = g8.evaluate(
            audio_path=voice_output.get("voiceover_path"))
        self._record_gate(assets_cache, job_id, "G8_audio_validation", g8_result)
        if abort := self._enforce_gate(conn, job_id, "G8", g8_result,
                                        failed_at="audio_validation"):
            return abort

        return script_output, voice_output

    def _stage_composition(
        self, conn: Any, job_id: int, topic: str,
        research_output: dict[str, Any],
        script_output: dict[str, Any], voice_output: dict[str, Any],
        assets_cache: str, output_dir: str,
    ) -> dict[str, Any]:
        """Run Visual→G9→Composer→G10.

        Returns compose_output dict on success or a failure dict.
        """
        logger.info("G8: running Visual Director agent")
        visual_output = self._run_visual_director_phase(
            conn, job_id, topic, research_output, script_output,
            output_dir, assets_cache,
            voice_output=voice_output,
        )

        if visual_output.get("status") == "failed":
            return self._fail_agent(conn, job_id, "visual_director",
                                    visual_output, _ASSET_SOURCING_FAILED)

        g9 = GateAssetValidation()
        visual_assets = visual_output.get("assets", [])
        asset_paths = [a.get("path", "") for a in visual_assets]
        g9_result = g9.evaluate(asset_paths=asset_paths, assets=visual_assets)
        self._record_gate(assets_cache, job_id, "G9_asset_validation", g9_result)
        if abort := self._enforce_gate(conn, job_id, "G9", g9_result,
                                        failed_at="asset_validation"):
            return abort

        logger.info("G9: running Composer agent")
        mark_agent_running(conn, job_id, "composer")
        compose_output = self._run_composer(
            job_id=job_id, assets=visual_output.get("assets", []),
            audio_files=voice_output.get("audio_files", []),
            script_scenes=script_output.get("script", []),
            output_dir=output_dir, assets_cache=assets_cache,
            voiceover_path=voice_output.get("voiceover_path", ""),
            timestamps=voice_output.get("timestamps", []),
            narrative_structure=script_output.get("narrative_structure", []),
        )

        if compose_output.get("status") == "failed":
            return self._fail_agent(conn, job_id, "composer",
                                    compose_output, _COMPOSER_FAILED)
        self._complete_agent(conn, assets_cache, job_id, "composer")

        cp_config = load_settings().content_planning
        hard_limit = cp_config.hard_limit_sec if cp_config else 60
        g10 = GateVideoValidation()
        g10_result = g10.evaluate(video_path=compose_output.get("video_path"),
                                  hard_limit_sec=hard_limit)
        self._record_gate(assets_cache, job_id, "G10_video_validation", g10_result)
        if abort := self._enforce_gate(conn, job_id, "G10", g10_result,
                                        failed_at="video_validation"):
            return abort

        return compose_output

    def run_pipeline(
        self,
        topic: str,
        niche: str = "indonesian_artists",
        output_dir: str = "outputs",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the full topic-to-output pipeline.

        Gate sequence: G1→G2→Safety→G3→Researcher→G4→G5→G6→
                       Scriptwriter→G7→Voice→G8→Visual→G9→
                       Composer→G10→Reviewer→Package
        """
        conn = get_connection(self.db_path)
        settings = load_settings()
        assets_cache = str(kwargs.get("assets_cache") or settings.assets_cache)
        logger.info("Pipeline START: niche='%s'", niche)

        # Load niche configuration — single source of truth
        try:
            niche_config = load_niche(niche)
        except FileNotFoundError:
            logger.error("Niche config not found: %r — aborting pipeline", niche)
            return {"status": "failed",
                    "reason": f"Niche config {niche!r} not found"}
        safety_rules = niche_config.safety_rules
        channel_description = build_channel_description(niche_config)
        language_name = get_language_name(niche_config)
        tone_name = get_tone_name(niche_config)
        angle_name = get_angle_name(niche_config)

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
        stage1 = self._stage_safety(conn, topic, niche, assets_cache,
                                     output_dir, config_snapshot=config_snapshot)
        if isinstance(stage1, dict):
            return stage1
        job_id, cost_result = stage1

        try:
            # Stage 2: Research (G3→G5)
            research_output = self._stage_research(
                conn, job_id, topic, safety_rules, channel_description,
                language_name, tone_name, angle_name,
                assets_cache, output_dir,
            )
            if isinstance(research_output, dict) and research_output.get("status") == "failed":
                return research_output

            # Stage 3: Content creation (G6→G8)
            stage3 = self._stage_content(
                conn, job_id, topic, safety_rules, channel_description,
                language_name, tone_name, angle_name,
                research_output, assets_cache, output_dir,
            )
            if isinstance(stage3, dict) and stage3.get("status") == "failed":
                return stage3
            script_output, voice_output = stage3

            # Stage 4: Composition (Visual→G10)
            compose_output = self._stage_composition(
                conn, job_id, topic, research_output,
                script_output, voice_output,
                assets_cache, output_dir,
            )
            if isinstance(compose_output, dict) and compose_output.get("status") == "failed":
                return compose_output

            # Stage 5: Review + Package
            logger.info("G10: running Reviewer agent")
            abort, review_output, pkg_output = self._retry_review_and_package(
                conn, job_id, topic, script_output, compose_output,
                safety_rules, niche, output_dir, assets_cache,
                voice_output=voice_output,
            )
            if abort:
                return abort

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

    def _load_agent_output(self, assets_cache: str, job_id: int,
                           agent_name: str) -> dict[str, Any]:
        """Load a completed agent's output.json from the artifact workspace."""
        from clipper_agency.core.paths import agent_output_file
        from clipper_agency.core.artifacts import read_json
        path = agent_output_file(assets_cache, job_id, agent_name)
        try:
            return read_json(path)
        except (FileNotFoundError, ValueError):
            return {}

    def _try_load_cached(
        self, assets_cache: str, job_id: int, agent_name: str,
    ) -> dict[str, Any]:
        """Validate cached artifacts and return output.json if valid.

        Returns an empty dict when cache is invalid so the caller can
        fall through to re-running the agent.
        """
        vr = validate_agent_cache(assets_cache, job_id, agent_name)
        if not vr.passed:
            logger.info("Cache invalid for %s job #%d: %s",
                        agent_name, job_id, "; ".join(vr.issues))
            return {}
        return self._load_agent_output(assets_cache, job_id, agent_name)

    def _run_cached_or_fresh(
        self, agent_name: str, use_cache: bool, assets_cache: str,
        job_id: int, run_fn,
    ) -> dict[str, Any]:
        """Try cached output when use_cache is True; fall back to fresh run."""
        if not use_cache:
            return run_fn()
        cached = self._try_load_cached(assets_cache, job_id, agent_name)
        if cached:
            return cached
        return run_fn()

    def _run_visual_director_phase(
        self, conn: Any, job_id: int, topic: str,
        research_output: dict[str, Any], script_output: dict[str, Any],
        output_dir: str, assets_cache: str,
        voice_output: dict[str, Any] | None = None,
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

        visual_output = self._run_visual_director(
            job_id=job_id, script=script_output.get("script", []),
            topic=topic,
            output_dir=output_dir, assets_cache=assets_cache,
            research_contract_path=research_contract_path,
            research_brief_path=research_brief_path,
            story_beats=research_output.get("story_beats", []),
            timestamps=vo.get("timestamps", []),
            do_not_use=research_output.get("do_not_use", []),
            asset_candidates=research_output.get("asset_candidates", []),
            voiceover_duration_sec=vo.get("voiceover_duration_sec", 0.0),
        )
        if visual_output.get("status") != "failed":
            self._complete_agent(conn, assets_cache, job_id, "visual_director")
        return visual_output

    def _retry_composer_stage(
        self, conn, job_id: int, visual_output: dict[str, Any],
        voice_output: dict[str, Any], output_dir: str, assets_cache: str,
    ) -> tuple[dict[str, Any], dict | None]:
        """Run composer with error handling and G10 gate enforcement.

        Returns (compose_output, abort_response). If abort_response is not
        None, it should be returned immediately from run_pipeline_from.
        """
        mark_agent_running(conn, job_id, "composer")
        # Load script scenes from completed scriptwriter for subtitles
        script_output = self._load_agent_output(assets_cache, job_id, "scriptwriter")

        compose_output = self._run_composer(
            job_id=job_id,
            assets=visual_output.get("assets", []),
            audio_files=voice_output.get("audio_files", []),
            output_dir=output_dir, assets_cache=assets_cache,
            script_scenes=script_output.get("script", []),
            voiceover_path=voice_output.get("voiceover_path", ""),
            timestamps=voice_output.get("timestamps", []),
            narrative_structure=script_output.get("narrative_structure", []),
        )

        if compose_output.get("status") == "failed":
            return compose_output, self._fail_agent(
                conn, job_id, "composer", compose_output, _COMPOSER_FAILED)
        self._complete_agent(conn, assets_cache, job_id, "composer")

        cp_config = load_settings().content_planning
        hard_limit = cp_config.hard_limit_sec if cp_config else 60
        g10 = GateVideoValidation()
        g10_result = g10.evaluate(
            video_path=compose_output.get("video_path"),
            hard_limit_sec=hard_limit,
        )
        self._record_gate(assets_cache, job_id,
                          "G10_video_validation", g10_result)
        abort = self._enforce_gate(
            conn, job_id, "G10", g10_result,
            failed_at="video_validation",
        )
        return compose_output, abort

    def _retry_review_and_package(
        self, conn, job_id: int, topic: str,
        script_output: dict[str, Any], compose_output: dict[str, Any],
        safety_rules: list[str], niche: str,
        output_dir: str, assets_cache: str,
        voice_output: dict[str, Any] | None = None,
    ) -> tuple[dict | None, dict | None, dict | None]:
        """Run review and packaging stages. Returns (abort, review_output, pkg_output)."""
        vo = voice_output or {}
        mark_agent_running(conn, job_id, "reviewer")
        review_output = self._run_reviewer(
            job_id=job_id, topic=topic,
            script=script_output.get("script", []),
            caption=script_output.get("caption", ""),
            safety_rules=safety_rules,
            audio_duration_sec=vo.get("voiceover_duration_sec", 0.0),
            visual_duration_sec=compose_output.get("duration_sec", 0.0),
            narrative_structure=script_output.get("narrative_structure", []),
            unverified_claims=script_output.get("unverified_claims", []),
        )
        self._complete_agent(conn, assets_cache, job_id, "reviewer")

        pkg_output = self._package_output(
            job_id=job_id,
            video_path=compose_output.get("video_path", ""),
            caption=script_output.get("caption", ""),
            topic=topic, niche=niche, output_dir=output_dir,
            template_name=compose_output.get("template_name"),
        )

        if pkg_output.get("status") == "failed":
            update_job_status(conn, job_id, "FAILED",
                              pkg_output.get("error", _PACKAGING_FAILED))
            return {
                "status": "failed", "failed_at": "packaging",
                "reason": pkg_output.get("error", _PACKAGING_FAILED),
                "job_id": job_id,
            }, review_output, pkg_output

        update_manifest_final(assets_cache, job_id, {
            "video": pkg_output.get("video_path", ""),
            "caption": pkg_output.get("caption_path", ""),
            "thumbnail": pkg_output.get("thumbnail_path", ""),
            "metadata": pkg_output.get("metadata_path", ""),
        })
        return None, review_output, pkg_output

    def _reconstruct_upstream_outputs(
        self, from_idx: int, assets_cache: str, job_id: int,
    ) -> tuple[dict[str, Any], dict[str, Any],
               dict[str, Any], dict[str, Any]]:
        """Load completed upstream agent outputs."""
        loader = self._load_agent_output
        research = loader(assets_cache, job_id, "segment_producer") \
            if from_idx > PIPELINE_ORDER.index("segment_producer") else {}
        script = loader(assets_cache, job_id, "scriptwriter") \
            if from_idx > PIPELINE_ORDER.index("scriptwriter") else {}
        voice = loader(assets_cache, job_id, "voice_producer") \
            if from_idx > PIPELINE_ORDER.index("voice_producer") else {}
        visual = loader(assets_cache, job_id, "visual_director") \
            if from_idx > PIPELINE_ORDER.index("visual_director") else {}
        return research, script, voice, visual

    def _retry_safety_stage(
        self, conn: Any, job_id: int, topic: str,
        assets_cache: str, from_idx: int,
    ) -> dict | None:
        """Run safety if needed during retry. Returns abort on hard_fail."""
        if from_idx > PIPELINE_ORDER.index("safety"):
            return None
        mark_agent_running(conn, job_id, "safety")
        safety_result = self._run_safety(
            job_id=job_id, topic=topic, assets_cache=assets_cache,
        )
        if safety_result.get("status") == "hard_fail":
            reason = safety_result.get("reason", "Safety failed")
            mark_agent_failed(conn, job_id, "safety", reason)
            update_job_status(conn, job_id, "FAILED", reason)
            return {
                "status": "failed", "failed_at": "safety",
                "reason": reason, "job_id": job_id,
            }
        self._complete_agent(conn, assets_cache, job_id, "safety")
        return None

    def _retry_research_stage(
        self, conn: Any, job_id: int, topic: str,
        safety_rules: list[str], channel_description: str,
        language: str, tone: str, content_angle: str,
        assets_cache: str, output_dir: str, from_idx: int,
    ) -> tuple[dict[str, Any] | None, dict | None]:
        """Run research if needed. Returns (research_output, abort)."""
        if from_idx > PIPELINE_ORDER.index("segment_producer"):
            return None, None
        research_result = self._stage_research(
            conn, job_id, topic, safety_rules, channel_description,
            language, tone, content_angle,
            assets_cache, output_dir,
        )
        if isinstance(research_result, dict) and research_result.get(
            "status",
        ) == "failed":
            return {}, research_result
        return research_result, None

    def _retry_downstream_stages(
        self, conn: Any, job_id: int, topic: str,
        niche_ctx: dict[str, Any],
        niche: str, output_dir: str, assets_cache: str,
        from_idx: int, use_cache: bool,
        research_output: dict[str, Any], script_output: dict[str, Any],
        voice_output: dict[str, Any], visual_output: dict[str, Any],
    ) -> dict | None:
        """Run retry stages after research. Returns abort on failure."""
        safety_rules = niche_ctx["safety_rules"]
        channel_description = niche_ctx["channel_description"]
        language = niche_ctx["language"]
        tone = niche_ctx["tone"]
        content_angle = niche_ctx["content_angle"]
        if from_idx <= PIPELINE_ORDER.index("scriptwriter"):
            script_output = self._run_cached_or_fresh(
                "scriptwriter", use_cache, assets_cache, job_id,
                lambda: self._run_content_scriptwriter(
                    conn, job_id, topic, safety_rules,
                    channel_description, language, tone, content_angle,
                    research_output, assets_cache,
                ),
            )
            if script_output.get("status") == "failed":
                return self._fail_agent(conn, job_id, "scriptwriter",
                                        script_output, _SCRIPT_BUDGET_FAILED)

        if from_idx <= PIPELINE_ORDER.index("voice_producer"):
            voice_output = self._run_cached_or_fresh(
                "voice_producer", use_cache, assets_cache, job_id,
                lambda: self._run_content_voice(
                    conn, job_id, script_output,
                    output_dir, assets_cache,
                ),
            )

        if from_idx <= PIPELINE_ORDER.index("visual_director"):
            visual_output = self._run_visual_director_phase(
                conn, job_id, topic, research_output, script_output,
                output_dir, assets_cache,
                voice_output=voice_output,
            )
            if visual_output.get("status") == "failed":
                return self._fail_agent(conn, job_id, "visual_director",
                                        visual_output, _ASSET_SOURCING_FAILED)

        if from_idx <= PIPELINE_ORDER.index("composer"):
            compose_output, abort = self._retry_composer_stage(
                conn, job_id, visual_output, voice_output,
                output_dir, assets_cache,
            )
            if abort:
                return abort
        else:
            compose_output = self._load_agent_output(
                assets_cache, job_id, "composer")

        if from_idx <= PIPELINE_ORDER.index("reviewer"):
            abort, _, _ = self._retry_review_and_package(
                conn, job_id, topic, script_output, compose_output,
                safety_rules, niche, output_dir, assets_cache,
                voice_output=voice_output,
            )
            if abort:
                return abort
        return None

    def run_pipeline_from(
        self, job_id: int, from_agent: str, use_cache: bool = False,
    ) -> dict[str, Any]:
        """Re-run pipeline from a specific agent, reusing completed outputs.

        Reconstructs intermediate data from persisted agent output.json files
        and skips agents that completed before ``from_agent``.
        """
        conn = get_connection(self.db_path)
        job = get_job(conn, job_id)
        if not job:
            return {"status": "failed", "reason": f"Job {job_id} not found",
                    "job_id": job_id}

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
        append_audit_log(conn, action="pipeline_retry", actor="engine",
                         resource_type="job", resource_id=job_id,
                         details=json.dumps({"from_agent": from_agent,
                                              "use_cache": use_cache}))

        if from_agent not in PIPELINE_ORDER:
            update_job_status(conn, job_id, "FAILED",
                               f"Unknown agent: {from_agent}")
            return {"status": "failed", "reason": f"Unknown agent: {from_agent}",
                    "job_id": job_id}

        from_idx = PIPELINE_ORDER.index(from_agent)
        (research_output, script_output,
         voice_output, visual_output) = self._reconstruct_upstream_outputs(
            from_idx, assets_cache, job_id,
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
                    "Niche config not found: %r — aborting retry", niche,
                )
                return {"status": "failed",
                        "reason": f"Niche config {niche!r} not found"}
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
                conn, job_id, topic, assets_cache, from_idx,
            )
            if abort:
                return abort

            # Stage: Research (segment_producer + gates G3-G5)
            fresh, abort = self._retry_research_stage(
                conn, job_id, topic, safety_rules, channel_description,
                language_name, tone_name, angle_name,
                assets_cache, output_dir, from_idx,
            )
            if abort:
                return abort
            if fresh is not None:
                research_output = fresh

            abort = self._retry_downstream_stages(
                conn, job_id, topic, niche_ctx,
                niche, output_dir, assets_cache, from_idx, use_cache,
                research_output, script_output, voice_output, visual_output,
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
        self, conn: Any, job_id: int, topic: str,
        safety_rules: list[str], channel_description: str,
        language: str, tone: str, content_angle: str,
        research_output: dict[str, Any],
        assets_cache: str,
    ) -> dict[str, Any]:
        """Run scriptwriter stage of content creation."""
        g6 = GateCreativeMemory()
        self._record_gate(assets_cache, job_id, "G6_creative_memory",
                          g6.evaluate())

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
            job_id=job_id, topic=topic,
            research_brief=research_output.get("research_brief", ""),
            safety_rules=safety_rules,
            channel_description=channel_description,
            language=language, tone=tone, content_angle=resolved_angle,
            assets_cache=assets_cache,
            blueprint=blueprint if blueprint else None,
        )
        self._complete_agent(conn, assets_cache, job_id, "scriptwriter")

        g7 = GateScriptValidation()
        script_scenes = script_output.get("script", [])
        script_text = " ".join(
            s.get("text", "") for s in script_scenes
        ) if isinstance(script_scenes, list) else str(script_scenes)
        g7_result = g7.evaluate(
            script=script_text,
            caption=script_output.get("caption", ""),
        )
        self._record_gate(assets_cache, job_id, "G7_script_validation",
                          g7_result)

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
            logger.info("Duration gate: estimated=%.1fs %s",
                        estimated, budget_check["reason"])
            if not budget_check["pass"]:
                reason = (
                    f"Script duration {estimated:.1f}s exceeds "
                    f"hard limit {budget.hard}s"
                )
                mark_agent_failed(conn, job_id, "scriptwriter", reason)
                update_job_status(conn, job_id, "FAILED", reason)
                script_output["status"] = "failed"
                script_output["error"] = reason

        return script_output

    def _run_content_voice(
        self, conn: Any, job_id: int,
        script_output: dict[str, Any],
        output_dir: str, assets_cache: str,
    ) -> dict[str, Any]:
        """Run voice producer stage of content creation."""
        mark_agent_running(conn, job_id, "voice_producer")
        voice_output = self._run_voice_producer(
            job_id=job_id,
            script=script_output.get("script", []),
            voiceover_text=script_output.get("voiceover_text", ""),
            output_dir=output_dir, assets_cache=assets_cache,
        )
        self._complete_agent(conn, assets_cache, job_id, "voice_producer")

        g8 = GateAudioValidation()
        g8_result = g8.evaluate(
            audio_path=voice_output.get("voiceover_path"))
        self._record_gate(assets_cache, job_id, "G8_audio_validation",
                          g8_result)
        return voice_output

    # ── Agent runner methods (extracted for testability) ──

    def _run_safety(self, job_id: int, topic: str,
                    **kwargs: Any) -> dict[str, Any]:
        agent = SafetyAgent()
        return agent.execute(job_id=job_id, topic=topic, **kwargs)

    def _run_researcher(self, job_id: int, topic: str,
                        safety_rules: list[str] | None = None,
                        output_dir: str = "outputs",
                        **kwargs: Any) -> dict[str, Any]:
        agent = SegmentProducerAgent()
        return agent.execute(job_id=job_id, topic=topic,
                             safety_rules=safety_rules or [],
                             output_dir=output_dir, **kwargs)

    def _run_scriptwriter(self, job_id: int, topic: str,
                          research_brief: str = "",
                          safety_rules: list[str] | None = None,
                          **kwargs: Any) -> dict[str, Any]:
        agent = ScriptwriterAgent()
        return agent.execute(
            job_id=job_id, topic=topic,
            research_brief=research_brief,
            safety_rules=safety_rules or [],
            **kwargs,
        )

    def _run_voice_producer(self, job_id: int,
                            script: list[dict] | None = None,
                            output_dir: str = "outputs",
                            **kwargs: Any) -> dict[str, Any]:
        agent = VoiceProducerAgent()
        return agent.execute(
            job_id=job_id, script=script or [],
            output_dir=output_dir,
            **kwargs,
        )

    def _run_visual_director(self, job_id: int,
                             script: list[dict] | None = None,
                             topic: str = "",
                             source_urls: list[str] | None = None,
                             output_dir: str = "outputs",
                             **kwargs: Any) -> dict[str, Any]:
        agent = VisualDirectorAgent()
        return agent.execute(
            job_id=job_id, script=script or [],
            topic=topic,
            source_urls=source_urls or [],
            output_dir=output_dir,
            **kwargs,
        )

    def _run_composer(self, job_id: int,
                      assets: list[dict] | None = None,
                      audio_files: list[str] | None = None,
                      output_dir: str = "outputs",
                      **kwargs: Any) -> dict[str, Any]:
        agent = ComposerAgent()
        return agent.execute(
            job_id=job_id, assets=assets or [],
            audio_files=audio_files or [],
            output_dir=output_dir,
            **kwargs,
        )

    def _run_reviewer(self, job_id: int, topic: str,
                      script: list[dict] | None = None,
                      caption: str = "",
                      safety_rules: list[str] | None = None,
                      **kwargs: Any) -> dict[str, Any]:
        agent = ReviewerAgent()
        return agent.execute(
            job_id=job_id, topic=topic,
            script=script or [],
            caption=caption,
            safety_rules=safety_rules or [],
            **kwargs,
        )

    def _package_output(self, job_id: int, video_path: str,
                        caption: str,
                        topic: str, niche: str,
                        output_dir: str = "outputs",
                        **kwargs: Any) -> dict[str, Any]:
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
