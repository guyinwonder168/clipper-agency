"""Composer Agent — FFmpeg-based video assembly and thumbnail generation."""

import dataclasses
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.core.artifacts import write_json
from clipper_agency.core.card_generator import CardGenerator, CardType
from clipper_agency.core.card_to_video import card_to_video
from clipper_agency.core.ffmpeg_preflight import FFmpegPreflight
from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming
from clipper_agency.core.paths import (
    agent_input_file,
    agent_output_file,
    ensure_agent_dir,
)
from clipper_agency.core.scene_normalizer import SceneNormalizer
from clipper_agency.core.scene_validator import SceneValidator
from clipper_agency.rendering.engine import render_plan
from clipper_agency.rendering.renderers.b_roll_narration import build_b_roll_narration_plan
from clipper_agency.rendering.renderers.news_card import build_news_card_plan
from clipper_agency.rendering.renderers.rapid_update import build_rapid_update_plan
from clipper_agency.rendering.templates import load_render_template

logger = logging.getLogger(__name__)

_FFMPEG_CONCAT_TIMEOUT = 600  # seconds
_FFMPEG_NORMALIZE_TIMEOUT = 120  # seconds


class ComposerAgent(BaseAgent):
    """Assembles final video from assets and audio using FFmpeg."""

    _ADAPTERS = {
        "news_card": build_news_card_plan,
        "b_roll_narration": build_b_roll_narration_plan,
        "rapid_update": build_rapid_update_plan,
    }

    @property
    def agent_name(self) -> str:
        return "composer"

    def execute(
        self,
        job_id: int,
        assets: list[dict] | None = None,
        audio_files: list[str] | None = None,
        output_dir: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        video_assets = assets or []
        voice_files = audio_files or []

        # ── FFmpeg preflight diagnostics ──
        preflight_result = self._run_preflight(output_dir, job_id)
        if preflight_result is not None:
            return preflight_result

        assets_cache = kwargs.get("assets_cache", "")
        agent_dir = self._record_input(
            assets_cache, job_id, len(video_assets), len(voice_files),
        )

        logger.info(
            "Composer: %d video assets, %d audio files",
            len(video_assets), len(voice_files),
        )

        # ── Template rendering path ──
        template_name = kwargs.get("template_name")
        if template_name:
            return self._render_via_template(
                job_id=job_id,
                assets=video_assets,
                output_dir=output_dir,
                assets_cache=assets_cache,
                agent_dir=agent_dir,
                template_name=template_name,
                caption=kwargs.get("caption", ""),
                title=kwargs.get("title", template_name),
            )

        return self._execute_assembly(
            video_assets, voice_files, output_dir, assets_cache,
            job_id, agent_dir,
        )

    def _execute_assembly(
        self,
        video_assets: list[dict],
        voice_files: list[str],
        output_dir: str,
        assets_cache: str,
        job_id: int,
        agent_dir: str,
    ) -> dict[str, Any]:
        """Run the assembly pipeline: concat scenes + mix audio + thumbnail."""
        if not video_assets and not voice_files:
            logger.warning("Composer: no assets or audio — skipping")
            return {
                "status": "completed",
                "video_path": "",
                "thumbnail_path": "",
            }

        video_path = f"{output_dir}/job_{job_id}/video.mp4"
        thumbnail_path = f"{output_dir}/job_{job_id}/thumbnail.png"

        try:
            return self._try_assemble(
                video_assets, voice_files, video_path, thumbnail_path,
                assets_cache, job_id, agent_dir,
            )
        except subprocess.CalledProcessError as e:
            return self._handle_ffmpeg_error(e, video_path, agent_dir)
        except Exception as e:
            logger.exception("Composer: unexpected error")
            return {
                "status": "failed",
                "error": str(e),
                "video_path": video_path,
                "thumbnail_path": "",
            }

    def _try_assemble(
        self,
        video_assets: list[dict],
        voice_files: list[str],
        video_path: str,
        thumbnail_path: str,
        assets_cache: str,
        job_id: int,
        agent_dir: str,
    ) -> dict[str, Any]:
        """Attempt assembly. Raises on FFmpeg or unexpected errors."""
        assemble_result = self._assemble_video(
            video_assets, voice_files, video_path,
        )
        ffmpeg_cmd = assemble_result["cmd"]
        card_fallback_scenes = assemble_result.get(
            "card_fallback_scenes", [],
        )
        if not ffmpeg_cmd:
            logger.error(
                "Composer: no valid scenes assembled — failing (card_fallback=%s)",
                card_fallback_scenes,
            )
            output = {
                "status": "failed",
                "error": "No valid scenes to assemble",
                "video_path": "",
                "thumbnail_path": "",
                "card_fallback_scenes": card_fallback_scenes,
            }
            if agent_dir:
                write_json(agent_output_file(assets_cache, job_id, "composer"), output)
            return output
        self._generate_thumbnail(video_path, thumbnail_path)

        logger.info(
            "Composer: completed — video=%s thumbnail=%s cards=%d",
            video_path, thumbnail_path, len(card_fallback_scenes),
        )

        output = {
            "status": "completed",
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
            "card_fallback_scenes": card_fallback_scenes,
        }
        if agent_dir:
            self._persist_diagnostics(agent_dir, ffmpeg_cmd, "")
            write_json(agent_output_file(assets_cache, job_id, "composer"),
                        output)
        return output

    def _handle_ffmpeg_error(
        self,
        error: subprocess.CalledProcessError,
        video_path: str,
        agent_dir: str,
    ) -> dict[str, Any]:
        """Build a failure dict from an FFmpeg CalledProcessError."""
        stderr_raw = error.stderr or b""
        stderr_text = stderr_raw.strip()
        if isinstance(stderr_text, bytes):
            stderr_text = stderr_text.decode()
        logger.error("Composer: FFmpeg failed — %s", stderr_text[:500])
        if agent_dir:
            self._persist_diagnostics(agent_dir, getattr(error, 'cmd', []), stderr_text)
        return {
            "status": "failed",
            "error": stderr_text or str(error),
            "video_path": video_path,
            "thumbnail_path": "",
        }

    def _render_via_template(
        self,
        job_id: int,
        assets: list[dict],
        output_dir: str,
        assets_cache: str,
        agent_dir: str,
        template_name: str,
        caption: str,
        title: str,
    ) -> dict[str, Any]:
        """Route through template-based rendering engine."""
        template = load_render_template(template_name)
        adapter = self._ADAPTERS.get(template.type)

        if adapter is None:
            logger.warning(
                "Composer: unknown template type %r — falling back to pipeline",
                template.type,
            )
            return self.execute(
                job_id=job_id,
                assets=assets,
                audio_files=[],
                output_dir=output_dir,
                assets_cache=assets_cache,
                caption=caption,
            )

        source_paths = [Path(a["path"]) for a in assets if a.get("path")]

        if assets_cache:
            diagnostics_dir = Path(assets_cache) / f"job_{job_id}" / "agents" / "composer"
        else:
            diagnostics_dir = Path(output_dir) / f"job_{job_id}" / "diagnostics"

        # Persist loaded template config for debugging
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        write_json(diagnostics_dir / "template_config.json", template.model_dump())

        plan = adapter(
            template=template,
            source_paths=source_paths,
            caption=caption,
            title=title,
            diagnostics_dir=diagnostics_dir,
        )

        output_path = Path(output_dir) / f"job_{job_id}" / "video.mp4"
        result = render_plan(plan, output_path, diagnostics_dir)

        output = {
            "status": "completed",
            "video_path": str(result.video_path),
            "thumbnail_path": str(result.thumbnail_path),
            "template_name": template_name,
            "diagnostics_dir": str(diagnostics_dir),
        }

        if agent_dir:
            write_json(agent_output_file(assets_cache, job_id, "composer"), output)

        logger.info(
            "Composer: template render completed — template=%s video=%s",
            template_name, result.video_path,
        )

        return output

    def _run_preflight(self, output_dir: str, job_id: int) -> dict[str, Any] | None:
        """Run FFmpeg preflight.  Returns a failure dict or ``None`` on success."""
        try:
            preflight = FFmpegPreflight.probe()
        except Exception:
            logger.exception("Composer: FFmpeg preflight probe failed")
            return {
                "status": "failed",
                "error": "FFmpeg preflight probe failed",
            }
        preflight_dir = (
            Path(output_dir) / f"job_{job_id}" / "agents" / "composer"
        )
        preflight_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            preflight_dir / "preflight.json",
            dataclasses.asdict(preflight),
        )
        if not preflight.all_ok():
            logger.error(
                "Composer: FFmpeg preflight failed — ffmpeg=%s ffprobe=%s "
                "libx264=%s aac=%s mp3=%s",
                preflight.ffmpeg_found,
                preflight.ffprobe_found,
                preflight.libx264_available,
                preflight.aac_available,
                preflight.mp3_decode_available,
            )
            return {
                "status": "failed",
                "error": "FFmpeg preflight failed",
                "preflight": dataclasses.asdict(preflight),
            }
        return None

    def _record_input(
        self,
        assets_cache: str,
        job_id: int,
        video_asset_count: int,
        audio_file_count: int,
    ) -> str:
        """Persist Composer input diagnostics and return agent dir, if enabled."""
        if not assets_cache:
            return ""

        agent_dir = ensure_agent_dir(assets_cache, job_id, "composer")
        write_json(agent_input_file(assets_cache, job_id, "composer"), {
            "job_id": job_id,
            "video_asset_count": video_asset_count,
            "audio_file_count": audio_file_count,
        })
        return agent_dir

    def _persist_diagnostics(self, agent_dir: str, ffmpeg_cmd: list | str,
                              stderr_text: str) -> None:
        """Save FFmpeg command and stderr to agent artifact directory."""
        cmd_str = " ".join(ffmpeg_cmd) if isinstance(ffmpeg_cmd, list) else str(ffmpeg_cmd)
        cmd_file = Path(agent_dir) / "ffmpeg_command.txt"
        cmd_file.write_text(cmd_str)

        if stderr_text:
            log_file = Path(agent_dir) / "ffmpeg_stderr.log"
            log_file.write_text(stderr_text)

    def _process_scene(
        self,
        temp_dir: Path,
        normalizer: Any,
        card_gen: Any,
        scene_num: int,
        scene_path: str,
        asset: dict | None = None,
    ) -> tuple[str | None, bool]:
        """Process a single scene: validate, normalize, or generate card fallback.

        Returns ``(output_path, was_card_fallback)``.
        """
        validation = SceneValidator.validate(scene_path)

        if validation.valid:
            norm_path = temp_dir / f"scene_{scene_num}_norm.mp4"
            result = normalizer.normalize(scene_path, str(norm_path))
            if result.success:
                return str(result.path), False
            logger.warning(
                "Composer: normalize failed scene %d — card fallback: %s",
                scene_num, result.error,
            )
        else:
            logger.info(
                "Composer: scene %d invalid (%s) — card fallback",
                scene_num, "; ".join(validation.issues[:2]),
            )

        # Generate card fallback
        card_mp4 = temp_dir / f"scene_{scene_num}_card.mp4"
        card_png = temp_dir / f"card_{scene_num}.png"
        card_gen.generate(
            CardType.CONTEXT, f"Scene {scene_num}", str(card_png),
        )
        ctv = card_to_video(str(card_png), str(card_mp4), duration=5)
        if ctv.success:
            return str(card_mp4), True
        logger.error(
            "Composer: card_to_video failed scene %d: %s",
            scene_num, ctv.error,
        )
        return None, True

    def _build_filter(
        self, assets: list[dict], audio_files: list[str]
    ) -> str:
        video_inputs = [a for a in assets if a.get("path")]
        num_videos = len(video_inputs)

        if num_videos == 0:
            return "null"

        # Build concat filter for video streams
        concat_inputs = "".join(f"[{i}:v]" for i in range(num_videos))
        concat_filter = (
            f"{concat_inputs}concat=n={num_videos}:v=1[outv]"
        )

        # Build amix filter for audio streams — voice files only (no bg music)
        if audio_files:
            audio_inputs = "".join(
                f"[{num_videos + i}:a]" for i in range(len(audio_files))
            )
            concat_filter += (
                f";{audio_inputs}"
                f"amix=inputs={len(audio_files)}:duration=first[outa]"
            )
        else:
            concat_filter += ";anullsrc[outa]"

        return concat_filter

    def _assemble_video(
        self, assets: list[dict], audio_files: list[str], output_path: str
    ) -> dict[str, Any]:
        """Assemble final video from assets with scene normalization and card fallback.

        Pipeline:
        1. Validate each scene file
        2. Valid scenes → normalize to 1080×1920
        3. Invalid/missing scenes → generate card → convert to 5 s video
        4. Concat all normalized scenes + mix audio
        5. Write ``card_fallback.json`` metadata tracking which scenes used cards.
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="composer_"))
        normalized_scene_paths: list[str] = []
        card_fallback_scenes: list[int] = []

        try:
            normalizer = SceneNormalizer()
            card_gen = CardGenerator()

            for i, asset in enumerate(assets):
                scene_path = asset.get("path", "")
                scene_num = int(asset.get("scene", i + 1))
                norm_path, was_card = self._process_scene(
                    temp_dir, normalizer, card_gen,
                    scene_num, scene_path, asset=asset,
                )
                if norm_path:
                    normalized_scene_paths.append(norm_path)
                if was_card:
                    card_fallback_scenes.append(scene_num)

            # ── Filter out empty entries (scenes where card gen failed) ──
            valid_normalized = [p for p in normalized_scene_paths if p]
            if not valid_normalized:
                logger.warning("Composer: no valid scenes to assemble")
                return {"cmd": [], "card_fallback_scenes": card_fallback_scenes}

            # Build normalized asset list preserving treatment metadata
            normalized_assets = []
            for i, asset in enumerate(assets):
                norm_path = normalized_scene_paths[i] if i < len(normalized_scene_paths) else None
                if norm_path:
                    enriched = {"scene": i + 1, "path": norm_path}
                    # Preserve treatment metadata from visual director
                    for field in ("treatment", "target_duration", "transition_in", "transition_out"):
                        if field in asset:
                            enriched[field] = asset[field]
                    normalized_assets.append(enriched)

            cmd = ["ffmpeg", "-y"]
            for n in valid_normalized:
                cmd.extend(["-i", n])
            for af in audio_files:
                cmd.extend(["-i", af])

            filter_graph = self._build_filter(
                normalized_assets, audio_files,
            )
            cmd.extend([
                "-filter_complex", filter_graph,
                "-map", "[outv]",
                "-map", "[outa]",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",
                output_path,
            ])

            logger.info(
                "Composer: starting FFmpeg concat — %d video + %d audio → %s",
                len(valid_normalized), len(audio_files), output_path,
            )
            run_ffmpeg_streaming(cmd, timeout=600, label="concat")
            logger.info("Composer: FFmpeg concat completed — %s", output_path)

            # ── Persist card fallback metadata ──
            output_dir = Path(output_path).parent
            metadata = {"card_fallback_scenes": card_fallback_scenes}
            (output_dir / "card_fallback.json").write_text(json.dumps(metadata))

            return {"cmd": cmd, "card_fallback_scenes": card_fallback_scenes}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _generate_thumbnail(self, video_path: str, thumbnail_path: str) -> None:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", "00:00:00",
            "-frames:v", "1",
            "-vf", "scale=720:1280",
            thumbnail_path,
        ]
        run_ffmpeg_streaming(cmd, timeout=60, label="thumbnail")
