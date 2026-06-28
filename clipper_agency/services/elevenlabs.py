"""ElevenLabs text-to-speech service.

Migrated (Phase 1, ADR 0029) from hand-rolled httpx calls to the OFFICIAL
``elevenlabs`` Python SDK. The SDK returns TYPED response objects, which
permanently eliminates the bug class where a wrong JSON key silently produced
empty timestamps: alignment is now accessed via the typed attributes
``.characters`` / ``.character_start_times_seconds`` /
``.character_end_times_seconds`` on ``CharacterAlignmentResponseModel`` rather
than via fragile string-dict lookups.

Phase 2 (ADR 0029) wraps both ``convert`` calls in ``_with_retry`` for
production resilience (retry on HTTP 429 / 5xx with exponential backoff +
jitter; do NOT retry 4xx caller errors). SDK typed errors propagate unchanged
after retries exhaust — see :data:`_RETRY_STATUS_CODES`.

The public service contract is UNCHANGED so ``voice_producer`` is untouched.
"""

import base64
import logging
import os
import random
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol, TypeVar

import httpx
from elevenlabs import ElevenLabs, VoiceSettings
from elevenlabs.core import ApiError

logger = logging.getLogger(__name__)

CHAR_LIMIT = 10_000

# --- Retry / backoff policy (CLAUDE.md: every external API call needs retry +
# exponential backoff + jitter — non-negotiable). ---------------------------------
# Retry ONLY transient failures: HTTP 429 (rate limit) + 5xx (server errors).
# 4xx caller errors (400/401/403/404/...) are NOT retried — the request itself
# is wrong; retrying burns quota without changing the outcome.
_RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3  # 1 initial + 2 retries.
_BACKOFF_BASE_SEC = 1.0  # delay = base * 2**(attempt-1) + jitter.
_BACKOFF_JITTER_FRAC = 0.5  # jitter ∈ [0, 0.5 * base_delay).

# Per-call request timeout (seconds). Restores the P1 httpx timeout=120 ceiling
# the SDK migration dropped (ECC P1 review). The SDK exposes this as the native
# ``request_options={"timeout_in_seconds": N}`` RequestOptions knob on BOTH
# ``convert`` and ``convert_with_timestamps`` — no guessing, no httpx leak.
_REQUEST_TIMEOUT_SEC = 120

_T = TypeVar("_T")

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


def _request_options() -> dict[str, Any]:
    """Per-call SDK ``RequestOptions`` for both ``convert`` methods.

    Restores the P1-dropped httpx timeout=120 ceiling via the SDK's NATIVE
    ``request_options={"timeout_in_seconds": N}`` knob (a ``RequestOptions``
    TypedDict field on both ``convert`` and ``convert_with_timestamps``) — no
    httpx leak, no guessing. Returned as a plain dict (TypedDict is structural).
    """
    return {"timeout_in_seconds": _REQUEST_TIMEOUT_SEC}


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff + jitter for *attempt* (1-based, the attempt that
    just failed). ``base * 2**(attempt-1) + uniform(0, jitter_frac * base)``.
    """
    base = _BACKOFF_BASE_SEC * (2 ** (attempt - 1))
    return base + random.uniform(0.0, _BACKOFF_JITTER_FRAC * base)


def _with_retry(call: Callable[[], _T], *, what: str) -> _T:
    """Run a SDK call with retry-on-transient-failure.

    Retries on two transient-failure kinds:
    - ``httpx.TransportError`` (timeout, connection reset, DNS, ...) — the SDK
      surfaces these DIRECTLY (they are NOT ``ApiError``); inherently transient,
      always retried.
    - ``elevenlabs.core.ApiError`` whose ``status_code`` is in
      :data:`_RETRY_STATUS_CODES` (HTTP 429 + 5xx).
    Non-retryable errors — 4xx caller errors (400/401/403/...) and any other
    exception — propagate UNCHANGED on the first attempt (Phase 1 contract: SDK
    typed errors propagate untouched; nothing is swallowed). After retries
    exhaust, the last error is re-raised.

    Args:
        call: Zero-arg callable performing ONE SDK request.
        what: Human label for the retry log (e.g. ``"convert_with_timestamps"``).

    Returns:
        Whatever *call* returns on a successful attempt.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return call()
        except (httpx.TransportError, ApiError) as exc:
            # - httpx.TransportError (timeout, connection reset, DNS, ...): the
            #   SDK surfaces these DIRECTLY — they are NOT ApiError (which is
            #   only for received HTTP error responses) — and are inherently
            #   transient, so always retry.
            # - ApiError: retry only on transient status codes (429 + 5xx);
            #   4xx caller errors propagate immediately.
            if isinstance(exc, ApiError):
                status = getattr(exc, "status_code", None)
                if status not in _RETRY_STATUS_CODES:
                    raise  # Non-retryable: 4xx caller error or unknown status.
                detail = f"HTTP {status}"
            else:
                detail = f"transport {type(exc).__name__}"
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                delay = _backoff_delay(attempt)
                logger.warning(
                    "ElevenLabs %s transient failure (%s); retry %d/%d in %.2fs",
                    what,
                    detail,
                    attempt,
                    _MAX_ATTEMPTS - 1,
                    delay,
                )
                time.sleep(delay)
            # else: final attempt exhausted → fall through to re-raise.
    # Exhausted all retries on a retryable failure — re-raise the last error
    # unchanged (Phase 1 propagation contract: typed errors propagate untouched).
    assert last_exc is not None  # loop only reaches here after a retryable failure.
    raise last_exc


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
        # Materialize the stream INSIDE _with_retry: convert() returns a LAZY
        # Iterator[bytes] and the HTTP request (and any transient ApiError) only
        # fires during iteration. Wrapping _join_audio_stream in the retry lambda
        # keeps the materialization — and thus the transient error — inside the
        # retry's try/except. Wrapping only the bare convert() call would retry
        # iterator CONSTRUCTION (which cannot fail), letting the real HTTP error
        # escape past _with_retry during b"".join.
        audio_bytes = _with_retry(
            lambda: _join_audio_stream(
                self._client.text_to_speech.convert(
                    voice_id=voice_id,
                    model_id=_model_id(),
                    text=text,
                    voice_settings=_build_voice_settings(_voice_settings_from_env()),
                    request_options=_request_options(),
                )
            ),
            what="convert",
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
        resp = _with_retry(
            lambda: self._client.text_to_speech.convert_with_timestamps(
                voice_id=voice_id,
                model_id=_model_id(),
                text=text,
                voice_settings=_build_voice_settings(settings),
                request_options=_request_options(),
            ),
            what="convert_with_timestamps",
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
