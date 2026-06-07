"""Scriptwriter Agent — Continuous voiceover narration generator via LLM."""

import json
import logging
import re
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
from clipper_agency.config.loader import get_agent_config
from clipper_agency.core.artifacts import write_json, write_text
from clipper_agency.core.paths import agent_dir, agent_input_file, agent_output_file
from clipper_agency.llm.client import OpenRouterClient

logger = logging.getLogger(__name__)

# Fallback prompt if prompts/scriptwriter.md is missing or empty
_FALLBACK_PROMPT = """You are a voiceover scriptwriter for {{channel_description}}.

Write in {{language}} with a {{tone}} style. Content focus: {{content_angle}}.

Write a SINGLE CONTINUOUS voiceover narration ({{min_words}}-{{max_words}} words, no emojis, spoken-word style).
Target duration: {{target_duration_sec}} seconds. Target words: ~{{target_words}}.
Map each section to a story beat using narrative_structure with word_range.

Output JSON:
{{"voiceover_text": "...", "narrative_structure": [...], "hook_text_onscreen": "...", "caption": "...", "hashtags": [...], "quality_score": 8, "quality_notes": "..."}}

Safety rules:
{{safety_rules_text}}
"""

# Default word count bounds (overridden by ContentPlanningConfig when available)
_DEFAULT_TARGET_SEC = 55
_DEFAULT_HARD_LIMIT_SEC = 60
_DEFAULT_WORDS_PER_SEC = 2.0

# Unicode emoji detection pattern
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002600-\U000026ff"  # misc symbols
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"             # zero-width joiner
    "]+",
    re.UNICODE,
)


def _contains_emoji(text: str) -> bool:
    """Return True if text contains any emoji characters."""
    return bool(_EMOJI_RE.search(text))


def _word_count(text: str) -> int:
    """Return the number of whitespace-separated words in text."""
    return len(text.split())


def _extract_blueprint(blueprint: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Extract blueprint data from dict param or legacy kwargs."""
    bp = blueprint or {}
    return {
        "story_beats": bp.get("story_beats") or kwargs.get("story_beats"),
        "verified_facts": bp.get("verified_facts") or kwargs.get("verified_facts"),
        "unverified_claims": bp.get("unverified_claims") or kwargs.get("unverified_claims"),
        "format_decision": bp.get("format_decision") or kwargs.get("format_decision"),
        "target_duration_sec": bp.get("target_duration_sec"),
        "hard_limit_sec": bp.get("hard_limit_sec"),
        "estimated_words_per_second": bp.get("estimated_words_per_second"),
    }


def _write_input_artifacts(
    assets_cache: str, job_id: int, agent_name: str, data: dict[str, Any],
) -> None:
    """Persist input artifacts if assets_cache is set."""
    if not assets_cache:
        return
    write_json(agent_input_file(assets_cache, job_id, agent_name), data)


def _format_system_prompt(
    channel_description: str, language: str, tone: str,
    content_angle: str, rules: list[str], bp_data: dict[str, Any], topic: str,
) -> str:
    """Serialize blueprint data and build the formatted system prompt."""
    safety_rules_text = "\n".join(f"- {r}" for r in rules) if rules else "None"
    beats_json = json.dumps(bp_data.get("story_beats") or [], ensure_ascii=False, indent=2)
    facts_json = json.dumps(bp_data.get("verified_facts") or [], ensure_ascii=False, indent=2)
    claims_json = json.dumps(bp_data.get("unverified_claims") or [], ensure_ascii=False, indent=2)
    decision_json = json.dumps(bp_data.get("format_decision") or {}, ensure_ascii=False, indent=2)

    # Duration-driven word budget (fallback to ContentPlanningConfig defaults)
    target_sec = bp_data.get("target_duration_sec") or 55
    hard_limit = bp_data.get("hard_limit_sec") or 60
    words_per_sec = bp_data.get("estimated_words_per_second") or 2.0
    target_words = int(target_sec * words_per_sec)
    min_words = int(target_words * 0.85)
    max_words = int(hard_limit * words_per_sec)

    prompt_template = load_prompt("scriptwriter", _FALLBACK_PROMPT, PROMPTS_DIR)
    return prompt_template.format(
        channel_description=channel_description or "a content creator",
        language=language or "English",
        tone=tone or "casual",
        content_angle=content_angle or "trending topics",
        safety_rules_text=safety_rules_text,
        story_beats_json=beats_json,
        verified_facts_json=facts_json,
        unverified_claims_json=claims_json,
        format_decision_json=decision_json,
        topic=topic,
        target_duration_sec=target_sec,
        hard_limit_sec=hard_limit,
        min_words=min_words,
        max_words=max_words,
        target_words=target_words,
    )


def _write_output_artifacts(
    assets_cache: str, job_id: int, agent_name: str, result: dict[str, Any],
) -> None:
    """Persist output artifacts if assets_cache is set."""
    if not assets_cache:
        return
    base_dir = agent_dir(assets_cache, job_id, agent_name)
    write_json(f"{base_dir}/narrative_structure.json", result["narrative_structure"])
    write_json(f"{base_dir}/script.json", {"scenes": result["narrative_structure"]})
    write_text(f"{base_dir}/voiceover.txt", result["voiceover_text"])
    write_text(f"{base_dir}/caption.txt", result["caption"])
    write_json(f"{base_dir}/hashtags.json", result["hashtags"])
    write_json(agent_output_file(assets_cache, job_id, agent_name), result)


class ScriptwriterAgent(BaseAgent):
    """Generates continuous voiceover narration from an edit blueprint."""

    @property
    def agent_name(self) -> str:
        return "scriptwriter"

    def execute(
        self,
        job_id: int,
        topic: str = "",
        research_brief: str = "",
        safety_rules: list[str] | None = None,
        channel_description: str = "",
        language: str = "",
        tone: str = "",
        content_angle: str = "",
        assets_cache: str = "",
        blueprint: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        bp_data = _extract_blueprint(blueprint, kwargs)
        rules = safety_rules or []
        logger.info("Scriptwriter: job_id=%s, beats=%d", job_id, len(bp_data["story_beats"] or []))

        _write_input_artifacts(assets_cache, job_id, self.agent_name, {
            "job_id": job_id, "topic": topic, **bp_data, "safety_rules": rules,
        })

        system_prompt = _format_system_prompt(
            channel_description, language, tone, content_angle, rules, bp_data, topic,
        )
        user_content = f"Topic: {topic}\n\nResearch Brief: {research_brief}"

        agent_cfg = get_agent_config("scriptwriter")
        llm = OpenRouterClient()
        response = llm.chat(
            model=agent_cfg["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=agent_cfg["temperature"],
            max_completion_tokens=agent_cfg.get("max_completion_tokens"),
        )

        parsed = self._parse_script_response(response["content"])
        # Dynamic word bounds from ContentPlanningConfig
        target_sec = bp_data.get("target_duration_sec") or _DEFAULT_TARGET_SEC
        hard_limit = bp_data.get("hard_limit_sec") or _DEFAULT_HARD_LIMIT_SEC
        words_per_sec = bp_data.get("estimated_words_per_second") or _DEFAULT_WORDS_PER_SEC
        min_words = int(target_sec * words_per_sec * 0.85)
        max_words = int(hard_limit * words_per_sec)
        validation_errors = _validate_output(parsed, min_words=min_words, max_words=max_words)
        if validation_errors:
            logger.warning("Scriptwriter validation issues: %s", validation_errors)

        voiceover_text = parsed["voiceover_text"]
        word_count = _word_count(voiceover_text)
        estimated_duration = word_count / 2.5

        logger.info(
            "Scriptwriter: %d words, %.1fs estimated, %d narrative beats",
            word_count, estimated_duration, len(parsed["narrative_structure"]),
        )

        result = {
            "status": "completed",
            "voiceover_text": voiceover_text,
            "narrative_structure": parsed["narrative_structure"],
            "hook_text_onscreen": parsed["hook_text_onscreen"],
            "caption": parsed["caption"],
            "hashtags": parsed["hashtags"],
            "estimated_duration_sec": round(estimated_duration, 1),
        }

        _write_output_artifacts(assets_cache, job_id, self.agent_name, result)
        return result

    def _parse_script_response(
        self,
        content: str,
        *_args: Any,
    ) -> dict[str, Any]:
        """Parse the JSON voiceover response from the LLM."""
        try:
            stripped = content.strip().strip("```json").strip("```").strip()
            data = json.loads(stripped)
        except (json.JSONDecodeError, KeyError):
            return _empty_output()

        voiceover_text = data.get("voiceover_text", "")
        if not isinstance(voiceover_text, str):
            voiceover_text = str(voiceover_text)

        narrative_structure = _normalize_narrative_structure(
            data.get("narrative_structure", []),
        )

        return {
            "voiceover_text": voiceover_text,
            "narrative_structure": narrative_structure,
            "hook_text_onscreen": data.get("hook_text_onscreen", ""),
            "caption": data.get("caption", ""),
            "hashtags": data.get("hashtags", []),
            "quality_score": data.get("quality_score", 0),
            "quality_notes": data.get("quality_notes", ""),
        }


def _validate_output(
    parsed: dict[str, Any],
    min_words: int = 0,
    max_words: int = 9999,
) -> list[str]:
    """Validate parsed output and return list of error strings (empty = valid)."""
    errors: list[str] = []
    voiceover_text = parsed.get("voiceover_text", "")

    wc = _word_count(voiceover_text)
    if wc < min_words:
        errors.append(f"voiceover_text too short: {wc} words (min {min_words})")
    if wc > max_words:
        errors.append(f"voiceover_text too long: {wc} words (max {max_words})")
    if _contains_emoji(voiceover_text):
        errors.append("voiceover_text contains emojis")

    return errors


def _normalize_narrative_structure(
    raw_beats: list[dict[str, Any]],
    *_args: Any,
) -> list[dict[str, Any]]:
    """Normalize narrative_structure entries, ensuring required fields exist."""
    normalized: list[dict[str, Any]] = []
    for i, beat in enumerate(raw_beats):
        b = dict(beat)
        if "beat_id" not in b:
            b["beat_id"] = i + 1
        if "section" not in b:
            b["section"] = f"section_{i + 1}"
        if "description" not in b:
            b["description"] = ""
        if "word_range" not in b:
            b["word_range"] = [0, 0]
        if "overlay_text" not in b:
            b["overlay_text"] = ""
        if "caption_keywords" not in b:
            b["caption_keywords"] = []
        normalized.append(b)
    return normalized


def _empty_output() -> dict[str, Any]:
    """Return a valid empty output when parsing fails."""
    return {
        "voiceover_text": "",
        "narrative_structure": [],
        "hook_text_onscreen": "",
        "caption": "",
        "hashtags": [],
        "quality_score": 0,
        "quality_notes": "",
    }
