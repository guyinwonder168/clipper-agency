"""Tests for ElevenLabs voice generation service."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.services.elevenlabs import (
    ElevenLabsService,
    chars_to_words,
    DEFAULT_VOICE_SETTINGS,
)


# ---------------------------------------------------------------------------
# Existing tests (backward compat)
# ---------------------------------------------------------------------------


def test_service_init():
    with patch.dict("os.environ", {}, clear=True):
        svc = ElevenLabsService()
        assert svc.api_key is None


@patch("httpx.Client")
def test_generate_voice(mock_httpx, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake_audio_data"
    mock_httpx.return_value.__enter__.return_value.post.return_value = mock_response

    with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
        svc = ElevenLabsService()
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


def _make_timestamps_response(chars: list[str], starts: list[float], ends: list[float]) -> dict:
    """Build a fake /with-timestamps JSON response."""
    audio_b64 = base64.b64encode(b"fake_audio_bytes").decode()
    return {
        "audio": audio_b64,
        "alignment": {
            "chars": chars,
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        },
    }


@patch("httpx.Client")
def test_generate_voice_with_timestamps(mock_httpx):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _make_timestamps_response(
        chars=["H", "e", "l", "l", "o", " ", "w", "o", "r", "l", "d"],
        starts=[0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5],
        ends=[0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55],
    )
    mock_httpx.return_value.__enter__.return_value.post.return_value = mock_response

    with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
        svc = ElevenLabsService()
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


@patch("httpx.Client")
def test_generate_voice_with_timestamps_uses_default_settings(mock_httpx):
    """Voice settings should default to the audio-first architecture defaults."""
    mock_response = MagicMock()
    mock_response.json.return_value = _make_timestamps_response([], [], [])
    mock_httpx.return_value.__enter__.return_value.post.return_value = mock_response

    with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
        svc = ElevenLabsService()
        svc.generate_voice_with_timestamps(text="test", voice_id="v")

    call_kwargs = mock_httpx.return_value.__enter__.return_value.post.call_args
    body = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
    assert body["voice_settings"]["stability"] == 0.4
    assert body["voice_settings"]["similarity_boost"] == 0.75
    assert body["voice_settings"]["style"] == 0.7
    assert body["voice_settings"]["use_speaker_boost"] is True


@patch("httpx.Client")
def test_generate_voice_with_timestamps_custom_settings(mock_httpx):
    """Custom voice settings should override defaults."""
    mock_response = MagicMock()
    mock_response.json.return_value = _make_timestamps_response([], [], [])
    mock_httpx.return_value.__enter__.return_value.post.return_value = mock_response

    custom = {"stability": 0.8, "similarity_boost": 0.9}
    with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key"}):
        svc = ElevenLabsService()
        svc.generate_voice_with_timestamps(
            text="test", voice_id="v", voice_settings=custom,
        )

    call_kwargs = mock_httpx.return_value.__enter__.return_value.post.call_args
    body = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
    assert body["voice_settings"]["stability"] == 0.8
    assert body["voice_settings"]["similarity_boost"] == 0.9


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
