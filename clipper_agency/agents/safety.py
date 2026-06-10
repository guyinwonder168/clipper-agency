"""Safety Agent — content safety checking via LLM."""

import json
import logging
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
from clipper_agency.config.loader import get_agent_config
from clipper_agency.core.artifacts import write_json, write_text
from clipper_agency.core.paths import agent_input_file, agent_output_file, agent_dir
from clipper_agency.llm.client import OpenRouterClient

logger = logging.getLogger(__name__)

SAFETY_PROMPT = """You are a content safety checker. Analyze the following topic and return a JSON verdict:
- "pass": Topic is safe for content generation
- "soft_warning": Topic contains unverified claims that need cautious wording
- "hard_block": Topic involves illegal content, defamation, hate speech, or banned platform policy

Rules:
- Hard-block: illegal activities, hate speech, defamation, explicit harmful content
- Soft-warning: unverified rumors, unconfirmed news, speculative claims
- Pass: everything else (entertainment news, celebrity updates, trending topics)

Respond ONLY with valid JSON: {"verdict": "...", "reason": "..."}
"""


class SafetyAgent(BaseAgent):
    """Analyzes a topic for content safety before pipeline execution."""

    def __init__(self, trace_writer: Any | None = None) -> None:
        self._trace_writer = trace_writer

    @property
    def agent_name(self) -> str:
        return "safety"

    def execute(
        self,
        job_id: int,
        topic: str = "",
        safety_rules: list[str] | None = None,
        assets_cache: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        rules = safety_rules or []
        logger.info("Safety: checking rules=%d", len(rules))

        input_data = {"job_id": job_id, "topic": topic, "safety_rules": rules}
        if assets_cache:
            write_json(agent_input_file(assets_cache, job_id, self.agent_name), input_data)

        settings_cfg = get_agent_config("safety")
        llm = OpenRouterClient(trace_writer=self._trace_writer)
        prompt = load_prompt("safety", SAFETY_PROMPT, PROMPTS_DIR)
        messages = [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Topic: {topic}\nRules: {rules}",
                },
            ]
        if self._trace_writer:
            response = llm.chat_traced(
                model=settings_cfg["model"],
                messages=messages,
                job_id=job_id,
                agent=self.agent_name,
                task="safety_check",
                temperature=settings_cfg["temperature"],
                max_completion_tokens=settings_cfg.get("max_completion_tokens"),
                prompt_template_id="safety.md",
            )
        else:
            response = llm.chat(
                model=settings_cfg["model"],
                messages=messages,
            temperature=settings_cfg["temperature"],
            max_completion_tokens=settings_cfg.get("max_completion_tokens"),
            )
        result = self._parse_response(response["content"])
        if assets_cache:
            write_json(agent_output_file(assets_cache, job_id, self.agent_name), result)
            write_text(
                f"{agent_dir(assets_cache, job_id, self.agent_name)}/summary.md",
                f"# Safety Summary\n\nStatus: {result.get('status')}\n\nReason: {result.get('reason', '')}\n",
            )
        logger.info("Safety: verdict=%s", result.get("status"))
        return result

    def _parse_response(self, content: str) -> dict[str, Any]:
        """Parse the JSON verdict from the LLM response."""
        try:
            stripped = content.strip().strip("```json").strip("```").strip()
            data = json.loads(stripped)
            verdict = data.get("verdict", "hard_block")
            reason = data.get("reason", "No reason given")
            if verdict == "pass":
                return {"status": "pass", "reason": reason}
            elif verdict == "soft_warning":
                return {
                    "status": "soft_warning",
                    "reason": reason,
                    "requires_cautious_wording": True,
                }
            else:
                return {"status": "hard_fail", "reason": reason}
        except (json.JSONDecodeError, KeyError) as e:
            return {"status": "hard_fail", "reason": f"Failed to parse response: {e}"}
