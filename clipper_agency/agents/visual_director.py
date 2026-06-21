"""Visual Director Agent — beat-driven visual planning with audio-first architecture.

Supports two planning paths:
1. Beat-driven (audio-first): Receives story_beats + timestamps from upstream
   agents and plans visuals aligned to the audio timeline.
2. Legacy (scene-based): Falls back to scene-based planning when beat data is
   not available.
"""

import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.config.schema import StoryBeat, WordTimestamp
from clipper_agency.core.artifacts import write_json
from clipper_agency.core.candidate_semantic_ranker import rank_candidates, select_best_candidate
from clipper_agency.core.frame_inspection_pipeline import run_frame_inspection_pipeline
from clipper_agency.core.inspection_cache import (
    compute_asset_content_hash,
    compute_cache_key,
    lookup,
    store,
)
from clipper_agency.core.media_probe import probe_video
from clipper_agency.core.paths import (
    agent_input_file,
    agent_output_file,
    ensure_agent_dir,
)
from clipper_agency.core.semantic_visual_review import score_visual_relevance
from clipper_agency.services.pexels import PexelsService
from clipper_agency.services.ytdlp import YtDlpService

logger = logging.getLogger(__name__)

# Visual hierarchy constants — higher priority first
_PRIORITY_SOURCE_CLIP = "source_clip"
_PRIORITY_SCREENSHOT = "screenshot"
_PRIORITY_PORTRAIT = "portrait"
_PRIORITY_TEXT_CARD = "text_card"
_PRIORITY_STOCK = "stock"
_PUNCTUATION_CHARS = ".,!?;:"

# Action types handled by _execute_action — used to normalize fallback types.
_EXECUTABLE_ACTION_TYPES = frozenset(
    {
        "tiktok_clip",
        "pexels_video",
        "pexels_image",
        "text_card",
    }
)


# ---------------------------------------------------------------------------
# Config-gating helpers for OCR and face detection
# ---------------------------------------------------------------------------


def _is_ocr_enabled() -> bool:
    """Check whether OCR inspection is enabled in quality config."""
    from clipper_agency.config.loader import load_settings

    return load_settings().quality.ocr.enabled


def _is_face_enabled() -> bool:
    """Check whether face detection is enabled in quality config."""
    from clipper_agency.config.loader import load_settings

    return load_settings().quality.face_detection.enabled


class VisualDirectorAgent(BaseAgent):
    """Sources video assets and plans scene layouts for video composition."""

    _IMAGE_SOURCES = frozenset({"pexels_image"})
    _VIDEO_SOURCES = frozenset({"tiktok_clip", "pexels_video", "tiktok", "pexels"})

    def __init__(self, trace_writer: Any | None = None) -> None:
        self._trace_writer = trace_writer
        self._candidate_inspections: list[dict] = []
        self._inspection_metrics: dict[str, dict] = {}
        self._face_data: dict[str, list] = {}
        self._runtime_inspection_enabled: bool = True

    @property
    def agent_name(self) -> str:
        return "visual_director"

    def execute(
        self,
        job_id: int,
        script: list[dict] | None = None,
        topic: str = "",
        source_urls: list[str] | None = None,
        output_dir: str = "",
        research_contract_path: str = "",
        research_brief_path: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._candidate_inspections = []
        self._inspection_metrics = {}
        self._face_data = {}
        story_beats = kwargs.get("story_beats")
        timestamps = kwargs.get("timestamps")
        do_not_use = kwargs.get("do_not_use", [])
        voiceover_duration_sec = kwargs.get("voiceover_duration_sec", 0.0)
        beat_timeline = kwargs.get("beat_timeline")

        # Detect beat-driven path: story_beats and timestamps present
        beat_driven = bool(story_beats) and bool(timestamps)

        scenes = script or []
        if not beat_driven:
            timeline_data = kwargs.get("timeline")
            if timeline_data:
                scenes = self._resolve_scene_data(script, timeline_data)

        assets_cache = kwargs.get("assets_cache", "")
        agent_dir = ""
        if assets_cache:
            agent_dir = ensure_agent_dir(assets_cache, job_id, "visual_director")
            write_json(
                agent_input_file(assets_cache, job_id, "visual_director"),
                {
                    "job_id": job_id,
                    "scene_count": len(story_beats) if beat_driven else len(scenes),
                    "topic": topic,
                    "has_research_data": bool(research_contract_path),
                    "beat_driven": beat_driven,
                },
            )

        logger.info(
            "Visual: beat_driven=%s beats=%d scenes=%d has_research=%s",
            beat_driven,
            len(story_beats or []),
            len(scenes),
            bool(research_contract_path),
        )

        try:
            if beat_driven:
                plan, assets = self._run_beat_driven_planning(
                    story_beats=story_beats,
                    timestamps=timestamps,
                    do_not_use=do_not_use,
                    voiceover_duration_sec=voiceover_duration_sec,
                    job_id=job_id,
                    output_dir=output_dir,
                    agent_dir=agent_dir,
                    topic=topic,
                    beat_timeline=beat_timeline,
                )
                pexels_videos: list[dict] = []
            elif research_contract_path:
                plan, assets = self._run_llm_planning(
                    scenes,
                    job_id,
                    output_dir,
                    research_contract_path,
                    research_brief_path,
                    agent_dir,
                )
                pexels_videos = []
            else:
                plan, assets, pexels_videos = self._run_legacy_planning(
                    scenes,
                    job_id,
                    topic,
                    output_dir,
                    source_urls,
                    agent_dir,
                )

            output = {
                "status": "completed",
                "assets": assets,
                "candidate_inspections": getattr(self, "_candidate_inspections", []),
            }
            self._write_artifacts(
                assets_cache,
                job_id,
                agent_dir,
                topic,
                plan,
                assets,
                output,
                beat_driven,
                research_contract_path,
                pexels_videos,
                source_urls,
            )

            logger.info("Visual: completed %d assets", len(assets))
            return output
        except Exception as e:
            logger.exception("Visual: asset sourcing failed")
            return {"status": "failed", "error": str(e), "assets": []}

    def _write_artifacts(
        self,
        assets_cache: str,
        job_id: int,
        agent_dir: str,
        topic: str,
        plan: list[dict],
        assets: list[dict],
        output: dict[str, Any],
        beat_driven: bool,
        research_contract_path: str,
        pexels_videos: list[dict],
        source_urls: list[str] | None,
    ) -> None:
        """Write output JSON and provenance metadata to agent workspace."""
        if not agent_dir:
            return
        write_json(
            agent_output_file(assets_cache, job_id, "visual_director"),
            output,
        )
        clips = self._build_provenance(assets)
        provenance_data: dict[str, Any] = {
            "topic": topic,
            "scene_count": len(plan),
            "clips": clips,
            "beat_driven": beat_driven,
        }
        if not research_contract_path and not beat_driven:
            provenance_data["pexels_results"] = len(pexels_videos)
            provenance_data["source_url_count"] = len(source_urls or [])
        write_json(f"{agent_dir}/provenance.json", provenance_data)

    # ------------------------------------------------------------------
    # Beat-driven planning (audio-first)
    # ------------------------------------------------------------------

    def _run_beat_driven_planning(
        self,
        story_beats: list[dict],
        timestamps: list[dict],
        do_not_use: list[str],
        voiceover_duration_sec: float,
        job_id: int,
        output_dir: str,
        agent_dir: str,
        topic: str = "",
        beat_timeline: list | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Beat-driven planning aligned to audio timeline. Returns (plan, assets)."""
        parsed_beats = [StoryBeat(**b) for b in story_beats]
        parsed_ts = [WordTimestamp(**t) for t in timestamps]

        # ADR 0020 / RC-5: honor the canonical timeline even when empty.
        # build_canonical_timeline returns [] on degenerate input; the falsy
        # `if beat_timeline:` guard treated [] like a missing timeline and
        # fell through to the PRIVATE divergent recompute. `is not None`
        # preserves the single-source-of-truth contract (timeline_to_duration_map
        # tolerates [] safely -> {}).
        if beat_timeline is not None:
            from clipper_agency.core.beat_timeline import timeline_to_duration_map

            beat_durations = timeline_to_duration_map(beat_timeline)
        else:
            beat_durations = self._calculate_beat_durations(parsed_beats, parsed_ts)

        scenes_dir = (
            f"{agent_dir}/scenes" if agent_dir else f"{output_dir or 'outputs'}/job_{job_id}"
        )
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)

        llm_plan = self._plan_beats_with_llm(
            parsed_beats=parsed_beats,
            beat_durations=beat_durations,
            do_not_use=do_not_use,
            voiceover_duration_sec=voiceover_duration_sec,
            topic=topic,
            job_id=job_id,
        )

        if llm_plan is not None:
            plan = llm_plan
        else:
            plan = self._plan_beats_fallback(
                parsed_beats,
                beat_durations,
                do_not_use,
            )

        allowed_beat_ids = [beat.beat_id for beat in parsed_beats]
        plan = self._normalize_beat_plan(plan, allowed_beat_ids)
        plan = self._deduplicate_llm_plan_urls(plan, do_not_use)

        plan, self._candidate_inspections = self._inspect_and_select_candidates(
            plan,
            parsed_beats,
            job_id,
            agent_dir,
        )

        # PR 6: re-attach each action's clip window from its beat's matching candidate
        # (by source_url). Works for both the LLM plan and the fallback plan — the LLM
        # generates actions from scratch and does not carry candidate metadata, so this
        # post-pass restores source_start_sec/source_end_sec before execution.
        plan = self._attach_candidate_windows(plan, parsed_beats)

        assets = self._execute_beat_plan(plan, scenes_dir)

        if agent_dir:
            write_json(f"{agent_dir}/scene_plan.json", plan)
        return plan, assets

    def _attach_candidate_windows(
        self, plan: list[dict], parsed_beats: list[StoryBeat]
    ) -> list[dict]:
        """PR 6 — copy source_start_sec/source_end_sec from each beat's matching candidate
        (by ``source_url``) onto the planned action.

        The LLM plan and ``_apply_best_candidate`` rebuild actions from ``source_url`` and do
        not carry candidate-level window metadata, so this post-pass restores the clip window
        the qualification boundary (PR 5) attached to each qualified candidate. Beats whose
        action has no matching candidate url are left unchanged (default 0.0/None downstream).
        """
        beats_by_id = {b.beat_id: b for b in parsed_beats}
        for item in plan:
            bid = item.get("beat_id")
            beat = beats_by_id.get(bid) if isinstance(bid, int) else None
            action = item.get("action") if isinstance(item, dict) else None
            if not beat or not isinstance(action, dict):
                continue
            url = action.get("source_url", "")
            if not url:
                continue
            match = next((c for c in beat.asset_candidates if c.url == url), None)
            if match is None:
                continue
            action["source_start_sec"] = match.source_start_sec
            action["source_end_sec"] = match.source_end_sec
        return plan

    def _calculate_beat_durations(
        self,
        beats: list[StoryBeat],
        timestamps: list[WordTimestamp],
    ) -> dict[int, float]:
        """Calculate exact duration per beat from audio word timestamps.

        Each beat's word_range maps to indices in the full voiceover text.
        Duration = last_word.end - first_word.start for the beat's word range.

        Falls back to evenly distributed duration when word ranges don't align.
        """
        total_ts_duration = timestamps[-1].end - timestamps[0].start if timestamps else 0.0
        durations: dict[int, float] = {}

        for beat in beats:
            beat_words = beat.overlay_text.split() if beat.overlay_text else []
            if beat_words and timestamps:
                first_word = beat_words[0].lower().strip(_PUNCTUATION_CHARS)
                last_word = beat_words[-1].lower().strip(_PUNCTUATION_CHARS)
                start_time, end_time = self._find_word_range_timestamps(
                    first_word,
                    last_word,
                    timestamps,
                )
                if start_time is not None and end_time is not None:
                    durations[beat.beat_id] = round(end_time - start_time, 3)
                else:
                    durations[beat.beat_id] = 0.0
            else:
                durations[beat.beat_id] = 0.0

        self._distribute_zero_beat_durations(durations, total_ts_duration)
        return durations

    @staticmethod
    def _find_word_range_timestamps(
        first_word: str,
        last_word: str,
        timestamps: list[WordTimestamp],
    ) -> tuple[float | None, float | None]:
        """Find start/end times for a beat's word range in the timestamp list."""
        start_time = None
        end_time = None
        for ts in timestamps:
            ts_clean = ts.word.lower().strip(_PUNCTUATION_CHARS)
            if ts_clean == first_word and start_time is None:
                start_time = ts.start
            if ts_clean == last_word:
                end_time = ts.end
        return start_time, end_time

    @staticmethod
    def _distribute_zero_beat_durations(
        durations: dict[int, float],
        total_ts_duration: float,
    ) -> None:
        """Distribute remaining duration evenly among beats with zero duration."""
        zero_beats = [bid for bid, d in durations.items() if d <= 0.0]
        if not zero_beats or total_ts_duration <= 0.0:
            return
        assigned_total = sum(d for d in durations.values() if d > 0.0)
        remaining = total_ts_duration - assigned_total
        per_beat = max(remaining / len(zero_beats), 0.5)
        for bid in zero_beats:
            durations[bid] = round(per_beat, 3)

    def _plan_beats_with_llm(
        self,
        parsed_beats: list[StoryBeat],
        beat_durations: dict[int, float],
        do_not_use: list[str],
        voiceover_duration_sec: float,
        topic: str,
        job_id: int = 0,
    ) -> list[dict] | None:
        """LLM plans per-beat visual strategy using beat-driven instructions."""
        try:
            from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
            from clipper_agency.config.loader import get_agent_config
            from clipper_agency.llm.client import OpenRouterClient

            agent_cfg = get_agent_config("visual_director")
            llm = OpenRouterClient(trace_writer=self._trace_writer)
            prompt_text = load_prompt("visual_director", "", PROMPTS_DIR)
            safety_rules_text = "None"

            beats_payload = []
            for beat in parsed_beats:
                duration = beat_durations.get(beat.beat_id, 5.0)
                assets_info = [
                    {"type": a.type, "url": a.url, "reason": a.reason}
                    for a in beat.asset_candidates
                ]
                beats_payload.append(
                    {
                        "beat_id": beat.beat_id,
                        "role": beat.role,
                        "narration_goal": beat.narration_goal,
                        "spoken_point": beat.spoken_point,
                        "visual_must_show": beat.visual_must_show,
                        "visual_must_not_show": beat.visual_must_not_show,
                        "overlay_text": beat.overlay_text,
                        "caption_keywords": beat.caption_keywords,
                        "duration_sec": duration,
                        "asset_candidates": assets_info,
                        "fallback": {
                            "type": beat.fallback.type,
                            "headline": beat.fallback.headline,
                            "image_search": beat.fallback.image_search,
                        },
                        "risk_note": beat.risk_note,
                    }
                )

            user_content = json.dumps(
                {
                    "mode": "beat_driven",
                    "topic": topic,
                    "story_beats": beats_payload,
                    "do_not_use": do_not_use,
                    "voiceover_duration_sec": voiceover_duration_sec,
                    "total_beats": len(parsed_beats),
                },
                ensure_ascii=False,
            )

            messages = [
                {
                    "role": "system",
                    "content": prompt_text.format(
                        content_angle="TikTok infotainment",
                        language="Indonesian",
                        safety_rules_text=safety_rules_text,
                    ),
                },
                {"role": "user", "content": user_content},
            ]
            if self._trace_writer:
                response = llm.chat_traced(
                    model=agent_cfg["model"],
                    messages=messages,
                    job_id=job_id,
                    agent=self.agent_name,
                    task="plan_beats",
                    temperature=agent_cfg["temperature"],
                    max_completion_tokens=agent_cfg.get("max_completion_tokens"),
                    prompt_template_id="visual_director.md",
                )
            else:
                response = llm.chat(
                    model=agent_cfg["model"],
                    messages=messages,
                    temperature=agent_cfg["temperature"],
                    max_completion_tokens=agent_cfg.get("max_completion_tokens"),
                )

            parsed = json.loads(response["content"].strip().strip("```json").strip("```").strip())
            return parsed.get("scenes", [])

        except Exception as e:
            logger.warning("Beat-driven LLM planning failed: %s", e)
            return None

    def _plan_beats_fallback(
        self,
        beats: list[StoryBeat],
        beat_durations: dict[int, float],
        do_not_use: list[str],
    ) -> list[dict]:
        """Deterministic fallback when LLM fails: select visual per beat hierarchy."""
        used_urls: set[str] = set(do_not_use)
        plan: list[dict] = []
        for beat in beats:
            duration = beat_durations.get(beat.beat_id, 5.0)
            action = self._select_visual_for_beat(beat, list(used_urls))
            source_url = action.get("source_url", "")
            if source_url:
                used_urls.add(source_url)
            plan.append(
                {
                    "scene_number": beat.beat_id,
                    "beat_id": beat.beat_id,
                    "role": beat.role,
                    "reasoning": f"Fallback plan for beat {beat.beat_id} ({beat.role})",
                    "treatment": self._default_treatment_for_role(beat.role),
                    "target_duration": duration,
                    "transition_in": "crossfade",
                    "transition_out": "crossfade",
                    "action": action,
                    "fallback": {
                        "type": "text_card",
                        "headline": beat.overlay_text[:50]
                        if beat.overlay_text
                        else f"Beat {beat.beat_id}",
                        "style": "news_card",
                        "image_search": beat.fallback.image_search or topic_safe_query(beat),
                    },
                }
            )
        return plan

    def _select_visual_for_beat(
        self,
        beat: StoryBeat,
        do_not_use: list[str],
    ) -> dict:
        """Select visual action for a beat using the priority hierarchy.

        Hierarchy:
        1. Direct source clip (TikTok/Instagram from asset_candidates)
        2. Official screenshot (from asset_candidates)
        3. Subject portrait with Ken Burns (Pexels search)
        4. Text card with headline (fallback text card)
        5. Generic stock — ONLY if beat is abstract (no named subjects)
        """
        do_not_use_set = set(do_not_use)

        # Tier 1: Direct source clip
        clip = self._find_candidate_by_type(
            beat.asset_candidates,
            "tiktok_clip",
            do_not_use_set,
        )
        if clip:
            return {"type": "tiktok_clip", "source_url": clip.url}

        # Tier 2: Official screenshot
        screenshot = self._find_candidate_by_type(
            beat.asset_candidates,
            "screenshot",
            do_not_use_set,
        )
        if screenshot:
            return {
                "type": "pexels_image",
                "search_query": beat.fallback.image_search or beat.spoken_point[:50],
                "source_url": screenshot.url,
            }

        # Tier 3: Subject portrait with Ken Burns (Pexels search)
        search_query = (
            beat.fallback.image_search or beat.visual_must_show[:60] or beat.spoken_point[:50]
        )
        if search_query and not _is_abstract_beat(beat):
            return {
                "type": "pexels_image",
                "search_query": search_query,
            }

        # Tier 4: Text card with headline
        headline = beat.overlay_text or beat.fallback.headline or f"Beat {beat.beat_id}"
        return {
            "type": "text_card",
            "headline": headline[:60],
            "style": "news_card",
            "image_search": beat.fallback.image_search or search_query,
            "bg_color": "",
        }

    @staticmethod
    def _find_candidate_by_type(
        candidates: list,
        candidate_type: str,
        do_not_use_set: set[str],
    ):
        """Find first asset candidate matching type not in do_not_use set."""
        for candidate in candidates:
            if candidate.url in do_not_use_set:
                continue
            if candidate.type == candidate_type:
                return candidate
        return None

    def _execute_beat_plan(
        self,
        plan: list[dict],
        scenes_dir: str,
    ) -> list[dict]:
        """Execute beat-driven plan, producing assets compatible with composer."""
        pexels = PexelsService()
        ytdlp = YtDlpService()
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)

        assets: list[dict] = []
        for item in plan:
            scene_id = item.get("scene_number", item.get("beat_id", 0))
            action = item.get("action", {})
            fallback = item.get("fallback")
            result = self._execute_action(
                action,
                scene_id,
                scenes_dir,
                pexels,
                ytdlp,
            )

            if result is None and fallback:
                logger.info("Beat %d: primary failed, using fallback", scene_id)
                result = self._execute_action(
                    fallback,
                    scene_id,
                    scenes_dir,
                    pexels,
                    ytdlp,
                )

            if result:
                asset = {"scene": scene_id, **result}
            else:
                asset = {"scene": scene_id, "source": "none", "path": ""}

            # Pass through beat metadata for composer compatibility
            for field in (
                "treatment",
                "target_duration",
                "transition_in",
                "transition_out",
                "beat_id",
                "role",
                "start_time",
                "duration",
            ):
                if field in item:
                    asset[field] = item[field]

            asset = self._apply_default_treatment(asset)
            assets.append(asset)

        return assets

    @staticmethod
    def _default_treatment_for_role(role: str) -> str:
        """Select default treatment based on beat role."""
        role_treatments = {
            "hook": "hook_big_caption",
            "closing_cta": "fade_to_black",
        }
        return role_treatments.get(role, "broll_standard")

    @staticmethod
    def _normalize_beat_plan(plan: list[dict], allowed_beat_ids: list[int]) -> list[dict]:
        """Keep only allowed beat IDs and preserve narrative beat order."""
        by_beat_id = {item.get("beat_id", item.get("scene_number")): item for item in plan}
        normalized: list[dict] = []
        for beat_id in allowed_beat_ids:
            item = dict(by_beat_id.get(beat_id, {}))
            item.setdefault("scene_number", beat_id)
            item["beat_id"] = beat_id
            normalized.append(item)
        return normalized

    @staticmethod
    def _deduplicate_llm_plan_urls(plan: list[dict], do_not_use: list[str]) -> list[dict]:
        """Remove duplicate source_urls from LLM-generated plan actions."""
        used_urls: set[str] = set(do_not_use)
        deduped: list[dict] = []
        for item in plan:
            action = dict(item.get("action", {}))
            source_url = action.get("source_url", "")
            if source_url and source_url in used_urls:
                action.pop("source_url", None)
            if source_url:
                used_urls.add(source_url)
            item = dict(item)
            item["action"] = action
            deduped.append(item)
        return deduped

    def _inspect_and_select_candidates(
        self,
        plan: list[dict],
        parsed_beats: list[StoryBeat],
        job_id: int,
        agent_dir: str,
    ) -> tuple[list[dict], list[dict]]:
        """Inspect candidates semantically and update plan with best selections.

        Returns (updated_plan, candidate_inspections).
        On any error, returns the original plan unchanged.
        """
        try:
            return self._do_inspect_and_select(plan, parsed_beats, job_id, agent_dir)
        except Exception as exc:
            logger.warning("Candidate inspection skipped (error): %s", exc)
            return plan, []

    def _do_inspect_and_select(
        self,
        plan: list[dict],
        parsed_beats: list[StoryBeat],
        job_id: int,
        agent_dir: str,
    ) -> tuple[list[dict], list[dict]]:
        """Inner implementation of candidate inspection."""
        beat_by_id = {b.beat_id: b for b in parsed_beats}
        cache_dir = f"{agent_dir}/inspection_cache" if agent_dir else ""
        all_inspections: list[dict] = []

        for plan_item in plan:
            beat_id = plan_item.get("beat_id")
            beat = beat_by_id.get(beat_id)
            if not beat or not beat.asset_candidates:
                continue

            candidates = self._collect_candidate_scores(
                beat,
                plan_item,
                job_id,
                cache_dir,
                agent_dir,
                all_inspections,
            )
            self._apply_best_candidate(plan_item, beat, candidates)

        return plan, all_inspections

    def _collect_candidate_scores(
        self,
        beat: StoryBeat,
        plan_item: dict,
        job_id: int,
        cache_dir: str,
        agent_dir: str,
        all_inspections: list[dict],
    ) -> list[dict]:
        """Build scored candidate list for a single beat."""
        candidates: list[dict] = []
        for candidate in beat.asset_candidates:
            scored = self._score_one_candidate(
                candidate,
                beat,
                plan_item,
                job_id,
                cache_dir,
                agent_dir,
            )
            if scored:
                candidates.append(scored)
                all_inspections.append(scored.get("inspection_diag", {}))
        return candidates

    def _score_one_candidate(
        self,
        candidate: Any,
        beat: StoryBeat,
        plan_item: dict,
        job_id: int,
        cache_dir: str,
        agent_dir: str = "",
    ) -> dict | None:
        """Score a single candidate using cache or multimodal inspection."""
        asset_id = f"{candidate.type}_{candidate.url[:40]}"
        cache_key = compute_cache_key(
            asset_path=candidate.url,
            asset_hash=compute_asset_content_hash(candidate),
            beat_claim=beat.spoken_point,
            evidence_contract_hash="",
            model="multimodal",
            prompt_version="1.0",
        )
        cached = lookup(cache_dir, cache_key) if cache_dir else None
        inspection = cached or self._run_multimodal_inspection(
            candidate,
            beat,
            job_id,
            cache_dir,
            cache_key,
            agent_dir=agent_dir,
        )
        if inspection is None:
            return None

        rel = score_visual_relevance(
            beat={"beat_id": beat.beat_id, "claim": beat.spoken_point},
            asset_inspection=inspection,
        )
        return {
            "asset_id": asset_id,
            "beat_id": str(beat.beat_id),
            "role": beat.role,
            "treatment": plan_item.get("treatment", ""),
            "inspection": inspection,
            "visual_relevance": {
                "person_match": rel.person_match,
                "event_match": rel.event_match,
                "claim_support": rel.claim_support,
                "visual_quality": rel.visual_quality,
            },
            "cleanliness_score": self._compute_cleanliness_score(candidate, inspection),
            "candidate": candidate,
            "inspection_diag": {
                "beat_id": beat.beat_id,
                "asset_id": asset_id,
                "decision": inspection.get("decision", "unknown"),
                "from_cache": cached is not None,
            },
        }

    def _compute_cleanliness_score(
        self,
        candidate: Any,
        inspection: dict,
    ) -> float:
        """Compute cleanliness score from OCR/face metrics or fall back to proxy.

        When Worker A/B have stored inspection metrics for this candidate's URL,
        call ``score_source_cleanliness()`` with the actual values.  Otherwise
        fall back to the legacy ``visual_quality`` proxy from the VLM inspection.

        All exceptions are caught and logged at debug level to avoid crashing
        the pipeline.
        """
        metrics = self._inspection_metrics.get(getattr(candidate, "url", ""), None)
        if not metrics:
            return inspection.get("visual_quality", 0.5)

        try:
            from clipper_agency.core.source_cleanliness import score_source_cleanliness

            result = score_source_cleanliness(
                ocr_text_area_ratio=metrics.get("ocr_text_area_ratio", 0.0),
                has_logo=metrics.get("has_logo", False),
                logo_coverage_ratio=metrics.get("logo_coverage_ratio", 0.0),
                safe_crop_available=metrics.get("safe_crop_available", False),
                face_obstructed=metrics.get("face_obstructed", False),
                resolution=metrics.get("resolution", (1920, 1080)),
                has_burned_captions=metrics.get("has_burned_captions", False),
            )
            return result.get("cleanliness_score", inspection.get("visual_quality", 0.5))
        except Exception:
            logger.debug(
                "cleanliness scoring failed for %s", getattr(candidate, "url", ""), exc_info=True
            )
            return inspection.get("visual_quality", 0.5)

    def _run_ocr_and_face_on_frames(
        self,
        frame_paths: list[str],
    ) -> tuple[str, list[dict]]:
        """Run OCR and face detection on extracted keyframes.

        Returns:
            (ocr_text, face_results) — aggregated OCR text from all frames
            and a list of face detection result dicts (one per frame).
        """
        ocr_text = ""
        face_results: list[dict] = []

        if not frame_paths:
            return ocr_text, face_results

        # OCR inspection
        if _is_ocr_enabled():
            try:
                from clipper_agency.core.ocr_adapter import PaddleOCRAdapter

                adapter = PaddleOCRAdapter()
                texts: list[str] = []
                for frame_path in frame_paths:
                    result = adapter.inspect(frame_path, 0.0)
                    for region in result.regions:
                        texts.append(region.text)
                ocr_text = " ".join(texts)
            except Exception:
                logger.debug("OCR inspection failed", exc_info=True)

        # Face detection
        if _is_face_enabled():
            try:
                from clipper_agency.core.face_adapter import MediaPipeFaceDetector

                detector = MediaPipeFaceDetector()
                for frame_path in frame_paths:
                    result = detector.detect(frame_path, 0.0)
                    face_results.append(
                        {
                            "frame_path": frame_path,
                            "faces": [
                                {"bbox": f.bbox, "confidence": f.confidence} for f in result.faces
                            ],
                            "provider": result.provider,
                        }
                    )
            except Exception:
                logger.debug("Face detection failed", exc_info=True)

        return ocr_text, face_results

    def _run_multimodal_inspection(
        self,
        candidate: Any,
        beat: StoryBeat,
        job_id: int,
        cache_dir: str,
        cache_key: str,
        agent_dir: str = "",
    ) -> dict | None:
        """Attempt multimodal inspection; return inspection dict or None."""
        try:
            from clipper_agency.llm.client import OpenRouterClient
            from clipper_agency.llm.multimodal_client import MultimodalInspectionClient

            frame_paths = self._extract_candidate_frames(candidate, agent_dir)

            # --- Enhanced frame inspection pipeline (config-gated) ---
            enhanced_paths = self._try_enhanced_frame_inspection(
                candidate,
                beat,
                job_id,
                agent_dir,
            )
            if enhanced_paths is not None:
                frame_paths = enhanced_paths
            # --- END enhanced pipeline ---

            # --- OCR + face detection on extracted keyframes ---
            ocr_text, face_data = self._run_ocr_and_face_on_frames(frame_paths)
            if face_data:
                self._face_data[candidate.url] = face_data
            # --- END OCR + face ---

            client = OpenRouterClient(trace_writer=self._trace_writer)
            inspector = MultimodalInspectionClient(
                client=client,
                trace_writer=self._trace_writer,
            )
            result = inspector.inspect_asset(
                job_id=job_id,
                beat_id=str(beat.beat_id),
                asset_id=f"{candidate.type}_{candidate.url[:40]}",
                beat={
                    "beat_id": beat.beat_id,
                    "role": beat.role,
                    "narration_goal": beat.narration_goal,
                    "spoken_point": beat.spoken_point,
                },
                frame_paths=frame_paths,
                ocr_text=ocr_text,
                source_metadata={"url": candidate.url, "type": candidate.type},
            )
            if cache_dir and result.get("decision") != "error":
                store(cache_dir, cache_key, result)
            return result
        except Exception as exc:
            logger.debug("Multimodal inspection skipped for %s: %s", candidate.url, exc)
            return None

    def _try_enhanced_frame_inspection(
        self,
        candidate: Any,
        beat: StoryBeat,
        job_id: int,
        agent_dir: str,
    ) -> list[str] | None:
        """Run the full frame inspection pipeline for video candidates.

        Returns enhanced frame paths (deduplicated + hashed) when applicable,
        or None when the pipeline should be skipped (non-video, disabled, no
        local file, or any error).
        """
        if not self._runtime_inspection_enabled:
            return None

        _VIDEO_TYPES = {"tiktok_clip"}
        if candidate.type not in _VIDEO_TYPES:
            return None

        if not agent_dir:
            return None

        try:
            frames_dir = Path(agent_dir) / "candidate_frames"
            video_name = f"vid_{hash(candidate.url) & 0xFFFF}.mp4"
            video_path = frames_dir / video_name

            if not video_path.exists():
                return None

            asset_id = f"{candidate.type}_{candidate.url[:40]}"
            from clipper_agency.config.loader import load_settings

            _fi = load_settings()
            manifest = run_frame_inspection_pipeline(
                video_path=str(video_path),
                job_id=job_id,
                beat_id=str(beat.beat_id),
                asset_id=asset_id,
                cache_root=agent_dir,
                allowed_base_dir=agent_dir,
                max_frames=_fi.frame_inspection_max_frames,
                interval_sec=_fi.frame_inspection_interval_sec,
            )

            paths = [f.path for f in manifest.frames if f.path]
            return paths if paths else None
        except Exception as exc:
            logger.debug(
                "Enhanced frame inspection failed for %s: %s",
                candidate.url,
                exc,
            )
            return None

    def _extract_candidate_frames(
        self,
        candidate: Any,
        agent_dir: str,
    ) -> list[str]:
        """Download a candidate asset and return local frame paths for inspection.

        Returns empty list for text types or on any download error (graceful
        degradation — the inspector can still work from URL/metadata alone).
        """
        _IMAGE_TYPES = {"photo", "screenshot"}
        _VIDEO_TYPES = {"tiktok_clip"}
        _SKIP_TYPES = {"text_card", "text_overlay"}

        if candidate.type in _SKIP_TYPES or not candidate.url:
            return []

        if not agent_dir:
            return []

        frames_dir = Path(agent_dir) / "candidate_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        if candidate.type in _IMAGE_TYPES:
            return self._download_image_frame(candidate.url, frames_dir)

        if candidate.type in _VIDEO_TYPES:
            return self._download_video_frame(candidate.url, frames_dir)

        return []

    def _download_image_frame(
        self,
        url: str,
        frames_dir: Path,
    ) -> list[str]:
        """Download an image URL and return its local path as a single frame."""
        import httpx

        try:
            ext = Path(url.split("?")[0]).suffix or ".jpg"
            dest = frames_dir / f"img_{hash(url) & 0xFFFF}{ext}"
            if dest.exists():
                return [str(dest)]
            with httpx.Client(timeout=30) as client:
                resp = client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            return [str(dest)]
        except Exception as exc:
            logger.debug("Image download for inspection failed: %s", exc)
            return []

    def _download_video_frame(
        self,
        url: str,
        frames_dir: Path,
    ) -> list[str]:
        """Download a video and extract one frame for inspection."""
        from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming
        from clipper_agency.core.frame_extractor import extract_frames

        try:
            video_dest = frames_dir / f"vid_{hash(url) & 0xFFFF}.mp4"
            if not video_dest.exists():
                ytdlp = YtDlpService()
                result = ytdlp.download(url, str(video_dest))
                if not result or not result.path:
                    return []
            frame_dir = frames_dir / "extracted"
            frame_dir.mkdir(parents=True, exist_ok=True)
            frames = extract_frames(
                video_path=str(video_dest),
                timestamps=[0.5],
                output_dir=str(frame_dir),
                ffmpeg_runner=run_ffmpeg_streaming,
            )
            return [f.path for f in frames if f.path]
        except Exception as exc:
            logger.debug("Video frame extraction for inspection failed: %s", exc)
            return []

    def _apply_best_candidate(
        self,
        plan_item: dict,
        beat: StoryBeat,
        candidates: list[dict],
    ) -> None:
        """Rank candidates and replace plan action with best one if accepted.

        When all candidates are rejected (or only fallback accepted), the
        original LLM-planned action is replaced with the beat's fallback so
        that a rejected asset is never rendered.
        """
        if not candidates:
            return
        beat_dict = {"beat_id": beat.beat_id}
        ranked = rank_candidates(beat_dict, candidates)
        best = select_best_candidate(ranked)
        if best and best.decision == "accept" and best.asset_id != "fallback":
            matched = next(
                (c for c in candidates if c.get("asset_id") == best.asset_id),
                None,
            )
            if matched:
                cand = matched.get("candidate")
                plan_item["action"] = self._candidate_to_action(cand, beat)
                return
        # All candidates rejected → use fallback text card, not the original
        # LLM action which references a now-rejected asset.
        # All candidates rejected → use fallback, not the original LLM action
        # which references a now-rejected asset.
        fallback = plan_item.get("fallback")
        if fallback:
            action = dict(fallback)
            # Normalize unsupported fallback types to text_card so
            # _execute_action always has a handler (see discussion_r3410008182).
            if action.get("type") not in _EXECUTABLE_ACTION_TYPES:
                action["type"] = "text_card"
            plan_item["action"] = action
        else:
            plan_item["action"] = {
                "type": "text_card",
                "headline": (beat.overlay_text or f"Beat {beat.beat_id}")[:60],
                "style": "news_card",
            }

    @staticmethod
    def _candidate_to_action(candidate: Any, beat: StoryBeat) -> dict:
        """Convert an AssetCandidate into a plan action dict."""
        if candidate.type == "tiktok_clip":
            return {"type": "tiktok_clip", "source_url": candidate.url}
        if candidate.type == "screenshot":
            return {
                "type": "pexels_image",
                "source_url": candidate.url,
                "search_query": beat.fallback.image_search or beat.spoken_point[:50],
            }
        if candidate.type == "photo":
            return {
                "type": "pexels_image",
                "source_url": candidate.url,
                "search_query": beat.fallback.image_search or beat.spoken_point[:50],
            }
        return {"type": "text_card", "headline": beat.overlay_text[:60]}

    def _resolve_beat_plan_assets(
        self,
        plan: list[dict],
        do_not_use: list[str],
    ) -> list[dict]:
        """Resolve source_urls for each beat, replacing duplicates/missing with candidates.

        For each beat, if the current source_url is missing, blocked, or already
        used, attempt to find a replacement from ``asset_candidates``.  If no
        usable URL exists for a ``tiktok_clip`` action, fall back to text_card.
        """
        blocked: set[str] = set(do_not_use)
        used_urls: set[str] = set()
        resolved: list[dict] = []

        for beat in plan:
            beat = dict(beat)
            action = dict(beat.get("action", {}))
            source_url: str | None = action.get("source_url")

            def _is_url_usable(url: str | None) -> bool:
                return bool(url) and url not in blocked and url not in used_urls

            if _is_url_usable(source_url):
                used_urls.add(source_url)  # type: ignore[arg-type]
            else:
                replacement = self._find_replacement_url(
                    beat.get("asset_candidates", []),
                    action.get("type", ""),
                    blocked,
                    used_urls,
                )
                if replacement:
                    action["source_url"] = replacement
                    used_urls.add(replacement)
                else:
                    action.pop("source_url", None)

            if action.get("type") == "tiktok_clip" and not action.get("source_url"):
                action = {
                    "type": "text_card",
                    "reason": "No usable source URL for tiktok_clip; fallback to text_card",
                }

            beat["action"] = action
            resolved.append(beat)
        return resolved

    @staticmethod
    def _find_replacement_url(
        candidates: list[dict],
        action_type: str,
        blocked: set[str],
        used_urls: set[str],
    ) -> str | None:
        """Return the first candidate URL matching action type and not blocked/used."""
        for candidate in candidates:
            url = candidate.get("url", "")
            cand_type = candidate.get("type", "")
            if not url or url in blocked or url in used_urls:
                continue
            if cand_type == action_type:
                return url
            if cand_type == "video" and action_type == "tiktok_clip" and "tiktok.com" in url:
                return url
        return None

    def _plan_intro_card(
        self,
        video_format: str,
        topic: str,
    ) -> dict | None:
        """Plan an intro card (scene 0) for roundup video formats.

        Returns ``None`` for non-roundup formats (single story, text-only).
        """
        _ROUNDUP_FORMATS = frozenset({"three_story_roundup", "two_story_highlight"})

        if video_format not in _ROUNDUP_FORMATS:
            return None

        return {
            "scene_number": 0,
            "beat_id": 0,
            "role": "intro_card",
            "target_duration": 3.0,
            "action": {
                "type": "text_card",
                "headline": topic,
                "style": "breaking_news",
            },
        }

    # ------------------------------------------------------------------
    # Legacy planning paths (kept for backward compatibility)
    # ------------------------------------------------------------------

    def _resolve_scene_data(
        self,
        script: list[dict] | None,
        timeline_data: list[dict] | None = None,
    ) -> list[dict]:
        """Merge script scenes with reconciled timeline data.

        When timeline is present, use its durations as source-of-truth.
        Falls back to raw script when no timeline available.
        """
        script = script or []
        if timeline_data:
            return [
                {
                    "scene": t.get("scene", i + 1),
                    "role": t.get("role", "body"),
                    "text": t.get("text", ""),
                    "target_duration": t.get("target_duration_sec", 5),
                }
                for i, t in enumerate(timeline_data)
            ]
        return [
            {
                "scene": s.get("scene", i + 1),
                "role": s.get("role", "body"),
                "text": s.get("text", ""),
                "target_duration": s.get("duration", s.get("target_duration", 5)),
            }
            for i, s in enumerate(script)
        ]

    def _run_llm_planning(
        self,
        scenes: list[dict],
        job_id: int,
        output_dir: str,
        research_contract_path: str,
        research_brief_path: str,
        agent_dir: str,
    ) -> tuple[list[dict], list[dict]]:
        """LLM-driven planning path. Returns (plan, assets)."""
        compact_data = self._compact_research_data(
            research_contract_path,
            research_brief_path,
        )
        scenes_dir = (
            f"{agent_dir}/scenes" if agent_dir else f"{output_dir or 'outputs'}/job_{job_id}"
        )
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)

        llm_plan = self._plan_with_llm(scenes, compact_data, job_id=job_id)

        if llm_plan is not None:
            plan = llm_plan
            assets = self._execute_plan(plan, scenes_dir)
        else:
            urls = [v["url"] for v in compact_data.get("video_sources", [])]
            plan = self._plan_scenes(scenes, urls, [])
            assets = self._download_assets(plan, job_id, scenes_dir)

        if agent_dir:
            write_json(f"{agent_dir}/scene_plan.json", plan)
        return plan, assets

    def _run_legacy_planning(
        self,
        scenes: list[dict],
        job_id: int,
        topic: str,
        output_dir: str,
        source_urls: list[str] | None,
        agent_dir: str,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Legacy sequential planning. Returns (plan, assets, pexels_videos)."""
        urls = source_urls or []
        pexels_videos = self._search_pexels(topic)
        plan = self._plan_scenes(scenes, urls, pexels_videos)
        if agent_dir:
            write_json(f"{agent_dir}/scene_plan.json", plan)

        scenes_dir = (
            f"{agent_dir}/scenes" if agent_dir else f"{output_dir or 'outputs'}/job_{job_id}"
        )
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)
        assets = self._download_assets(plan, job_id, scenes_dir)
        return plan, assets, pexels_videos

    def _search_pexels(self, topic: str) -> list[dict]:
        service = PexelsService()
        return service.search_videos(topic, per_page=10)

    def _build_provenance(self, assets: list[dict]) -> dict[str, dict[str, Any]]:
        """Build per-clip provenance metadata for each downloaded asset."""
        clips: dict[str, dict[str, Any]] = {}
        for asset in assets:
            scene_id = str(asset["scene"])
            path = asset.get("path", "")
            clip_data: dict[str, Any] = {"source": asset["source"]}
            if path and os.path.isfile(path):
                info = probe_video(path, Path(path).parent)
                if info is not None:
                    clip_data.update(
                        {
                            "original_width": info.width,
                            "original_height": info.height,
                            "codec": info.codec,
                            "duration": info.duration,
                            "file_size": info.file_size,
                            "probed": True,
                            "probe_error": None,
                        }
                    )
                else:
                    clip_data.update(
                        {
                            "probed": False,
                            "probe_error": "ffprobe returned no data",
                            "file_size": os.path.getsize(path),
                        }
                    )
            else:
                clip_data.update(
                    {
                        "probed": False,
                        "probe_error": "No file path available",
                    }
                )
            clip_data["downloaded_at"] = datetime.datetime.now(datetime.UTC).isoformat()
            clips[scene_id] = clip_data
        return clips

    def _compact_research_data(
        self,
        contract_path: str,
        brief_path: str,
    ) -> dict[str, Any]:
        """Strip noise, keep signal for LLM planning prompt."""
        try:
            contract = json.loads(Path(contract_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"video_sources": [], "context_sources": []}

        compact_videos = []
        for v in contract.get("video_sources", []):
            compact_videos.append(
                {k: v[k] for k in ("url", "desc", "plays", "likes", "shares", "author") if k in v}
            )
        compact_videos.sort(key=lambda x: x.get("plays", 0), reverse=True)

        compact_contexts = []
        for c in contract.get("context_sources", []):
            compact_contexts.append({k: c[k] for k in ("title", "description") if k in c})

        result: dict[str, Any] = {
            "video_sources": compact_videos,
            "context_sources": compact_contexts,
        }

        if brief_path:
            try:
                brief = Path(brief_path).read_text(encoding="utf-8").strip()
                if brief:
                    result["research_brief"] = brief
            except (FileNotFoundError, IsADirectoryError):
                pass

        return result

    def _plan_with_llm(
        self,
        scenes: list[dict],
        compact_data: dict,
        job_id: int = 0,
    ) -> list[dict] | None:
        """LLM plans per-scene visual strategy. Returns None on failure."""
        try:
            from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
            from clipper_agency.config.loader import get_agent_config
            from clipper_agency.llm.client import OpenRouterClient

            agent_cfg = get_agent_config("visual_director")
            llm = OpenRouterClient(trace_writer=self._trace_writer)
            prompt_text = load_prompt("visual_director", "", PROMPTS_DIR)
            safety_rules_text = "None"

            user_content = json.dumps(
                {
                    "scenes": scenes,
                    "research": compact_data,
                },
                ensure_ascii=False,
            )

            messages = [
                {
                    "role": "system",
                    "content": prompt_text.format(
                        content_angle="TikTok infotainment",
                        language="Indonesian",
                        safety_rules_text=safety_rules_text,
                    ),
                },
                {"role": "user", "content": user_content},
            ]
            if self._trace_writer:
                response = llm.chat_traced(
                    model=agent_cfg["model"],
                    messages=messages,
                    job_id=job_id,
                    agent=self.agent_name,
                    task="plan_scenes",
                    temperature=agent_cfg["temperature"],
                    max_completion_tokens=agent_cfg.get("max_completion_tokens"),
                    prompt_template_id="visual_director.md",
                )
            else:
                response = llm.chat(
                    model=agent_cfg["model"],
                    messages=messages,
                    temperature=agent_cfg["temperature"],
                    max_completion_tokens=agent_cfg.get("max_completion_tokens"),
                )

            parsed = json.loads(response["content"].strip().strip("```json").strip("```").strip())
            return parsed.get("scenes", [])

        except Exception as e:
            logger.warning("LLM planning failed: %s", e)
            return None

    def _plan_scenes(
        self,
        scenes: list[dict],
        source_urls: list[str],
        pexels_videos: list[dict],
    ) -> list[dict]:
        plan: list[dict] = []
        url_idx = 0
        pexels_idx = 0

        for scene in scenes:
            if url_idx < len(source_urls):
                plan.append(
                    {
                        "scene": scene["scene"],
                        "source": "tiktok",
                        "url": source_urls[url_idx],
                        "duration": scene.get("duration", 5),
                    }
                )
                url_idx += 1
            elif pexels_idx < len(pexels_videos):
                video = pexels_videos[pexels_idx]
                video_url = video["video_files"][0]["link"] if video.get("video_files") else ""
                plan.append(
                    {
                        "scene": scene["scene"],
                        "source": "pexels",
                        "url": video_url,
                        "duration": scene.get("duration", 5),
                    }
                )
                pexels_idx += 1
            else:
                plan.append(
                    {
                        "scene": scene["scene"],
                        "source": "none",
                        "url": "",
                        "duration": scene.get("duration", 5),
                    }
                )

        return plan

    def _download_assets(
        self,
        plan: list[dict],
        _job_id: int,
        scenes_dir: str,
    ) -> list[dict]:
        assets: list[dict] = []
        pexels = PexelsService()
        ytdlp = YtDlpService()

        for item in plan:
            scene_id = item["scene"]
            source = item["source"]
            url = item["url"]

            if source == "tiktok":
                output_path = f"{scenes_dir}/scene_{scene_id}.mp4"
                result = ytdlp.download(url, output_path)
                file_path = result.path if result else ""
                assets.append(
                    {
                        "scene": scene_id,
                        "source": source,
                        "path": file_path,
                    }
                )
            elif source == "pexels":
                path = pexels.download_video(
                    url,
                    scenes_dir,
                    f"scene_{scene_id}.mp4",
                )
                assets.append(
                    {
                        "scene": scene_id,
                        "source": source,
                        "path": path,
                    }
                )
            else:
                assets.append(
                    {
                        "scene": scene_id,
                        "source": source,
                        "path": "",
                    }
                )

        return assets

    def _execute_plan(
        self,
        plan: list[dict],
        scenes_dir: str,
    ) -> list[dict]:
        """Execute the LLM-generated visual plan with fallback chain."""
        pexels = PexelsService()
        ytdlp = YtDlpService()
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)

        assets: list[dict] = []
        for item in plan:
            scene_id = item["scene_number"]
            action = item.get("action", {})
            fallback = item.get("fallback")
            result = self._execute_action(
                action,
                scene_id,
                scenes_dir,
                pexels,
                ytdlp,
            )

            if result is None and fallback:
                logger.info("Scene %d: primary failed, using fallback", scene_id)
                result = self._execute_action(
                    fallback,
                    scene_id,
                    scenes_dir,
                    pexels,
                    ytdlp,
                )

            if result:
                asset = {"scene": scene_id, **result}
            else:
                asset = {"scene": scene_id, "source": "none", "path": ""}

            for field in (
                "treatment",
                "target_duration",
                "transition_in",
                "transition_out",
            ):
                if field in item:
                    asset[field] = item[field]

            asset = self._apply_default_treatment(asset)
            assets.append(asset)

        return assets

    def _apply_default_treatment(self, asset: dict) -> dict:
        """Fill in missing treatment metadata with sensible defaults."""
        source = asset.get("source", "")

        defaults: dict[str, Any] = {
            "transition_in": "crossfade",
            "transition_out": "crossfade",
        }

        if source in self._IMAGE_SOURCES:
            defaults["treatment"] = "ken_burns_zoom_in"
            defaults["target_duration"] = 5
        elif source == "text_card":
            defaults["treatment"] = "text_card_reveal"
            defaults["target_duration"] = 4
        else:
            defaults["treatment"] = "broll_standard"
            defaults["target_duration"] = 5

        for key, value in defaults.items():
            asset.setdefault(key, value)

        return asset

    def _execute_action(
        self,
        action: dict,
        scene_id: int,
        scenes_dir: str,
        pexels: PexelsService,
        ytdlp: YtDlpService,
    ) -> dict | None:
        """Execute a single action. Returns {source, path} or None on failure."""
        action_type = action.get("type", "none")
        handlers = {
            "tiktok_clip": self._exec_tiktok_clip,
            "pexels_video": self._exec_pexels_video,
            "pexels_image": self._exec_pexels_image,
            "text_card": self._exec_text_card,
        }
        handler = handlers.get(action_type)
        if handler:
            return handler(action, scene_id, scenes_dir, pexels, ytdlp)
        return None

    def _exec_tiktok_clip(
        self,
        action: dict,
        scene_id: int,
        scenes_dir: str,
        _pexels: PexelsService,
        ytdlp: YtDlpService,
    ) -> dict | None:
        url = action.get("source_url", "")
        if not url:
            return None
        output_path = f"{scenes_dir}/scene_{scene_id}.mp4"
        result = ytdlp.download(url, output_path)
        if not result:
            return None
        # PR 6: carry the clip window (attached by _attach_candidate_windows) to Composer.
        asset: dict = {"source": "tiktok_clip", "path": result.path}
        if "source_start_sec" in action:
            asset["source_start_sec"] = action["source_start_sec"]
        if "source_end_sec" in action:
            asset["source_end_sec"] = action["source_end_sec"]
        return asset

    def _exec_pexels_video(
        self,
        action: dict,
        scene_id: int,
        scenes_dir: str,
        pexels: PexelsService,
        _ytdlp: YtDlpService,
    ) -> dict | None:
        query = action.get("search_query", "")
        if not query:
            return None
        try:
            videos = pexels.search_videos(query, per_page=1)
            if videos and videos[0].get("video_files"):
                video_url = videos[0]["video_files"][0]["link"]
                path = pexels.download_video(
                    video_url,
                    scenes_dir,
                    f"scene_{scene_id}.mp4",
                )
                return {"source": "pexels_video", "path": path} if path else None
        except Exception:
            pass
        return None

    def _exec_pexels_image(
        self,
        action: dict,
        scene_id: int,
        scenes_dir: str,
        pexels: PexelsService,
        _ytdlp: YtDlpService,
    ) -> dict | None:
        query = action.get("search_query", "")
        return self._fetch_image(query, scene_id, scenes_dir, pexels)

    def _exec_text_card(
        self,
        action: dict,
        scene_id: int,
        scenes_dir: str,
        pexels: PexelsService,
        _ytdlp: YtDlpService,
    ) -> dict | None:
        from clipper_agency.core.card_generator import CardGenerator, CardType

        headline = action.get("headline", "")
        style = action.get("style", "news_card")

        # Map style to CardType
        card_type = CardType.HEADLINE
        if style == "news_card":
            card_type = CardType.HEADLINE
        elif "cta" in style.lower():
            card_type = CardType.CTA
        elif "fact" in style.lower():
            card_type = CardType.FACT

        # Generate styled 1080x1920 card
        card_path = Path(scenes_dir) / f"scene_{scene_id}_img.png"
        card_gen = CardGenerator()
        card_gen.generate(card_type, headline, str(card_path))

        return {
            "source": "text_card",
            "path": str(card_path),
            "headline": headline,
            "style": style,
            "bg_color": action.get("bg_color", ""),
        }

    def _fetch_image(
        self,
        query: str,
        scene_id: int,
        scenes_dir: str,
        pexels: PexelsService,
    ) -> dict | None:
        """3-tier image fallback: Pexels photos -> Firecrawl -> None."""
        import httpx

        if query:
            try:
                photos = pexels.search_photos(query, per_page=1)
                if photos:
                    img_url = photos[0].get("src", {}).get("medium", "")
                    if img_url:
                        path = Path(scenes_dir) / f"scene_{scene_id}_img.jpg"
                        try:
                            with httpx.Client(timeout=30) as client:
                                resp = client.get(img_url)
                                resp.raise_for_status()
                                path.write_bytes(resp.content)
                            return {"source": "pexels_image", "path": str(path)}
                        except Exception:
                            pass
            except Exception:
                pass

        return None


def _is_abstract_beat(beat: StoryBeat) -> bool:
    """Check if a beat is about abstract concepts (no named subjects)."""
    abstract_indicators = ["trend", "phenomenon", "concept", "general", "culture"]
    text = f"{beat.narration_goal} {beat.spoken_point}".lower()
    return any(indicator in text for indicator in abstract_indicators)


def topic_safe_query(beat: StoryBeat) -> str:
    """Generate a safe search query from beat data."""
    return (
        beat.visual_must_show[:60]
        or beat.fallback.image_search
        or beat.spoken_point[:50]
        or f"beat {beat.beat_id}"
    )
