"""ElevenLabs text-to-speech service."""

import base64
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CHAR_LIMIT = 10_000

# Default voice settings for the audio-first architecture. Single source of
# truth — _voice_settings_from_env reads every default from here (incl. speed).
DEFAULT_VOICE_SETTINGS: dict[str, Any] = {
    "stability": 0.4,
    "similarity_boost": 0.75,
    "style": 0.7,
    "use_speaker_boost": True,
    "speed": 1.0,
}

# Default TTS model (Free-tier-safe). Paid plans unlock eleven_v3 (emotion /
# intonation tags) and eleven_turbo_v2_5 (low-latency) — switch via .env.
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


def _model_id() -> str:
    """TTS model id, env-overridable via ``ELEVENLABS_MODEL``.

    Mitigation: missing/empty var falls back to ``DEFAULT_MODEL_ID`` so a
    bare ``.env`` never breaks TTS.
    """
    return os.getenv("ELEVENLABS_MODEL", DEFAULT_MODEL_ID) or DEFAULT_MODEL_ID


def _env_float(name: str, default: float) -> float:
    """Env var as float; missing or unparseable → ``default``."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Env var as bool. Empty → ``default``; ``false/0/no/off`` → False; else True."""
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("false", "0", "no", "off")


def _voice_settings_from_env() -> dict[str, Any]:
    """Voice settings from env, each knob falling back to its default.

    A partial ``.env`` (e.g. only ``ELEVENLABS_VOICE_STYLE`` set) still yields
    a valid settings dict and never raises. Knobs:

    - ``ELEVENLABS_VOICE_STABILITY`` (0.0–1.0, default 0.4)
    - ``ELEVENLABS_VOICE_SIMILARITY`` (0.0–1.0, default 0.75)
    - ``ELEVENLABS_VOICE_STYLE`` (0.0–1.0, default 0.7; higher = more intonation)
    - ``ELEVENLABS_VOICE_SPEAKER_BOOST`` (bool, default true)
    - ``ELEVENLABS_VOICE_SPEED`` (0.7–1.2, default 1.0; pacing)
    """
    return {
        "stability": _env_float("ELEVENLABS_VOICE_STABILITY", DEFAULT_VOICE_SETTINGS["stability"]),
        "similarity_boost": _env_float(
            "ELEVENLABS_VOICE_SIMILARITY", DEFAULT_VOICE_SETTINGS["similarity_boost"]
        ),
        "style": _env_float("ELEVENLABS_VOICE_STYLE", DEFAULT_VOICE_SETTINGS["style"]),
        "use_speaker_boost": _env_bool(
            "ELEVENLABS_VOICE_SPEAKER_BOOST", DEFAULT_VOICE_SETTINGS["use_speaker_boost"]
        ),
        "speed": _env_float("ELEVENLABS_VOICE_SPEED", DEFAULT_VOICE_SETTINGS["speed"]),
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
            word,
            char_idx,
            char_timestamps,
        )
        if word_start is not None and word_end is not None:
            word_timestamps.append(
                {
                    "word": word,
                    "start": word_start,
                    "end": word_end,
                }
            )

    return word_timestamps


class ElevenLabsService:
    """Text-to-speech generation via ElevenLabs API."""

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("ELEVENLABS_API_KEY")

    def _post_tts(
        self,
        client: httpx.Client,
        path: str,
        text: str,
        voice_settings: dict[str, Any],
    ) -> httpx.Response:
        """POST a text-to-speech request and return the raw response.

        Shared by :meth:`generate_voice` and
        :meth:`generate_voice_with_timestamps` — same headers, timeout, and
        body shape (``text`` / ``model_id`` / ``voice_settings``); only the
        endpoint *path* differs. Raises ``HTTPStatusError`` on API errors.
        """
        resp = client.post(
            path,
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": _model_id(),
                "voice_settings": voice_settings,
            },
        )
        resp.raise_for_status()
        return resp

    def generate_voice(self, text: str, voice_id: str, output_path: str) -> str:
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
            resp = self._post_tts(
                client,
                f"/text-to-speech/{voice_id}",
                text,
                _voice_settings_from_env(),
            )
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

        settings = voice_settings or _voice_settings_from_env()

        logger.info(
            "ElevenLabs: TTS+timestamps request — voice_id=%s text_len=%d",
            voice_id,
            len(text),
        )
        with httpx.Client(base_url=self.BASE_URL, timeout=120) as client:
            resp = self._post_tts(
                client,
                f"/text-to-speech/{voice_id}/with-timestamps",
                text,
                settings,
            )
            data = resp.json()

        audio_bytes = _extract_audio_bytes(data)
        char_timestamps = _extract_char_timestamps(data)

        logger.info(
            "ElevenLabs: got audio (%d bytes) + %d char timestamps",
            len(audio_bytes),
            len(char_timestamps),
        )
        return audio_bytes, char_timestamps


def _extract_audio_bytes(data: dict) -> bytes:
    """Extract audio bytes from the with-timestamps response.

    The ``/with-timestamps`` endpoint returns the audio under the
    ``audio_base64`` key (verified live: top-level keys are ``audio_base64``,
    ``alignment``, ``normalized_alignment`` — there is no ``audio`` key).
    """
    audio_b64 = data.get("audio_base64", "")
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

    return [{"char": c, "start": s, "end": e} for c, s, e in zip(chars, starts, ends)]
