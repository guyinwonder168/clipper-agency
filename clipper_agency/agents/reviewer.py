"""Reviewer Agent — final content quality and safety review via LLM."""

import json
import logging
from typing import Any, TypedDict

from clipper_agency.agents.base import BaseAgent
from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
from clipper_agency.config.loader import get_agent_config
from clipper_agency.core.package_consistency import evaluate_package_consistency
from clipper_agency.llm.client import OpenRouterClient

logger = logging.getLogger(__name__)

_MAX_CAPTION_LEN = 150
_AV_DRIFT_TOLERANCE_SEC = 0.5

_FAIL_REASON_VISUAL_COVERAGE = "VISUAL_COVERAGE_FAILED"
_FAIL_REASON_TEXT_COLLISION = "TEXT_COLLISION_FAILED"
_FAIL_REASON_SAFE_AREA = "SAFE_AREA_FAILED"
_FAIL_REASON_PACKAGE_CONSISTENCY = "PACKAGE_CONSISTENCY_FAILED"
_FAIL_REASON_SEMANTIC_REVIEW = "SEMANTIC_REVIEW_FAILED"

REVIEWER_PROMPT = """You are a content quality reviewer for a TikTok creator channel
producing short-form infotainment videos with voiceover narration.

Review the provided content for:

1. **Voiceover Quality**: Natural spoken-word style, engaging pacing, clear delivery
2. **Visual-Audio Alignment**: Visuals match what's being said (no disconnect)
3. **Caption Effectiveness**: Compelling, TikTok-optimized caption with hashtags
4. **Safety Compliance**: No illegal, defamatory, or harmful content
5. **Fact Safety**: Unverified claims use appropriate hedging language

Safety rules to enforce:
{safety_rules_text}

Programmatic checks already passed:
{programmatic_results}

Return a JSON verdict:
{{
  "verdict": "pass" or "fail",
  "score": 0-100,
  "feedback": "Detailed feedback",
  "issues": ["list", "of", "issues", "if any"]
}}
"""

_CHECK_PASS = "pass"
_CHECK_FAIL = "fail"
_CHECK_SKIP = "skip"
_CHECK_WARN = "warn"


def _check_av_sync(audio_duration: float, visual_duration: float) -> dict[str, Any]:
    """Verify audio and visual durations are within tolerance."""
    if audio_duration == 0 or visual_duration == 0:
        return {"check": "av_sync", "status": _CHECK_SKIP, "detail": "Missing duration data"}
    drift = abs(audio_duration - visual_duration)
    if drift > _AV_DRIFT_TOLERANCE_SEC:
        return {
            "check": "av_sync",
            "status": _CHECK_FAIL,
            "detail": f"Drift {drift:.2f}s exceeds {_AV_DRIFT_TOLERANCE_SEC}s",
            "audio_sec": audio_duration,
            "visual_sec": visual_duration,
        }
    return {"check": "av_sync", "status": _CHECK_PASS, "drift_sec": round(drift, 2)}


def _check_caption_quality(caption: str) -> dict[str, Any]:
    """Verify caption follows TikTok best practices."""
    issues: list[str] = []
    if not caption.strip():
        return {"check": "caption_quality", "status": _CHECK_FAIL, "detail": "Caption is empty"}
    if len(caption) > _MAX_CAPTION_LEN:
        issues.append(f"Caption length {len(caption)} exceeds {_MAX_CAPTION_LEN}")
    if "#" not in caption:
        issues.append("No hashtag found")
    if issues:
        return {"check": "caption_quality", "status": _CHECK_WARN, "issues": issues}
    return {"check": "caption_quality", "status": _CHECK_PASS}


def _check_fact_safety(unverified_claims: list[dict]) -> dict[str, Any]:
    """Verify unverified claims use safe wording."""
    if not unverified_claims:
        return {"check": "fact_safety", "status": _CHECK_PASS, "detail": "No unverified claims"}
    missing = [
        f"Claim {i}" for i, c in enumerate(unverified_claims) if "safe_wording" not in c
    ]
    if missing:
        return {
            "check": "fact_safety",
            "status": _CHECK_WARN,
            "detail": f"Missing safe_wording: {', '.join(missing)}",
        }
    return {"check": "fact_safety", "status": _CHECK_PASS}


def _check_narrative_structure(
    narrative: list[dict],
) -> dict[str, Any]:
    """Verify narrative beats have required fields."""
    if not narrative:
        return {"check": "narrative_structure", "status": _CHECK_SKIP, "detail": "No narrative"}
    required = {"beat_id", "section", "word_range"}
    for i, beat in enumerate(narrative):
        missing = required - beat.keys()
        if missing:
            return {
                "check": "narrative_structure",
                "status": _CHECK_WARN,
                "detail": f"Beat {i} missing fields: {', '.join(sorted(missing))}",
            }
    return {"check": "narrative_structure", "status": _CHECK_PASS, "beats": len(narrative)}


def _format_script_text(script: list[dict] | None) -> str:
    """Build readable script text from scene list."""
    return "\n".join(
        f"Scene {s.get('scene', i)}: {s.get('text', '')}"
        for i, s in enumerate(script or [])
    )


def _format_programmatic_results(results: list[dict[str, Any]]) -> str:
    """Format programmatic check results for prompt inclusion."""
    lines = [f"- {r['check']}: {r['status']}" for r in results]
    return "\n".join(lines)


def _format_safety_rules(rules: list[str]) -> str:
    """Format safety rules for prompt inclusion."""
    return "\n".join(f"- {r}" for r in rules) if rules else "None"


class ReviewContext(TypedDict, total=False):
    """Bundled audio-first / quality-gate parameters for ReviewerAgent.execute()."""

    audio_duration_sec: float
    visual_duration_sec: float
    narrative_structure: list[dict]
    unverified_claims: list[dict]
    visual_plan_actions: list[dict]
    story_mode_decision: dict
    thumbnail_text: str
    main_entities: list[str]


class ReviewerAgent(BaseAgent):
    """Reviews final content for quality, safety, and originality."""

    @property
    def agent_name(self) -> str:
        return "reviewer"

    # Expose pure functions as static methods for testability
    _check_av_sync = staticmethod(_check_av_sync)
    _check_caption_quality = staticmethod(_check_caption_quality)
    _check_fact_safety = staticmethod(_check_fact_safety)
    _check_narrative_structure = staticmethod(_check_narrative_structure)

    def _check_hard_gates(
        self,
        checks: dict[str, Any],
        audio_duration_sec: float,
        visual_duration_sec: float,
        visual_plan_actions: list[dict] | None,
    ) -> dict[str, Any] | None:
        """Return a fail dict if any hard gate triggers, else None."""
        # Hard gate 1: AV drift where video is shorter than audio
        if checks["av_sync"]["status"] == _CHECK_FAIL:
            if visual_duration_sec < audio_duration_sec:
                return {
                    "status": "fail",
                    "score": 0,
                    "feedback": (
                        f"Hard gate: video ({visual_duration_sec}s) "
                        f"shorter than audio ({audio_duration_sec}s)"
                    ),
                    "issues": ["av_duration_mismatch"],
                    "programmatic_checks": checks,
                }

        # Hard gate 2: Broken tiktok_clip actions (missing source_url)
        if visual_plan_actions:
            for action in visual_plan_actions:
                if action.get("type") == "tiktok_clip" and not action.get("source_url"):
                    return {
                        "status": "fail",
                        "score": 0,
                        "feedback": "Hard gate: broken tiktok_clip action (missing source_url)",
                        "issues": ["broken_tiktok_clip_action"],
                        "programmatic_checks": checks,
                    }

        return None

    def _fail_if_visual_coverage_failed(self, diagnostics: dict | None) -> dict[str, Any] | None:
        """Return fail dict if visual coverage hard-failed, else None."""
        if not diagnostics:
            return None
        vc = diagnostics.get("visual_coverage")
        if not vc or vc.get("status") != "fail":
            return None
        hard_fails = [i for i in vc.get("issues", []) if isinstance(i, dict) and i.get("severity") == "hard_fail"]
        if hard_fails:
            return {
                "status": "fail",
                "reason": _FAIL_REASON_VISUAL_COVERAGE,
                "score": 0,
                "feedback": f"Hard gate: visual coverage failed ({len(hard_fails)} hard-fail issues)",
                "issues": ["visual_coverage_failed"],
                "programmatic_checks": {},
            }
        return None

    def _fail_if_text_collision_failed(self, diagnostics: dict | None) -> dict[str, Any] | None:
        """Return fail dict if text collision hard-failed, else None."""
        if not diagnostics:
            return None
        tc = diagnostics.get("text_collision")
        if not tc:
            return None
        hard_fails = [i for i in tc if isinstance(i, dict) and i.get("severity") == "hard_fail"]
        if hard_fails:
            return {
                "status": "fail",
                "reason": _FAIL_REASON_TEXT_COLLISION,
                "score": 0,
                "feedback": f"Hard gate: text collision detected ({len(hard_fails)} issues)",
                "issues": ["text_collision_failed"],
                "programmatic_checks": {},
            }
        return None

    def _fail_if_safe_area_failed(self, diagnostics: dict | None) -> dict[str, Any] | None:
        """Return fail dict if safe area hard-failed, else None."""
        if not diagnostics:
            return None
        sa = diagnostics.get("safe_area")
        if not sa:
            return None
        hard_fails = [i for i in sa if isinstance(i, dict) and i.get("severity") == "hard_fail"]
        if hard_fails:
            return {
                "status": "fail",
                "reason": _FAIL_REASON_SAFE_AREA,
                "score": 0,
                "feedback": f"Hard gate: safe area violation ({len(hard_fails)} issues)",
                "issues": ["safe_area_failed"],
                "programmatic_checks": {},
            }
        return None

    def _fail_if_package_consistency_failed(
        self,
        story_mode_decision: dict | None,
        thumbnail_text: str,
        main_entities: list[str],
        caption: str,
        topic: str,
        script: list[dict] | None,
    ) -> dict[str, Any] | None:
        """Return fail dict if package consistency check fails, else None."""
        if not story_mode_decision:
            return None
        result = evaluate_package_consistency(
            topic=topic,
            script=_format_script_text(script),
            thumbnail_text=thumbnail_text or "",
            caption=caption or "",
            story_mode=story_mode_decision.get("story_mode", ""),
            main_entities=main_entities or [],
        )
        if result.status == "fail":
            return {
                "status": "fail",
                "reason": _FAIL_REASON_PACKAGE_CONSISTENCY,
                "score": 0,
                "feedback": f"Hard gate: package consistency — {result.issue}: {result.detail}",
                "issues": ["package_consistency_failed"],
                "programmatic_checks": {},
            }
        return None

    def _fail_if_semantic_review_failed(self, diagnostics: dict | None) -> dict[str, Any] | None:
        """Return fail dict with repair_plan if semantic review reports revise/reject."""
        if not diagnostics:
            return None
        sr = diagnostics.get("semantic_review")
        if not sr:
            return None
        decision = sr.get("decision", "")
        if decision not in ("revise", "reject"):
            return None

        from clipper_agency.config.schema import RepairPatch, RepairPlan

        patches = sr.get("patches", [])
        repair_patches = [
            RepairPatch(
                beat_id=str(p.get("beat_id", "")),
                action=p.get("action", "replace_visual"),
                reason=p.get("reason", "semantic_mismatch"),
                rerun_from=p.get("rerun_from", "visual_director"),
                timestamp_start_sec=p.get("timestamp_start_sec", 0.0),
                timestamp_end_sec=p.get("timestamp_end_sec", 0.0),
                required_visual=p.get("required_visual", ""),
            )
            for p in patches
        ]

        plan = RepairPlan(
            decision=decision,
            max_repair_cycles=2,
            patches=repair_patches,
        )

        return {
            "status": "fail",
            "reason": _FAIL_REASON_SEMANTIC_REVIEW,
            "score": 0,
            "feedback": f"Semantic review: {decision} ({len(repair_patches)} patches)",
            "issues": ["semantic_review_failed"],
            "repair_plan": plan.model_dump(),
            "programmatic_checks": {},
        }

    def execute(
        self,
        job_id: int,
        topic: str = "",
        script: list[dict] | None = None,
        caption: str = "",
        safety_rules: list[str] | None = None,
        context: ReviewContext | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Merge context dict with legacy kwargs for backward compat
        ctx: dict[str, Any] = dict(context or {})
        _legacy_keys = (
            "audio_duration_sec", "visual_duration_sec", "narrative_structure",
            "unverified_claims", "visual_plan_actions", "story_mode_decision",
            "thumbnail_text", "main_entities",
        )
        for key in _legacy_keys:
            if key in kwargs and key not in ctx:
                ctx[key] = kwargs.pop(key)

        audio_duration_sec: float = ctx.get("audio_duration_sec", 0.0)
        visual_duration_sec: float = ctx.get("visual_duration_sec", 0.0)
        narrative_structure: list[dict] | None = ctx.get("narrative_structure")
        unverified_claims: list[dict] | None = ctx.get("unverified_claims")
        visual_plan_actions: list[dict] | None = ctx.get("visual_plan_actions")
        story_mode_decision: dict | None = ctx.get("story_mode_decision")
        thumbnail_text: str = ctx.get("thumbnail_text", "")
        main_entities: list[str] | None = ctx.get("main_entities")

        scenes = script or []
        logger.info("Reviewer: scenes=%d", len(scenes))

        # 1. Programmatic quality checks (fast, free, deterministic)
        av_sync = _check_av_sync(audio_duration_sec, visual_duration_sec)
        caption_q = _check_caption_quality(caption)
        fact_safety = _check_fact_safety(unverified_claims or [])
        narrative_q = _check_narrative_structure(
            narrative_structure or [],
        )
        programmatic_results = [av_sync, caption_q, fact_safety, narrative_q]

        checks = {
            "av_sync": av_sync,
            "caption_quality": caption_q,
            "fact_safety": fact_safety,
            "narrative_structure": narrative_q,
        }

        # 2. Hard gates: force FAIL before expensive LLM call
        hard_gate_result = self._check_hard_gates(
            checks, audio_duration_sec, visual_duration_sec, visual_plan_actions,
        )
        if hard_gate_result is not None:
            return hard_gate_result

        # 2b. New deterministic quality gates (Batch 2)
        diagnostics = kwargs.get("diagnostics")
        gate_result = (
            self._fail_if_visual_coverage_failed(diagnostics)
            or self._fail_if_text_collision_failed(diagnostics)
            or self._fail_if_safe_area_failed(diagnostics)
            or self._fail_if_package_consistency_failed(
                story_mode_decision, thumbnail_text, main_entities, caption, topic, script,
            )
            or self._fail_if_semantic_review_failed(diagnostics)
        )
        if gate_result is not None:
            return gate_result

        # 3. Build text for LLM review
        script_text = _format_script_text(scenes)
        safety_rules_text = _format_safety_rules(safety_rules or [])
        results_text = _format_programmatic_results(programmatic_results)

        # 4. LLM review
        agent_cfg = get_agent_config("reviewer")
        llm = OpenRouterClient()
        prompt = load_prompt("reviewer", REVIEWER_PROMPT, PROMPTS_DIR)
        response = llm.chat(
            model=agent_cfg["model"],
            messages=[
                {
                    "role": "system",
                    "content": prompt.format(
                        safety_rules_text=safety_rules_text,
                        programmatic_results=results_text,
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\n"
                        f"Script:\n{script_text}\n\n"
                        f"Caption: {caption}"
                    ),
                },
            ],
            temperature=agent_cfg["temperature"],
            max_completion_tokens=agent_cfg.get("max_completion_tokens"),
        )
        review = self._parse_review_response(response["content"])
        logger.info(
            "Reviewer: verdict=%s score=%d issues=%d",
            review["verdict"], review["score"], len(review["issues"]),
        )

        # 5. Return combined output
        return {
            "status": review["verdict"],
            "score": review["score"],
            "feedback": review["feedback"],
            "issues": review["issues"],
            "programmatic_checks": checks,
        }

    def _parse_review_response(self, content: str) -> dict[str, Any]:
        """Parse the JSON review response from the LLM."""
        try:
            stripped = content.strip().strip("```json").strip("```").strip()
            data = json.loads(stripped)
            return {
                "verdict": data.get("verdict", "fail"),
                "score": data.get("score", 0),
                "feedback": data.get("feedback", "No feedback"),
                "issues": data.get("issues", []),
            }
        except (json.JSONDecodeError, KeyError):
            return {
                "verdict": "fail",
                "score": 0,
                "feedback": "Failed to parse review response",
                "issues": ["parse_error"],
            }
