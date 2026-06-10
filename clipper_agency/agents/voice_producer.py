"""Voice Producer Agent — text-to-speech generation with provider fallback.

Audio-first architecture: generates a single continuous voiceover from
``voiceover_text`` (not per-scene).  Provider order:
ElevenLabs (with timestamps) → Gemini TTS → Fish Audio → clear failure.

Artifacts are persisted under ``assets_cache/job_{id}/agents/voice_producer/``.
"""

import json
import logging
import os
import subprocess
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.config.schema import VoiceoverOutput, WordTimestamp
from clipper_agency.core.artifacts import write_json
from clipper_agency.core.paths import (
    agent_input_file,
    agent_output_file,
    ensure_agent_dir,
)
from clipper_agency.services.elevenlabs import ElevenLabsService, chars_to_words
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

# Per-provider character limits for TTS chunking safety net
_PROVIDER_CHAR_LIMITS: dict[str, int] = {
    "elevenlabs": 10_000,
    "gemini_tts": 5_000,
    "fish_audio": 5_000,
}


def _chunk_text(text: str, chunk_size_words: int = 250) -> list[str]:
    """Split text at sentence boundaries into chunks of ~chunk_size_words."""
    import re

    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_words = 0

    for sentence in sentences:
        words = sentence.split()
        if current_words + len(words) > chunk_size_words and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_words = 0
        current_chunk.append(sentence)
        current_words += len(words)

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [text]


class VoiceProducerAgent(BaseAgent):
    """Converts voiceover text to a single audio file with word-level timestamps.

    Supports both the new ``voiceover_text`` parameter (single continuous
    narration) and the legacy ``script`` parameter (list of scenes).  When
    ``voiceover_text`` is provided the new single-audio flow is used; when
    only ``script`` is given the scene texts are joined into a single
    voiceover for backward compatibility.
    """

    def __init__(self, trace_writer: Any | None = None) -> None:
        self._trace_writer = trace_writer

    @property
    def agent_name(self) -> str:
        return "voice_producer"

    def execute(
        self,
        job_id: int,
        script: list[dict] | None = None,
        voiceover_text: str = "",
        output_dir: str = "",
        voice_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Determine voiceover text — new param takes priority
        text = voiceover_text
        if not text and script:
            text = " ".join(s.get("text", "") for s in script if s.get("text"))

        if not text:
            logger.info("Voice: no text to process")
            return self._empty_output(job_id, kwargs.get("assets_cache", ""))

        assets_cache = kwargs.get("assets_cache", "")
        agent_dir = ensure_agent_dir(assets_cache, job_id, "voice_producer") if assets_cache else ""

        # Persist input contract
        if agent_dir:
            write_json(agent_input_file(assets_cache, job_id, "voice_producer"), {
                "job_id": job_id,
                "text_length": len(text),
                "voice_id": voice_id,
            })

        # Generate single continuous voiceover
        result = self._generate_continuous_voiceover(
            text, voice_id, job_id, assets_cache,
        )

        # Persist output contract
        if agent_dir:
            write_json(agent_output_file(assets_cache, job_id, "voice_producer"),
                        result)

        return result

    # ── Single continuous voiceover generation ──

    def _generate_continuous_voiceover(
        self,
        text: str,
        voice_id: str | None,
        job_id: int,
        assets_cache: str,
    ) -> dict[str, Any]:
        """Try providers in priority order to generate a single voiceover.

        Returns a dict matching the :class:`VoiceoverOutput` schema.
        """
        for provider in _PROVIDER_ORDER:
            key_envs = _PROVIDER_KEYS.get(provider, ())
            if not any(os.getenv(key_env) for key_env in key_envs):
                logger.info("Voice: %s — missing key, skipping", provider)
                continue

            resolved_voice = voice_id or _voice_ids.get(provider, "")
            logger.info("Voice: trying %s (single audio)", provider)

            try:
                char_limit = _PROVIDER_CHAR_LIMITS.get(provider, 5000)
                if len(text) > char_limit:
                    logger.warning(
                        "Voice: text (%d chars) exceeds %s limit (%d), chunking",
                        len(text), provider, char_limit,
                    )
                    return self._build_success_output(
                        self._generate_chunked_voiceover(
                            text, resolved_voice, job_id, assets_cache, provider,
                        ),
                        provider,
                    )

                if provider == "elevenlabs":
                    result = self._try_elevenlabs_with_timestamps(
                        text, resolved_voice, job_id, assets_cache,
                    )
                else:
                    result = self._try_provider_with_approx_timestamps(
                        provider, text, resolved_voice, job_id, assets_cache,
                    )

                if result.get("status") == "success":
                    return self._build_success_output(
                        result, provider,
                    )

            except Exception as exc:
                logger.warning("Voice: %s failed: %s", provider, exc)
                continue

        logger.error("Voice: all providers failed")
        return self._build_failed_output()

    def _try_elevenlabs_with_timestamps(
        self,
        text: str,
        voice_id: str,
        job_id: int,
        assets_cache: str,
    ) -> dict[str, Any]:
        """Generate voiceover using ElevenLabs with native timestamps."""
        service = self._create_service("elevenlabs")
        audio_bytes, char_timestamps = service.generate_voice_with_timestamps(
            text, voice_id,
        )

        # Save audio file
        output_path = self._voiceover_output_path(job_id, assets_cache)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        # Convert char timestamps to word timestamps
        word_ts = self._extract_word_timestamps(char_timestamps, text)

        return {
            "status": "success",
            "voiceover_path": output_path,
            "timestamps": word_ts,
            "provider": "elevenlabs",
        }

    def _try_provider_with_approx_timestamps(
        self,
        provider: str,
        text: str,
        voice_id: str,
        job_id: int,
        assets_cache: str,
    ) -> dict[str, Any]:
        """Generate voiceover using Gemini or Fish Audio with approx timestamps."""
        service = self._create_service(provider)
        output_path = self._voiceover_output_path(job_id, assets_cache)
        service.generate_voice(text, voice_id, output_path)

        # Approximate timestamps from audio duration
        word_ts = self._approximate_timestamps(output_path, text)

        return {
            "status": "success",
            "voiceover_path": output_path,
            "timestamps": word_ts,
            "provider": provider,
        }

    # ── Timestamp methods ──

    def _extract_word_timestamps(
        self, char_timestamps: list[dict], text: str,
    ) -> list[dict]:
        """Convert ElevenLabs character-level timestamps to word-level."""
        raw = chars_to_words(text, char_timestamps)
        # Validate via Pydantic model
        return [WordTimestamp(**w).model_dump() for w in raw]

    def _approximate_timestamps(
        self, audio_path: str, text: str,
    ) -> list[dict]:
        """Estimate word timestamps by distributing words across audio duration.

        Used as a fallback when the TTS provider does not return native
        timestamps (Gemini TTS, Fish Audio).
        """
        duration = self._probe_audio_duration(audio_path)
        words = text.split()
        if not words or duration <= 0:
            return []

        per_word = duration / len(words)
        timestamps: list[dict] = []
        for i, word in enumerate(words):
            ts = WordTimestamp(
                word=word,
                start=round(i * per_word, 3),
                end=round((i + 1) * per_word, 3),
            )
            timestamps.append(ts.model_dump())

        return timestamps

    # ── Output builders ──

    @staticmethod
    def _voiceover_output_path(job_id: int, assets_cache: str) -> str:
        """Return the canonical path for the single voiceover audio."""
        if assets_cache:
            return os.path.join(
                ensure_agent_dir(assets_cache, job_id, "voice_producer"),
                "voiceover.mp3",
            )
        return f"outputs/job_{job_id}/voiceover.mp3"

    def _build_success_output(
        self,
        result: dict[str, Any],
        provider: str,
    ) -> dict[str, Any]:
        """Build a VoiceoverOutput-compatible success dict."""
        voiceover_path = result["voiceover_path"]
        duration = self._probe_audio_duration(voiceover_path)
        timestamps = result.get("timestamps", [])

        output = VoiceoverOutput(
            status="success",
            voiceover_path=voiceover_path,
            voiceover_duration_sec=duration,
            timestamps=[WordTimestamp(**t) for t in timestamps],
            provider=provider,
        )
        dump = output.model_dump()
        # Add backward-compat fields
        dump["audio_files"] = [voiceover_path]
        dump["attempts"] = [{"provider": provider, "status": "success"}]
        return dump

    @staticmethod
    def _build_failed_output() -> dict[str, Any]:
        """Build a failure dict matching VoiceoverOutput schema."""
        return {
            "status": "failed",
            "voiceover_path": "",
            "voiceover_duration_sec": 0.0,
            "timestamps": [],
            "provider": "",
            "error": "All TTS providers failed",
            "audio_files": [],
            "attempts": [],
        }

    # ── Chunked voiceover (safety net for long text) ──

    def _stitch_timestamps(
        self,
        chunk_timestamps: list[list[dict]],
        chunk_durations: list[float],
    ) -> list[dict]:
        """Merge per-chunk timestamps with cumulative audio offsets."""
        stitched: list[dict] = []
        offset = 0.0

        for chunk_ts, duration in zip(chunk_timestamps, chunk_durations):
            for ts in chunk_ts:
                stitched.append({
                    "word": ts["word"],
                    "start": ts["start"] + offset,
                    "end": ts["end"] + offset,
                })
            offset += duration

        return stitched

    def _concat_audio_chunks(self, chunk_paths: list[str], output_path: str) -> str:
        """Concatenate audio chunks using FFmpeg demuxer."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False,
        ) as list_file:
            for path in chunk_paths:
                list_file.write(f"file '{path}'\n")
            list_path = Path(list_file.name)

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_path), "-c", "copy", output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
        list_path.unlink(missing_ok=True)
        return output_path

    def _generate_chunked_voiceover(
        self,
        text: str,
        voice_id: str | None,
        job_id: int,
        assets_cache: str,
        provider: str,
    ) -> dict[str, Any]:
        """Generate voiceover by chunking text, generating per-chunk, then concatenating."""
        chunks = _chunk_text(text)
        logger.warning("Voice: chunking %d chars into %d chunks", len(text), len(chunks))

        chunk_paths: list[str] = []
        chunk_timestamps: list[list[dict]] = []
        chunk_durations: list[float] = []

        output_dir = os.path.dirname(self._voiceover_output_path(job_id, assets_cache))

        for i, chunk in enumerate(chunks):
            chunk_path = os.path.join(output_dir, f"chunk_{i:03d}.mp3")

            if provider == "elevenlabs":
                service = self._create_service("elevenlabs")
                audio_bytes, char_ts = service.generate_voice_with_timestamps(
                    chunk, voice_id or "",
                )
                os.makedirs(os.path.dirname(chunk_path), exist_ok=True)
                with open(chunk_path, "wb") as f:
                    f.write(audio_bytes)
                word_ts = self._extract_word_timestamps(char_ts, chunk)
            else:
                service = self._create_service(provider)
                service.generate_voice(chunk, voice_id or "", chunk_path)
                word_ts = self._approximate_timestamps(chunk_path, chunk)

            chunk_paths.append(chunk_path)
            chunk_timestamps.append(word_ts)
            chunk_durations.append(self._probe_audio_duration(chunk_path))

        # Concatenate audio
        final_path = self._voiceover_output_path(job_id, assets_cache)
        self._concat_audio_chunks(chunk_paths, final_path)

        # Stitch timestamps
        stitched = self._stitch_timestamps(chunk_timestamps, chunk_durations)

        return {
            "status": "success",
            "voiceover_path": final_path,
            "timestamps": stitched,
            "provider": provider,
        }

    # ── Helpers ──

    @staticmethod
    def _empty_output(job_id: int, assets_cache: str) -> dict[str, Any]:
        """Return a completed output with empty fields when there is no text."""
        path = ""
        if assets_cache:
            path = os.path.join(
                ensure_agent_dir(assets_cache, job_id, "voice_producer"),
                "voiceover.mp3",
            )
        return {
            "status": "completed",
            "voiceover_path": path,
            "voiceover_duration_sec": 0.0,
            "timestamps": [],
            "provider": "",
            "audio_files": [],
            "attempts": [],
        }

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
