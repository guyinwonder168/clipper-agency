"""Tests for VoiceProducerAgent — audio duration probing and metadata."""

import json
from unittest.mock import patch

from clipper_agency.agents.voice_producer import VoiceProducerAgent


class TestVoiceProducerDurationMetadata:
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_parse_ffprobe_duration(self, mock_run, _mock_exists):
        """_probe_audio_duration returns float seconds or 0.0 on failure."""
        agent = VoiceProducerAgent()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps({
            "format": {"duration": "12.345"}
        })
        dur = agent._probe_audio_duration("/fake/audio.mp3")
        assert dur == 12.345

    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_probe_duration_failure_returns_zero(self, mock_run, _mock_exists):
        agent = VoiceProducerAgent()
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        dur = agent._probe_audio_duration("/fake/audio.mp3")
        assert dur == 0.0

    def test_probe_duration_missing_file(self):
        agent = VoiceProducerAgent()
        dur = agent._probe_audio_duration("/nonexistent/audio.mp3")
        assert dur == 0.0

    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_probe_duration_invalid_json(self, mock_run, _mock_exists):
        agent = VoiceProducerAgent()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "not json"
        dur = agent._probe_audio_duration("/fake/audio.mp3")
        assert dur == 0.0

    @patch("clipper_agency.agents.voice_producer.ensure_agent_dir")
    def test_voiceover_output_path_with_cache(self, mock_ensure):
        mock_ensure.return_value = "/cache/job_42/voice_producer"
        path = VoiceProducerAgent._voiceover_output_path(42, "/cache")
        assert "job_42" in path
        assert "voice_producer" in path
        assert path.endswith("voiceover.mp3")

    def test_voiceover_output_path_without_cache(self):
        path = VoiceProducerAgent._voiceover_output_path(42, "")
        assert path == "outputs/job_42/voiceover.mp3"

    def test_empty_output_structure(self):
        result = VoiceProducerAgent._empty_output(1, "")
        assert result["status"] == "completed"
        assert result["timestamps"] == []
        assert result["voiceover_path"] == ""

    def test_failed_output_structure(self):
        result = VoiceProducerAgent._build_failed_output()
        assert result["status"] == "failed"
        assert result["timestamps"] == []
        assert "All TTS providers failed" in result["error"]
        assert result["audio_files"] == []
