"""Scriptwriter Agent — Continuous voiceover narration generator via LLM."""

import json
import logging
import re
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
from clipper_agency.config.loader import load_settings
from clipper_agency.core.artifacts import write_json, write_text
from clipper_agency.core.paths import agent_dir, agent_input_file, agent_output_file
from clipper_agency.llm.client import OpenRouterClient

logger = logging.getLogger(__name__)

# Fallback prompt if prompts/scriptwriter.md is missing or empty
_FALLBACK_PROMPT = """You are a voiceover scriptwriter for {{channel_description}}.

Write in {{language}} with a {{tone}} style. Content focus: {{content_angle}}.

Write a SINGLE CONTINUOUS voiceover narration (75-110 words, no emojis, spoken-word style).
Map each section to a story beat using narrative_structure with word_range.

Output JSON:
{{"voiceover_text": "...", "narrative_structure": [...], "hook_text_onscreen": "...", "caption": "...", "hashtags": [...], "quality_score": 8, "quality_notes": "..."}}

Safety rules:
{{safety_rules_text}}
"""

# Voiceover text word count bounds
_MIN_WORDS = 75
_MAX_WORDS = 110

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
        # Extract blueprint data — support dict param or legacy kwargs
        bp = blueprint or {}
        story_beats = bp.get("story_beats") or kwargs.get("story_beats")
        verified_facts = bp.get("verified_facts") or kwargs.get("verified_facts")
        unverified_claims = bp.get("unverified_claims") or kwargs.get("unverified_claims")
        format_decision = bp.get("format_decision") or kwargs.get("format_decision")

        rules = safety_rules or []
        safety_rules_text = "\n".join(f"- {r}" for r in rules) if rules else "None"
        logger.info("Scriptwriter: topic=%s, beats=%d", topic[:80], len(story_beats or []))

        # Persist input artifacts
        if assets_cache:
            write_json(
                agent_input_file(assets_cache, job_id, self.agent_name),
                {
                    "job_id": job_id,
                    "topic": topic,
                    "story_beats": story_beats,
                    "verified_facts": verified_facts,
                    "unverified_claims": unverified_claims,
                    "format_decision": format_decision,
                    "safety_rules": rules,
                },
            )

        # Serialize blueprint data for the prompt
        beats_json = json.dumps(story_beats or [], ensure_ascii=False, indent=2)
        facts_json = json.dumps(verified_facts or [], ensure_ascii=False, indent=2)
        claims_json = json.dumps(unverified_claims or [], ensure_ascii=False, indent=2)
        decision_json = json.dumps(format_decision or {}, ensure_ascii=False, indent=2)

        # Load and format the prompt
        prompt_template = load_prompt("scriptwriter", _FALLBACK_PROMPT, PROMPTS_DIR)
        system_prompt = prompt_template.format(
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
        )

        # Build user message from research brief and topic
        user_content = f"Topic: {topic}\n\nResearch Brief: {research_brief}"

        settings = load_settings()
        llm = OpenRouterClient()
        response = llm.chat(
            model=settings.scriptwriter_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.7,
            max_tokens=2048,
        )

        parsed = self._parse_script_response(response["content"])

        # Validate voiceover text
        validation_errors = _validate_output(parsed)
        if validation_errors:
            logger.warning("Scriptwriter validation issues: %s", validation_errors)

        voiceover_text = parsed["voiceover_text"]
        word_count = _word_count(voiceover_text)
        estimated_duration = word_count / 2.5  # ~2.5 words/sec average

        logger.info(
            "Scriptwriter: %d words, %.1fs estimated, %d narrative beats",
            word_count,
            estimated_duration,
            len(parsed["narrative_structure"]),
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

        # Persist output artifacts
        if assets_cache:
            base_dir = agent_dir(assets_cache, job_id, self.agent_name)
            write_json(f"{base_dir}/narrative_structure.json", result["narrative_structure"])
            write_text(f"{base_dir}/voiceover.txt", result["voiceover_text"])
            write_text(f"{base_dir}/caption.txt", result["caption"])
            write_json(f"{base_dir}/hashtags.json", result["hashtags"])
            write_json(agent_output_file(assets_cache, job_id, self.agent_name), result)

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


def _validate_output(parsed: dict[str, Any]) -> list[str]:
    """Validate parsed output and return list of error strings (empty = valid)."""
    errors: list[str] = []
    voiceover_text = parsed.get("voiceover_text", "")

    wc = _word_count(voiceover_text)
    if wc < _MIN_WORDS:
        errors.append(f"voiceover_text too short: {wc} words (min {_MIN_WORDS})")
    if wc > _MAX_WORDS:
        errors.append(f"voiceover_text too long: {wc} words (max {_MAX_WORDS})")
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
