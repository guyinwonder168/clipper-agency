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

Given a research brief and topic, create:
1. A scene-by-scene TikTok script (hook, body, CTA)
2. An engaging caption
3. Relevant hashtags

Format your response as JSON:
{{
  "script": [{{"scene": 1, "text": "...", "duration": estimated_seconds}}, ...],
  "caption": "...",
  "hashtags": ["#tag1", "#tag2"],
  "estimated_duration": total_seconds
}}

Guidelines:
- Hook within first 3 seconds
- Keep total duration under 90 seconds
- Use casual, engaging tone
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
        assets_cache: str = "",
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
        response = llm.chat(
            model=settings.scriptwriter_model,
            messages=[
                {
                    "role": "system",
                    "content": prompt.format(
                        channel_description=channel_description or "a content creator",
                        safety_rules_text=safety_rules_text,
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
            return {
                "script": data.get("script", []),
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
