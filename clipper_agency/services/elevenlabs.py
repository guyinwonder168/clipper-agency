"""ElevenLabs text-to-speech service."""

import base64
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CHAR_LIMIT = 10_000

# Default voice settings for the audio-first architecture
DEFAULT_VOICE_SETTINGS: dict[str, Any] = {
    "stability": 0.4,
    "similarity_boost": 0.75,
    "style": 0.7,
    "use_speaker_boost": True,
}


def _scan_word_chars(
    word: str,
    char_idx: int,
    char_timestamps: list[dict],
) -> tuple[float | None, float | None, int]:
    """Scan char_timestamps starting at *char_idx* to find one word's bounds.

    Returns:
        ``(word_start, word_end, new_char_idx)`` where *new_char_idx* is
        the position to resume scanning for the next word.
    """
    word_start: float | None = None
    word_end: float | None = None
    word_chars_seen = 0

    while char_idx < len(char_timestamps) and word_chars_seen < len(word):
        ct = char_timestamps[char_idx]
        if ct.get("char", "").strip():
            if word_start is None:
                word_start = ct["start"]
            word_end = ct["end"]
            word_chars_seen += 1
        char_idx += 1

    return word_start, word_end, char_idx


def chars_to_words(text: str, char_timestamps: list[dict]) -> list[dict]:
    """Convert character-level timestamps to word-level timestamps.

    Args:
        text: The original text that was sent to TTS.
        char_timestamps: List of ``{"char": "x", "start": 0.0, "end": 0.1}``
            from ElevenLabs.

    Returns:
        List of ``{"word": "hello", "start": 0.0, "end": 0.5}``.
    """
    if not text or not char_timestamps:
        return []

    words = text.split()
    word_timestamps: list[dict] = []
    char_idx = 0

    for word in words:
        word_start, word_end, char_idx = _scan_word_chars(
            word, char_idx, char_timestamps,
        )
        if word_start is not None and word_end is not None:
            word_timestamps.append({
                "word": word,
                "start": word_start,
                "end": word_end,
            })

    return word_timestamps


class ElevenLabsService:
    """Text-to-speech generation via ElevenLabs API."""

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("ELEVENLABS_API_KEY")

    def generate_voice(
        self, text: str, voice_id: str, output_path: str
    ) -> str:
        """Generate speech audio from text and write to a file.

        Returns:
            The output file path.
        """
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("ElevenLabs: TTS request — voice_id=%s text_len=%d", voice_id, len(text))
        with httpx.Client(base_url=self.BASE_URL, timeout=120) as client:
            resp = client.post(
                f"/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.7},
                },
            )
            resp.raise_for_status()
            path.write_bytes(resp.content)

        logger.info("ElevenLabs: saved audio to %s (%d bytes)", output_path, len(resp.content))
        return str(path)

    def generate_voice_with_timestamps(
        self, text: str, voice_id: str, voice_settings: dict | None = None
    ) -> tuple[bytes, list[dict]]:
        """Generate speech audio with character-level timestamps.

        Uses the ``POST /v1/text-to-speech/{voice_id}/with-timestamps``
        endpoint which returns JSON with both audio (base64) and alignment
        data containing per-character start/end times.

        Args:
            text: The text to synthesize.
            voice_id: ElevenLabs voice identifier.
            voice_settings: Optional voice configuration.  Defaults to
                :data:`DEFAULT_VOICE_SETTINGS`.

        Returns:
            Tuple of ``(audio_bytes, char_timestamps)`` where
            ``char_timestamps`` is a list of
            ``{"char": "x", "start": 0.0, "end": 0.1}``.

        Raises:
            ValueError: If ``ELEVENLABS_API_KEY`` is not set.
            httpx.HTTPStatusError: On API errors.
        """
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")

        settings = voice_settings or DEFAULT_VOICE_SETTINGS

        logger.info(
            "ElevenLabs: TTS+timestamps request — voice_id=%s text_len=%d",
            voice_id, len(text),
        )
        with httpx.Client(base_url=self.BASE_URL, timeout=120) as client:
            resp = client.post(
                f"/text-to-speech/{voice_id}/with-timestamps",
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": settings,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        audio_bytes = _extract_audio_bytes(data)
        char_timestamps = _extract_char_timestamps(data)

        logger.info(
            "ElevenLabs: got audio (%d bytes) + %d char timestamps",
            len(audio_bytes), len(char_timestamps),
        )
        return audio_bytes, char_timestamps


def _extract_audio_bytes(data: dict) -> bytes:
    """Extract audio bytes from the with-timestamps response."""
    audio_b64 = data.get("audio", "")
    if not audio_b64:
        raise ValueError("ElevenLabs response missing audio data")
    return base64.b64decode(audio_b64)


def _extract_char_timestamps(data: dict) -> list[dict]:
    """Extract character-level timestamps from the with-timestamps response."""
    alignment = data.get("alignment", {})
    chars = alignment.get("chars", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    if not chars:
        return []

    return [
        {"char": c, "start": s, "end": e}
        for c, s, e in zip(chars, starts, ends)
    ]
