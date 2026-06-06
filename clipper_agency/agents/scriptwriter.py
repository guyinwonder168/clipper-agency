"""Scriptwriter Agent — TikTok script and caption generator via LLM."""

import json
import logging
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
from clipper_agency.config.loader import load_settings
from clipper_agency.core.artifacts import write_json, write_text
from clipper_agency.core.paths import agent_dir, agent_input_file, agent_output_file
from clipper_agency.llm.client import OpenRouterClient

logger = logging.getLogger(__name__)

SCRIPTWRITER_PROMPT = """You are a TikTok scriptwriter creating engaging scripts for {channel_description}.

Write scripts in {language} with a {tone} style.
Focus content on: {content_angle}.

VIDEO BUDGET (STRICT — do not exceed):
- Target duration: {target_duration_sec} seconds
- Hard limit: {hard_limit_sec} seconds
- Speaking rate: ~{estimated_words_per_second} words/second
- Maximum scenes: {max_scenes}

STORY DIRECTION (from Researcher — you MUST follow this):
- Format: {story_format}
- Story count: {story_count} (do NOT add extra stories or bonus content)
- Stories to cover: {stories_list}
- Content angle: {content_angle}

Given a research brief and topic, create:
1. A scene-by-scene TikTok script (opening_hook, story scenes, closing_cta)
2. An engaging caption in {language}
3. Relevant hashtags

Format your response as JSON:
{{
  "script": [
    {{"scene": 1, "role": "opening_hook", "text": "...", "word_count": 10, "estimated_duration_sec": 5.0}},
    ...
  ],
  "caption": "...",
  "hashtags": ["#tag1", "#tag2"],
  "estimated_duration": total_seconds
}}

Scene roles MUST be one of: "opening_hook", "story_1", "story_2", ..., "closing_cta".
Do NOT invent extra stories beyond the {story_count} provided.
Each scene text should be {max_words_per_scene:.0f} words or fewer to stay within budget.

Guidelines:
- Hook within first 3 seconds
- Total MUST stay under {hard_limit_sec} seconds
- Use {tone} tone
- Include a strong CTA (call to action)

Safety rules to follow:
{safety_rules_text}
"""


class ScriptwriterAgent(BaseAgent):
    """Generates TikTok scripts, captions, and hashtags from research briefs."""

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
        target_duration_sec: int = 55,
        hard_limit_sec: int = 60,
        estimated_words_per_second: float = 2.0,
        max_scenes: int = 8,
        story_format: str = "",
        story_count: int = 3,
        stories_list: list | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        rules = safety_rules or []
        safety_rules_text = "\n".join(f"- {r}" for r in rules) if rules else "None"
        logger.info("Scriptwriter: brief length=%d", len(research_brief))
        if assets_cache:
            write_json(
                agent_input_file(assets_cache, job_id, self.agent_name),
                {
                    "job_id": job_id,
                    "topic": topic,
                    "research_brief": research_brief,
                    "safety_rules": rules,
                },
            )

        settings = load_settings()
        llm = OpenRouterClient()
        prompt = load_prompt("scriptwriter", SCRIPTWRITER_PROMPT, PROMPTS_DIR)
        max_words_per_scene = (hard_limit_sec - 9) / max(max_scenes, 1) / estimated_words_per_second
        stories_str = ", ".join(stories_list) if stories_list else "see research brief"
        response = llm.chat(
            model=settings.scriptwriter_model,
            messages=[
                {
                    "role": "system",
                    "content": prompt.format(
                        channel_description=channel_description or "a content creator",
                        language=language or "English",
                        tone=tone or "casual",
                        content_angle=content_angle or "trending topics",
                        safety_rules_text=safety_rules_text,
                        target_duration_sec=target_duration_sec,
                        hard_limit_sec=hard_limit_sec,
                        estimated_words_per_second=estimated_words_per_second,
                        max_scenes=max_scenes,
                        story_format=story_format or "three_story_roundup",
                        story_count=story_count,
                        stories_list=stories_str,
                        max_words_per_scene=max_words_per_scene,
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\nResearch Brief: {research_brief}"
                    ),
                },
            ],
            temperature=0.7,
            max_tokens=2048,
        )
        parsed = self._parse_script_response(response["content"])
        logger.info(
            "Scriptwriter: %d scenes, duration=%ds",
            len(parsed["script"]),
            parsed.get("estimated_duration", 0),
        )
        result = {
            "status": "completed",
            "script": parsed["script"],
            "caption": parsed["caption"],
            "hashtags": parsed["hashtags"],
            "estimated_duration": parsed.get("estimated_duration", 0),
        }
        if assets_cache:
            base_dir = agent_dir(assets_cache, job_id, self.agent_name)
            write_json(f"{base_dir}/script.json", result["script"])
            write_text(f"{base_dir}/caption.txt", result["caption"])
            write_json(f"{base_dir}/hashtags.json", result["hashtags"])
            write_json(agent_output_file(assets_cache, job_id, self.agent_name), result)
        return result

    def _parse_script_response(self, content: str) -> dict[str, Any]:
        """Parse the JSON script response from the LLM."""
        try:
            stripped = content.strip().strip("```json").strip("```").strip()
            data = json.loads(stripped)
            script = _normalize_scenes(data.get("script", []))
            return {
                "script": script,
                "caption": data.get("caption", ""),
                "hashtags": data.get("hashtags", []),
                "estimated_duration": data.get("estimated_duration", 0),
            }
        except (json.JSONDecodeError, KeyError):
            return {
                "script": [],
                "caption": "",
                "hashtags": [],
                "estimated_duration": 0,
            }


def _normalize_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every scene has role, word_count, and estimated_duration_sec."""
    normalized: list[dict[str, Any]] = []
    for scene in scenes:
        s = dict(scene)
        if "role" not in s:
            s["role"] = "body"
        if "estimated_duration_sec" not in s and "duration" in s:
            s["estimated_duration_sec"] = s["duration"]
        if "word_count" not in s:
            s["word_count"] = len(s.get("text", "").split())
        normalized.append(s)
    return normalized
