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
from clipper_agency.core.paths import (
    agent_input_file,
    agent_output_file,
    ensure_agent_dir,
    visual_scene_file,
)
from clipper_agency.services.pexels import PexelsService
from clipper_agency.services.ytdlp import YtDlpService
from clipper_agency.core.media_probe import probe_video

logger = logging.getLogger(__name__)

# Visual hierarchy constants — higher priority first
_PRIORITY_SOURCE_CLIP = "source_clip"
_PRIORITY_SCREENSHOT = "screenshot"
_PRIORITY_PORTRAIT = "portrait"
_PRIORITY_TEXT_CARD = "text_card"
_PRIORITY_STOCK = "stock"
_PUNCTUATION_CHARS = ".,!?;:"


class VisualDirectorAgent(BaseAgent):
    """Sources video assets and plans scene layouts for video composition."""

    _IMAGE_SOURCES = frozenset({"pexels_image"})
    _VIDEO_SOURCES = frozenset({"tiktok_clip", "pexels_video", "tiktok", "pexels"})

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
        story_beats = kwargs.get("story_beats")
        timestamps = kwargs.get("timestamps")
        do_not_use = kwargs.get("do_not_use", [])
        voiceover_duration_sec = kwargs.get("voiceover_duration_sec", 0.0)

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
                )
                pexels_videos: list[dict] = []
            elif research_contract_path:
                plan, assets = self._run_llm_planning(
                    scenes, job_id, output_dir,
                    research_contract_path, research_brief_path,
                    agent_dir,
                )
                pexels_videos = []
            else:
                plan, assets, pexels_videos = self._run_legacy_planning(
                    scenes, job_id, topic, output_dir, source_urls, agent_dir,
                )

            output = {"status": "completed", "assets": assets}
            self._write_artifacts(
                assets_cache, job_id, agent_dir, topic, plan, assets,
                output, beat_driven, research_contract_path,
                pexels_videos, source_urls,
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
    ) -> tuple[list[dict], list[dict]]:
        """Beat-driven planning aligned to audio timeline. Returns (plan, assets)."""
        parsed_beats = [StoryBeat(**b) for b in story_beats]
        parsed_ts = [WordTimestamp(**t) for t in timestamps]

        beat_durations = self._calculate_beat_durations(parsed_beats, parsed_ts)

        scenes_dir = (
            f"{agent_dir}/scenes"
            if agent_dir
            else f"{output_dir or 'outputs'}/job_{job_id}"
        )
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)

        llm_plan = self._plan_beats_with_llm(
            parsed_beats=parsed_beats,
            beat_durations=beat_durations,
            do_not_use=do_not_use,
            voiceover_duration_sec=voiceover_duration_sec,
            topic=topic,
        )

        if llm_plan is not None:
            plan = llm_plan
        else:
            plan = self._plan_beats_fallback(
                parsed_beats, beat_durations, do_not_use,
            )

        allowed_beat_ids = [beat.beat_id for beat in parsed_beats]
        plan = self._normalize_beat_plan(plan, allowed_beat_ids)
        plan = self._deduplicate_llm_plan_urls(plan, do_not_use)

        assets = self._execute_beat_plan(plan, scenes_dir)

        if agent_dir:
            write_json(f"{agent_dir}/scene_plan.json", plan)
        return plan, assets

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
        total_ts_duration = (
            timestamps[-1].end - timestamps[0].start if timestamps else 0.0
        )
        durations: dict[int, float] = {}

        for beat in beats:
            beat_words = beat.overlay_text.split() if beat.overlay_text else []
            if beat_words and timestamps:
                first_word = beat_words[0].lower().strip(_PUNCTUATION_CHARS)
                last_word = beat_words[-1].lower().strip(_PUNCTUATION_CHARS)
                start_time, end_time = self._find_word_range_timestamps(
                    first_word, last_word, timestamps,
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
    ) -> list[dict] | None:
        """LLM plans per-beat visual strategy using beat-driven instructions."""
        try:
            from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
            from clipper_agency.config.loader import get_agent_config
            from clipper_agency.llm.client import OpenRouterClient

            agent_cfg = get_agent_config("visual_director")
            llm = OpenRouterClient()
            prompt_text = load_prompt("visual_director", "", PROMPTS_DIR)
            safety_rules_text = "None"

            beats_payload = []
            for beat in parsed_beats:
                duration = beat_durations.get(beat.beat_id, 5.0)
                assets_info = [
                    {"type": a.type, "url": a.url, "reason": a.reason}
                    for a in beat.asset_candidates
                ]
                beats_payload.append({
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
                })

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

            response = llm.chat(
                model=agent_cfg["model"],
                messages=[
                    {
                        "role": "system",
                        "content": prompt_text.format(
                            content_angle="TikTok infotainment",
                            language="Indonesian",
                            safety_rules_text=safety_rules_text,
                        ),
                    },
                    {"role": "user", "content": user_content},
                ],
                temperature=agent_cfg["temperature"],
                max_completion_tokens=agent_cfg.get("max_completion_tokens"),
            )

            parsed = json.loads(
                response["content"]
                .strip()
                .strip("```json")
                .strip("```")
                .strip()
            )
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
            plan.append({
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
                    "headline": beat.overlay_text[:50] if beat.overlay_text else f"Beat {beat.beat_id}",
                    "style": "news_card",
                    "image_search": beat.fallback.image_search or topic_safe_query(beat),
                },
            })
        return plan

    def _select_visual_for_beat(
        self, beat: StoryBeat, do_not_use: list[str],
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
            beat.asset_candidates, "tiktok_clip", do_not_use_set,
        )
        if clip:
            return {"type": "tiktok_clip", "source_url": clip.url}

        # Tier 2: Official screenshot
        screenshot = self._find_candidate_by_type(
            beat.asset_candidates, "screenshot", do_not_use_set,
        )
        if screenshot:
            return {
                "type": "pexels_image",
                "search_query": beat.fallback.image_search or beat.spoken_point[:50],
                "source_url": screenshot.url,
            }

        # Tier 3: Subject portrait with Ken Burns (Pexels search)
        search_query = (
            beat.fallback.image_search
            or beat.visual_must_show[:60]
            or beat.spoken_point[:50]
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
        candidates: list, candidate_type: str, do_not_use_set: set[str],
    ):
        """Find first asset candidate matching type not in do_not_use set."""
        for candidate in candidates:
            if candidate.url in do_not_use_set:
                continue
            if candidate.type == candidate_type:
                return candidate
        return None

    def _execute_beat_plan(
        self, plan: list[dict], scenes_dir: str,
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
                action, scene_id, scenes_dir, pexels, ytdlp,
            )

            if result is None and fallback:
                logger.info("Beat %d: primary failed, using fallback", scene_id)
                result = self._execute_action(
                    fallback, scene_id, scenes_dir, pexels, ytdlp,
                )

            if result:
                asset = {"scene": scene_id, **result}
            else:
                asset = {"scene": scene_id, "source": "none", "path": ""}

            # Pass through beat metadata for composer compatibility
            for field in (
                "treatment", "target_duration", "transition_in",
                "transition_out", "beat_id", "role",
                "start_time", "duration",
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
        by_beat_id = {
            item.get("beat_id", item.get("scene_number")): item
            for item in plan
        }
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

    def _resolve_beat_plan_assets(
        self, plan: list[dict], do_not_use: list[str],
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

    # ------------------------------------------------------------------
    # Legacy planning paths (kept for backward compatibility)
    # ------------------------------------------------------------------

    def _resolve_scene_data(
        self, script: list[dict] | None, timeline_data: list[dict] | None = None,
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
        self, scenes: list[dict], job_id: int, output_dir: str,
        research_contract_path: str, research_brief_path: str,
        agent_dir: str,
    ) -> tuple[list[dict], list[dict]]:
        """LLM-driven planning path. Returns (plan, assets)."""
        compact_data = self._compact_research_data(
            research_contract_path, research_brief_path,
        )
        scenes_dir = (
            f"{agent_dir}/scenes"
            if agent_dir
            else f"{output_dir or 'outputs'}/job_{job_id}"
        )
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)

        llm_plan = self._plan_with_llm(scenes, compact_data)

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
        self, scenes: list[dict], job_id: int, topic: str,
        output_dir: str, source_urls: list[str] | None,
        agent_dir: str,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Legacy sequential planning. Returns (plan, assets, pexels_videos)."""
        urls = source_urls or []
        pexels_videos = self._search_pexels(topic)
        plan = self._plan_scenes(scenes, urls, pexels_videos)
        if agent_dir:
            write_json(f"{agent_dir}/scene_plan.json", plan)

        scenes_dir = (
            f"{agent_dir}/scenes"
            if agent_dir
            else f"{output_dir or 'outputs'}/job_{job_id}"
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
                    clip_data.update({
                        "original_width": info.width,
                        "original_height": info.height,
                        "codec": info.codec,
                        "duration": info.duration,
                        "file_size": info.file_size,
                        "probed": True,
                        "probe_error": None,
                    })
                else:
                    clip_data.update({
                        "probed": False,
                        "probe_error": "ffprobe returned no data",
                        "file_size": os.path.getsize(path),
                    })
            else:
                clip_data.update({
                    "probed": False,
                    "probe_error": "No file path available",
                })
            clip_data["downloaded_at"] = (
                datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            clips[scene_id] = clip_data
        return clips

    def _compact_research_data(
        self, contract_path: str, brief_path: str,
    ) -> dict[str, Any]:
        """Strip noise, keep signal for LLM planning prompt."""
        try:
            contract = json.loads(Path(contract_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"video_sources": [], "context_sources": []}

        compact_videos = []
        for v in contract.get("video_sources", []):
            compact_videos.append({
                k: v[k] for k in ("url", "desc", "plays", "likes", "shares", "author")
                if k in v
            })
        compact_videos.sort(key=lambda x: x.get("plays", 0), reverse=True)

        compact_contexts = []
        for c in contract.get("context_sources", []):
            compact_contexts.append({
                k: c[k] for k in ("title", "description")
                if k in c
            })

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
        self, scenes: list[dict], compact_data: dict,
    ) -> list[dict] | None:
        """LLM plans per-scene visual strategy. Returns None on failure."""
        try:
            from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
            from clipper_agency.config.loader import get_agent_config
            from clipper_agency.llm.client import OpenRouterClient

            agent_cfg = get_agent_config("visual_director")
            llm = OpenRouterClient()
            prompt_text = load_prompt("visual_director", "", PROMPTS_DIR)
            safety_rules_text = "None"

            user_content = json.dumps({
                "scenes": scenes,
                "research": compact_data,
            }, ensure_ascii=False)

            response = llm.chat(
                model=agent_cfg["model"],
                messages=[
                    {
                        "role": "system",
                        "content": prompt_text.format(
                            content_angle="TikTok infotainment",
                            language="Indonesian",
                            safety_rules_text=safety_rules_text,
                        ),
                    },
                    {"role": "user", "content": user_content},
                ],
                temperature=agent_cfg["temperature"],
                max_completion_tokens=agent_cfg.get("max_completion_tokens"),
            )

            parsed = json.loads(
                response["content"].strip().strip("```json").strip("```").strip()
            )
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
                plan.append({
                    "scene": scene["scene"],
                    "source": "tiktok",
                    "url": source_urls[url_idx],
                    "duration": scene.get("duration", 5),
                })
                url_idx += 1
            elif pexels_idx < len(pexels_videos):
                video = pexels_videos[pexels_idx]
                video_url = (
                    video["video_files"][0]["link"]
                    if video.get("video_files")
                    else ""
                )
                plan.append({
                    "scene": scene["scene"],
                    "source": "pexels",
                    "url": video_url,
                    "duration": scene.get("duration", 5),
                })
                pexels_idx += 1
            else:
                plan.append({
                    "scene": scene["scene"],
                    "source": "none",
                    "url": "",
                    "duration": scene.get("duration", 5),
                })

        return plan

    def _download_assets(
        self, plan: list[dict], _job_id: int, scenes_dir: str,
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
                assets.append({
                    "scene": scene_id,
                    "source": source,
                    "path": file_path,
                })
            elif source == "pexels":
                path = pexels.download_video(
                    url, scenes_dir, f"scene_{scene_id}.mp4",
                )
                assets.append({
                    "scene": scene_id,
                    "source": source,
                    "path": path,
                })
            else:
                assets.append({
                    "scene": scene_id,
                    "source": source,
                    "path": "",
                })

        return assets

    def _execute_plan(
        self, plan: list[dict], scenes_dir: str,
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
                action, scene_id, scenes_dir, pexels, ytdlp,
            )

            if result is None and fallback:
                logger.info("Scene %d: primary failed, using fallback", scene_id)
                result = self._execute_action(
                    fallback, scene_id, scenes_dir, pexels, ytdlp,
                )

            if result:
                asset = {"scene": scene_id, **result}
            else:
                asset = {"scene": scene_id, "source": "none", "path": ""}

            for field in (
                "treatment", "target_duration",
                "transition_in", "transition_out",
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
        self, action: dict, scene_id: int, scenes_dir: str,
        pexels: PexelsService, ytdlp: YtDlpService,
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
        self, action: dict, scene_id: int, scenes_dir: str,
        _pexels: PexelsService, ytdlp: YtDlpService,
    ) -> dict | None:
        url = action.get("source_url", "")
        if not url:
            return None
        output_path = f"{scenes_dir}/scene_{scene_id}.mp4"
        result = ytdlp.download(url, output_path)
        return {"source": "tiktok_clip", "path": result.path} if result else None

    def _exec_pexels_video(
        self, action: dict, scene_id: int, scenes_dir: str,
        pexels: PexelsService, _ytdlp: YtDlpService,
    ) -> dict | None:
        query = action.get("search_query", "")
        if not query:
            return None
        try:
            videos = pexels.search_videos(query, per_page=1)
            if videos and videos[0].get("video_files"):
                video_url = videos[0]["video_files"][0]["link"]
                path = pexels.download_video(
                    video_url, scenes_dir, f"scene_{scene_id}.mp4",
                )
                return {"source": "pexels_video", "path": path} if path else None
        except Exception:
            pass
        return None

    def _exec_pexels_image(
        self, action: dict, scene_id: int, scenes_dir: str,
        pexels: PexelsService, _ytdlp: YtDlpService,
    ) -> dict | None:
        query = action.get("search_query", "")
        return self._fetch_image(query, scene_id, scenes_dir, pexels)

    def _exec_text_card(
        self, action: dict, scene_id: int, scenes_dir: str,
        pexels: PexelsService, _ytdlp: YtDlpService,
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
        self, query: str, scene_id: int, scenes_dir: str,
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
