import json
import os
from unittest.mock import patch

from clipper_agency.agents.voice_producer import VoiceProducerAgent


class TestVoiceProducerDurationMetadata:
    def test_build_audio_metadata(self, tmp_path):
        """_build_audio_metadata creates per-scene duration records."""
        agent = VoiceProducerAgent()
        output_dir = str(tmp_path)
        voices_dir = os.path.join(output_dir, "voices")
        os.makedirs(voices_dir)
        for i in range(1, 4):
            path = os.path.join(voices_dir, f"scene_{i}.mp3")
            with open(path, "wb") as f:
                f.write(b"\x00" * 1024)

        meta = agent._build_audio_metadata(output_dir, scene_count=3)
        assert len(meta) == 3
        assert meta[0]["scene"] == 1
        assert "audio_duration_sec" in meta[0]
        assert "audio_path" in meta[0]
        assert "provider" in meta[0]

    def test_missing_audio_returns_empty(self):
        agent = VoiceProducerAgent()
        meta = agent._build_audio_metadata("/nonexistent", scene_count=3)
        assert meta == []

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
