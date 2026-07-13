"""Tests for Fish Audio text-to-speech service."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from clipper_agency.services.fish_audio import FishAudioService


def test_init_reads_api_key_from_env():
    with patch.dict("os.environ", {"FISHAUDIO_API_KEY": "test-key"}, clear=True):
        svc = FishAudioService()
    assert svc.api_key == "test-key"


def test_init_no_api_key():
    with patch.dict("os.environ", {}, clear=True):
        svc = FishAudioService()
    assert svc.api_key is None


def test_generate_voice_no_key_raises(tmp_path):
    with patch.dict("os.environ", {}, clear=True):
        svc = FishAudioService()
    out = str(tmp_path / "out.mp3")
    with pytest.raises(ValueError, match="FISHAUDIO_API_KEY not set"):
        svc.generate_voice("hello", "voice-1", out)


@patch("httpx.Client")
def test_generate_voice_success(mock_httpx, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake audio data"
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_httpx.return_value.__exit__ = MagicMock(return_value=False)

    with patch.dict("os.environ", {"FISHAUDIO_API_KEY": "test-key"}, clear=True):
        output = tmp_path / "voice.mp3"
        result = FishAudioService().generate_voice(
            text="Hello world",
            voice_id="abc-123",
            output_path=str(output),
        )

    assert result == str(output)
    assert output.read_bytes() == b"fake audio data"

    post_call = mock_client.post.call_args
    assert post_call.args[0] == "/tts"
    assert post_call.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert post_call.kwargs["json"]["text"] == "Hello world"
    assert post_call.kwargs["json"]["reference_id"] == "abc-123"
    assert post_call.kwargs["json"]["format"] == "mp3"


@patch("httpx.Client")
def test_generate_voice_http_error(mock_httpx, tmp_path):
    error_response = MagicMock()
    error_response.status_code = 402

    mock_client = MagicMock()
    mock_client.post.return_value = error_response
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Payment Required",
        request=MagicMock(),
        response=error_response,
    )
    mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_httpx.return_value.__exit__ = MagicMock(return_value=False)

    with patch.dict("os.environ", {"FISHAUDIO_API_KEY": "test-key"}, clear=True):
        svc = FishAudioService()
        out = str(tmp_path / "voice.mp3")
        with pytest.raises(httpx.HTTPStatusError, match="Payment Required"):
            svc.generate_voice(
                text="Hello",
                voice_id="v1",
                output_path=out,
            )


@patch("httpx.Client")
def test_generate_voice_creates_parent_dirs(mock_httpx, tmp_path):
    mock_response = MagicMock()
    mock_response.content = b"data"
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_httpx.return_value.__exit__ = MagicMock(return_value=False)

    nested = tmp_path / "deep" / "nested" / "dir" / "voice.mp3"

    with patch.dict("os.environ", {"FISHAUDIO_API_KEY": "k"}, clear=True):
        result = FishAudioService().generate_voice(
            text="test",
            voice_id="v",
            output_path=str(nested),
        )

    assert Path(result).parent.is_dir()
    assert nested.read_bytes() == b"data"
