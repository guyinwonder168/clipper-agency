"""Voice Producer Agent — text-to-speech generation with provider fallback.

Provider order: ElevenLabs → Gemini TTS → Fish Audio → clear failure.
Artifacts are persisted under ``assets_cache/job_{id}/agents/voice_producer/``.
"""

import json
import logging
import os
import subprocess
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.core.artifacts import write_json
from clipper_agency.core.paths import (
    agent_input_file,
    agent_output_file,
    ensure_agent_dir,
)
from clipper_agency.services.elevenlabs import ElevenLabsService
from clipper_agency.services.fish_audio import FishAudioService
from clipper_agency.services.gemini_tts import GeminiTTSService

logger = logging.getLogger(__name__)

# Default voice IDs per provider
_voice_ids = {
    "elevenlabs": "JBFqnCBsd6RMkjVDRZzb",
    "fish_audio": "",
}

# Provider priority — tried in this order
_PROVIDER_ORDER = ["elevenlabs", "gemini_tts", "fish_audio"]

# Map provider name → accepted env vars
_PROVIDER_KEYS = {
    "elevenlabs": ("ELEVENLABS_API_KEY",),
    "gemini_tts": ("GEMINI_API_KEY",),
    "fish_audio": ("FISHAUDIO_API_KEY",),
}


class VoiceProducerAgent(BaseAgent):
    """Converts script scenes to audio files using configured TTS providers."""

    @property
    def agent_name(self) -> str:
        return "voice_producer"

    def execute(
        self,
        job_id: int,
        script: list[dict] | None = None,
        output_dir: str = "",
        voice_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        scenes = script or []

        if not scenes:
            logger.info("Voice: no scenes to process")
            return {"status": "completed", "audio_files": [], "attempts": []}

        assets_cache = kwargs.get("assets_cache", "")
        agent_dir = ensure_agent_dir(assets_cache, job_id, "voice_producer") if assets_cache else ""

        # Persist input contract
        if agent_dir:
            write_json(agent_input_file(assets_cache, job_id, "voice_producer"), {
                "job_id": job_id,
                "scene_count": len(scenes),
                "voice_id": voice_id,
            })

        attempts, audio_files = self._attempt_providers(
            scenes, voice_id, job_id, assets_cache,
        )

        # Build audio metadata with ffprobe durations
        provider_name = ""
        for attempt in attempts:
            if attempt.get("status") in ("success", "partial"):
                provider_name = attempt.get("provider", "")
                break
        audio_meta = self._build_audio_metadata(
            agent_dir, len(scenes), provider_name
        ) if agent_dir else []

        all_generated = len(audio_files) >= len(scenes)
        output = {
            "status": "completed" if all_generated else "failed",
            "audio_files": audio_files,
            "audio_metadata": audio_meta,
            "attempts": attempts,
        }
        if not all_generated:
            output["error"] = "All TTS providers failed"

        # Persist output contract
        if agent_dir:
            write_json(agent_output_file(assets_cache, job_id, "voice_producer"),
                        output)
            write_json(
                os.path.join(agent_dir, "provider_attempts.json"),
                attempts,
            )

        return output

    def _attempt_providers(
        self,
        scenes: list[dict],
        voice_id: str | None,
        job_id: int,
        assets_cache: str,
    ) -> tuple[list[dict], list[str]]:
        """Try each provider in priority order.

        If a provider partially succeeds, remaining scenes are passed to the
        next provider.  Returns (attempts, audio_files).
        """
        attempts: list[dict] = []
        audio_files: list[str] = []
        remaining = list(scenes)

        for provider in _PROVIDER_ORDER:
            if not remaining:
                break

            attempt = self._try_provider(provider, remaining, voice_id,
                                         job_id, assets_cache)
            attempts.append(attempt)

            if attempt["status"] == "success":
                audio_files.extend(attempt["audio_files"])
                break

            if attempt["status"] == "partial":
                completed_ids = attempt["completed_scene_ids"]
                audio_files.extend(attempt["audio_files"])
                remaining = [s for s in remaining
                             if s.get("scene", 0) not in completed_ids]

        return attempts, audio_files

    def _try_provider(
        self,
        provider: str,
        scenes: list[dict],
        voice_id: str | None,
        job_id: int,
        assets_cache: str,
    ) -> dict[str, Any]:
        """Try generating voice with a single provider.

        Returns an attempt dict with status, audio_files, and error.
        """
        key_envs = _PROVIDER_KEYS.get(provider, ())
        if not any(os.getenv(key_env) for key_env in key_envs):
            logger.info("Voice: %s — missing key", provider)
            return {"provider": provider, "status": "missing_key",
                    "audio_files": []}

        resolved_voice = voice_id or _voice_ids.get(provider, "")
        logger.info("Voice: trying %s (%d scenes)", provider, len(scenes))

        service = self._create_service(provider)
        audio_files: list[str] = []
        completed_ids: set[int] = set()

        for scene in scenes:
            text = scene.get("text", "")
            scene_id = scene.get("scene", 0)

            if assets_cache:
                voices_dir = os.path.join(
                    ensure_agent_dir(assets_cache, job_id, "voice_producer"),
                    "voices",
                )
                os.makedirs(voices_dir, exist_ok=True)
                output_path = os.path.join(voices_dir,
                                           f"scene_{scene_id}.mp3")
            else:
                output_path = f"outputs/job_{job_id}/scene_{scene_id}.mp3"

            try:
                path = service.generate_voice(text, resolved_voice, output_path)
            except Exception as exc:
                logger.warning("Voice: %s — failed on scene %d: %s",
                               provider, scene_id, exc)
                if audio_files:
                    return {
                        "provider": provider,
                        "status": "partial",
                        "audio_files": audio_files,
                        "completed_scene_ids": completed_ids,
                        "error": str(exc),
                    }
                return {"provider": provider, "status": "failed",
                        "error": str(exc), "audio_files": []}

            audio_files.append(path)
            completed_ids.add(scene_id)

        logger.info("Voice: %s — completed %d files", provider, len(audio_files))
        return {"provider": provider, "status": "success",
                "audio_files": audio_files}

    # ── Service factory (kept for testability) ──

    def _create_service(self, provider: str):
        """Create the TTS service instance for the given provider."""
        if provider == "elevenlabs":
            return ElevenLabsService()
        if provider == "gemini_tts":
            return GeminiTTSService()
        if provider == "fish_audio":
            return FishAudioService()
        raise ValueError(f"Unknown TTS provider: {provider}")

    def _probe_audio_duration(self, filepath: str) -> float:
        """Measure audio duration in seconds using ffprobe."""
        if not os.path.exists(filepath):
            return 0.0
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", filepath],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return 0.0
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0.0))
        except Exception:
            return 0.0

    def _build_audio_metadata(self, output_dir: str, scene_count: int, provider: str = "") -> list[dict]:
        """Build per-scene audio metadata with ffprobe durations."""
        voices_dir = os.path.join(output_dir, "voices")
        if not os.path.isdir(voices_dir):
            return []
        meta_list: list[dict] = []
        for i in range(1, scene_count + 1):
            path = os.path.join(voices_dir, f"scene_{i}.mp3")
            duration = self._probe_audio_duration(path)
            meta_list.append({
                "scene": i,
                "audio_path": path,
                "audio_duration_sec": duration,
                "provider": provider,
            })
        return meta_list
