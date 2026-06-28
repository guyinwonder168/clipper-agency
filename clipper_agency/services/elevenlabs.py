"""ElevenLabs text-to-speech service.

Migrated (Phase 1, ADR 0029) from hand-rolled httpx calls to the OFFICIAL
``elevenlabs`` Python SDK. The SDK returns TYPED response objects, which
permanently eliminates the bug class where a wrong JSON key silently produced
empty timestamps: alignment is now accessed via the typed attributes
``.characters`` / ``.character_start_times_seconds`` /
``.character_end_times_seconds`` on ``CharacterAlignmentResponseModel`` rather
than via fragile string-dict lookups.

The public service contract is UNCHANGED so ``voice_producer`` is untouched.
"""

import base64
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from elevenlabs import ElevenLabs, VoiceSettings

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


def _build_voice_settings(settings: dict[str, Any]) -> VoiceSettings:
    """Build a typed SDK ``VoiceSettings`` from a plain settings dict.

    Only known fields are forwarded; unknown keys are ignored so a partial
    caller-supplied dict cannot break construction. All ``VoiceSettings``
    fields are optional in the SDK, so missing keys simply use SDK defaults.
    """
    return VoiceSettings(
        stability=settings.get("stability"),
        similarity_boost=settings.get("similarity_boost"),
        style=settings.get("style"),
        use_speaker_boost=settings.get("use_speaker_boost"),
        speed=settings.get("speed"),
    )


class _TimestampsResponse(Protocol):
    """Structural type for the SDK ``AudioWithTimestampsResponse``.

    Lets tests inject a lightweight stub (e.g. ``SimpleNamespace``) without
    importing the concrete SDK type.
    """

    audio_base_64: str

    @property
    def alignment(self) -> Any: ...


def _alignment_to_char_timestamps(alignment: Any) -> list[dict]:
    """Project a typed alignment onto the ``{"char","start","end"}`` shape.

    Reads the TYPED attributes ``.characters`` / ``.character_start_times_seconds``
    / ``.character_end_times_seconds`` (the SDK never exposes the old ``chars``
    key here), so a key-typo cannot silently yield an empty list. Returns ``[]``
    when the alignment is absent or empty — matching the legacy contract.
    """
    if alignment is None:
        return []
    chars = getattr(alignment, "characters", None) or []
    starts = getattr(alignment, "character_start_times_seconds", None) or []
    ends = getattr(alignment, "character_end_times_seconds", None) or []
    if not chars:
        return []
    return [{"char": c, "start": s, "end": e} for c, s, e in zip(chars, starts, ends)]


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


def _decode_audio(resp: _TimestampsResponse) -> bytes:
    """Decode the SDK response's base64 audio payload to raw bytes.

    The SDK exposes audio as ``audio_base_64`` (a base64 STRING, not bytes).
    """
    audio_b64 = getattr(resp, "audio_base_64", "") or ""
    if not audio_b64:
        raise ValueError("ElevenLabs response missing audio data")
    return base64.b64decode(audio_b64)


def _join_audio_stream(stream: Iterator[bytes]) -> bytes:
    """Materialize a chunked ``convert()`` byte stream into one buffer."""
    return b"".join(stream)


class ElevenLabsService:
    """Text-to-speech generation via the official ElevenLabs SDK."""

    def __init__(self) -> None:
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        # One client per service; api_key is None here when unset — guarded by
        # the per-method ``if not self.api_key`` checks (legacy contract).
        self._client = ElevenLabs(api_key=self.api_key or "")

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
        audio_bytes = _join_audio_stream(
            self._client.text_to_speech.convert(
                voice_id=voice_id,
                model_id=_model_id(),
                text=text,
                voice_settings=_build_voice_settings(_voice_settings_from_env()),
            )
        )
        path.write_bytes(audio_bytes)

        logger.info("ElevenLabs: saved audio to %s (%d bytes)", output_path, len(audio_bytes))
        return str(path)

    def generate_voice_with_timestamps(
        self, text: str, voice_id: str, voice_settings: dict | None = None
    ) -> tuple[bytes, list[dict]]:
        """Generate speech audio with character-level timestamps.

        Uses the SDK ``text_to_speech.convert_with_timestamps`` which returns a
        TYPED ``AudioWithTimestampsResponse`` (audio as base64 +
        ``CharacterAlignmentResponseModel`` alignment). Alignment is read via
        typed attributes, so the legacy ``chars`` vs ``characters`` key-typo
        bug class cannot recur.

        Args:
            text: The text to synthesize.
            voice_id: ElevenLabs voice identifier.
            voice_settings: Optional voice configuration dict. Defaults to
                :data:`DEFAULT_VOICE_SETTINGS` via ``_voice_settings_from_env``.

        Returns:
            Tuple of ``(audio_bytes, char_timestamps)`` where
            ``char_timestamps`` is a list of
            ``{"char": "x", "start": 0.0, "end": 0.1}``.

        Raises:
            ValueError: If ``ELEVENLABS_API_KEY`` is not set.
        """
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")

        settings = voice_settings or _voice_settings_from_env()

        logger.info(
            "ElevenLabs: TTS+timestamps request — voice_id=%s text_len=%d",
            voice_id,
            len(text),
        )
        resp = self._client.text_to_speech.convert_with_timestamps(
            voice_id=voice_id,
            model_id=_model_id(),
            text=text,
            voice_settings=_build_voice_settings(settings),
        )

        audio_bytes = _decode_audio(resp)
        char_timestamps = _alignment_to_char_timestamps(getattr(resp, "alignment", None))

        # DEBUG-only character count — never logs raw audio / base64.
        logger.debug(
            "ElevenLabs: alignment character count=%d",
            len(char_timestamps),
        )
        logger.info(
            "ElevenLabs: got audio (%d bytes) + %d char timestamps",
            len(audio_bytes),
            len(char_timestamps),
        )
        return audio_bytes, char_timestamps
