"""Segment Producer Agent — research, fact-checking, story structuring, and edit planning.

Combines 5 specialist roles:
  1. Fact Checker — verify claims, label confidence, produce safe wording.
  2. Viral Analyst — decide video format based on asset availability.
  3. Clip Scout — evaluate source clips for quality and relevance.
  4. Story Producer — structure narrative into story beats.
  5. Edit Planner — plan visual requirements per beat.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.config.loader import get_agent_config, load_settings
from clipper_agency.core.artifacts import write_json, write_text
from clipper_agency.core.paths import (
    agent_dir,
    agent_input_file,
    agent_output_file,
    ensure_research_cache_dir,
    firecrawl_cache_file,
    research_brief_cache_file,
    scrapecreators_cache_file,
    segment_producer_brief_file,
    segment_producer_contract_file,
)
from clipper_agency.llm.client import OpenRouterClient
from clipper_agency.services.brave import BraveSearchService
from clipper_agency.services.firecrawl_service import FirecrawlService
from clipper_agency.services.scrapecreators import ScrapeCreatorsService
from clipper_agency.services.tavily import TavilyService
from clipper_agency.services.ytdlp import YtDlpService

from clipper_agency.core.duration_budget import allocate_duration_budget
from clipper_agency.core.story_decision_reconciliation import reconcile_story_decisions
from clipper_agency.core.story_mode import classify_story_mode
from clipper_agency.core.story_mode_contract import derive_story_mode_contract

logger = logging.getLogger(__name__)

# ── token guard ──────────────────────────────────────────────────────────────
# Prevent LLM context overflow from overly large search results.
MAX_SOURCE_CHARS = 40_000  # ~10K tokens worth of text
MAX_CHARS_PER_SOURCE = 500

# ── source quality tiers ────────────────────────────────────────────────────
# Base relevance scores by source type.  TikTok clips downgraded due to
# watermarks and hardcoded subtitles; firecrawl is lowest (article text).
SOURCE_QUALITY_TIERS: dict[str, float] = {
    "youtube_official": 0.95,
    "web_video": 0.85,
    "tiktok_clip": 0.50,   # downgraded — watermark / hardcoded subs
    "image": 0.70,
    "article": 0.40,
    "firecrawl": 0.30,
}
DEFAULT_SOURCE_QUALITY: float = 0.40

# Map source_type → candidate type for _build_asset_candidates_from_sources.
_SOURCE_TYPE_TO_CANDIDATE_TYPE: dict[str, str] = {
    "tiktok_clip": "tiktok_clip",
    "firecrawl": "screenshot",
    "image": "photo",
    "article": "screenshot",
    "youtube_official": "tiktok_clip",
    "web_video": "tiktok_clip",
}


SEGMENT_PRODUCER_PROMPT = """You are a Segment Producer for {channel_description}.

You combine 5 specialist roles:

1. **Fact Checker** — Verify every claim. Label as "verified", "likely", or "unconfirmed". If unconfirmed, provide safe wording.
2. **Viral Analyst** — Decide video format based on asset availability. Choose the format that maximizes engagement.
3. **Clip Scout** — Evaluate every source clip for quality. Reject blurry, irrelevant, or misleading footage.
4. **Story Producer** — Structure the narrative into story beats. Every beat must serve the story arc.
5. **Edit Planner** — Plan the edit blueprint. Decide what visual goes with each beat.

Write your output in {language} with a {tone} style.
Focus research on: {content_angle}.

Rules to follow:
{rules_text}

Video duration budget:
- Target duration: {target_duration_sec} seconds
- Hard limit: {hard_limit_sec} seconds
- Estimated speaking rate: {estimated_words_per_second} words/second
- Max stories allowed: {max_stories_per_video}

Search results:
{sources_text}

You MUST produce a JSON response with these fields:

1. "research_brief" — concise brief covering:
   - Key facts and verified information
   - Trending angles and viral potential
   - Content suggestions for short-form video
   - Any risks or sensitive topics to handle carefully

2. "content_direction" — format and story selection:
   - "recommended_format": one of "single_story_deep_dive", "three_story_roundup", "two_story_highlight", or "text_only"
   - "reason": brief explanation
   - "selected_story_count": number (1-{max_stories_per_video})
   - "selected_stories": list of story slugs or headlines
   - "content_angle": suggested angle for Scriptwriter
   - "risk_notes": any safety/caution notes

3. "story_beats" — array of beats, each with:
   - "beat_id": sequential integer (1, 2, 3...)
   - "role": one of "hook", "main_claim", "evidence", "reaction", "closing_cta"
   - "narration_goal": what the narrator should communicate
   - "spoken_point": the actual talking point (1-2 sentences)
   - "safe_wording": legally safe version of the claim
   - "visual_must_show": what the visual MUST display
   - "visual_must_not_show": what the visual must NOT display
   - "overlay_text": short on-screen text (max 6 words)
   - "caption_keywords": 2-4 keywords for subtitle display
   - "asset_candidates": array of {{"type", "url", "reason"}} for visual assets
   - "fallback": {{"type", "headline", "image_search"}} if no asset found
   - "evidence_source": URL or "none"
   - "risk_note": "" or risk warning

4. "format_decision" — structured format choice:
   - "format": one of "single_story_deep_dive", "three_story_roundup", "two_story_highlight", "text_only"
   - "story_count": number of stories
   - "rationale": why this format
   - "video_asset_ratio": ratio of clips available vs needed (0.0-1.0)

5. "verified_facts" — array of {{"fact", "source_url", "confidence", "safe_wording"}}

6. "unverified_claims" — array of {{"claim", "label", "safe_wording"}}

7. "do_not_use" — array of strings: visual types/sources to avoid

8. "reference_style" — production parameters:
   - "format": chosen format
   - "target_duration_sec": target duration
   - "hook_duration_sec": hook duration (2-3 seconds)
   - "avg_scene_duration_sec": average scene duration
   - "caption_style": "keyword" or "full"
   - "transition_style": "hard_cut" or "crossfade"
   - "visual_priority": ordered list of visual types

Rules:
- Every beat must have a clear visual plan (asset or fallback)
- If a claim is unconfirmed, use safe wording
- Hook beat must be attention-grabbing within 2 seconds
- Closing CTA must include engagement prompt
- Target 35-60 seconds total
- First beat (hook) should be 2-3 seconds
- Use {language}, {tone} tone
- Apply safety_rules from niche config
"""


class SegmentProducerAgent(BaseAgent):
    """Segment Producer: research, fact-check, story structure, and edit planning.

    Combines 5 specialist roles (Fact Checker, Viral Analyst, Clip Scout,
    Story Producer, Edit Planner) to produce a comprehensive edit blueprint
    with story beats, format decisions, and asset evaluations.

    Caches ScrapeCreators and Firecrawl API responses per job so
    expensive API calls are only made once per topic/job run.
    """

    def __init__(self, trace_writer: Any | None = None) -> None:
        self._trace_writer = trace_writer

    @property
    def agent_name(self) -> str:
        return "segment_producer"

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

        # ── Resolve target duration from settings ────────────────────────
        settings = load_settings()
        target_dur = (
            settings.content_planning.target_duration_sec
            if settings.content_planning
            else 55
        )

        # ── 1. Gather sources (cached or live) ──────────────────────────
        scrapecreators_data = self._get_scrapecreators(topic, output_dir, job_id)
        firecrawl_data = self._get_firecrawl(topic, max_results, output_dir, job_id)
        aggregated = self._aggregate_data(firecrawl_data, scrapecreators_data)

        # ── 1b. Extract visual asset candidates from raw sources ────────
        all_sources = self._normalize_sources(firecrawl_data, scrapecreators_data)
        discovered_candidates = self._build_asset_candidates_from_sources(all_sources)

        # ── 2. Synthesize research brief (cached or live LLM) ───────────
        synthesis = self._get_research_brief(
            aggregated, topic, rules, output_dir, job_id,
            channel_description, language, tone, content_angle,
        )

        # ── 2b. Multi-provider asset discovery (uses synthesis entities) ─
        multi_sources, provider_attempts = self._discover_multi_source_assets(
            topic=topic,
            entities=synthesis.get("entities", {}),
            config=settings,
        )
        multi_candidates = self._build_asset_candidates_from_sources(multi_sources)

        # ── 2c. YouTube thumbnail fallback candidates ────────────────────
        thumbnail_candidates = self._get_thumbnail_fallback_candidates(
            multi_sources, output_dir, job_id,
        )

        # ── 3. Classify story mode (early, deterministic) ─────────────
        classifier_decision = classify_story_mode(topic, target_duration_sec=target_dur)

        # ── 4. Reconcile classifier + legacy format_decision ───────────
        legacy_format = synthesis.get("format_decision")
        story_beats_raw = synthesis.get("story_beats", [])
        reconciled = reconcile_story_decisions(
            classifier_decision, legacy_format,
        )

        # ── 5. Derive production contract from canonical decision ──────
        contract = derive_story_mode_contract(reconciled)

        # ── 6. Allocate budget from reconciled mode ────────────────────
        duration_budget = allocate_duration_budget(
            story_mode=reconciled.story_mode,
            item_count=reconciled.item_count,
            target_duration_sec=target_dur,
        )

        # ── 7. Merge global candidates + distribute to beats ───────────
        global_candidates = self._merge_asset_candidates(
            synthesis.get("asset_candidates", []),
            discovered_candidates,
            multi_candidates,
            thumbnail_candidates,
        )
        story_beats_distributed = self._distribute_candidates_to_beats(
            story_beats_raw, global_candidates,
        )

        result = {
            "status": "completed",
            "research_brief": synthesis["research_brief"],
            "sources": aggregated,
            "risk_flags": [],
            "story_beats": story_beats_distributed,
            "format_decision": legacy_format,
            "asset_candidates": global_candidates,
            "provider_attempts": provider_attempts,
            "do_not_use": synthesis.get("do_not_use", []),
            "verified_facts": synthesis.get("verified_facts", []),
            "unverified_claims": synthesis.get("unverified_claims", []),
            "reference_style": synthesis.get("reference_style"),
            "story_mode_decision": contract,
            "duration_budget": duration_budget.model_dump(),
        }
        if assets_cache:
            result.update(
                self._persist_contract_artifacts(
                    assets_cache=assets_cache,
                    job_id=job_id,
                    topic=topic,
                    brief=synthesis["research_brief"],
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
            logger.info("Segment Producer: ScrapeCreators cache HIT (%s)", cache_path)
            with open(cache_path) as fh:
                return json.load(fh)

        logger.info("Segment Producer: ScrapeCreators cache MISS — calling API")
        try:
            service = ScrapeCreatorsService()
            data = service.search_tiktok_videos(topic)
            with open(cache_path, "w") as fh:
                json.dump(data, fh, indent=2)
            logger.debug("Segment Producer: saved %d results to %s", len(data), cache_path)
            return data
        except Exception:
            logger.exception("Segment Producer: ScrapeCreators API failed")
            return []

    def _get_firecrawl(
        self, topic: str, max_results: int, output_dir: str, job_id: int
    ) -> list[dict]:
        cache_path = firecrawl_cache_file(output_dir, job_id)

        if os.path.exists(cache_path):
            logger.info("Segment Producer: Firecrawl cache HIT (%s)", cache_path)
            with open(cache_path) as fh:
                return json.load(fh)

        logger.info("Segment Producer: Firecrawl cache MISS — calling API")
        try:
            service = FirecrawlService()
            data = service.search(topic, max_results)
            with open(cache_path, "w") as fh:
                json.dump(data, fh, indent=2)
            logger.debug("Segment Producer: saved %d Firecrawl results to %s", len(data), cache_path)
            return data
        except Exception:
            logger.exception("Segment Producer: Firecrawl API failed")
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
    ) -> dict[str, Any]:
        cache_path = research_brief_cache_file(output_dir, job_id)

        if os.path.exists(cache_path):
            logger.info("Segment Producer: research_brief cache HIT (%s)", cache_path)
            with open(cache_path) as fh:
                cached = json.load(fh)
                # Backward-compatible: old cache may only have research_brief
                if "story_beats" not in cached:
                    cached["story_beats"] = []
                return cached

        logger.info("Segment Producer: research_brief cache MISS — calling LLM")
        result = self._synthesize_research(
            aggregated, topic, safety_rules,
            channel_description, language, tone, content_angle,
            job_id=job_id,
        )

        with open(cache_path, "w") as fh:
            json.dump(result, fh, indent=2)
        logger.debug("Segment Producer: saved research_brief to %s", cache_path)
        return result

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

    @staticmethod
    def _normalize_sources(
        firecrawl_data: list[dict],
        scrapecreators_data: list[dict],
    ) -> list[dict]:
        """Convert legacy separate source lists into unified source_type dicts."""
        sources: list[dict] = []
        for item in scrapecreators_data:
            sources.append({**item, "source_type": "tiktok_clip", "source": "scrapecreators"})
        for item in firecrawl_data:
            sources.append({**item, "source_type": "firecrawl", "source": "firecrawl"})
        return sources

    @staticmethod
    def _build_asset_candidates_from_sources(
        sources: list[dict] | None = None,
        firecrawl_data: list[dict] | None = None,
        scrapecreators_data: list[dict] | None = None,
    ) -> list[dict]:
        """Build visual asset candidates from raw research sources.

        Supports two calling conventions:
          1. New:   _build_asset_candidates_from_sources(sources=unified_list)
          2. Legacy: _build_asset_candidates_from_sources(firecrawl_data=..., scrapecreators_data=...)
        """
        if sources is None:
            sources = SegmentProducerAgent._normalize_sources(
                firecrawl_data or [], scrapecreators_data or [],
            )

        candidates: list[dict] = []
        for item in sources:
            url = item.get("url", "")
            if not url:
                continue
            source_type = item.get("source_type", "")
            base_score = SOURCE_QUALITY_TIERS.get(source_type, DEFAULT_SOURCE_QUALITY)
            candidate_type = _SOURCE_TYPE_TO_CANDIDATE_TYPE.get(source_type, "screenshot")
            candidate = {
                "type": candidate_type,
                "url": url,
                "reason": (
                    item.get("description") or item.get("title") or item.get("desc")
                    or "Candidate source"
                ),
                "source": item.get("source", source_type),
                "page_url": url,
                "title": item.get("title", ""),
                "relevance_score": base_score,
                "provenance": (
                    "primary_clip" if source_type == "tiktok_clip" else "supporting_context"
                ),
                "license_status": "unknown",
                "source_type": source_type,
            }
            candidates.append(candidate)
        return candidates

    @staticmethod
    def _score_keyword_match(
        text: str,
        keywords_lower: list[str],
        total_keywords: int,
    ) -> float:
        """Return fraction of keywords found in text."""
        matched = sum(1 for kw in keywords_lower if kw in text)
        return matched / total_keywords

    def _build_scrapecreators_candidates(
        self,
        items: list[dict],
        keywords_lower: list[str],
        total_keywords: int,
    ) -> list[dict]:
        """Build candidates from ScrapeCreators results with relevance scores."""
        candidates: list[dict] = []
        for item in items:
            url = item.get("url", "")
            if not url:
                continue
            title = item.get("title", "")
            relevance = self._score_keyword_match(
                title.lower(), keywords_lower, total_keywords,
            ) * 0.7 + 0.3

            # Download URL logic: prefer no-watermark → existing download → canonical
            download_url, download_url_type = self._resolve_download_url(item, url)

            candidates.append({
                "url": url,
                "type": "tiktok_clip",
                "source": "scrapecreators",
                "relevance_score": relevance,
                "provenance": "scrapecreators_tiktok",
                "download_url": download_url,
                "download_url_type": download_url_type,
                "play_count": item.get("play_count"),
                "title": title,
            })
        return candidates

    @staticmethod
    def _resolve_download_url(item: dict, fallback_url: str) -> tuple[str, str]:
        """Resolve download URL from item, preferring no-watermark variant."""
        if item.get("download_no_watermark_addr"):
            return item["download_no_watermark_addr"], "no_watermark"
        if item.get("download_url"):
            return item["download_url"], "standard"
        return fallback_url, "canonical"

    def _build_firecrawl_candidates(
        self,
        items: list[dict],
        keywords_lower: list[str],
        total_keywords: int,
    ) -> list[dict]:
        """Build candidates from Firecrawl results with relevance scores."""
        candidates: list[dict] = []
        for item in items:
            url = item.get("url", "")
            if not url:
                continue
            title = item.get("title", "")
            content = item.get("content", "")
            search_text = f"{title} {content}".lower()
            relevance = self._score_keyword_match(
                search_text, keywords_lower, total_keywords,
            ) * 0.6 + 0.2

            candidates.append({
                "url": url,
                "type": "article",
                "source": "firecrawl",
                "relevance_score": relevance,
                "provenance": "firecrawl_search",
                "title": title,
            })

            image_url = item.get("image")
            if image_url:
                candidates.append({
                    "url": image_url,
                    "type": "image",
                    "source": "firecrawl",
                    "relevance_score": relevance,
                    "provenance": "firecrawl_search",
                })
        return candidates

    @staticmethod
    def _ensure_minimum_coverage(candidates: list[dict]) -> None:
        """Add fallback text_card for important beats lacking video/image coverage."""
        video_types = {"tiktok_clip", "video"}
        image_types = {"photo", "screenshot", "image"}
        video_count = sum(1 for c in candidates if c.get("type") in video_types)
        image_count = sum(1 for c in candidates if c.get("type") in image_types)

        if video_count < 2 or image_count < 1:
            candidates.append({
                "type": "text_card",
                "source": "fallback",
                "relevance_score": 0.0,
                "provenance": "generated_fallback",
                "url": "",
            })

    def _build_asset_portfolio(
        self,
        scrapecreators_results: list[dict],
        firecrawl_results: list[dict],
        beat_keywords: list[str],
        is_important_beat: bool = False,
    ) -> list[dict]:
        """Build ranked asset portfolio with relevance scores and download metadata."""
        keywords_lower = [kw.lower() for kw in beat_keywords]
        total_keywords = len(keywords_lower) or 1

        candidates = self._build_scrapecreators_candidates(
            scrapecreators_results, keywords_lower, total_keywords,
        )
        candidates.extend(
            self._build_firecrawl_candidates(
                firecrawl_results, keywords_lower, total_keywords,
            ),
        )

        candidates.sort(key=lambda c: c["relevance_score"], reverse=True)

        if is_important_beat:
            self._ensure_minimum_coverage(candidates)

        return candidates

    # ── multi-source asset discovery ──────────────────────────────────────

    def _build_search_queries(self, topic: str, entities: dict) -> list[str]:
        """Derive search queries from topic + entity names."""
        queries = [topic]
        if not isinstance(entities, dict):
            return queries
        entity_list = entities.get("entities", [])
        if not isinstance(entity_list, list):
            return queries
        for entity in entity_list:
            if len(queries) >= 3:
                break
            name = entity.get("name", "") if isinstance(entity, dict) else str(entity)
            if name:
                queries.append(f"{name} {topic}")
        return queries

    def _discover_multi_source_assets(
        self,
        topic: str,
        entities: dict,
        config: Any,
    ) -> tuple[list[dict], list[dict]]:
        """Search YouTube, Tavily, Brave for additional asset candidates.

        Returns ``(sources, attempts)`` where ``attempts`` records which
        provider was queried, with what query, and how many results came back.
        """
        sources: list[dict] = []
        attempts: list[dict] = []
        search_queries = self._build_search_queries(topic, entities)

        # YouTube search (free, no API key needed)
        try:
            ytdlp = YtDlpService()
            for query in search_queries:
                results = ytdlp.search(query, max_results=3)
                sources.extend(results)
                attempts.append({
                    "provider": "youtube",
                    "query": query,
                    "result_count": len(results),
                })
        except Exception:
            logger.exception("YouTube multi-source search failed")
            attempts.append({
                "provider": "youtube",
                "query": ", ".join(search_queries),
                "result_count": 0,
                "error": "search_failed",
            })

        # Tavily search (if API key configured)
        tavily_key = getattr(config, "tavily_api_key", "")
        if tavily_key and isinstance(tavily_key, str):
            try:
                tavily = TavilyService(tavily_key)
                for query in search_queries:
                    results = tavily.search(query, max_results=3)
                    sources.extend(results)
                    attempts.append({
                        "provider": "tavily",
                        "query": query,
                        "result_count": len(results),
                    })
            except Exception:
                logger.exception("Tavily multi-source search failed")
                attempts.append({
                    "provider": "tavily",
                    "query": ", ".join(search_queries),
                    "result_count": 0,
                    "error": "search_failed",
                })

        # Brave search (if API key configured)
        brave_key = getattr(config, "brave_api_key", "")
        if brave_key and isinstance(brave_key, str):
            try:
                brave = BraveSearchService(brave_key)
                for query in search_queries:
                    results = brave.search_videos(query, max_results=3)
                    sources.extend(results)
                    attempts.append({
                        "provider": "brave",
                        "query": query,
                        "result_count": len(results),
                    })
            except Exception:
                logger.exception("Brave multi-source search failed")
                attempts.append({
                    "provider": "brave",
                    "query": ", ".join(search_queries),
                    "result_count": 0,
                    "error": "search_failed",
                })

        return sources, attempts

    @staticmethod
    def _merge_asset_candidates(*candidate_groups: list[dict]) -> list[dict]:
        """Merge asset candidate groups, deduplicating by URL."""
        seen_urls: set[str] = set()
        merged: list[dict] = []
        for group in candidate_groups:
            for candidate in group:
                url = candidate.get("url", "")
                key = url or json.dumps(candidate, sort_keys=True)
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                merged.append(candidate)
        return merged

    # ── per-beat candidate distribution ───────────────────────────────────

    @staticmethod
    def _extract_beat_keywords(beat: dict) -> list[str]:
        """Extract lowercase keywords from beat context for candidate matching.

        Combines keywords from visual_must_show, caption_keywords, and
        spoken_point. Filters words shorter than 3 characters.
        """
        keywords: set[str] = set()

        for chunk in beat.get("visual_must_show", "").split(","):
            for word in chunk.strip().split():
                if len(word) >= 3:
                    keywords.add(word.lower())

        for kw in beat.get("caption_keywords", []):
            kw_stripped = kw.strip().lower()
            if kw_stripped:
                keywords.add(kw_stripped)

        for word in beat.get("spoken_point", "").split():
            if len(word) >= 3:
                keywords.add(word.lower())

        return list(keywords)

    @staticmethod
    def _score_candidate_for_beat(
        candidate: dict, keywords_lower: list[str],
    ) -> float:
        """Score candidate relevance to a beat via keyword overlap (0.0-1.0)."""
        if not keywords_lower:
            return 0.0

        text = f"{candidate.get('title', '')} {candidate.get('reason', '')}".lower()
        if not text.strip():
            return 0.0

        matched = sum(1 for kw in keywords_lower if kw in text)
        return matched / len(keywords_lower)

    @staticmethod
    def _distribute_candidates_to_beats(
        story_beats: list[dict],
        global_candidates: list[dict],
        max_per_beat: int = 5,
    ) -> list[dict]:
        """Distribute global asset candidates to beats lacking candidates.

        Uses keyword matching to assign relevant candidates per beat.
        Beats that already have asset_candidates are left unchanged.
        Returns a NEW list of beat dicts (does not mutate input).
        """
        if not global_candidates:
            return [dict(b) for b in story_beats]

        result: list[dict] = []
        for beat in story_beats:
            beat_copy = dict(beat)
            if beat_copy.get("asset_candidates"):
                result.append(beat_copy)
                continue

            keywords = SegmentProducerAgent._extract_beat_keywords(beat_copy)
            if not keywords:
                result.append(beat_copy)
                continue

            scored: list[tuple[float, dict]] = []
            for candidate in global_candidates:
                score = SegmentProducerAgent._score_candidate_for_beat(
                    candidate, keywords,
                )
                if score > 0.0:
                    candidate_copy = dict(candidate)
                    candidate_copy["related_beat_id"] = beat_copy.get("beat_id")
                    scored.append((score, candidate_copy))

            scored.sort(key=lambda x: x[0], reverse=True)
            beat_copy["asset_candidates"] = [c for _, c in scored[:max_per_beat]]
            result.append(beat_copy)

        return result

    @staticmethod
    def _get_thumbnail_fallback_candidates(
        multi_sources: list[dict],
        output_dir: str,
        job_id: int,
    ) -> list[dict]:
        """Generate image candidates from YouTube thumbnails when video download fails."""
        candidates: list[dict] = []
        for source in multi_sources:
            if source.get("source_type") != "youtube_official":
                continue
            thumb_url = source.get("thumbnail_url", "")
            if not thumb_url:
                continue
            candidates.append({
                "type": "photo",
                "url": thumb_url,
                "source": "youtube_thumbnail",
                "reason": f"Thumbnail fallback for: {source.get('title', '')}",
                "relevance_score": SOURCE_QUALITY_TIERS.get("image", 0.70),
                "source_type": "image",
                "provenance": "youtube_thumbnail_fallback",
                "video_url": source.get("url", ""),
            })
        return candidates

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

        brief_path = segment_producer_brief_file(assets_cache, job_id)
        contract_path = segment_producer_contract_file(assets_cache, job_id)
        write_json(raw_scrapecreators_path, scrapecreators_data)
        write_json(raw_firecrawl_path, firecrawl_data)
        write_text(brief_path, brief)
        write_json(video_sources_path, scrapecreators_data)
        write_json(context_sources_path, firecrawl_data)
        write_json(music_candidates_path, [])
        write_json(entities_path, {})
        write_json(risk_flags_path, [])

        asset_candidates_path = base / "normalized" / "asset_candidates.json"
        write_json(asset_candidates_path, output.get("asset_candidates", []))

        provider_attempts_path = base / "normalized" / "provider_attempts.json"
        write_json(provider_attempts_path, output.get("provider_attempts", []))

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
            "asset_candidates": output.get("asset_candidates", []),
            "asset_candidates_path": str(asset_candidates_path),
            "story_beats": output.get("story_beats", []),
            "provider_attempts": output.get("provider_attempts", []),
            "provider_attempts_path": str(provider_attempts_path),
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
        job_id: int = 0,
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
                    "Segment Producer: source text truncated at %d chars "
                    "(%d of %d sources used to avoid LLM context overflow)",
                    total_chars,
                    len(trimmed),
                    len(sources),
                )
                break

        sources_text = "\n\n".join(trimmed)
        rules_text = "\n".join(f"- {r}" for r in safety_rules) if safety_rules else "None"

        logger.info(
            "Segment Producer: synthesizing research "
            "(%d sources, %d chars of text)",
            len(trimmed),
            len(sources_text),
        )

        settings = load_settings()
        cp_config = settings.content_planning
        agent_cfg = get_agent_config("segment_producer")
        llm = OpenRouterClient(trace_writer=self._trace_writer)
        messages = [
                {
                    "role": "system",
                    "content": SEGMENT_PRODUCER_PROMPT.format(
                        channel_description=channel_description or "a content creator",
                        language=language or "English",
                        tone=tone or "casual",
                        content_angle=content_angle or "trending topics",
                        rules_text=rules_text,
                        sources_text=sources_text,
                        target_duration_sec=cp_config.target_duration_sec if cp_config else 55,
                        hard_limit_sec=cp_config.hard_limit_sec if cp_config else 60,
                        estimated_words_per_second=cp_config.estimated_words_per_second if cp_config else 2.0,
                        max_stories_per_video=cp_config.max_stories_per_video if cp_config else 3,
                    ),
                },
                {
                    "role": "user",
                    "content": f"Research topic: {topic}",
                },
            ]
        if self._trace_writer:
            response = llm.chat_traced(
                model=agent_cfg["model"],
                messages=messages,
                job_id=job_id,
                agent=self.agent_name,
                task="synthesize_research",
                temperature=agent_cfg["temperature"],
                max_completion_tokens=agent_cfg.get("max_completion_tokens"),
                prompt_template_id="segment_producer.md",
            )
        else:
            response = llm.chat(
                model=agent_cfg["model"],
                messages=messages,
            temperature=agent_cfg["temperature"],
            max_completion_tokens=agent_cfg.get("max_completion_tokens"),
            )
        parsed = self._parse_synthesis_response(response["content"])
        return {
            "research_brief": parsed["research_brief"],
            "content_direction": parsed.get("content_direction"),
            "source_count": len(sources),
            "story_beats": parsed.get("story_beats", []),
            "format_decision": parsed.get("format_decision"),
            "asset_candidates": parsed.get("asset_candidates", []),
            "do_not_use": parsed.get("do_not_use", []),
            "verified_facts": parsed.get("verified_facts", []),
            "unverified_claims": parsed.get("unverified_claims", []),
            "reference_style": parsed.get("reference_style"),
        }

    def _parse_synthesis_response(self, content: str) -> dict[str, Any]:
        """Parse LLM synthesis response into research_brief + structured fields."""
        try:
            stripped = content.strip()
            if stripped.startswith("```"):
                stripped = stripped.removeprefix("```json").removeprefix("```")
                stripped = stripped.removesuffix("```").strip()
            data = json.loads(stripped)
            brief = data.get("research_brief", "")
            # Ensure brief is always a string for write_text downstream
            if isinstance(brief, dict):
                brief = json.dumps(brief, indent=2)
            return {
                "research_brief": str(brief),
                "content_direction": data.get("content_direction"),
                "story_beats": self._enrich_beats_with_evidence_contracts(
                    data.get("story_beats", [])
                ),
                "format_decision": data.get("format_decision"),
                "asset_candidates": data.get("asset_candidates", []),
                "do_not_use": data.get("do_not_use", []),
                "verified_facts": data.get("verified_facts", []),
                "unverified_claims": data.get("unverified_claims", []),
                "reference_style": data.get("reference_style"),
            }
        except (json.JSONDecodeError, KeyError):
            return {
                "research_brief": content,
                "content_direction": None,
                "story_beats": [],
                "format_decision": None,
                "asset_candidates": [],
                "do_not_use": [],
                "verified_facts": [],
                "unverified_claims": [],
                "reference_style": None,
            }

    @staticmethod
    def _enrich_beats_with_evidence_contracts(beats: list[dict]) -> list[dict]:
        """Populate evidence_contract on each beat from visual_must_show/not_show."""
        enriched = []
        for beat in beats:
            must_show = beat.get("visual_must_show", "")
            must_not_show = beat.get("visual_must_not_show", "")
            preferred = [s.strip() for s in must_show.split(",") if s.strip()] if must_show else []
            forbidden = [s.strip() for s in must_not_show.split(",") if s.strip()] if must_not_show else []
            beat["evidence_contract"] = {
                "preferred": preferred,
                "acceptable": [],
                "forbidden": forbidden,
            }
            enriched.append(beat)
        return enriched
