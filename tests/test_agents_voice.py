"""Tests for VoiceProducerAgent — single audio generation."""

from unittest import mock

import pytest

from clipper_agency.agents.voice_producer import VoiceProducerAgent


class TestVoiceProducerName:
    """Agent name property."""

    def test_voice_producer_agent_name(self):
        agent = VoiceProducerAgent()
        assert agent.agent_name == "voice_producer"


class TestVoiceProducerSingleAudio:
    """Voice generation via single continuous voiceover text."""

    def test_execute_with_voiceover_text(self, mocker, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        mock_ts = mocker.patch(
            "clipper_agency.services.elevenlabs.ElevenLabsService"
            ".generate_voice_with_timestamps",
            return_value=(b"audio_bytes", [
                {"char": "H", "start": 0.0, "end": 0.05},
                {"char": "i", "start": 0.05, "end": 0.1},
            ]),
        )
        mocker.patch(
            "clipper_agency.agents.voice_producer.VoiceProducerAgent"
            "._probe_audio_duration",
            return_value=0.5,
        )
        agent = VoiceProducerAgent()
        result = agent.execute(
            job_id=1,
            voiceover_text="Hi",
            voice_id="JBFqnCBsd6RMkjVDRZzb",
        )
        assert result["status"] == "success"
        assert result["voiceover_path"]
        assert result["voiceover_duration_sec"] == 0.5
        assert result["provider"] == "elevenlabs"
        mock_ts.assert_called_once()

    def test_execute_passes_correct_params(self, mocker, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        mock_ts = mocker.patch(
            "clipper_agency.services.elevenlabs.ElevenLabsService"
            ".generate_voice_with_timestamps",
            return_value=(b"audio", []),
        )
        mocker.patch(
            "clipper_agency.agents.voice_producer.VoiceProducerAgent"
            "._probe_audio_duration",
            return_value=1.0,
        )
        agent = VoiceProducerAgent()
        agent.execute(
            job_id=1,
            voiceover_text="Hello world",
            voice_id="voice123",
        )
        mock_ts.assert_called_once_with("Hello world", "voice123")

    def test_execute_defaults_voice_id(self, mocker, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        mock_ts = mocker.patch(
            "clipper_agency.services.elevenlabs.ElevenLabsService"
            ".generate_voice_with_timestamps",
            return_value=(b"audio", []),
        )
        mocker.patch(
            "clipper_agency.agents.voice_producer.VoiceProducerAgent"
            "._probe_audio_duration",
            return_value=1.0,
        )
        agent = VoiceProducerAgent()
        agent.execute(job_id=1, voiceover_text="Test")
        call_args = mock_ts.call_args
        assert call_args[0][1] == "JBFqnCBsd6RMkjVDRZzb"

    def test_execute_handles_empty_text(self, mocker, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        mock_ts = mocker.patch(
            "clipper_agency.services.elevenlabs.ElevenLabsService"
            ".generate_voice_with_timestamps",
        )
        agent = VoiceProducerAgent()
        result = agent.execute(job_id=1, voiceover_text="")
        assert result["status"] == "completed"
        assert result["timestamps"] == []
        mock_ts.assert_not_called()

    def test_execute_handles_elevenlabs_failure(self, mocker, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")

        def failing_ts(text, voice_id):
            raise Exception("ElevenLabs API error")

        mocker.patch(
            "clipper_agency.services.elevenlabs.ElevenLabsService"
            ".generate_voice_with_timestamps",
            side_effect=failing_ts,
        )
        # Ensure no fallback providers
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("FISHAUDIO_API_KEY", raising=False)

        agent = VoiceProducerAgent()
        result = agent.execute(
            job_id=1,
            voiceover_text="Test voiceover",
        )
        assert result["status"] == "failed"
        assert "All TTS providers failed" in result.get("error", "")

    def test_output_contract_matches_voiceover_output_model(self, mocker, monkeypatch):
        """Output should include all VoiceoverOutput schema fields."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        mocker.patch(
            "clipper_agency.services.elevenlabs.ElevenLabsService"
            ".generate_voice_with_timestamps",
            return_value=(b"audio", [
                {"char": "H", "start": 0.0, "end": 0.05},
                {"char": "i", "start": 0.05, "end": 0.1},
            ]),
        )
        mocker.patch(
            "clipper_agency.agents.voice_producer.VoiceProducerAgent"
            "._probe_audio_duration",
            return_value=0.5,
        )
        agent = VoiceProducerAgent()
        result = agent.execute(job_id=1, voiceover_text="Hi")

        # VoiceoverOutput required fields
        assert "status" in result
        assert "voiceover_path" in result
        assert "voiceover_duration_sec" in result
        assert "timestamps" in result
        assert "provider" in result

        # Backward compat fields
        assert "audio_files" in result
        assert "attempts" in result

    def test_timestamps_contain_word_start_end(self, mocker, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
        char_ts = [
            {"char": "H", "start": 0.0, "end": 0.05},
            {"char": "e", "start": 0.05, "end": 0.1},
            {"char": "l", "start": 0.1, "end": 0.15},
            {"char": "l", "start": 0.15, "end": 0.2},
            {"char": "o", "start": 0.2, "end": 0.25},
        ]
        mocker.patch(
            "clipper_agency.services.elevenlabs.ElevenLabsService"
            ".generate_voice_with_timestamps",
            return_value=(b"audio", char_ts),
        )
        mocker.patch(
            "clipper_agency.agents.voice_producer.VoiceProducerAgent"
            "._probe_audio_duration",
            return_value=0.5,
        )
        agent = VoiceProducerAgent()
        result = agent.execute(job_id=1, voiceover_text="Hello")

        ts = result["timestamps"]
        assert len(ts) == 1
        assert ts[0]["word"] == "Hello"
        assert ts[0]["start"] == 0.0
        assert ts[0]["end"] == 0.25
