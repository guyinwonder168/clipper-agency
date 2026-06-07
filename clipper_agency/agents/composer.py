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
from clipper_agency.rendering.audio_sequencer import build_audio_video_concat
from clipper_agency.rendering.engine import render_plan
from clipper_agency.rendering.primitives import escape_drawtext
from clipper_agency.rendering.renderers.b_roll_narration import build_b_roll_narration_plan
from clipper_agency.rendering.renderers.news_card import build_news_card_plan
from clipper_agency.rendering.renderers.rapid_update import build_rapid_update_plan
from clipper_agency.rendering.subtitle_engine import (
    build_keyword_captions,
    build_subtitle_overlays,
    build_word_subtitle_captions,
)
from clipper_agency.rendering.templates import load_render_template

logger = logging.getLogger(__name__)

_FFMPEG_CONCAT_TIMEOUT = 600  # seconds
_FFMPEG_NORMALIZE_TIMEOUT = 120  # seconds

# Lazy singletons — avoid per-call YAML re-parsing.
_treatment_builder: "TreatmentFilterBuilder | None" = None  # type: ignore[name-defined]  # noqa: F821
_treatment_config: "TreatmentConfig | None" = None  # type: ignore[name-defined]  # noqa: F821

_DEFAULT_TRANSITION = "crossfade"
_SAFETY_MARGIN = 0.1
_MIN_CLIP_HEADROOM = 0.15
_MIN_TRANSITION_DUR = 0.05
_OUTV = "[outv]"

# Audio-first smart trim constants
_BOUNDARY_TOLERANCE = 0.15       # ±15% tolerance for boundary match
_MAX_SLOWDOWN = 0.30             # Max 30% speed reduction
_DURATION_CLOSE_ENOUGH = 0.05    # 50ms tolerance for duration match

# Keyword caption drawtext style
_KEYWORD_FONTSIZE = 48           # Large font for mobile readability
_KEYWORD_BORDERW = 3             # Thick dark outline
_KEYWORD_Y_OFFSET = 40          # Bottom margin (closer to bottom than subtitles)


def _get_treatment_builder():
    """Return the module-level TreatmentFilterBuilder singleton."""
    global _treatment_builder
    if _treatment_builder is None:
        from clipper_agency.rendering.treatment_config import TreatmentConfig
        from clipper_agency.rendering.treatment_filters import TreatmentFilterBuilder
        _treatment_builder = TreatmentFilterBuilder(TreatmentConfig())
    return _treatment_builder


def _get_treatment_config():
    """Return the module-level TreatmentConfig singleton for transition lookups."""
    global _treatment_config
    if _treatment_config is None:
        from clipper_agency.rendering.treatment_config import TreatmentConfig
        _treatment_config = TreatmentConfig()
    return _treatment_config


def _build_transition_chain(
    trim_parts: list[str],
    video_labels: list[str],
    normalized_assets: list[dict],
    num_videos: int,
) -> str:
    """Build the video filter section: trim parts + transition chain.

    For single-scene outputs, the trimmed label maps directly to [outv].
    For multi-scene, scenes are joined via xfade or concat transitions
    based on each scene's ``transition_out`` metadata.

    Returns the complete video filter string (without audio).
    """
    if num_videos == 1:
        # Single scene: rename trimmed output directly to [outv].
        single = trim_parts[0]
        label = video_labels[0]
        return single.replace(f"[{label}]", _OUTV)

    config = _get_treatment_config()
    transition_parts: list[str] = []
    current_label = video_labels[0]
    cumulative_duration = float(
        normalized_assets[0].get("target_duration", 5)
    )

    for i in range(1, num_videos):
        prev_asset = normalized_assets[i - 1]
        next_dur = float(normalized_assets[i].get("target_duration", 5))
        is_last = i == num_videos - 1

        # Resolve transition definition; unknown → crossfade fallback.
        trans_name = prev_asset.get("transition_out", _DEFAULT_TRANSITION)
        trans_def = config.get_transition(trans_name)
        if trans_def is None:
            trans_def = config.get_transition(_DEFAULT_TRANSITION)

        # Per-asset override for transition duration.
        trans_duration = float(
            prev_asset.get("transition_duration", trans_def.default_duration)
        )

        if trans_def.ffmpeg_filter is not None:
            # ── xfade transition ──
            prev_dur = float(prev_asset.get("target_duration", 5))
            max_dur = min(prev_dur, next_dur) - _MIN_CLIP_HEADROOM
            trans_duration = min(
                trans_duration, max(_MIN_TRANSITION_DUR, max_dur)
            )
            offset = max(
                0.0, cumulative_duration - trans_duration - _SAFETY_MARGIN
            )

            filter_str = (
                trans_def.ffmpeg_filter
                .replace("{duration}", f"{trans_duration}")
                .replace("{offset}", f"{offset}")
            )
            out_label = "outv" if is_last else f"x{i}"
            transition_parts.append(
                f"[{current_label}][{video_labels[i]}]"
                f"{filter_str}[{out_label}]"
            )
            current_label = out_label
            cumulative_duration += next_dur - trans_duration
        else:
            # ── hard cut → concat ──
            out_label = "outv" if is_last else f"c{i}"
            transition_parts.append(
                f"[{current_label}][{video_labels[i]}]"
                f"concat=n=2:v=1[{out_label}]"
            )
            current_label = out_label
            cumulative_duration += next_dur

    return ";".join(trim_parts + transition_parts)


def _has_xfade_transitions(normalized_assets: list[dict]) -> bool:
    """Return True if any asset uses an xfade-based transition (not hard_cut)."""
    config = _get_treatment_config()
    for asset in normalized_assets:
        name = asset.get("transition_out")
        if name is None:
            continue
        trans_def = config.get_transition(name)
        if trans_def is not None and trans_def.ffmpeg_filter is not None:
            return True
    return False


def _build_subtitle_chain(video_filter: str, script_scenes: list[dict]) -> str:
    """Append subtitle drawtext overlays to the video filter chain."""
    overlays = build_subtitle_overlays(script_scenes)
    if not overlays:
        return video_filter
    video_filter = video_filter.replace(_OUTV, "[vsub_in]", 1)
    current_label = "vsub_in"
    for i, ov in enumerate(overlays):
        next_label = "outv" if i == len(overlays) - 1 else f"sub{i}"
        escaped = escape_drawtext(ov.text)
        video_filter += (
            f";[{current_label}]drawtext=text='{escaped}'"
            f":enable='between(t,{ov.start_seconds},{ov.end_seconds})'"
            f":fontsize=36:fontcolor=white"
            f":borderw=2:bordercolor=black"
            f":x=(w-tw)/2:y=h-th-60[{next_label}]"
        )
        current_label = next_label
    return video_filter


def _build_keyword_chain(video_filter: str, captions: list) -> str:
    """Append keyword caption drawtext overlays to the video filter chain.

    Uses larger font and thicker outline than subtitles for mobile readability.
    Style: white text with dark shadow, positioned near bottom of frame.
    """
    if not captions:
        return video_filter
    video_filter = video_filter.replace(_OUTV, "[kcap_in]", 1)
    current_label = "kcap_in"
    for i, cap in enumerate(captions):
        next_label = "outv" if i == len(captions) - 1 else f"kcap{i}"
        escaped = escape_drawtext(cap.text)
        video_filter += (
            f";[{current_label}]drawtext=text='{escaped}'"
            f":enable='between(t,{cap.start_seconds},{cap.end_seconds})'"
            f":fontsize={_KEYWORD_FONTSIZE}:fontcolor=white"
            f":borderw={_KEYWORD_BORDERW}:bordercolor=black"
            f":shadowcolor=black:shadowx=2:shadowy=2"
            f":x=(w-tw)/2:y=h-th-{_KEYWORD_Y_OFFSET}[{next_label}]"
        )
        current_label = next_label
    return video_filter


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
        # ── Audio-first mode ──
        voiceover_path = kwargs.get("voiceover_path")
        timestamps = kwargs.get("timestamps")
        narrative_structure = kwargs.get("narrative_structure")

        if voiceover_path and timestamps and narrative_structure:
            preflight_result = self._run_preflight(output_dir, job_id)
            if preflight_result is not None:
                return preflight_result

            assets_cache = kwargs.get("assets_cache", "")
            agent_dir = self._record_input(
                assets_cache, job_id,
                len(assets or []), 1,
            )
            return self._execute_audio_first(
                job_id=job_id,
                voiceover_path=voiceover_path,
                timestamps=timestamps,
                narrative_structure=narrative_structure,
                assets=assets or [],
                output_dir=output_dir,
                assets_cache=assets_cache,
                agent_dir=agent_dir,
            )

        # ── Legacy per-scene mode ──
        video_assets = assets or []
        voice_files = audio_files or []
        script_scenes = kwargs.get("script_scenes", [])

        # ── Timeline override: use canonical durations from planner ──
        timeline = kwargs.get("timeline")
        if timeline:
            video_assets = self._apply_timeline_to_assets(video_assets, timeline)

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
            job_id, agent_dir, script_scenes=script_scenes,
        )

    def _execute_assembly(
        self,
        video_assets: list[dict],
        voice_files: list[str],
        output_dir: str,
        assets_cache: str,
        job_id: int,
        agent_dir: str,
        script_scenes: list[dict] | None = None,
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
                script_scenes=script_scenes,
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
        script_scenes: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Attempt assembly. Raises on FFmpeg or unexpected errors."""
        assemble_result = self._assemble_video(
            video_assets, voice_files, video_path,
            script_scenes=script_scenes,
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

    def _assemble_video(
        self, assets: list[dict], audio_files: list[str], output_path: str,
        script_scenes: list[dict] | None = None,
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
                    scene_num, scene_path,
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

            normalized_assets = self._enrich_normalized_assets(
                assets, normalized_scene_paths,
            )

            cmd = self._build_assembly_cmd(
                valid_normalized, normalized_assets, audio_files, output_path,
                script_scenes=script_scenes,
            )

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

    def _enrich_normalized_assets(
        self, assets: list[dict], normalized_scene_paths: list[str],
    ) -> list[dict]:
        """Build enriched asset list preserving treatment metadata."""
        enriched: list[dict] = []
        for i, asset in enumerate(assets):
            norm_path = (
                normalized_scene_paths[i]
                if i < len(normalized_scene_paths)
                else None
            )
            if norm_path:
                item = {"scene": i + 1, "path": norm_path}
                for field in (
                    "treatment", "target_duration",
                    "transition_in", "transition_out",
                ):
                    if field in asset:
                        item[field] = asset[field]
                enriched.append(item)
        return enriched

    @staticmethod
    def _timeline_item_to_dict(item):
        """Convert TimelineItem dataclass or dict to dict."""
        if isinstance(item, dict):
            return item
        import dataclasses
        return dataclasses.asdict(item)

    def _apply_timeline_to_assets(self, assets, timeline):
        """Override asset durations with canonical timeline durations."""
        if not timeline:
            return assets
        resolved = []
        for i, asset in enumerate(assets):
            new_asset = dict(asset)
            if i < len(timeline):
                td_item = self._timeline_item_to_dict(timeline[i])
                td = td_item.get("target_duration_sec")
                if td is not None:
                    new_asset["target_duration"] = td
                new_asset["role"] = td_item.get("role", asset.get("role", "body"))
            resolved.append(new_asset)
        return resolved

    def _build_timeline_audio_map(self, timeline):
        """Build scene-indexed audio file mapping from timeline."""
        if not timeline:
            return {}
        return {
            i: self._timeline_item_to_dict(t).get("audio_path", "")
            for i, t in enumerate(timeline)
        }

    @staticmethod
    def _build_assembly_cmd(
        valid_normalized: list[str],
        normalized_assets: list[dict],
        audio_files: list[str],
        output_path: str,
        script_scenes: list[dict] | None = None,
    ) -> list[str]:
        """Build the FFmpeg assembly command from normalized assets."""
        cmd = ["ffmpeg", "-y"]
        for n in valid_normalized:
            cmd.extend(["-i", n])
        for af in audio_files:
            cmd.extend(["-i", af])

        # Build per-input trim + transition chain filter graph.
        # Each asset's target_duration controls the trim length; defaults to 5.
        num_videos = len([a for a in normalized_assets if a.get("path")])
        trim_parts: list[str] = []
        video_labels: list[str] = []
        builder = _get_treatment_builder()
        for i in range(num_videos):
            asset = normalized_assets[i]
            duration = asset.get("target_duration", 5)
            treatment_filter = builder.build(asset)
            label = f"t{i}"
            video_labels.append(label)
            if treatment_filter != "null":
                trim_parts.append(
                    f"[{i}:v]{treatment_filter},"
                    f"trim=duration={duration},"
                    f"setpts=PTS-STARTPTS,fps=30[{label}]"
                )
            else:
                trim_parts.append(
                    f"[{i}:v]trim=duration={duration},"
                    f"setpts=PTS-STARTPTS,fps=30[{label}]"
                )

        video_filter = _build_transition_chain(
            trim_parts, video_labels, normalized_assets, num_videos,
        )

        # ── Subtitle overlay chain (from script_scenes) ──
        if script_scenes:
            video_filter = _build_subtitle_chain(video_filter, script_scenes)

        # Use audio_sequencer for per-scene audio pairing (replaces broken amix).
        # Transition chain already handles video output to [outv], so we only
        # need the audio concat from audio_sequencer (Mode B / has_xfade=True).
        audio_filter, _outv, _outa = build_audio_video_concat(
            scene_labels=video_labels,
            num_video_inputs=num_videos,
            audio_file_count=len(audio_files) if audio_files else 0,
            has_xfade=True,
        )
        if audio_filter == "anullsrc":
            video_filter += ";anullsrc[outa]"
        else:
            video_filter += ";" + audio_filter

        cmd.extend([
            "-filter_complex", video_filter,
            "-map", _OUTV,
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            output_path,
        ])
        return cmd

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

    # ── Audio-first smart trim helpers ──

    def _probe_duration(self, clip_path: str) -> float:
        """Get clip duration in seconds using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=duration",
            "-of", "csv=p=0",
            str(clip_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffprobe duration failed for {clip_path}: {result.stderr}"
            )
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        if not lines:
            raise RuntimeError(f"ffprobe returned no duration for {clip_path}")
        return float(lines[0])

    def _detect_scene_boundaries(self, clip_path: str) -> list[float]:
        """Detect scene change timestamps using ffprobe keyframe analysis.

        Keyframes often coincide with scene boundaries in encoded video.
        Returns list of timestamps (seconds) or empty list on failure.
        """
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-skip_frame", "nokey",
            "-show_entries", "frame=pkt_pts_time",
            "-of", "csv=p=0",
            str(clip_path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        if result.returncode != 0:
            return []

        boundaries: list[float] = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    boundaries.append(float(line))
                except ValueError:
                    continue
        return boundaries

    def _find_best_cut_point(
        self, boundaries: list[float], target_duration: float,
    ) -> float:
        """Find the best scene boundary to cut at, or fall back to target."""
        tolerance = target_duration * _BOUNDARY_TOLERANCE
        best: float | None = None
        best_diff = tolerance

        for boundary in boundaries:
            diff = abs(boundary - target_duration)
            if diff <= best_diff:
                best = boundary
                best_diff = diff

        return best if best is not None else target_duration

    def _smart_trim(
        self,
        clip_path: str,
        target_duration_sec: float,
        temp_dir: Path,
    ) -> str:
        """Smart trim a clip to target duration.

        Strategy:
        1. Probe clip duration
        2. Run scene boundary detection
        3. If boundary within ±15% of target: trim at boundary + speed-adjust
        4. If no good boundary: trim from start + speed-adjust
        5. If clip shorter: slow down max 30% or loop

        Returns path to trimmed clip.
        """
        clip_dur = self._probe_duration(clip_path)
        output_path = str(
            temp_dir / f"trimmed_{Path(clip_path).stem}.mp4"
        )

        if abs(clip_dur - target_duration_sec) < _DURATION_CLOSE_ENOUGH:
            shutil.copy2(clip_path, output_path)
            return output_path

        if clip_dur > target_duration_sec:
            return self._trim_long_clip(
                clip_path, target_duration_sec, output_path,
            )
        return self._stretch_short_clip(
            clip_path, clip_dur, target_duration_sec, output_path,
        )

    def _trim_long_clip(
        self,
        clip_path: str,
        target: float,
        output_path: str,
    ) -> str:
        """Trim a clip that is longer than the target duration."""
        boundaries = self._detect_scene_boundaries(clip_path)
        cut_point = self._find_best_cut_point(boundaries, target)

        speed_factor = target / cut_point
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-ss", "0", "-to", f"{cut_point:.4f}",
            "-filter:v", f"setpts={speed_factor:.4f}*PTS",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an", output_path,
        ]
        run_ffmpeg_streaming(cmd, timeout=120, label="smart_trim")
        return output_path

    def _stretch_short_clip(
        self,
        clip_path: str,
        clip_dur: float,
        target: float,
        output_path: str,
    ) -> str:
        """Stretch or loop a clip that is shorter than the target duration."""
        if clip_dur * (1 + _MAX_SLOWDOWN) >= target:
            # Slowdown alone is enough
            speed_factor = target / clip_dur
            cmd = [
                "ffmpeg", "-y",
                "-i", str(clip_path),
                "-filter:v", f"setpts={speed_factor:.4f}*PTS",
                "-t", f"{target:.4f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-an", output_path,
            ]
        else:
            # Need to loop to fill duration
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", str(clip_path),
                "-t", f"{target:.4f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-an", output_path,
            ]
        run_ffmpeg_streaming(cmd, timeout=120, label="smart_trim_stretch")
        return output_path

    # ── Audio-first composition ──

    @staticmethod
    def _compute_beat_durations(
        narrative_structure: list[dict],
        timestamps: list[dict],
    ) -> list[float]:
        """Compute duration for each beat from word-level timestamps."""
        durations: list[float] = []
        for beat in narrative_structure:
            word_range = beat.get("word_range", [])
            if len(word_range) < 2 or not timestamps:
                durations.append(5.0)
                continue

            start_idx = max(0, min(word_range[0], len(timestamps) - 1))
            end_idx = max(start_idx + 1, min(word_range[1], len(timestamps)))

            ts_start = timestamps[start_idx]
            ts_end = timestamps[end_idx - 1]

            start_time = (
                ts_start.get("start", 0.0) if isinstance(ts_start, dict)
                else getattr(ts_start, "start", 0.0)
            )
            end_time = (
                ts_end.get("end", start_time + 5.0) if isinstance(ts_end, dict)
                else getattr(ts_end, "end", start_time + 5.0)
            )
            durations.append(max(0.5, end_time - start_time))
        return durations

    @staticmethod
    def _enrich_audio_first_assets(
        assets: list[dict],
        trimmed_clips: list[str],
        beat_durations: list[float],
    ) -> list[dict]:
        """Build enriched asset list for audio-first assembly."""
        enriched: list[dict] = []
        for i, clip_path in enumerate(trimmed_clips):
            item: dict[str, Any] = {
                "scene": i + 1,
                "path": clip_path,
                "target_duration": beat_durations[i] if i < len(beat_durations) else 5.0,
            }
            if i < len(assets):
                for field in (
                    "treatment", "transition_in", "transition_out",
                    "transition_duration", "type", "headline",
                ):
                    if field in assets[i]:
                        item[field] = assets[i][field]
            enriched.append(item)
        return enriched

    @staticmethod
    def _align_assets_to_narrative_beats(
        narrative_structure: list[dict],
        assets: list[dict],
    ) -> list[dict]:
        """Align visual assets to narrative beats by beat_id, ignoring phantom assets."""
        assets_by_beat_id = {
            asset.get("beat_id"): asset
            for asset in assets
            if asset.get("beat_id") is not None
        }
        aligned: list[dict] = []
        for beat in narrative_structure:
            beat_id = beat.get("beat_id")
            asset = dict(assets_by_beat_id.get(beat_id, {}))
            asset["beat_id"] = beat_id
            aligned.append(asset)
        return aligned

    @staticmethod
    def _build_audio_first_cmd(
        voiceover_path: str,
        trimmed_clips: list[str],
        normalized_assets: list[dict],
        keyword_captions: list,
        output_path: str,
    ) -> list[str]:
        """Build FFmpeg command for audio-first composition.

        Voiceover is input 0 (audio anchor, never trimmed).
        Visual clips are inputs 1..N, trimmed/fitted to beat durations.
        """
        cmd = ["ffmpeg", "-y"]

        # Input 0: voiceover (audio anchor)
        cmd.extend(["-i", voiceover_path])

        # Inputs 1..N: visual clips
        for clip in trimmed_clips:
            cmd.extend(["-i", clip])

        num_videos = len(trimmed_clips)

        # Build per-input trim + transition chain
        trim_parts: list[str] = []
        video_labels: list[str] = []
        builder = _get_treatment_builder()

        for i in range(num_videos):
            asset = normalized_assets[i] if i < len(normalized_assets) else {}
            duration = asset.get("target_duration", 5)
            treatment_filter = builder.build(asset)
            label = f"t{i}"
            video_labels.append(label)
            if treatment_filter != "null":
                trim_parts.append(
                    f"[{i + 1}:v]{treatment_filter},"
                    f"trim=duration={duration},"
                    f"setpts=PTS-STARTPTS,fps=30[{label}]"
                )
            else:
                trim_parts.append(
                    f"[{i + 1}:v]trim=duration={duration},"
                    f"setpts=PTS-STARTPTS,fps=30[{label}]"
                )

        video_filter = _build_transition_chain(
            trim_parts, video_labels, normalized_assets, num_videos,
        )

        # Keyword caption chain
        if keyword_captions:
            video_filter = _build_keyword_chain(video_filter, keyword_captions)

        cmd.extend([
            "-filter_complex", video_filter,
            "-map", _OUTV,
            "-map", "0:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            output_path,
        ])
        return cmd

    def _execute_audio_first(
        self,
        job_id: int,
        voiceover_path: str,
        timestamps: list[dict],
        narrative_structure: list[dict],
        assets: list[dict],
        output_dir: str,
        assets_cache: str,
        agent_dir: str,
    ) -> dict[str, Any]:
        """Execute audio-first composition pipeline.

        Uses single voiceover as timeline anchor. Visuals are smart-trimmed
        to match beat durations derived from word timestamps.
        """
        video_path = f"{output_dir}/job_{job_id}/video.mp4"
        thumbnail_path = f"{output_dir}/job_{job_id}/thumbnail.png"

        try:
            return self._try_audio_first_assemble(
                job_id, voiceover_path, timestamps,
                narrative_structure, assets,
                video_path, thumbnail_path, assets_cache, agent_dir,
            )
        except subprocess.CalledProcessError as e:
            return self._handle_ffmpeg_error(e, video_path, agent_dir)
        except Exception as e:
            logger.exception("Composer (audio-first): unexpected error")
            return {
                "status": "failed",
                "error": str(e),
                "video_path": video_path,
                "thumbnail_path": "",
            }

    def _try_audio_first_assemble(
        self,
        job_id: int,
        voiceover_path: str,
        timestamps: list[dict],
        narrative_structure: list[dict],
        assets: list[dict],
        video_path: str,
        thumbnail_path: str,
        assets_cache: str,
        agent_dir: str,
    ) -> dict[str, Any]:
        """Attempt audio-first assembly. Raises on FFmpeg or unexpected errors."""
        beat_durations = self._compute_beat_durations(
            narrative_structure, timestamps,
        )

        temp_dir = Path(tempfile.mkdtemp(prefix="composer_af_"))
        trimmed_clips: list[str] = []
        card_fallback_scenes: list[int] = []

        try:
            aligned_assets = self._align_assets_to_narrative_beats(
                narrative_structure, assets,
            )
            self._collect_beat_clips(
                beat_durations, aligned_assets, temp_dir,
                trimmed_clips, card_fallback_scenes,
            )

            if not trimmed_clips:
                output = {
                    "status": "failed",
                    "error": "No visual assets to compose",
                    "video_path": "",
                    "thumbnail_path": "",
                }
                if agent_dir:
                    write_json(
                        agent_output_file(assets_cache, job_id, "composer"),
                        output,
                    )
                return output

            return self._run_audio_first_render(
                job_id, voiceover_path, timestamps, narrative_structure,
                aligned_assets, beat_durations, trimmed_clips, card_fallback_scenes,
                video_path, thumbnail_path, assets_cache, agent_dir,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _collect_beat_clips(
        self,
        beat_durations: list[float],
        assets: list[dict],
        temp_dir: Path,
        trimmed_clips: list[str],
        card_fallback_scenes: list[int],
    ) -> None:
        """Process each beat's asset into a trimmed clip, using card fallback when needed."""
        normalizer = SceneNormalizer()
        card_gen = CardGenerator()

        for i, beat_dur in enumerate(beat_durations):
            if i >= len(assets):
                break
            asset = assets[i]
            scene_path = asset.get("path", "")

            if scene_path and Path(scene_path).exists():
                self._process_existing_scene(
                    temp_dir, normalizer, card_gen, i, beat_dur,
                    scene_path, trimmed_clips, card_fallback_scenes,
                )
            else:
                self._generate_card_fallback(
                    temp_dir, card_gen, i, beat_dur, asset,
                    trimmed_clips, card_fallback_scenes,
                )

    def _process_existing_scene(
        self,
        temp_dir: Path,
        normalizer: SceneNormalizer,
        card_gen: CardGenerator,
        index: int,
        beat_dur: float,
        scene_path: str,
        trimmed_clips: list[str],
        card_fallback_scenes: list[int],
    ) -> None:
        """Normalize and smart-trim an existing scene asset."""
        norm_path, was_card = self._process_scene(
            temp_dir, normalizer, card_gen, index + 1, scene_path,
        )
        if norm_path:
            trimmed = self._smart_trim(norm_path, beat_dur, temp_dir)
            trimmed_clips.append(trimmed)
        if was_card:
            card_fallback_scenes.append(index + 1)

    def _generate_card_fallback(
        self,
        temp_dir: Path,
        card_gen: CardGenerator,
        index: int,
        beat_dur: float,
        asset: dict,
        trimmed_clips: list[str],
        card_fallback_scenes: list[int],
    ) -> None:
        """Generate a text-card video clip as fallback for a missing visual asset."""
        card_mp4 = temp_dir / f"card_beat_{index}.mp4"
        card_png = temp_dir / f"card_beat_{index}.png"
        card_gen.generate(
            CardType.CONTEXT,
            asset.get("headline", f"Beat {index + 1}"),
            str(card_png),
        )
        ctv = card_to_video(
            str(card_png), str(card_mp4), duration=max(1, int(beat_dur)),
        )
        if ctv.success:
            trimmed_clips.append(str(card_mp4))
        card_fallback_scenes.append(index + 1)

    def _run_audio_first_render(
        self,
        job_id: int,
        voiceover_path: str,
        timestamps: list[dict],
        narrative_structure: list[dict],
        assets: list[dict],
        beat_durations: list[float],
        trimmed_clips: list[str],
        card_fallback_scenes: list[int],
        video_path: str,
        thumbnail_path: str,
        assets_cache: str,
        agent_dir: str,
    ) -> dict[str, Any]:
        """Build FFmpeg command, render, generate thumbnail, and return result."""
        keyword_captions = build_word_subtitle_captions(
            timestamps,
            hook_duration=beat_durations[0] if beat_durations else 0.0,
        )

        enriched = self._enrich_audio_first_assets(
            assets, trimmed_clips, beat_durations,
        )

        cmd = self._build_audio_first_cmd(
            voiceover_path=voiceover_path,
            trimmed_clips=trimmed_clips,
            normalized_assets=enriched,
            keyword_captions=keyword_captions,
            output_path=video_path,
        )

        logger.info(
            "Composer (audio-first): assembling %d clips + voiceover → %s",
            len(trimmed_clips), video_path,
        )
        run_ffmpeg_streaming(cmd, timeout=600, label="audio_first")

        self._generate_thumbnail(video_path, thumbnail_path)

        output = {
            "status": "completed",
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
            "card_fallback_scenes": card_fallback_scenes,
            "mode": "audio_first",
        }
        if agent_dir:
            self._persist_diagnostics(agent_dir, cmd, "")
            write_json(
                agent_output_file(assets_cache, job_id, "composer"), output,
            )
        return output
