"""Researcher Agent — web search and content research synthesis."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.config.loader import load_settings
from clipper_agency.core.artifacts import write_json, write_text
from clipper_agency.core.paths import (
    agent_dir,
    agent_input_file,
    agent_output_file,
    ensure_research_cache_dir,
    firecrawl_cache_file,
    researcher_brief_file,
    researcher_contract_file,
    research_brief_cache_file,
    scrapecreators_cache_file,
)
from clipper_agency.llm.client import OpenRouterClient
from clipper_agency.services.firecrawl_service import FirecrawlService
from clipper_agency.services.scrapecreators import ScrapeCreatorsService

logger = logging.getLogger(__name__)

# ── token guard ──────────────────────────────────────────────────────────────
# Prevent LLM context overflow from overly large search results.
MAX_SOURCE_CHARS = 40_000  # ~10K tokens worth of text
MAX_CHARS_PER_SOURCE = 500


RESEARCH_PROMPT = """You are a research assistant for {channel_description}.

Write your output in {language} with a {tone} style.
Focus research on: {content_angle}.

Analyze the provided search results and create a concise research brief.

Rules to follow:
{rules_text}

Search results:
{sources_text}

Return a JSON response with two fields:

1. "research_brief" — concise brief covering:
   - Key facts and verified information
   - Trending angles and viral potential
   - Content suggestions for short-form video
   - Any risks or sensitive topics to handle carefully

2. "content_direction" — recommend the best approach for this content:
   - "recommended_format": one of "three_story_roundup", "single_story_deep", or "rapid_bulletin"
   - "reason": brief explanation
   - "selected_story_count": number (1-6)
   - "selected_stories": list of story slugs or headlines
   - "content_angle": suggested angle for Scriptwriter
   - "risk_notes": any safety/caution notes
"""


class ResearcherAgent(BaseAgent):
    """Researches a topic using web search tools and LLM synthesis.

    Caches ScrapeCreators and Firecrawl API responses per job so
    expensive API calls are only made once per topic/job run.
    """

    @property
    def agent_name(self) -> str:
        return "researcher"

    def execute(
        self,
        job_id: int,
        topic: str = "",
        safety_rules: list[str] | None = None,
        channel_description: str = "",
        language: str = "",
        tone: str = "",
        content_angle: str = "",
        max_results: int = 5,
        output_dir: str = "",
        assets_cache: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        rules = safety_rules or []
        if assets_cache:
            write_json(
                agent_input_file(assets_cache, job_id, self.agent_name),
                {
                    "job_id": job_id,
                    "topic": topic,
                    "safety_rules": rules,
                    "max_results": max_results,
                },
            )
        ensure_research_cache_dir(output_dir, job_id)

        # ── 1. Gather sources (cached or live) ──────────────────────────
        scrapecreators_data = self._get_scrapecreators(topic, output_dir, job_id)
        firecrawl_data = self._get_firecrawl(topic, max_results, output_dir, job_id)
        aggregated = self._aggregate_data(firecrawl_data, scrapecreators_data)

        # ── 2. Synthesize research brief (cached or live LLM) ───────────
        brief = self._get_research_brief(aggregated, topic, rules, output_dir, job_id,
                                          channel_description, language, tone, content_angle)

        result = {
            "status": "completed",
            "research_brief": brief,
            "sources": aggregated,
            "risk_flags": [],
        }
        if assets_cache:
            result.update(
                self._persist_contract_artifacts(
                    assets_cache=assets_cache,
                    job_id=job_id,
                    topic=topic,
                    brief=brief,
                    firecrawl_data=firecrawl_data,
                    scrapecreators_data=scrapecreators_data,
                    output=result,
                )
            )
        return result

    # ── source gathering (with cache) ───────────────────────────────────────

    def _get_scrapecreators(
        self, topic: str, output_dir: str, job_id: int
    ) -> list[dict]:
        cache_path = scrapecreators_cache_file(output_dir, job_id)

        if os.path.exists(cache_path):
            logger.info("Researcher: ScrapeCreators cache HIT (%s)", cache_path)
            with open(cache_path) as fh:
                return json.load(fh)

        logger.info("Researcher: ScrapeCreators cache MISS — calling API")
        try:
            service = ScrapeCreatorsService()
            data = service.search_tiktok_videos(topic)
            with open(cache_path, "w") as fh:
                json.dump(data, fh, indent=2)
            logger.debug("Researcher: saved %d results to %s", len(data), cache_path)
            return data
        except Exception:
            logger.exception("Researcher: ScrapeCreators API failed")
            return []

    def _get_firecrawl(
        self, topic: str, max_results: int, output_dir: str, job_id: int
    ) -> list[dict]:
        cache_path = firecrawl_cache_file(output_dir, job_id)

        if os.path.exists(cache_path):
            logger.info("Researcher: Firecrawl cache HIT (%s)", cache_path)
            with open(cache_path) as fh:
                return json.load(fh)

        logger.info("Researcher: Firecrawl cache MISS — calling API")
        try:
            service = FirecrawlService()
            data = service.search(topic, max_results)
            with open(cache_path, "w") as fh:
                json.dump(data, fh, indent=2)
            logger.debug("Researcher: saved %d Firecrawl results to %s", len(data), cache_path)
            return data
        except Exception:
            logger.exception("Researcher: Firecrawl API failed")
            return []

    # ── research brief synthesis (with cache + token guard) ─────────────────

    def _get_research_brief(
        self,
        aggregated: dict[str, Any],
        topic: str,
        safety_rules: list[str],
        output_dir: str,
        job_id: int,
        channel_description: str = "",
        language: str = "",
        tone: str = "",
        content_angle: str = "",
    ) -> str:
        cache_path = research_brief_cache_file(output_dir, job_id)

        if os.path.exists(cache_path):
            logger.info("Researcher: research_brief cache HIT (%s)", cache_path)
            with open(cache_path) as fh:
                return json.load(fh)["research_brief"]

        logger.info("Researcher: research_brief cache MISS — calling LLM")
        result = self._synthesize_research(aggregated, topic, safety_rules,
                                            channel_description, language, tone, content_angle)
        brief = result["research_brief"]

        with open(cache_path, "w") as fh:
            json.dump({"research_brief": brief}, fh, indent=2)
        logger.debug("Researcher: saved research_brief to %s", cache_path)
        return brief

    # ── helpers ─────────────────────────────────────────────────────────────

    def _aggregate_data(
        self, firecrawl_data: list[dict], scrapecreators_data: list[dict]
    ) -> dict[str, Any]:
        sources = list(firecrawl_data) + list(scrapecreators_data)
        return {
            "firecrawl_count": len(firecrawl_data),
            "scrapecreators_count": len(scrapecreators_data),
            "total_sources": len(sources),
            "sources": sources,
        }

    def _persist_contract_artifacts(
        self,
        assets_cache: str,
        job_id: int,
        topic: str,
        brief: str,
        firecrawl_data: list[dict],
        scrapecreators_data: list[dict],
        output: dict[str, Any],
    ) -> dict[str, str]:
        base = Path(agent_dir(assets_cache, job_id, self.agent_name))
        raw_scrapecreators_path = base / "raw" / "scrapecreators_response.json"
        raw_firecrawl_path = base / "raw" / "firecrawl_response.json"
        video_sources_path = base / "normalized" / "video_sources.json"
        context_sources_path = base / "normalized" / "context_sources.json"
        music_candidates_path = base / "normalized" / "music_candidates.json"
        entities_path = base / "normalized" / "entities.json"
        risk_flags_path = base / "normalized" / "risk_flags.json"

        brief_path = researcher_brief_file(assets_cache, job_id)
        contract_path = researcher_contract_file(assets_cache, job_id)
        write_json(raw_scrapecreators_path, scrapecreators_data)
        write_json(raw_firecrawl_path, firecrawl_data)
        write_text(brief_path, brief)
        write_json(video_sources_path, scrapecreators_data)
        write_json(context_sources_path, firecrawl_data)
        write_json(music_candidates_path, [])
        write_json(entities_path, {})
        write_json(risk_flags_path, [])

        contract = {
            "topic": topic,
            "topic_brief_path": brief_path,
            "raw_scrapecreators_path": str(raw_scrapecreators_path),
            "raw_firecrawl_path": str(raw_firecrawl_path),
            "video_sources": scrapecreators_data,
            "context_sources": firecrawl_data,
            "music_candidates": [],
            "entities": {},
            "risk_flags": [],
            "cache_key": f"job_{job_id}:{topic}",
            "cache_freshness": "fresh",
        }
        write_json(contract_path, contract)

        paths = {
            "research_contract_path": contract_path,
            "research_brief_path": brief_path,
        }
        write_json(agent_output_file(assets_cache, job_id, self.agent_name), {**output, **paths})
        return paths

    def _synthesize_research(
        self,
        aggregated: dict[str, Any],
        topic: str,
        safety_rules: list[str],
        channel_description: str = "",
        language: str = "",
        tone: str = "",
        content_angle: str = "",
    ) -> dict[str, Any]:
        sources = aggregated.get("sources", [])

        # ── token guard: truncate per-source and total ──────────────────
        trimmed: list[str] = []
        total_chars = 0
        for s in sources:
            text = str(s)[:MAX_CHARS_PER_SOURCE]
            trimmed.append(text)
            total_chars += len(text)
            if total_chars >= MAX_SOURCE_CHARS:
                logger.warning(
                    "Researcher: source text truncated at %d chars "
                    "(%d of %d sources used to avoid LLM context overflow)",
                    total_chars,
                    len(trimmed),
                    len(sources),
                )
                break

        sources_text = "\n\n".join(trimmed)
        rules_text = "\n".join(f"- {r}" for r in safety_rules) if safety_rules else "None"

        logger.info(
            "Researcher: synthesizing research "
            "(%d sources, %d chars of text)",
            len(trimmed),
            len(sources_text),
        )

        settings = load_settings()
        llm = OpenRouterClient()
        response = llm.chat(
            model=settings.researcher_model,
            messages=[
                {
                    "role": "system",
                    "content": RESEARCH_PROMPT.format(
                        channel_description=channel_description or "a content creator",
                        language=language or "English",
                        tone=tone or "casual",
                        content_angle=content_angle or "trending topics",
                        rules_text=rules_text, sources_text=sources_text
                    ),
                },
                {
                    "role": "user",
                    "content": f"Research topic: {topic}",
                },
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        parsed = self._parse_synthesis_response(response["content"])
        return {
            "research_brief": parsed["research_brief"],
            "content_direction": parsed.get("content_direction"),
            "source_count": len(sources),
        }

    def _parse_synthesis_response(self, content: str) -> dict[str, Any]:
        """Parse LLM synthesis response into research_brief + content_direction."""
        try:
            stripped = content.strip()
            if stripped.startswith("```"):
                stripped = stripped.removeprefix("```json").removeprefix("```")
                stripped = stripped.removesuffix("```").strip()
            data = json.loads(stripped)
            return {
                "research_brief": data.get("research_brief", ""),
                "content_direction": data.get("content_direction"),
            }
        except (json.JSONDecodeError, KeyError):
            return {"research_brief": content, "content_direction": None}
