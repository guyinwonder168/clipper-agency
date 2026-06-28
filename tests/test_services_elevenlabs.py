"""Tests for ElevenLabs voice generation service.

Migrated (Phase 1, ADR 0029) to mock the OFFICIAL ``elevenlabs`` SDK client
instead of patching ``httpx``. ``convert_with_timestamps`` returns a TYPED
``AudioWithTimestampsResponse``; tests stub it with ``SimpleNamespace`` holding
the same typed attributes (``.characters`` / ``.character_start_times_seconds``
/ ``.character_end_times_seconds``) the production code reads — so a key-typo
bug (e.g. ``chars`` vs ``characters``) would surface here, not slip through.
"""

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from elevenlabs.core import ApiError

from clipper_agency.services.elevenlabs import (
    DEFAULT_VOICE_SETTINGS,
    ElevenLabsService,
    chars_to_words,
)

# ---------------------------------------------------------------------------
# SDK stub helpers
# ---------------------------------------------------------------------------


def _make_alignment(
    characters: list[str], starts: list[float], ends: list[float]
) -> SimpleNamespace:
    """Stub the SDK ``CharacterAlignmentResponseModel`` typed attributes."""
    return SimpleNamespace(
        characters=characters,
        character_start_times_seconds=starts,
        character_end_times_seconds=ends,
    )


def _make_timestamps_response(
    characters: list[str],
    starts: list[float],
    ends: list[float],
    audio: bytes = b"fake_audio_bytes",
) -> SimpleNamespace:
    """Stub the SDK ``AudioWithTimestampsResponse`` typed object.

    Mirrors the real SDK shape: ``audio_base_64`` is a base64 STRING (not
    bytes) and ``alignment`` carries the typed char/seconds attributes.
    """
    return SimpleNamespace(
        audio_base_64=base64.b64encode(audio).decode(),
        alignment=_make_alignment(characters, starts, ends),
        normalized_alignment=_make_alignment(characters, starts, ends),
    )


def _stub_service(
    svc: ElevenLabsService, timestamps_resp=None, convert_audio: bytes = b"fake_audio_data"
):
    """Patch the SDK client bound to *svc* with a MagicMock.

    ``convert`` returns a byte stream (joined in production); ``convert_with_timestamps``
    returns the provided typed stub. Returns the mock for call assertions.
    """
    mock_client = MagicMock()
    mock_client.text_to_speech.convert.return_value = iter([convert_audio])
    if timestamps_resp is None:
        timestamps_resp = _make_timestamps_response([], [], [])
    mock_client.text_to_speech.convert_with_timestamps.return_value = timestamps_resp
    svc._client = mock_client
    return mock_client


# ---------------------------------------------------------------------------
# Existing tests (backward compat)
# ---------------------------------------------------------------------------


def test_service_init():
    with patch.dict("os.environ", {}, clear=True):
        svc = ElevenLabsService()
        assert svc.api_key is None


def test_generate_voice(tmp_path):
    with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
        svc = ElevenLabsService()
        _stub_service(svc, convert_audio=b"fake_audio_data")
        output_path = tmp_path / "voice.mp3"
        result = svc.generate_voice(
            text="Halo, ini suara uji coba",
            voice_id="test-voice-id",
            output_path=str(output_path),
        )
    assert result == str(output_path)
    assert output_path.read_bytes() == b"fake_audio_data"


def test_generate_voice_no_key(tmp_path):
    with patch.dict("os.environ", {}, clear=True):
        svc = ElevenLabsService()
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            svc.generate_voice("test", "voice", str(tmp_path / "v.mp3"))


# ---------------------------------------------------------------------------
# generate_voice_with_timestamps tests
# ---------------------------------------------------------------------------


def test_generate_voice_with_timestamps():
    resp = _make_timestamps_response(
        characters=["H", "e", "l", "l", "o", " ", "w", "o", "r", "l", "d"],
        starts=[0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5],
        ends=[0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55],
    )
    with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
        svc = ElevenLabsService()
        _stub_service(svc, timestamps_resp=resp)
        audio_bytes, timestamps = svc.generate_voice_with_timestamps(
            text="Hello world",
            voice_id="test-voice-id",
        )

    assert audio_bytes == b"fake_audio_bytes"
    assert len(timestamps) == 11
    assert timestamps[0]["char"] == "H"
    assert timestamps[0]["start"] == 0.0


def test_generate_voice_with_timestamps_no_key():
    with patch.dict("os.environ", {}, clear=True):
        svc = ElevenLabsService()
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            svc.generate_voice_with_timestamps("test", "voice")


# Env knobs read by _voice_settings_from_env / _model_id. Cleared in
# default-settings tests so a developer's loaded .env cannot leak through and
# flip the asserted defaults (hermetic — no real network / no .env dependency).
_VOICE_ENV_KNOBS = (
    "ELEVENLABS_MODEL",
    "ELEVENLABS_VOICE_STABILITY",
    "ELEVENLABS_VOICE_SIMILARITY",
    "ELEVENLABS_VOICE_STYLE",
    "ELEVENLABS_VOICE_SPEAKER_BOOST",
    "ELEVENLABS_VOICE_SPEED",
)


def test_generate_voice_with_timestamps_uses_default_settings(monkeypatch):
    """Voice settings should default to the audio-first architecture defaults."""
    # Arrange — isolate env: API key set, every voice/model knob removed so a
    # developer's loaded .env cannot flip the asserted defaults.
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    for knob in _VOICE_ENV_KNOBS:
        monkeypatch.delenv(knob, raising=False)

    svc = ElevenLabsService()
    mock_client = _stub_service(svc)

    # Act
    svc.generate_voice_with_timestamps(text="test", voice_id="v")

    # Assert — SDK received a typed VoiceSettings with default values.
    call_kwargs = mock_client.text_to_speech.convert_with_timestamps.call_args.kwargs
    vs = call_kwargs["voice_settings"]
    assert vs.stability == 0.4
    assert vs.similarity_boost == 0.75
    assert vs.style == 0.7
    assert vs.use_speaker_boost is True


def test_generate_voice_with_timestamps_custom_settings(monkeypatch):
    """Custom voice settings should override defaults."""
    # Arrange
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    for knob in _VOICE_ENV_KNOBS:
        monkeypatch.delenv(knob, raising=False)

    svc = ElevenLabsService()
    mock_client = _stub_service(svc)

    # Act
    custom = {"stability": 0.8, "similarity_boost": 0.9}
    svc.generate_voice_with_timestamps(
        text="test",
        voice_id="v",
        voice_settings=custom,
    )

    # Assert
    call_kwargs = mock_client.text_to_speech.convert_with_timestamps.call_args.kwargs
    vs = call_kwargs["voice_settings"]
    assert vs.stability == 0.8
    assert vs.similarity_boost == 0.9


# ---------------------------------------------------------------------------
# Regression: typed-alignment shape lock
# ---------------------------------------------------------------------------


def test_generate_voice_with_timestamps_locks_char_shape(monkeypatch):
    """Regression (ADR 0029): a typed alignment of ['H','i'] with known
    start/end must yield EXACTLY the {"char","start","end"} list shape —
    locking the contract that a ``chars`` vs ``characters`` key-typo
    cannot silently empty out.
    """
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    resp = _make_timestamps_response(
        characters=["H", "i"],
        starts=[0.0, 0.12],
        ends=[0.12, 0.24],
        audio=b"hi",
    )
    svc = ElevenLabsService()
    _stub_service(svc, timestamps_resp=resp)

    audio_bytes, timestamps = svc.generate_voice_with_timestamps(text="Hi", voice_id="v")

    assert audio_bytes == b"hi"
    assert timestamps == [
        {"char": "H", "start": 0.0, "end": 0.12},
        {"char": "i", "start": 0.12, "end": 0.24},
    ]


def test_generate_voice_with_timestamps_empty_alignment(monkeypatch):
    """Missing/empty typed alignment → empty char list (no KeyError)."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    resp = _make_timestamps_response([], [], [])
    svc = ElevenLabsService()
    _stub_service(svc, timestamps_resp=resp)

    audio_bytes, timestamps = svc.generate_voice_with_timestamps(text="", voice_id="v")
    assert audio_bytes == b"fake_audio_bytes"
    assert timestamps == []


def test_generate_voice_with_timestamps_missing_audio(monkeypatch):
    """Empty audio_base_64 raises ValueError (no silent empty file)."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    # audio_base_64 present but empty string
    resp = SimpleNamespace(
        audio_base_64="",
        alignment=_make_alignment([], [], []),
        normalized_alignment=_make_alignment([], [], []),
    )
    svc = ElevenLabsService()
    _stub_service(svc, timestamps_resp=resp)

    with pytest.raises(ValueError, match="missing audio data"):
        svc.generate_voice_with_timestamps(text="x", voice_id="v")


# ---------------------------------------------------------------------------
# chars_to_words tests
# ---------------------------------------------------------------------------


class TestCharsToWords:
    """Character-to-word timestamp conversion."""

    def test_simple_two_words(self):
        text = "hello world"
        char_ts = [
            {"char": "h", "start": 0.0, "end": 0.1},
            {"char": "e", "start": 0.1, "end": 0.2},
            {"char": "l", "start": 0.2, "end": 0.3},
            {"char": "l", "start": 0.3, "end": 0.4},
            {"char": "o", "start": 0.4, "end": 0.5},
            {"char": " ", "start": 0.5, "end": 0.55},
            {"char": "w", "start": 0.55, "end": 0.6},
            {"char": "o", "start": 0.6, "end": 0.7},
            {"char": "r", "start": 0.7, "end": 0.8},
            {"char": "l", "start": 0.8, "end": 0.9},
            {"char": "d", "start": 0.9, "end": 1.0},
        ]
        result = chars_to_words(text, char_ts)
        assert len(result) == 2
        assert result[0]["word"] == "hello"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 0.5
        assert result[1]["word"] == "world"
        assert result[1]["start"] == 0.55
        assert result[1]["end"] == 1.0

    def test_handles_punctuation(self):
        text = "Hello, world!"
        char_ts = [
            {"char": "H", "start": 0.0, "end": 0.05},
            {"char": "e", "start": 0.05, "end": 0.1},
            {"char": "l", "start": 0.1, "end": 0.15},
            {"char": "l", "start": 0.15, "end": 0.2},
            {"char": "o", "start": 0.2, "end": 0.25},
            {"char": ",", "start": 0.25, "end": 0.3},
            {"char": " ", "start": 0.3, "end": 0.35},
            {"char": "w", "start": 0.35, "end": 0.4},
            {"char": "o", "start": 0.4, "end": 0.45},
            {"char": "r", "start": 0.45, "end": 0.5},
            {"char": "l", "start": 0.5, "end": 0.55},
            {"char": "d", "start": 0.55, "end": 0.6},
            {"char": "!", "start": 0.6, "end": 0.65},
        ]
        result = chars_to_words(text, char_ts)
        # "Hello," and "world!" are the split tokens
        assert len(result) == 2
        assert result[0]["word"] == "Hello,"
        assert result[1]["word"] == "world!"

    def test_empty_text_returns_empty(self):
        assert chars_to_words("", []) == []
        assert chars_to_words("", [{"char": "a", "start": 0, "end": 1}]) == []

    def test_single_word(self):
        text = "hello"
        char_ts = [
            {"char": "h", "start": 0.0, "end": 0.1},
            {"char": "e", "start": 0.1, "end": 0.2},
            {"char": "l", "start": 0.2, "end": 0.3},
            {"char": "l", "start": 0.3, "end": 0.4},
            {"char": "o", "start": 0.4, "end": 0.5},
        ]
        result = chars_to_words(text, char_ts)
        assert len(result) == 1
        assert result[0]["word"] == "hello"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 0.5

    def test_empty_char_timestamps_returns_empty(self):
        assert chars_to_words("hello world", []) == []


# ---------------------------------------------------------------------------
# DEFAULT_VOICE_SETTINGS constant test
# ---------------------------------------------------------------------------


def test_default_voice_settings_values():
    assert DEFAULT_VOICE_SETTINGS["stability"] == 0.4
    assert DEFAULT_VOICE_SETTINGS["similarity_boost"] == 0.75
    assert DEFAULT_VOICE_SETTINGS["style"] == 0.7
    assert DEFAULT_VOICE_SETTINGS["use_speaker_boost"] is True


# ---------------------------------------------------------------------------
# Retry / backoff / typed-error propagation (Phase 2, ADR 0029)
# ---------------------------------------------------------------------------
# ``elevenlabs.core.ApiError`` is the SDK's base HTTP error (4xx subclasses
# like BadRequestError extend it; 5xx raise the base class with status_code
# set). It is constructed with ``ApiError(status_code=N)`` and exposes the
# status via the ``.status_code`` attribute (keyword-only at construction).
# Tests build it with the REAL class so the helper's isinstance + getattr
# status_code reads are exercised against the genuine SDK type.


def _retry_service(svc: ElevenLabsService, side_effects: list):
    """Patch the SDK client whose ``convert_with_timestamps`` plays back
    *side_effects* in order (raise / return). Returns the mock client."""
    mock_client = MagicMock()
    mock_client.text_to_speech.convert_with_timestamps.side_effect = side_effects
    svc._client = mock_client
    return mock_client


def test_retry_on_5xx_then_success(monkeypatch):
    """Retry on transient HTTP 500/429, then succeed: 3 calls, result returned."""
    # Arrange — make backoff sleeps instant so the test does not wait.
    monkeypatch.setattr("clipper_agency.services.elevenlabs.time.sleep", lambda _: None)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    ok_resp = _make_timestamps_response(["H", "i"], [0.0, 0.1], [0.1, 0.2])
    svc = ElevenLabsService()
    mock_client = _retry_service(
        svc,
        [
            ApiError(status_code=500),
            ApiError(status_code=429),
            ok_resp,
        ],
    )

    # Act
    audio_bytes, timestamps = svc.generate_voice_with_timestamps(text="Hi", voice_id="v")

    # Assert — retried twice (3 total attempts) and returned the 3rd result.
    assert mock_client.text_to_speech.convert_with_timestamps.call_count == 3
    assert audio_bytes == b"fake_audio_bytes"
    assert len(timestamps) == 2


def test_no_retry_on_4xx_caller_error(monkeypatch):
    """Non-retryable HTTP 400: 1 call, propagates unchanged (no retries)."""
    # Arrange — sleep must NOT be called for a 4xx (no backoff).
    monkeypatch.setattr("clipper_agency.services.elevenlabs.time.sleep", lambda _: None)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    svc = ElevenLabsService()
    mock_client = _retry_service(svc, [ApiError(status_code=400)])

    # Act / Assert — propagates the SAME typed error after a single attempt.
    with pytest.raises(ApiError) as excinfo:
        svc.generate_voice_with_timestamps(text="x", voice_id="v")
    assert excinfo.value.status_code == 400
    assert mock_client.text_to_speech.convert_with_timestamps.call_count == 1


def test_exhaust_retries_then_raise(monkeypatch):
    """Always HTTP 503: 3 attempts (max), last ApiError re-raised unchanged."""
    # Arrange
    monkeypatch.setattr("clipper_agency.services.elevenlabs.time.sleep", lambda _: None)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    svc = ElevenLabsService()
    mock_client = _retry_service(
        svc,
        [ApiError(status_code=503), ApiError(status_code=503), ApiError(status_code=503)],
    )

    # Act / Assert — exhausted retries, the typed error propagates.
    with pytest.raises(ApiError) as excinfo:
        svc.generate_voice_with_timestamps(text="x", voice_id="v")
    assert excinfo.value.status_code == 503
    assert mock_client.text_to_speech.convert_with_timestamps.call_count == 3


def _raising_iter(exc):
    """Iterator that raises *exc* on first ``next()`` — simulates the SDK's LAZY
    ``convert`` byte-stream, whose HTTP request + transient ``ApiError`` fire
    during ITERATION, not at iterator construction. A mock that raises on CALL
    would falsely pass even a buggy wrapper that only retries construction."""

    def _gen():
        raise exc
        yield  # pragma: no cover — makes _gen a generator function

    return _gen()


def test_retry_on_streaming_convert_then_success(monkeypatch, tmp_path):
    """generate_voice (streaming convert): retry must wrap stream MATERIALIZATION.

    The transient ApiError fires during ``b"".join`` iteration (lazy HTTP), so it
    must be caught + retried — not escape past _with_retry. This test FAILS on a
    wrapper that only retries the bare convert() call (iterator construction).
    """
    # Arrange — instant backoff.
    monkeypatch.setattr("clipper_agency.services.elevenlabs.time.sleep", lambda _: None)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    svc = ElevenLabsService()
    mock_client = MagicMock()
    mock_client.text_to_speech.convert.side_effect = [
        _raising_iter(ApiError(status_code=500)),
        _raising_iter(ApiError(status_code=429)),
        iter([b"chunk1", b"chunk2"]),
    ]
    svc._client = mock_client

    # Act
    out = tmp_path / "voice.mp3"
    result = svc.generate_voice(text="Hi", voice_id="v", output_path=str(out))

    # Assert — retried twice (3 total attempts) + the joined bytes were written.
    assert mock_client.text_to_speech.convert.call_count == 3
    assert out.read_bytes() == b"chunk1chunk2"
    assert result == str(out)


def test_retry_on_transport_error_then_success(monkeypatch):
    """Transport/timeout failures (httpx.TransportError — timeout, connection
    reset, DNS) are retried. The SDK surfaces these DIRECTLY during the request
    send / stream materialization; they are NOT ApiError (which is only for
    received HTTP error responses), so without this predicate a network blip
    would bypass backoff entirely (Codex P2 review)."""
    # Arrange — instant backoff.
    monkeypatch.setattr("clipper_agency.services.elevenlabs.time.sleep", lambda _: None)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    svc = ElevenLabsService()
    mock_client = MagicMock()
    mock_client.text_to_speech.convert_with_timestamps.side_effect = [
        httpx.ConnectTimeout("connect timeout"),
        httpx.ReadError("connection reset"),
        _make_timestamps_response(["H", "i"], [0.0, 0.1], [0.1, 0.2]),
    ]
    svc._client = mock_client

    # Act
    audio_bytes, timestamps = svc.generate_voice_with_timestamps(text="Hi", voice_id="v")

    # Assert — both transport failures retried, 3rd attempt succeeded.
    assert mock_client.text_to_speech.convert_with_timestamps.call_count == 3
    assert audio_bytes == b"fake_audio_bytes"
    assert len(timestamps) == 2
