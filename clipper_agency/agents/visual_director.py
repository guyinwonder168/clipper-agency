"""Visual Director Agent — video asset sourcing and scene planning."""

import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

from clipper_agency.agents.base import BaseAgent
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


class VisualDirectorAgent(BaseAgent):
    """Sources video assets and plans scene layouts for video composition."""

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
        scenes = script or []

        assets_cache = kwargs.get("assets_cache", "")
        agent_dir = ""
        if assets_cache:
            agent_dir = ensure_agent_dir(assets_cache, job_id, "visual_director")
            write_json(agent_input_file(assets_cache, job_id, "visual_director"), {
                "job_id": job_id,
                "scene_count": len(scenes),
                "topic": topic,
                "has_research_data": bool(research_contract_path),
            })

        logger.info(
            "Visual: scenes=%d has_research=%s",
            len(scenes), bool(research_contract_path),
        )

        try:
            if research_contract_path:
                plan, assets = self._run_llm_planning(
                    scenes, job_id, output_dir,
                    research_contract_path, research_brief_path,
                    agent_dir,
                )
                pexels_videos: list[dict] = []
            else:
                plan, assets, pexels_videos = self._run_legacy_planning(
                    scenes, job_id, topic, output_dir, source_urls, agent_dir,
                )

            clips = self._build_provenance(assets)
            output = {"status": "completed", "assets": assets}

            if agent_dir:
                write_json(agent_output_file(assets_cache, job_id, "visual_director"), output)
                provenance_data: dict[str, Any] = {
                    "topic": topic,
                    "scene_count": len(plan),
                    "clips": clips,
                }
                if not research_contract_path:
                    provenance_data["pexels_results"] = len(pexels_videos)
                    provenance_data["source_url_count"] = len(source_urls or [])
                write_json(f"{agent_dir}/provenance.json", provenance_data)

            logger.info("Visual: completed %d assets", len(assets))
            return output
        except Exception as e:
            logger.exception("Visual: asset sourcing failed")
            return {"status": "failed", "error": str(e), "assets": []}

    def _run_llm_planning(
        self, scenes: list[dict], job_id: int, output_dir: str,
        research_contract_path: str, research_brief_path: str,
        agent_dir: str,
    ) -> tuple[list[dict], list[dict]]:
        """LLM-driven planning path. Returns (plan, assets)."""
        compact_data = self._compact_research_data(
            research_contract_path, research_brief_path,
        )
        scenes_dir = f"{agent_dir}/scenes" if agent_dir else f"{output_dir or 'outputs'}/job_{job_id}"
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

        scenes_dir = f"{agent_dir}/scenes" if agent_dir else f"{output_dir or 'outputs'}/job_{job_id}"
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

        # Compact video sources: keep signal, strip noise
        compact_videos = []
        for v in contract.get("video_sources", []):
            compact_videos.append({
                k: v[k] for k in ("url", "desc", "plays", "likes", "shares", "author")
                if k in v
            })

        # Sort by plays descending
        compact_videos.sort(key=lambda x: x.get("plays", 0), reverse=True)

        # Compact context sources: keep title + description only
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

        # Read research brief if available
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
            from clipper_agency.config.loader import load_settings
            from clipper_agency.llm.client import OpenRouterClient

            settings = load_settings()
            llm = OpenRouterClient()
            prompt_text = load_prompt(
                "visual_director", "", PROMPTS_DIR,
            )
            safety_rules = getattr(settings, "safety_rules", [])
            safety_rules_text = "\n".join(f"- {r}" for r in safety_rules) if safety_rules else "None"

            user_content = json.dumps({
                "scenes": scenes,
                "research": compact_data,
            }, ensure_ascii=False)

            model_name = settings.visual_director_model
            response = llm.chat(
                model=model_name,
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
                temperature=0.5,
                max_tokens=2048,
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
                video_url = video["video_files"][0]["link"] if video.get("video_files") else ""
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
        self, plan: list[dict], _job_id: int, scenes_dir: str
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
                path = pexels.download_video(url, scenes_dir,
                                             f"scene_{scene_id}.mp4")
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
            result = self._execute_action(action, scene_id, scenes_dir, pexels, ytdlp)

            if result is None and fallback:
                logger.info("Scene %d: primary failed, using fallback", scene_id)
                result = self._execute_action(fallback, scene_id, scenes_dir, pexels, ytdlp)

            if result:
                asset = {"scene": scene_id, **result}
            else:
                asset = {"scene": scene_id, "source": "none", "path": ""}

            # Pass through treatment metadata from LLM plan
            for field in ("treatment", "target_duration", "transition_in", "transition_out"):
                if field in item:
                    asset[field] = item[field]

            assets.append(asset)

        return assets

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
                path = pexels.download_video(video_url, scenes_dir, f"scene_{scene_id}.mp4")
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
        image_search = action.get("image_search", "")
        image_result = self._fetch_image(image_search, scene_id, scenes_dir, pexels)
        return {
            "source": "text_card",
            "path": image_result.get("path", "") if image_result else "",
            "headline": action.get("headline", ""),
            "style": action.get("style", "news_card"),
            "bg_color": action.get("bg_color", ""),
        }

    def _fetch_image(
        self, query: str, scene_id: int, scenes_dir: str,
        pexels: PexelsService,
    ) -> dict | None:
        """3-tier image fallback: Pexels photos -> Firecrawl -> None."""
        import httpx

        # Tier 1: Pexels photos
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

        # Tier 2: Firecrawl article search -> og:image (deferred)
        # Tier 3: Gradient card (no image) — returns None, Composer uses gradient

        return None
