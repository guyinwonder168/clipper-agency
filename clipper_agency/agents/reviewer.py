"""Reviewer Agent — final content quality and safety review via LLM."""

import json
import logging
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
from clipper_agency.config.loader import load_settings
from clipper_agency.llm.client import OpenRouterClient

logger = logging.getLogger(__name__)

_MAX_CAPTION_LEN = 150
_AV_DRIFT_TOLERANCE_SEC = 0.5

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

    def execute(
        self,
        job_id: int,
        topic: str = "",
        script: list[dict] | None = None,
        caption: str = "",
        safety_rules: list[str] | None = None,
        audio_duration_sec: float = 0.0,
        visual_duration_sec: float = 0.0,
        narrative_structure: list[dict] | None = None,
        unverified_claims: list[dict] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
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

        # 2. Build text for LLM review
        script_text = _format_script_text(scenes)
        safety_rules_text = _format_safety_rules(safety_rules or [])
        results_text = _format_programmatic_results(programmatic_results)

        # 3. LLM review
        settings = load_settings()
        llm = OpenRouterClient()
        prompt = load_prompt("reviewer", REVIEWER_PROMPT, PROMPTS_DIR)
        response = llm.chat(
            model=settings.reviewer_model,
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
            temperature=0.2,
            max_tokens=1024,
        )
        review = self._parse_review_response(response["content"])
        logger.info(
            "Reviewer: verdict=%s score=%d issues=%d",
            review["verdict"], review["score"], len(review["issues"]),
        )

        # 4. Return combined output
        return {
            "status": review["verdict"],
            "score": review["score"],
            "feedback": review["feedback"],
            "issues": review["issues"],
            "programmatic_checks": {
                "av_sync": av_sync,
                "caption_quality": caption_q,
                "fact_safety": fact_safety,
                "narrative_structure": narrative_q,
            },
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
