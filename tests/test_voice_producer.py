"""Tests for VoiceProducerAgent — provider fallback, timestamps, and artifacts."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from clipper_agency.agents.voice_producer import VoiceProducerAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VOICEOVER_TEXT = "Hello this is a test voiceover for the single audio approach."


def _mock_elevenlabs_service(with_timestamps=True, audio=b"fake_audio"):
    """Return a mock ElevenLabs service with timestamp support."""
    svc = mock.MagicMock()
    if with_timestamps:
        char_ts = [
            {"char": "H", "start": 0.0, "end": 0.05},
            {"char": "e", "start": 0.05, "end": 0.1},
            {"char": "l", "start": 0.1, "end": 0.15},
            {"char": "l", "start": 0.15, "end": 0.2},
            {"char": "o", "start": 0.2, "end": 0.25},
        ]
        svc.generate_voice_with_timestamps.return_value = (audio, char_ts)
    svc.generate_voice.return_value = "/fake/path.mp3"
    return svc


def _mock_service(succeed: bool):
    """Return a mock TTS service instance (for Gemini/Fish fallback)."""
    svc = mock.MagicMock()
    if succeed:
        svc.generate_voice.return_value = "/fake/path.mp3"
    else:
        svc.generate_voice.side_effect = ValueError("service unavailable")
    return svc


# ---------------------------------------------------------------------------
# Provider fallback tests
# ---------------------------------------------------------------------------


class TestVoiceProducerFallback:
    """TTS provider priority and fallback behaviour."""

    def test_elevenlabs_succeeds_with_timestamps(self, tmp_path, monkeypatch):
        """When ElevenLabs key is present and service succeeds,
        single audio with timestamps should be returned."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")

        agent = VoiceProducerAgent()
        el_svc = _mock_elevenlabs_service()

        with mock.patch.object(agent, "_create_service", return_value=el_svc), \
             mock.patch.object(agent, "_probe_audio_duration", return_value=5.0):
            result = agent.execute(
                job_id=1,
                voiceover_text=VOICEOVER_TEXT,
                assets_cache=str(tmp_path),
            )

        assert result["status"] == "success"
        assert result["provider"] == "elevenlabs"
        assert result["voiceover_duration_sec"] == 5.0
        assert len(result["timestamps"]) > 0

    def test_elevenlabs_fails_fallsback_to_gemini(self, tmp_path, monkeypatch):
        """When ElevenLabs fails, Gemini should be tried next."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        monkeypatch.setenv("GEMINI_API_KEY", "gem-key")

        agent = VoiceProducerAgent()

        el_svc = _mock_elevenlabs_service()
        el_svc.generate_voice_with_timestamps.side_effect = Exception("EL failed")
        gemini_svc = _mock_service(True)

        services = {"elevenlabs": el_svc, "gemini_tts": gemini_svc}

        def _create(provider):
            return services[provider]

        with mock.patch.object(agent, "_create_service", side_effect=_create), \
             mock.patch.object(agent, "_probe_audio_duration", return_value=3.0):
            result = agent.execute(
                job_id=2,
                voiceover_text=VOICEOVER_TEXT,
                assets_cache=str(tmp_path),
            )

        assert result["status"] == "success"
        assert result["provider"] == "gemini_tts"

    def test_all_providers_fail_returns_clear_failure(self, tmp_path, monkeypatch):
        """When all providers fail, output should show a clear failure status."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
        monkeypatch.setenv("FISHAUDIO_API_KEY", "fish-key")

        agent = VoiceProducerAgent()

        el_svc = _mock_elevenlabs_service()
        el_svc.generate_voice_with_timestamps.side_effect = Exception("EL failed")

        services = {
            "elevenlabs": el_svc,
            "gemini_tts": _mock_service(False),
            "fish_audio": _mock_service(False),
        }

        def _create(provider):
            return services[provider]

        with mock.patch.object(agent, "_create_service", side_effect=_create):
            result = agent.execute(
                job_id=3,
                voiceover_text=VOICEOVER_TEXT,
                assets_cache=str(tmp_path),
            )

        assert result["status"] == "failed"
        assert "All TTS providers failed" in result.get("error", "")

    def test_no_keys_configured_returns_failure(self, tmp_path, monkeypatch):
        """When no TTS keys are configured, status should be failed."""
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("FISHAUDIO_API_KEY", raising=False)

        agent = VoiceProducerAgent()
        result = agent.execute(
            job_id=4,
            voiceover_text=VOICEOVER_TEXT,
            assets_cache=str(tmp_path),
        )

        assert result["status"] == "failed"
        assert "All TTS providers failed" in result.get("error", "")

    def test_fish_audio_api_key_enables_fish_provider(self, tmp_path, monkeypatch):
        """FISHAUDIO_API_KEY should enable fish_audio provider."""
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("FISHAUDIO_API_KEY", raising=False)
        monkeypatch.setenv("FISHAUDIO_API_KEY", "fish-key")

        agent = VoiceProducerAgent()

        def _create(provider):
            assert provider == "fish_audio"
            return _mock_service(True)

        with mock.patch.object(agent, "_create_service", side_effect=_create), \
             mock.patch.object(agent, "_probe_audio_duration", return_value=3.0):
            result = agent.execute(
                job_id=5,
                voiceover_text=VOICEOVER_TEXT,
                assets_cache=str(tmp_path),
            )

        assert result["status"] == "success"
        assert result["provider"] == "fish_audio"


# ---------------------------------------------------------------------------
# Timestamp extraction tests
# ---------------------------------------------------------------------------


class TestTimestampExtraction:
    """Word-level timestamp extraction from ElevenLabs responses."""

    def test_extract_word_timestamps_from_char_timestamps(self):
        agent = VoiceProducerAgent()
        char_ts = [
            {"char": "H", "start": 0.0, "end": 0.05},
            {"char": "e", "start": 0.05, "end": 0.1},
            {"char": "l", "start": 0.1, "end": 0.15},
            {"char": "l", "start": 0.15, "end": 0.2},
            {"char": "o", "start": 0.2, "end": 0.25},
        ]
        result = agent._extract_word_timestamps(char_ts, "Hello")
        assert len(result) == 1
        assert result[0]["word"] == "Hello"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 0.25

    def test_extract_word_timestamps_empty_input(self):
        agent = VoiceProducerAgent()
        result = agent._extract_word_timestamps([], "")
        assert result == []


class TestApproximateTimestamps:
    """Approximate timestamp fallback for non-ElevenLabs providers."""

    def test_approximate_timestamps_distributes_evenly(self):
        agent = VoiceProducerAgent()
        with mock.patch.object(agent, "_probe_audio_duration", return_value=6.0):
            result = agent._approximate_timestamps("/fake/audio.mp3", "one two three")
        assert len(result) == 3
        # Each word gets 2.0 seconds (6.0 / 3)
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.0
        assert result[1]["start"] == 2.0
        assert result[1]["end"] == 4.0
        assert result[2]["start"] == 4.0
        assert result[2]["end"] == 6.0

    def test_approximate_timestamps_empty_text(self):
        agent = VoiceProducerAgent()
        with mock.patch.object(agent, "_probe_audio_duration", return_value=5.0):
            result = agent._approximate_timestamps("/fake/audio.mp3", "")
        assert result == []

    def test_approximate_timestamps_zero_duration(self):
        agent = VoiceProducerAgent()
        with mock.patch.object(agent, "_probe_audio_duration", return_value=0.0):
            result = agent._approximate_timestamps("/fake/audio.mp3", "hello")
        assert result == []

    def test_approximate_timestamps_single_word(self):
        agent = VoiceProducerAgent()
        with mock.patch.object(agent, "_probe_audio_duration", return_value=3.0):
            result = agent._approximate_timestamps("/fake/audio.mp3", "hello")
        assert len(result) == 1
        assert result[0]["word"] == "hello"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 3.0


# ---------------------------------------------------------------------------
# Artifact persistence tests
# ---------------------------------------------------------------------------


class TestVoiceProducerArtifacts:
    """Voice Producer writes input/output to agent dir."""

    def test_persists_input_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        agent = VoiceProducerAgent()
        el_svc = _mock_elevenlabs_service()

        with mock.patch.object(agent, "_create_service", return_value=el_svc), \
             mock.patch.object(agent, "_probe_audio_duration", return_value=3.0):
            agent.execute(
                job_id=7, voiceover_text=VOICEOVER_TEXT,
                assets_cache=str(tmp_path),
            )

        input_file = tmp_path / "job_7" / "agents" / "voice_producer" / "input.json"
        assert input_file.exists()
        data = json.loads(input_file.read_text())
        assert data["job_id"] == 7
        assert "text_length" in data

    def test_persists_output_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        agent = VoiceProducerAgent()
        el_svc = _mock_elevenlabs_service()

        with mock.patch.object(agent, "_create_service", return_value=el_svc), \
             mock.patch.object(agent, "_probe_audio_duration", return_value=3.0):
            agent.execute(
                job_id=8, voiceover_text=VOICEOVER_TEXT,
                assets_cache=str(tmp_path),
            )

        output_file = tmp_path / "job_8" / "agents" / "voice_producer" / "output.json"
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["status"] == "success"
        assert "voiceover_path" in data
        assert "timestamps" in data

    def test_voiceover_file_written(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        agent = VoiceProducerAgent()
        el_svc = _mock_elevenlabs_service(audio=b"real_audio_data")

        with mock.patch.object(agent, "_create_service", return_value=el_svc), \
             mock.patch.object(agent, "_probe_audio_duration", return_value=3.0):
            agent.execute(
                job_id=10, voiceover_text=VOICEOVER_TEXT,
                assets_cache=str(tmp_path),
            )

        voiceover = tmp_path / "job_10" / "agents" / "voice_producer" / "voiceover.mp3"
        assert voiceover.exists()
        assert voiceover.read_bytes() == b"real_audio_data"

    def test_no_backward_compat_stubs_created(self, tmp_path, monkeypatch):
        """After Batch 2 cleanup, scene_1.mp3 should NOT be created."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        agent = VoiceProducerAgent()
        el_svc = _mock_elevenlabs_service(audio=b"audio_data")

        with mock.patch.object(agent, "_create_service", return_value=el_svc), \
             mock.patch.object(agent, "_probe_audio_duration", return_value=3.0):
            agent.execute(
                job_id=11, voiceover_text=VOICEOVER_TEXT,
                assets_cache=str(tmp_path),
            )

        stub = tmp_path / "job_11" / "agents" / "voice_producer" / "voices" / "scene_1.mp3"
        assert not stub.exists()


# ---------------------------------------------------------------------------
# Backward compat tests (script parameter still works)
# ---------------------------------------------------------------------------


class TestVoiceProducerScriptCompat:
    """Legacy script parameter should still work via text joining."""

    SCENES = [
        {"scene": 1, "text": "Hello", "duration": 5},
        {"scene": 2, "text": "World", "duration": 3},
    ]

    def test_script_joins_to_single_text(self, tmp_path, monkeypatch):
        """When script is passed without voiceover_text, texts should be joined."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")

        agent = VoiceProducerAgent()
        el_svc = _mock_elevenlabs_service()

        with mock.patch.object(agent, "_create_service", return_value=el_svc), \
             mock.patch.object(agent, "_probe_audio_duration", return_value=3.0):
            result = agent.execute(
                job_id=20, script=self.SCENES,
                assets_cache=str(tmp_path),
            )

        assert result["status"] == "success"
        # Verify the joined text was passed
        call_args = el_svc.generate_voice_with_timestamps.call_args
        assert "Hello" in call_args[0][0]
        assert "World" in call_args[0][0]

    def test_empty_script_returns_completed(self, monkeypatch):
        """Empty script should return completed status."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        agent = VoiceProducerAgent()
        result = agent.execute(job_id=21, script=[])
        assert result["status"] == "completed"
        assert result["timestamps"] == []


# ---------------------------------------------------------------------------
# Chunking safety-net tests
# ---------------------------------------------------------------------------


def test_chunk_text_splits_at_sentence_boundaries():
    """Text is split at sentence boundaries respecting word budget."""
    from clipper_agency.agents.voice_producer import _chunk_text

    text = "First sentence here. Second sentence goes on. Third one is short."
    chunks = _chunk_text(text, chunk_size_words=4)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.split()) <= 8  # Allow slack for sentence integrity


def test_chunk_text_short_text_returns_single():
    """Text shorter than chunk_size returns a single chunk."""
    from clipper_agency.agents.voice_producer import _chunk_text

    text = "Short text here."
    chunks = _chunk_text(text, chunk_size_words=250)

    assert len(chunks) == 1
    assert chunks[0] == text


def test_stitch_timestamps_adds_cumulative_offset():
    """Timestamps from later chunks get cumulative audio offset."""
    agent = VoiceProducerAgent()
    chunk_ts = [
        [{"word": "hello", "start": 0.0, "end": 0.5}],
        [{"word": "world", "start": 0.0, "end": 0.5}],
    ]
    chunk_durations = [10.0, 10.0]

    result = agent._stitch_timestamps(chunk_ts, chunk_durations)

    assert len(result) == 2
    assert result[0]["start"] == 0.0
    assert result[1]["start"] == pytest.approx(10.0)
    assert result[1]["end"] == pytest.approx(10.5)
