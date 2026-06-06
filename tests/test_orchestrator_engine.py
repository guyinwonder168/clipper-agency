"""Tests for the Orchestrator engine — pipeline coordination."""

import json
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from clipper_agency.config.loader import load_settings
from clipper_agency.config.schema import NicheConfig
from clipper_agency.db.connection import close_connection, get_connection
from clipper_agency.db.schema import initialize_schema
from clipper_agency.orchestrator.engine import Orchestrator


@pytest.fixture(autouse=True)
def mock_load_niche_autouse(mocker):
    """Mock load_niche to return a valid test NicheConfig for all tests."""
    test_config = NicheConfig(
        name="test_niche",
        description="Test niche for pipeline tests",
        language="id",
        tone="informal_investigative",
        content_angle="Gosip dan Analisis Ringan",
        platform="tiktok",
        duration_min=30,
        duration_max=90,
        safety_rules=["no_defamation", "mark_rumors_as_unconfirmed"],
        search_terms=["test search"],
        max_hashtags=5,
    )
    mocker.patch(
        "clipper_agency.orchestrator.engine.load_niche",
        return_value=test_config,
    )


@pytest.fixture
def db_initialized(temp_db_path):
    """Initialize schema on a temp database."""
    conn = get_connection(temp_db_path)
    initialize_schema(conn)
    yield temp_db_path
    close_connection(temp_db_path)


@pytest.fixture
def mock_safety_pass():
    """Mock SafetyAgent.execute returning pass."""
    return {"status": "pass", "reason": "Safe topic"}


@pytest.fixture
def mock_safety_hard_fail():
    """Mock SafetyAgent.execute returning hard_fail."""
    return {"status": "hard_fail", "reason": "Blocked content"}


@pytest.fixture
def mock_research_output():
    """Mock SegmentProducerAgent.execute output."""
    return {
        "status": "completed",
        "research_brief": "Research findings for topic",
        "sources": [{"url": "https://example.com", "title": "Source 1"}],
    }


@pytest.fixture
def mock_script_output():
    """Mock ScriptwriterAgent.execute output."""
    return {
        "status": "completed",
        "script": [
            {"scene": 1, "text": "Halo semua!", "duration": 3},
            {"scene": 2, "text": "Ada berita terbaru!", "duration": 4},
        ],
        "caption": "Breaking news tentang Ariana Grande!",
        "hashtags": ["#ArianaGrande", "#KonserJakarta"],
        "estimated_duration": 7,
    }


@pytest.fixture
def mock_voice_output():
    """Mock VoiceProducerAgent.execute output."""
    return {
        "status": "completed",
        "audio_files": ["outputs/job_1/scene_1.mp3", "outputs/job_1/scene_2.mp3"],
    }


@pytest.fixture
def mock_visual_output():
    """Mock VisualDirectorAgent.execute output."""
    return {
        "status": "completed",
        "assets": [
            {"scene": 1, "source": "pexels", "path": "assets/cache/scene_1.mp4"},
            {"scene": 2, "source": "pexels", "path": "assets/cache/scene_2.mp4"},
        ],
    }


@pytest.fixture
def mock_composer_output():
    """Mock ComposerAgent.execute output."""
    return {
        "status": "completed",
        "video_path": "outputs/job_1/final.mp4",
        "thumbnail_path": "outputs/job_1/thumbnail.png",
    }


@pytest.fixture
def mock_review_output():
    """Mock ReviewerAgent.execute output."""
    return {
        "status": "pass",
        "score": 85,
        "feedback": "Good content",
        "issues": [],
    }


@pytest.fixture
def mock_packager_output():
    """Mock OutputPackager.package output."""
    return {
        "status": "completed",
        "output_dir": "outputs/job_1",
        "video_path": "outputs/job_1/final.mp4",
        "caption_path": "outputs/job_1/caption.txt",
        "thumbnail_path": "outputs/job_1/thumbnail.png",
        "metadata_path": "outputs/job_1/metadata.json",
    }


@pytest.fixture
def mock_probe_video_ok(mocker):
    """Mock probe_video to return valid 1080x1920 h264 video info."""
    class MockVideoInfo:
        width = 1080
        height = 1920
        codec = "h264"
        pix_fmt = "yuv420p"
        duration = 30.0
        has_audio = True
        file_size = 1000000

    mocker.patch(
        "clipper_agency.orchestrator.gates.probe_video",
        return_value=MockVideoInfo(),
    )


@pytest.mark.usefixtures("mock_probe_video_ok")
class TestOrchestratorRunPipeline:
    """Tests for Orchestrator.run_pipeline()."""

    def test_creates_job_in_db(self, db_initialized, tmp_path):
        """Orchestrator should create a job record in the database."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline(topic="Test topic", niche="test_niche")

        assert result["status"] == "completed"
        assert result["job_id"] > 0
        conn = get_connection(db_initialized)
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (result["job_id"],)).fetchone()
        assert job is not None
        assert job["topic"] == "Test topic"

    def test_stops_on_safety_hard_fail(self, db_initialized):
        """Orchestrator should stop pipeline if safety returns hard_fail."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher:
            mock_safety.return_value = {"status": "hard_fail", "reason": "Blocked"}
            mock_researcher.return_value = {}

            result = orch.run_pipeline(topic="Bad topic", niche="test")

        assert result["status"] == "failed"
        assert result["failed_at"] == "safety"
        assert "Blocked" in str(result.get("reason", ""))
        # Researcher should NOT have been called
        mock_researcher.assert_not_called()

    def test_initializes_agent_states(self, db_initialized):
        """Orchestrator should create agent_states for all 7 agents."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": []}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": []}
            mock_visual.return_value = {"status": "completed", "assets": []}
            mock_composer.return_value = {"status": "completed", "video_path": "", "thumbnail_path": ""}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        conn = get_connection(db_initialized)
        expected_agents = ["safety", "segment_producer", "scriptwriter",
                          "voice_producer", "visual_director", "composer", "reviewer"]
        for agent_name in expected_agents:
            row = conn.execute(
                "SELECT * FROM agent_states WHERE job_id=? AND agent_name=?",
                (result["job_id"], agent_name),
            ).fetchone()
            assert row is not None, f"agent_state missing for {agent_name}"

    def test_full_pipeline_calls_all_agents_in_order(self, db_initialized, tmp_path):
        """Orchestrator should invoke agents in correct sequence."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            orch.run_pipeline(topic="Test", niche="test_niche")

        # Verify all agents were called
        mock_safety.assert_called_once()
        mock_researcher.assert_called_once()
        mock_scriptwriter.assert_called_once()
        mock_voice.assert_called_once()
        mock_visual.assert_called_once()
        mock_composer.assert_called_once()
        mock_reviewer.assert_called_once()
        mock_pkg.assert_called_once()

    def test_passes_research_to_scriptwriter(self, db_initialized):
        """Orchestrator should pass research output to scriptwriter."""
        orch = Orchestrator(db_path=db_initialized)
        research_brief = "Detailed research about Ariana Grande"

        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": research_brief, "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": []}
            mock_visual.return_value = {"status": "completed", "assets": []}
            mock_composer.return_value = {"status": "completed", "video_path": "", "thumbnail_path": ""}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            orch.run_pipeline(topic="Test", niche="test_niche")

        # Verify researcher was passed the topic
        # Verify scriptwriter received research_brief
        scriptwriter_call = mock_scriptwriter.call_args[1]
        assert scriptwriter_call["research_brief"] == research_brief

    def test_passes_assets_cache_to_safety(self, db_initialized, tmp_path):
        """Orchestrator should pass configured asset workspace to Safety."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": []}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": []}
            mock_visual.return_value = {"status": "completed", "assets": []}
            mock_composer.return_value = {"status": "completed", "video_path": "", "thumbnail_path": ""}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            orch.run_pipeline(
                topic="Test",
                niche="test_niche",
                assets_cache=str(tmp_path),
            )

        safety_call = mock_safety.call_args[1]
        assert safety_call["assets_cache"] == str(tmp_path)

    def test_passes_assets_cache_to_scriptwriter(self, db_initialized, tmp_path):
        """Orchestrator should pass configured asset workspace to Scriptwriter."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": []}
            mock_visual.return_value = {"status": "completed", "assets": []}
            mock_composer.return_value = {"status": "completed", "video_path": "", "thumbnail_path": ""}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            orch.run_pipeline(
                topic="Test",
                niche="test_niche",
                assets_cache=str(tmp_path),
            )

        scriptwriter_call = mock_scriptwriter.call_args[1]
        assert scriptwriter_call["assets_cache"] == str(tmp_path)

    def test_passes_script_and_research_to_voice_and_visual(self, db_initialized, tmp_path):
        """Orchestrator should pass script to voice producer and visual director."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        script_scenes = [{"scene": 1, "text": "Halo!", "duration": 3}]
        research_sources = [{"url": "https://example.com"}, {"url": "https://example2.com"}]

        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "brief", "sources": research_sources}
            mock_scriptwriter.return_value = {"status": "completed", "script": script_scenes, "caption": "Caption", "hashtags": [], "estimated_duration": 3}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": "v.mp4"}]}
            mock_composer.return_value = {"status": "completed", "video_path": "final.mp4", "thumbnail_path": "thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            orch.run_pipeline(topic="Test", niche="test_niche")

        # Voice producer should receive script
        voice_call = mock_voice.call_args[1]
        assert voice_call["script"] == script_scenes

        # Visual director should receive script and source_urls from research
        visual_call = mock_visual.call_args[1]
        assert visual_call["script"] == script_scenes
        # source_urls should come from research sources

    def test_passes_assets_and_audio_to_composer(self, db_initialized, tmp_path):
        """Orchestrator should pass visual assets and audio to composer."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a1.mp3"; audio.write_bytes(b"x")
        audio2 = tmp_path / "a2.mp3"; audio2.write_bytes(b"x")
        asset = tmp_path / "v1.mp4"; asset.write_bytes(b"x")
        audio_files = [str(audio), str(audio2)]
        assets = [{"scene": 1, "source": "pexels", "path": str(asset)}]

        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "brief", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": audio_files}
            mock_visual.return_value = {"status": "completed", "assets": assets}
            mock_composer.return_value = {"status": "completed", "video_path": "final.mp4", "thumbnail_path": "thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            orch.run_pipeline(topic="Test", niche="test_niche")

        composer_call = mock_composer.call_args[1]
        assert composer_call["assets"] == assets
        assert composer_call["audio_files"] == audio_files

    def test_updates_job_status_on_completion(self, db_initialized, tmp_path):
        """Orchestrator should set job status to COMPLETED on success."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        conn = get_connection(db_initialized)
        job = conn.execute("SELECT status FROM jobs WHERE id = ?", (result["job_id"],)).fetchone()
        assert job["status"] == "COMPLETED"

    def test_g1_preflight_empty_topic(self, db_initialized):
        """G1 should reject empty topics before running any agents."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety:
            result = orch.run_pipeline(topic="   ", niche="test")
            assert result["status"] == "failed"
            assert result["failed_at"] == "preflight"
            mock_safety.assert_not_called()

    def test_g1_preflight_no_niche(self, db_initialized):
        """G1 should reject when None niche_config is provided (empty string still treated as valid niche name)."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety:
            # Empty niche name passes G1 (gate only checks None, not empty string)
            # The pipeline proceeds and fails at safety when it hits a real agent
            mock_safety.return_value = {"status": "hard_fail", "reason": "Blocked"}
            result = orch.run_pipeline(topic="Test", niche="")
            assert result["status"] == "failed"
            assert result["failed_at"] == "safety"

    def test_composer_failure_sets_job_failed(self, db_initialized, tmp_path):
        """If composer fails, job should be marked FAILED at the composer stage."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "failed", "error": "FFmpeg not found", "video_path": "", "thumbnail_path": ""}
            mock_reviewer.return_value = {}
            mock_pkg.return_value = {}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result["failed_at"] == "composer"
        mock_reviewer.assert_not_called()
        mock_pkg.assert_not_called()

    def test_voice_producer_failure_aborts_pipeline(self, db_initialized):
        """If voice_producer returns status='failed', pipeline must abort at
        voice_producer stage — not advance to G8 or Composer."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "failed", "error": "All TTS providers failed", "audio_files": []}
            mock_visual.return_value = {}
            mock_composer.return_value = {}
            mock_reviewer.return_value = {}
            mock_pkg.return_value = {}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result["failed_at"] == "voice_producer"
        assert "All TTS providers failed" in result.get("reason", "")
        # Visual Director and downstream should NOT have been called
        mock_visual.assert_not_called()
        mock_composer.assert_not_called()
        mock_reviewer.assert_not_called()
        # Job should be FAILED in DB
        conn = get_connection(db_initialized)
        job = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (result["job_id"],),
        ).fetchone()
        assert job["status"] == "FAILED"

    def test_visual_director_failure_aborts_pipeline(self, db_initialized,
                                                      tmp_path):
        """If visual_director returns status='failed', pipeline must abort at
        visual_director stage — not advance to G9 or Composer."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "failed", "error": "Asset sourcing failed", "assets": []}
            mock_composer.return_value = {}
            mock_reviewer.return_value = {}
            mock_pkg.return_value = {}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result["failed_at"] == "visual_director"
        assert "Asset sourcing failed" in result.get("reason", "")
        # Composer and downstream should NOT have been called
        mock_composer.assert_not_called()
        mock_reviewer.assert_not_called()
        # Job should be FAILED in DB
        conn = get_connection(db_initialized)
        job = conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (result["job_id"],),
        ).fetchone()
        assert job["status"] == "FAILED"

    def test_default_output_dir(self, db_initialized, tmp_path):
        """Orchestrator should default output_dir to 'outputs'."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            orch.run_pipeline(topic="Test", niche="test_niche")

        # Voice, visual, and composer should use outputs dir
        voice_call = mock_voice.call_args[1]
        assert "outputs" in voice_call.get("output_dir", "")

    def test_generates_cost_estimate_data(self, db_initialized, tmp_path):
        """G2 should generate a cost estimate."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert "cost_estimate" in result
        assert result["cost_estimate"]["estimate_cents"] > 0

    # ── Bug-fix tests ──────────────────────────────────────────────

    def test_unwraps_aggregate_research_sources(self, db_initialized, tmp_path):
        """P0: Orchestrator passes research paths to Visual Director.
        The new Visual Director reads research_contract.json directly,
        so the orchestrator no longer extracts source_urls — it passes
        research_contract_path and research_brief_path instead."""
        orch = Orchestrator(db_path=db_initialized)
        # Create real audio so G8 passes
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        # Simulate the real SegmentProducerAgent output format
        aggregate_sources = {
            "firecrawl_count": 2,
            "scrapecreators_count": 1,
            "total_sources": 3,
            "sources": [
                {"url": "https://a.com", "title": "A"},
                {"url": "https://b.com", "title": "B"},
                {"url": "https://c.com", "title": "C"},
            ],
        }

        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed",
                "research_brief": "ok",
                "sources": aggregate_sources,
            }
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": []}
            mock_composer.return_value = {"status": "completed", "video_path": "/tmp/final.mp4", "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            orch.run_pipeline(topic="Test", niche="test_niche")

        # Visual director receives research_contract_path and research_brief_path
        visual_call = mock_visual.call_args[1]
        assert "research_contract_path" in visual_call
        assert "research_brief_path" in visual_call

    def test_g4_hard_fail_aborts_pipeline(self, db_initialized):
        """P1: G4 (PostResearchRisk) returning hard_fail must abort the
        pipeline — currently the result is computed but never checked."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            # Researcher returns a danger flag that triggers G4 hard_fail
            mock_researcher.return_value = {
                "status": "completed",
                "research_brief": "ok",
                "sources": [],
                "risk_flags": ["defamation"],
            }
            mock_scriptwriter.return_value = {}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result.get("failed_at") in ("post_research_risk", "g4")
        mock_scriptwriter.assert_not_called()

    def test_package_failure_sets_job_failed(self, db_initialized, tmp_path):
        """P1: When OutputPackager returns status='failed', the job must be
        marked FAILED — currently COMPLETED is set unconditionally."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": ["https://a.com", "https://b.com"]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            # Package returns FAILED
            mock_pkg.return_value = {"status": "failed", "error": "Disk full", "output_dir": "/tmp"}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result.get("failed_at") == "packaging"

        conn = get_connection(db_initialized)
        job = conn.execute("SELECT status FROM jobs WHERE id = ?", (result["job_id"],)).fetchone()
        assert job["status"] == "FAILED"

    # ── Task 10: Gate persistence & hard-fail enforcement ──────────

    def test_g5_hard_fail_aborts_before_scriptwriter(self, db_initialized):
        """G5 hard_fail (no sources) must stop pipeline before Scriptwriter."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed",
                "research_brief": "ok",
                "sources": [],  # triggers G5 hard_fail
            }
            mock_scriptwriter.return_value = {}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result.get("failed_at") == "source_quality"
        mock_scriptwriter.assert_not_called()

    def test_g8_hard_fail_aborts_before_visual(self, db_initialized):
        """G8 hard_fail (no audio) must stop pipeline before Visual Director."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed", "research_brief": "ok",
                "sources": ["https://a.com", "https://b.com"]
            }
            mock_scriptwriter.return_value = {
                "status": "completed",
                "script": [{"scene": 1, "text": "Test", "duration": 3}],
                "caption": "Caption", "hashtags": [], "estimated_duration": 3,
            }
            mock_voice.return_value = {
                "status": "completed",
                "audio_files": [],  # empty triggers G8 hard_fail
            }
            mock_visual.return_value = {}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result.get("failed_at") == "audio_validation"
        mock_visual.assert_not_called()

    def test_g9_hard_fail_aborts_before_composer(self, db_initialized, tmp_path):
        """G9 hard_fail (no assets) must stop pipeline before Composer."""
        orch = Orchestrator(db_path=db_initialized)

        # Create real audio file so G8 passes
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake-audio-data")

        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer:
            # provide enough sources + audio to pass G5/G8
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed", "research_brief": "ok",
                "sources": ["https://a.com", "https://b.com"],
            }
            mock_scriptwriter.return_value = {
                "status": "completed",
                "script": [{"scene": 1, "text": "Test", "duration": 3}],
                "caption": "Caption", "hashtags": [], "estimated_duration": 3,
            }
            mock_voice.return_value = {
                "status": "completed",
                "audio_files": [str(audio_file)],
            }
            mock_visual.return_value = {
                "status": "completed",
                "assets": [],  # zero assets → G9 hard_fail
            }
            mock_composer.return_value = {}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result.get("failed_at") == "asset_validation"
        mock_composer.assert_not_called()

    def test_g10_hard_fail_aborts_before_reviewer(self, db_initialized, tmp_path):
        """G10 hard_fail (missing/too-small video) must stop before Reviewer."""
        orch = Orchestrator(db_path=db_initialized)

        # Create real audio file so G8 passes
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake-audio-data")
        # Create real asset so G9 passes
        asset_path = tmp_path / "scene.mp4"
        asset_path.write_bytes(b"fake-video")

        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed", "research_brief": "ok",
                "sources": ["https://a.com"],
            }
            mock_scriptwriter.return_value = {
                "status": "completed",
                "script": [{"scene": 1, "text": "Test", "duration": 3}],
                "caption": "Caption", "hashtags": [], "estimated_duration": 3,
            }
            mock_voice.return_value = {
                "status": "completed",
                "audio_files": [str(audio_file)],
            }
            mock_visual.return_value = {
                "status": "completed",
                "assets": [{"scene": 1, "source": "pexels", "path": str(asset_path)}],
            }
            # G10: video_path points to nonexistent file → hard_fail
            mock_composer.return_value = {
                "status": "completed",
                "video_path": "/nonexistent/fake_video.mp4",
                "thumbnail_path": "/tmp/thumb.png",
            }
            mock_reviewer.return_value = {}

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "failed"
        assert result.get("failed_at") == "video_validation"
        mock_reviewer.assert_not_called()

    def test_gate_results_persisted_to_workspace(self, db_initialized, tmp_path):
        """Each gate should write a JSON result file under job_{id}/gates/."""
        orch = Orchestrator(db_path=db_initialized)
        assets_cache = str(tmp_path / "cache")

        # Create real audio file so G8 passes
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir(exist_ok=True)
        audio_file = audio_dir / "scene_1.mp3"
        audio_file.write_bytes(b"fake-audio-data")
        # Create real video file so G10 passes
        video_dir = tmp_path / "videos"
        video_dir.mkdir(exist_ok=True)
        video_file = video_dir / "video.mp4"
        video_file.write_bytes(b"X" * 2048)
        # Create real asset file so G9 passes
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir(exist_ok=True)
        asset_path = asset_dir / "scene_1.mp4"
        asset_path.write_bytes(b"fake-video")

        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed", "research_brief": "ok",
                "sources": ["https://a.com", "https://b.com"],
            }
            mock_scriptwriter.return_value = {
                "status": "completed",
                "script": [{"scene": 1, "text": "Test", "duration": 3}],
                "caption": "Caption", "hashtags": [], "estimated_duration": 3,
            }
            mock_voice.return_value = {
                "status": "completed",
                "audio_files": [str(audio_file)],
            }
            mock_visual.return_value = {
                "status": "completed",
                "assets": [{"scene": 1, "source": "pexels", "path": str(asset_path)}],
            }
            mock_composer.return_value = {
                "status": "completed",
                "video_path": str(video_file),
                "thumbnail_path": "/tmp/thumb.png",
            }
            mock_reviewer.return_value = {
                "status": "pass", "score": 80, "feedback": "ok", "issues": [],
            }
            mock_pkg.return_value = {
                "status": "completed", "output_dir": "/tmp",
                "video_path": "", "caption_path": "", "thumbnail_path": "",
                "metadata_path": "",
            }

            result = orch.run_pipeline(
                topic="Test", niche="test_niche", assets_cache=assets_cache,
            )

        assert result["status"] == "completed"
        job_id = result["job_id"]
        gates_dir = Path(assets_cache) / f"job_{job_id}" / "gates"

        # G1 runs before job creation (job_id=0) — check separately
        g1_file = Path(assets_cache) / "job_0" / "gates" / "G1_input_preflight.json"
        assert g1_file.exists(), f"Missing G1 gate file: {g1_file}"
        g1_data = json.loads(g1_file.read_text())
        assert "passed" in g1_data

        # All 9 remaining gates should be under the actual job_id
        expected_gates = [
            "G2_cost_estimate", "G3_research_cache",
            "G4_post_research_risk", "G5_source_quality", "G6_creative_memory",
            "G7_script_validation", "G8_audio_validation", "G9_asset_validation",
            "G10_video_validation",
        ]
        for gate_name in expected_gates:
            gate_file = gates_dir / f"{gate_name}.json"
            assert gate_file.exists(), f"Missing gate file: {gate_file}"
            data = json.loads(gate_file.read_text())
            assert "passed" in data
            assert "severity" in data
            assert "message" in data

    # ── Task 11: Agent state DB transitions ──────────────────────

    def test_agent_states_transition_to_completed(self, db_initialized, tmp_path):
        """All agent states should transition pending→running→completed."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed", "research_brief": "ok",
                "sources": ["https://a.com", "https://b.com"],
            }
            mock_scriptwriter.return_value = {
                "status": "completed", "script": [],
                "caption": "", "hashtags": [], "estimated_duration": 0,
            }
            mock_voice.return_value = {
                "status": "completed", "audio_files": [str(audio)],
            }
            mock_visual.return_value = {
                "status": "completed",
                "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}],
            }
            mock_composer.return_value = {
                "status": "completed",
                "video_path": str(video), "thumbnail_path": "/tmp/thumb.png",
            }
            mock_reviewer.return_value = {
                "status": "pass", "score": 80, "feedback": "ok", "issues": [],
            }
            mock_pkg.return_value = {
                "status": "completed", "output_dir": "/tmp",
                "video_path": "", "caption_path": "", "thumbnail_path": "",
                "metadata_path": "",
            }

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "completed"
        conn = get_connection(db_initialized)
        expected_agents = ["safety", "segment_producer", "scriptwriter",
                          "voice_producer", "visual_director", "composer",
                          "reviewer"]
        for agent_name in expected_agents:
            state = conn.execute(
                "SELECT state, started_at, completed_at FROM agent_states "
                "WHERE job_id=? AND agent_name=?",
                (result["job_id"], agent_name),
            ).fetchone()
            assert state is not None, f"Missing state for {agent_name}"
            assert state["state"] == "completed", \
                f"{agent_name} state is '{state['state']}', expected 'completed'"
            assert state["started_at"] is not None, \
                f"{agent_name} started_at is null"
            assert state["completed_at"] is not None, \
                f"{agent_name} completed_at is null"

    def test_failed_agent_state_persists(self, db_initialized):
        """Failed agent should have state=failed with error_message."""
        orch = Orchestrator(db_path=db_initialized)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed", "research_brief": "ok",
                "sources": [],
                "risk_flags": ["defamation"],
            }

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        conn = get_connection(db_initialized)
        # Researcher should be completed (it ran before G4 check)
        researcher_state = conn.execute(
            "SELECT state FROM agent_states WHERE job_id=? AND agent_name=?",
            (result["job_id"], "segment_producer"),
        ).fetchone()
        assert researcher_state["state"] == "completed"
        # Scriptwriter was never reached
        scriptwriter_state = conn.execute(
            "SELECT state FROM agent_states WHERE job_id=? AND agent_name=?",
            (result["job_id"], "scriptwriter"),
        ).fetchone()
        assert scriptwriter_state["state"] == "pending"


# ── Phase 13: Config snapshot persistence ────────────────────────


@pytest.mark.usefixtures("mock_probe_video_ok")
class TestConfigSnapshot:
    """Tests for config snapshot persistence in pipeline runs."""

    def test_pipeline_stores_config_snapshot_in_db(self, db_initialized, tmp_path):
        """run_pipeline should persist config_snapshot in the jobs table."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": [{"url": "https://a.com", "title": "S1"}]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline(topic="Test topic", niche="test_niche")

        assert result["status"] == "completed"
        conn = get_connection(db_initialized)
        job = conn.execute(
            "SELECT config_snapshot FROM jobs WHERE id = ?",
            (result["job_id"],),
        ).fetchone()
        assert job["config_snapshot"] is not None
        snapshot = json.loads(job["config_snapshot"])
        assert snapshot["niche"] == "test_niche"
        assert snapshot["topic"] == "Test topic"

    def test_manifest_includes_config_snapshot(self, db_initialized, tmp_path):
        """Manifest should include config_snapshot field."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)
        with patch.object(Orchestrator, "_run_safety") as mock_safety,\
             patch.object(Orchestrator, "_run_researcher") as mock_researcher,\
             patch.object(Orchestrator, "_run_scriptwriter") as mock_scriptwriter,\
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice,\
             patch.object(Orchestrator, "_run_visual_director") as mock_visual,\
             patch.object(Orchestrator, "_run_composer") as mock_composer,\
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer,\
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": [{"url": "https://a.com", "title": "S1"}]}
            mock_scriptwriter.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_voice.return_value = {"status": "completed", "audio_files": [str(audio)]}
            mock_visual.return_value = {"status": "completed", "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}]}
            mock_composer.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": "/tmp/thumb.png"}
            mock_reviewer.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline(topic="Test topic", niche="test_niche",
                                       assets_cache=str(tmp_path / "cache"))

        assert result["status"] == "completed"
        from clipper_agency.core.manifest import load_manifest
        ac = str(tmp_path / "cache")
        manifest = load_manifest(ac, result["job_id"])
        assert "config_snapshot" in manifest
        assert manifest["config_snapshot"]["niche"] == "test_niche"


@pytest.mark.usefixtures("mock_probe_video_ok")
class TestRunPipelineFrom:
    """Tests for retry/resume pipeline execution from a specific agent."""

    def _setup_completed_job(
        self, db_path: str, assets_cache: str, output_dir: str,
        completed_agents: list[str], failed_agent: str | None = None,
        config_snapshot: dict | None = None,
    ) -> int:
        """Create a job with completed/failed agent states and output artifacts."""
        from clipper_agency.db.connection import get_connection as _get_conn
        from clipper_agency.db.queries import (
            create_agent_state, create_job, mark_agent_completed,
            mark_agent_failed, update_job_status,
        )
        from clipper_agency.db.schema import initialize_schema as _init

        conn = _get_conn(db_path)
        _init(conn)
        snapshot = config_snapshot or {
            "topic": "Test topic", "niche": "test_niche",
            "output_dir": output_dir, "assets_cache": assets_cache,
        }
        job_id = create_job(conn, "Test topic", "test_niche",
                            config_snapshot=snapshot)

        all_agents = ["safety", "segment_producer", "scriptwriter",
                      "voice_producer", "visual_director", "composer", "reviewer"]
        for name in all_agents:
            create_agent_state(conn, job_id, name)

        for name in completed_agents:
            mark_agent_completed(conn, job_id, name)

        if failed_agent:
            mark_agent_failed(conn, job_id, failed_agent, "test failure")
            update_job_status(conn, job_id, "FAILED", "test failure")

        # Write output.json for completed agents
        from pathlib import Path as _P
        agent_outputs = {
            "safety": {"status": "pass", "reason": "Safe"},
            "segment_producer": {
                "status": "completed",
                "research_brief": "Research brief text",
                "sources": [{"url": "https://example.com", "title": "S1"}],
                "risk_flags": [],
            },
            "scriptwriter": {
                "status": "completed",
                "script": [{"scene": 1, "text": "Halo!", "duration": 3}],
                "caption": "Test caption",
                "hashtags": [],
                "estimated_duration": 3,
            },
            "voice_producer": {
                "status": "completed",
                "audio_files": [f"{assets_cache}/job_{job_id}/agents/voice_producer/voices/scene_1.mp3"],
            },
            "visual_director": {
                "status": "completed",
                "assets": [{"scene": 1, "source": "pexels", "path": f"{assets_cache}/job_{job_id}/agents/visual_director/scenes/scene_1.mp4"}],
            },
        }
        for agent_name, output in agent_outputs.items():
            if agent_name in completed_agents:
                out_path = _P(assets_cache) / f"job_{job_id}" / "agents" / agent_name / "output.json"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(output), encoding="utf-8")

        # Write manifest
        manifest_path = _P(assets_cache) / f"job_{job_id}" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "job_id": job_id, "topic": "Test topic",
            "config_snapshot": snapshot,
            "agents": {}, "gates": {}, "final_outputs": {},
        }), encoding="utf-8")

        close_connection(db_path)
        return job_id

    def test_retry_from_researcher_skips_safety(self, db_initialized, tmp_path):
        """run_pipeline_from('researcher') should not re-run safety."""
        ac = str(tmp_path / "cache")
        od = str(tmp_path / "outputs")
        job_id = self._setup_completed_job(
            db_initialized, ac, od,
            completed_agents=["safety"],
        )
        orch = Orchestrator(db_path=db_initialized)
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety") as mock_safety, \
             patch.object(Orchestrator, "_run_researcher") as mock_researcher, \
             patch.object(Orchestrator, "_run_scriptwriter") as mock_sw, \
             patch.object(Orchestrator, "_run_voice_producer") as mock_vp, \
              patch.object(Orchestrator, "_run_visual_director") as mock_vd, \
              patch.object(Orchestrator, "_run_composer") as mock_comp, \
              patch.object(Orchestrator, "_run_reviewer") as mock_rev, \
              patch.object(Orchestrator, "_package_output") as mock_pkg:
             mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": [{"url": "https://a.com", "title": "S1"}]}
             mock_sw.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
             mock_vp.return_value = {"status": "completed", "audio_files": []}
             mock_vd.return_value = {"status": "completed", "assets": []}
             mock_comp.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": ""}
             mock_rev.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
             mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

             result = orch.run_pipeline_from(job_id, from_agent="segment_producer")

        assert result["status"] == "completed"
        mock_safety.assert_not_called()
        mock_researcher.assert_called_once()

    def test_retry_from_safety_reruns_safety(self, db_initialized, tmp_path):
        """run_pipeline_from('safety') should run safety on the existing job."""
        ac = str(tmp_path / "cache")
        od = str(tmp_path / "outputs")
        job_id = self._setup_completed_job(
            db_initialized, ac, od,
            completed_agents=[],
        )
        orch = Orchestrator(db_path=db_initialized)
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety") as mock_safety, \
             patch.object(Orchestrator, "_run_researcher") as mock_researcher, \
             patch.object(Orchestrator, "_run_scriptwriter") as mock_sw, \
             patch.object(Orchestrator, "_run_voice_producer") as mock_vp, \
             patch.object(Orchestrator, "_run_visual_director") as mock_vd, \
             patch.object(Orchestrator, "_run_composer") as mock_comp, \
             patch.object(Orchestrator, "_run_reviewer") as mock_rev, \
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {"status": "completed", "research_brief": "ok", "sources": [{"url": "https://a.com", "title": "S1"}]}
            mock_sw.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_vp.return_value = {"status": "completed", "audio_files": []}
            mock_vd.return_value = {"status": "completed", "assets": []}
            mock_comp.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": ""}
            mock_rev.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline_from(job_id, from_agent="safety")

        assert result["status"] == "completed"
        mock_safety.assert_called_once()
        state = get_connection(db_initialized).execute(
            "SELECT state FROM agent_states WHERE job_id = ? AND agent_name = ?",
            (job_id, "safety"),
        ).fetchone()
        assert state["state"] == "completed"

    def test_retry_from_composer_reconstructs_all_upstream(self, db_initialized, tmp_path):
        """run_pipeline_from('composer') loads all upstream outputs from artifacts."""
        ac = str(tmp_path / "cache")
        od = str(tmp_path / "outputs")
        job_id = self._setup_completed_job(
            db_initialized, ac, od,
            completed_agents=["safety", "segment_producer", "scriptwriter",
                              "voice_producer", "visual_director"],
            failed_agent="composer",
        )
        orch = Orchestrator(db_path=db_initialized)
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety") as mock_safety, \
             patch.object(Orchestrator, "_run_researcher") as mock_researcher, \
             patch.object(Orchestrator, "_run_scriptwriter") as mock_sw, \
             patch.object(Orchestrator, "_run_voice_producer") as mock_vp, \
             patch.object(Orchestrator, "_run_visual_director") as mock_vd, \
             patch.object(Orchestrator, "_run_composer") as mock_comp, \
             patch.object(Orchestrator, "_run_reviewer") as mock_rev, \
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_comp.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": ""}
            mock_rev.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline_from(job_id, from_agent="composer")

        assert result["status"] == "completed"
        # Upstream agents should NOT be called
        mock_safety.assert_not_called()
        mock_researcher.assert_not_called()
        mock_sw.assert_not_called()
        mock_vp.assert_not_called()
        mock_vd.assert_not_called()
        # Composer + reviewer should be called
        mock_comp.assert_called_once()
        mock_rev.assert_called_once()

    def test_run_pipeline_from_updates_job_status_running(self, db_initialized, tmp_path):
        """run_pipeline_from sets job to RUNNING before execution."""
        ac = str(tmp_path / "cache")
        od = str(tmp_path / "outputs")
        job_id = self._setup_completed_job(
            db_initialized, ac, od,
            completed_agents=["safety", "segment_producer", "scriptwriter",
                              "voice_producer", "visual_director"],
            failed_agent="composer",
        )
        orch = Orchestrator(db_path=db_initialized)
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety"), \
             patch.object(Orchestrator, "_run_researcher"), \
             patch.object(Orchestrator, "_run_scriptwriter"), \
             patch.object(Orchestrator, "_run_voice_producer"), \
             patch.object(Orchestrator, "_run_visual_director"), \
             patch.object(Orchestrator, "_run_composer") as mock_comp, \
             patch.object(Orchestrator, "_run_reviewer") as mock_rev, \
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_comp.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": ""}
            mock_rev.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline_from(job_id, from_agent="composer")

        from clipper_agency.db.connection import get_connection as _gc
        conn = _gc(db_initialized)
        job = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert job["status"] == "COMPLETED"

    def test_run_pipeline_from_missing_job_returns_failure(self, db_initialized, tmp_path):
        """run_pipeline_from returns failure for nonexistent job."""
        orch = Orchestrator(db_path=db_initialized)
        result = orch.run_pipeline_from(99999, from_agent="segment_producer")
        assert result["status"] == "failed"

    def test_run_pipeline_from_passes_reconstructed_research_to_scriptwriter(
        self, db_initialized, tmp_path,
    ):
        """run_pipeline_from passes loaded research output to downstream stages."""
        ac = str(tmp_path / "cache")
        od = str(tmp_path / "outputs")
        job_id = self._setup_completed_job(
            db_initialized, ac, od,
            completed_agents=["safety", "segment_producer"],
        )
        orch = Orchestrator(db_path=db_initialized)
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety"), \
             patch.object(Orchestrator, "_run_researcher"), \
             patch.object(Orchestrator, "_run_scriptwriter") as mock_sw, \
             patch.object(Orchestrator, "_run_voice_producer") as mock_vp, \
             patch.object(Orchestrator, "_run_visual_director") as mock_vd, \
             patch.object(Orchestrator, "_run_composer") as mock_comp, \
             patch.object(Orchestrator, "_run_reviewer") as mock_rev, \
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_sw.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_vp.return_value = {"status": "completed", "audio_files": []}
            mock_vd.return_value = {"status": "completed", "assets": []}
            mock_comp.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": ""}
            mock_rev.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline_from(job_id, from_agent="scriptwriter")

        assert result["status"] == "completed"
        # Verify scriptwriter received the reconstructed research_brief
        sw_call = mock_sw.call_args[1]
        assert sw_call["research_brief"] == "Research brief text"

    def test_use_cache_valid_skips_paid_agent(self, db_initialized, tmp_path):
        """use_cache=True with valid artifacts should reuse cache, not re-run."""
        ac = str(tmp_path / "cache")
        od = str(tmp_path / "outputs")
        job_id = self._setup_completed_job(
            db_initialized, ac, od,
            completed_agents=["safety", "segment_producer", "scriptwriter",
                              "voice_producer", "visual_director"],
            failed_agent="composer",
        )
        # Write valid scriptwriter artifacts
        sw_dir = Path(ac) / f"job_{job_id}" / "agents" / "scriptwriter"
        sw_dir.mkdir(parents=True, exist_ok=True)
        (sw_dir / "script.json").write_text(json.dumps(
            [{"scene": 1, "text": "Halo!"}]))
        # Write valid voice producer artifacts
        vp_dir = Path(ac) / f"job_{job_id}" / "agents" / "voice_producer" / "voices"
        vp_dir.mkdir(parents=True, exist_ok=True)
        (vp_dir / "scene_1.mp3").write_bytes(b"x" * 100)

        orch = Orchestrator(db_path=db_initialized)
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety") as mock_safety, \
             patch.object(Orchestrator, "_run_scriptwriter") as mock_sw, \
             patch.object(Orchestrator, "_run_voice_producer") as mock_vp, \
             patch.object(Orchestrator, "_run_composer") as mock_comp, \
             patch.object(Orchestrator, "_run_reviewer") as mock_rev, \
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_comp.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": ""}
            mock_rev.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline_from(
                job_id, from_agent="composer", use_cache=True)

        assert result["status"] == "completed"
        mock_safety.assert_not_called()
        mock_sw.assert_not_called()
        mock_vp.assert_not_called()
        mock_comp.assert_called_once()

    def test_use_cache_invalid_falls_through_to_rerun(self, db_initialized, tmp_path):
        """use_cache=True with invalid artifacts should re-run the agent."""
        ac = str(tmp_path / "cache")
        od = str(tmp_path / "outputs")
        job_id = self._setup_completed_job(
            db_initialized, ac, od,
            completed_agents=["safety", "segment_producer", "scriptwriter",
                              "voice_producer", "visual_director"],
            failed_agent="composer",
        )
        # scriptwriter has output.json but NO script.json → validation fails
        # (the _setup_completed_job only writes output.json, not script.json)
        orch = Orchestrator(db_path=db_initialized)
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety"), \
             patch.object(Orchestrator, "_run_researcher"), \
             patch.object(Orchestrator, "_run_content_scriptwriter") as mock_sw, \
             patch.object(Orchestrator, "_run_content_voice"), \
             patch.object(Orchestrator, "_run_visual_director_phase"), \
             patch.object(Orchestrator, "_run_composer") as mock_comp, \
             patch.object(Orchestrator, "_run_reviewer") as mock_rev, \
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_sw.return_value = {"status": "completed", "script": [], "caption": "", "hashtags": [], "estimated_duration": 0}
            mock_comp.return_value = {"status": "completed", "video_path": str(video), "thumbnail_path": ""}
            mock_rev.return_value = {"status": "pass", "score": 80, "feedback": "ok", "issues": []}
            mock_pkg.return_value = {"status": "completed", "output_dir": "/tmp", "video_path": "", "caption_path": "", "thumbnail_path": "", "metadata_path": ""}

            result = orch.run_pipeline_from(
                job_id, from_agent="scriptwriter", use_cache=True)

        assert result["status"] == "completed"
        # scriptwriter should be re-run because cache was invalid
        mock_sw.assert_called_once()

    # ── Phase 15a: Template name propagation ────────────────────────

    def test_template_name_propagates_to_package_metadata(
        self, db_initialized, tmp_path
    ):
        """Composer template_name must flow through engine to packager metadata."""
        orch = Orchestrator(db_path=db_initialized)
        audio = tmp_path / "a.mp3"; audio.write_bytes(b"x")
        asset = tmp_path / "v.mp4"; asset.write_bytes(b"x")
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety") as mock_safety, \
             patch.object(Orchestrator, "_run_researcher") as mock_researcher, \
             patch.object(Orchestrator, "_run_scriptwriter") as mock_sw, \
             patch.object(Orchestrator, "_run_voice_producer") as mock_voice, \
             patch.object(Orchestrator, "_run_visual_director") as mock_visual, \
             patch.object(Orchestrator, "_run_composer") as mock_composer, \
             patch.object(Orchestrator, "_run_reviewer") as mock_reviewer, \
             patch("clipper_agency.orchestrator.engine.OutputPackager") as mock_pkg_cls:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            mock_researcher.return_value = {
                "status": "completed", "research_brief": "brief",
                "sources": ["https://a.com", "https://b.com"],
            }
            mock_sw.return_value = {
                "status": "completed", "script": [], "caption": "cap",
                "hashtags": [], "estimated_duration": 0,
            }
            mock_voice.return_value = {
                "status": "completed", "audio_files": [str(audio)],
            }
            mock_visual.return_value = {
                "status": "completed",
                "assets": [{"scene": 1, "source": "pexels", "path": str(asset)}],
            }
            mock_composer.return_value = {
                "status": "completed",
                "video_path": str(video),
                "thumbnail_path": "/tmp/thumb.png",
                "template_name": "news_card",
            }
            mock_reviewer.return_value = {
                "status": "pass", "score": 80, "feedback": "ok", "issues": [],
            }
            mock_pkg_inst = mock_pkg_cls.return_value
            mock_pkg_inst.package.return_value = {
                "status": "completed", "output_dir": str(tmp_path),
                "video_path": str(video), "caption_path": "",
                "thumbnail_path": "", "metadata_path": "",
            }

            result = orch.run_pipeline(topic="Test", niche="test_niche")

        assert result["status"] == "completed"
        # Verify template_name was passed to packager metadata
        pkg_call = mock_pkg_inst.package.call_args
        assert pkg_call[1]["metadata"]["template_name"] == "news_card"

    def test_run_pipeline_from_uses_snapshot_niche_ctx(self, db_initialized, tmp_path):
        """run_pipeline_from should use niche_ctx from snapshot if present."""
        ac = str(tmp_path / "cache")
        od = str(tmp_path / "outputs")
        # Create a job with niche_ctx already in the snapshot
        job_id = self._setup_completed_job(
            db_initialized, ac, od,
            completed_agents=["safety", "segment_producer", "scriptwriter",
                              "voice_producer", "visual_director"],
            failed_agent="composer",
            config_snapshot={
                "topic": "Test topic", "niche": "test_niche",
                "output_dir": od, "assets_cache": ac,
                "niche_ctx": {
                    "safety_rules": ["custom_rule"],
                    "channel_description": "Snapshot-based description",
                    "language": "fr",
                    "tone": "formal",
                    "content_angle": "Snapshot angle",
                },
            },
        )
        orch = Orchestrator(db_path=db_initialized)
        video = tmp_path / "out.mp4"; video.write_bytes(b"X" * 2048)

        with patch.object(Orchestrator, "_run_safety") as mock_safety, \
             patch.object(Orchestrator, "_run_researcher") as mock_researcher, \
             patch.object(Orchestrator, "_run_scriptwriter") as mock_sw, \
             patch.object(Orchestrator, "_run_voice_producer") as mock_vp, \
             patch.object(Orchestrator, "_run_visual_director") as mock_vd, \
             patch.object(Orchestrator, "_run_composer") as mock_comp, \
             patch.object(Orchestrator, "_run_reviewer") as mock_rev, \
             patch.object(Orchestrator, "_package_output") as mock_pkg:
            mock_comp.return_value = {
                "status": "completed",
                "video_path": str(video), "thumbnail_path": "",
            }
            mock_rev.return_value = {
                "status": "pass", "score": 80, "feedback": "ok", "issues": [],
            }
            mock_pkg.return_value = {
                "status": "completed", "output_dir": "/tmp",
                "video_path": "", "caption_path": "",
                "thumbnail_path": "", "metadata_path": "",
            }

            result = orch.run_pipeline_from(job_id, from_agent="composer")

        assert result["status"] == "completed"

    def test_run_pipeline_niche_not_found_fails(self, db_initialized, mocker):
        """run_pipeline should fail fast if niche YAML is missing."""
        mocker.patch(
            "clipper_agency.orchestrator.engine.load_niche",
            side_effect=FileNotFoundError("Niche not found: niches/missing.yaml"),
        )
        orch = Orchestrator(db_path=db_initialized)
        result = orch.run_pipeline(topic="Test", niche="missing_niche")
        assert result["status"] == "failed"
        assert "missing_niche" in str(result["reason"])


# ── Engine helper methods — coverage for uncovered paths ──────────


@pytest.mark.usefixtures("mock_probe_video_ok")
class TestEngineHelpers:
    """Tests for uncovered helper methods on Orchestrator."""

    # ── Agent runner methods (lines 774-849) ──

    def test_run_safety_creates_agent_and_executes(self, db_initialized):
        """_run_safety instantiates SafetyAgent and calls execute()."""
        orch = Orchestrator(db_path=db_initialized)
        with patch("clipper_agency.orchestrator.engine.SafetyAgent") as mock_cls:
            mock_agent = MagicMock()
            mock_agent.execute.return_value = {"status": "pass"}
            mock_cls.return_value = mock_agent

            result = orch._run_safety(job_id=1, topic="Test")

        mock_cls.assert_called_once()
        mock_agent.execute.assert_called_once_with(job_id=1, topic="Test")
        assert result == {"status": "pass"}

    def test_run_researcher_creates_agent_and_executes(self, db_initialized):
        """_run_researcher instantiates SegmentProducerAgent and calls execute()."""
        orch = Orchestrator(db_path=db_initialized)
        with patch("clipper_agency.orchestrator.engine.SegmentProducerAgent") as mock_cls:
            mock_agent = MagicMock()
            mock_agent.execute.return_value = {"status": "completed"}
            mock_cls.return_value = mock_agent

            result = orch._run_researcher(
                job_id=2, topic="Topic", safety_rules=["r1"],
                output_dir="/out",
            )

        mock_cls.assert_called_once()
        mock_agent.execute.assert_called_once_with(
            job_id=2, topic="Topic",
            safety_rules=["r1"], output_dir="/out",
        )
        assert result == {"status": "completed"}

    def test_run_scriptwriter_creates_agent_and_executes(self, db_initialized):
        """_run_scriptwriter instantiates ScriptwriterAgent and calls execute()."""
        orch = Orchestrator(db_path=db_initialized)
        with patch("clipper_agency.orchestrator.engine.ScriptwriterAgent") as mock_cls:
            mock_agent = MagicMock()
            mock_agent.execute.return_value = {"status": "completed"}
            mock_cls.return_value = mock_agent

            result = orch._run_scriptwriter(
                job_id=3, topic="Topic",
                research_brief="brief", safety_rules=["r1"],
            )

        mock_cls.assert_called_once()
        mock_agent.execute.assert_called_once_with(
            job_id=3, topic="Topic",
            research_brief="brief", safety_rules=["r1"],
        )
        assert result == {"status": "completed"}

    def test_run_voice_producer_creates_agent_and_executes(self, db_initialized):
        """_run_voice_producer instantiates VoiceProducerAgent and calls execute()."""
        orch = Orchestrator(db_path=db_initialized)
        with patch("clipper_agency.orchestrator.engine.VoiceProducerAgent") as mock_cls:
            mock_agent = MagicMock()
            mock_agent.execute.return_value = {"status": "completed"}
            mock_cls.return_value = mock_agent

            result = orch._run_voice_producer(
                job_id=4, script=[{"scene": 1}],
                output_dir="/out",
            )

        mock_cls.assert_called_once()
        mock_agent.execute.assert_called_once_with(
            job_id=4, script=[{"scene": 1}], output_dir="/out",
        )
        assert result == {"status": "completed"}

    def test_run_visual_director_creates_agent_and_executes(self, db_initialized):
        """_run_visual_director instantiates VisualDirectorAgent and calls execute()."""
        orch = Orchestrator(db_path=db_initialized)
        with patch("clipper_agency.orchestrator.engine.VisualDirectorAgent") as mock_cls:
            mock_agent = MagicMock()
            mock_agent.execute.return_value = {"status": "completed"}
            mock_cls.return_value = mock_agent

            result = orch._run_visual_director(
                job_id=5, script=[{"scene": 1}],
                topic="Topic", source_urls=["https://a.com"],
                output_dir="/out",
            )

        mock_cls.assert_called_once()
        mock_agent.execute.assert_called_once_with(
            job_id=5, script=[{"scene": 1}],
            topic="Topic", source_urls=["https://a.com"],
            output_dir="/out",
        )
        assert result == {"status": "completed"}

    def test_run_composer_creates_agent_and_executes(self, db_initialized):
        """_run_composer instantiates ComposerAgent and calls execute()."""
        orch = Orchestrator(db_path=db_initialized)
        with patch("clipper_agency.orchestrator.engine.ComposerAgent") as mock_cls:
            mock_agent = MagicMock()
            mock_agent.execute.return_value = {"status": "completed"}
            mock_cls.return_value = mock_agent

            result = orch._run_composer(
                job_id=6, assets=[{"path": "v.mp4"}],
                audio_files=["a.mp3"], output_dir="/out",
            )

        mock_cls.assert_called_once()
        mock_agent.execute.assert_called_once_with(
            job_id=6, assets=[{"path": "v.mp4"}],
            audio_files=["a.mp3"], output_dir="/out",
        )
        assert result == {"status": "completed"}

    def test_run_reviewer_creates_agent_and_executes(self, db_initialized):
        """_run_reviewer instantiates ReviewerAgent and calls execute()."""
        orch = Orchestrator(db_path=db_initialized)
        with patch("clipper_agency.orchestrator.engine.ReviewerAgent") as mock_cls:
            mock_agent = MagicMock()
            mock_agent.execute.return_value = {"status": "pass"}
            mock_cls.return_value = mock_agent

            result = orch._run_reviewer(
                job_id=7, topic="Topic",
                script=[{"scene": 1}], caption="cap",
                safety_rules=["r1"],
            )

        mock_cls.assert_called_once()
        mock_agent.execute.assert_called_once_with(
            job_id=7, topic="Topic",
            script=[{"scene": 1}], caption="cap",
            safety_rules=["r1"],
        )
        assert result == {"status": "pass"}

    # ── _load_agent_output (lines 391-400) ──

    def test_load_agent_output_returns_parsed_json(self, db_initialized, tmp_path):
        """_load_agent_output returns parsed JSON when output.json exists."""
        from clipper_agency.core.paths import agent_output_file

        orch = Orchestrator(db_path=db_initialized)
        ac = str(tmp_path / "cache")
        data = {"status": "completed", "key": "value"}
        out_path = Path(agent_output_file(ac, 1, "test_agent"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data), encoding="utf-8")

        result = orch._load_agent_output(ac, 1, "test_agent")
        assert result == data

    def test_load_agent_output_returns_empty_on_missing(self, db_initialized, tmp_path):
        """_load_agent_output returns {} when no output.json exists."""
        orch = Orchestrator(db_path=db_initialized)
        result = orch._load_agent_output(str(tmp_path / "cache"), 99, "no_agent")
        assert result == {}

    def test_load_agent_output_returns_empty_on_invalid_json(self, db_initialized, tmp_path):
        """_load_agent_output returns {} when output.json has invalid JSON."""
        from clipper_agency.core.paths import agent_output_file

        orch = Orchestrator(db_path=db_initialized)
        ac = str(tmp_path / "cache")
        out_path = Path(agent_output_file(ac, 1, "bad_agent"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("{invalid json", encoding="utf-8")

        result = orch._load_agent_output(ac, 1, "bad_agent")
        assert result == {}

    # ── _try_load_cached (lines 402-415) ──

    def test_try_load_cached_returns_output_on_valid_cache(
        self, db_initialized, tmp_path,
    ):
        """_try_load_cached returns cached output when validation passes."""
        orch = Orchestrator(db_path=db_initialized)
        cached_data = {"status": "completed", "from_cache": True}

        with patch("clipper_agency.orchestrator.engine.validate_agent_cache") as mock_validate, \
             patch.object(orch, "_load_agent_output", return_value=cached_data):
            from clipper_agency.core.validation import ValidationResult
            mock_validate.return_value = ValidationResult(passed=True)

            result = orch._try_load_cached("/cache", 1, "scriptwriter")

        assert result == cached_data

    def test_try_load_cached_returns_empty_on_invalid_cache(
        self, db_initialized,
    ):
        """_try_load_cached returns {} when cache validation fails."""
        orch = Orchestrator(db_path=db_initialized)

        with patch("clipper_agency.orchestrator.engine.validate_agent_cache") as mock_validate:
            from clipper_agency.core.validation import ValidationResult
            mock_validate.return_value = ValidationResult(
                passed=False, issues=["missing artifact"],
            )

            result = orch._try_load_cached("/cache", 1, "scriptwriter")

        assert result == {}

    # ── _run_cached_or_fresh (lines 417-427) ──

    def test_run_cached_or_fresh_skips_cache_when_false(self, db_initialized):
        """use_cache=False calls run_fn directly, skipping cache lookup."""
        orch = Orchestrator(db_path=db_initialized)
        run_fn = MagicMock(return_value={"fresh": True})

        with patch.object(orch, "_try_load_cached") as mock_cache:
            result = orch._run_cached_or_fresh(
                "agent", False, "/cache", 1, run_fn,
            )

        mock_cache.assert_not_called()
        run_fn.assert_called_once()
        assert result == {"fresh": True}

    def test_run_cached_or_fresh_returns_cached_on_hit(self, db_initialized):
        """use_cache=True with valid cache returns cached output, skips run_fn."""
        orch = Orchestrator(db_path=db_initialized)
        run_fn = MagicMock(return_value={"fresh": True})
        cached = {"cached": True}

        with patch.object(orch, "_try_load_cached", return_value=cached):
            result = orch._run_cached_or_fresh(
                "agent", True, "/cache", 1, run_fn,
            )

        run_fn.assert_not_called()
        assert result == cached

    def test_run_cached_or_fresh_falls_through_on_miss(self, db_initialized):
        """use_cache=True with invalid cache falls through to run_fn."""
        orch = Orchestrator(db_path=db_initialized)
        run_fn = MagicMock(return_value={"fresh": True})

        with patch.object(orch, "_try_load_cached", return_value={}):
            result = orch._run_cached_or_fresh(
                "agent", True, "/cache", 1, run_fn,
            )

        run_fn.assert_called_once()
        assert result == {"fresh": True}

    # ── _run_visual_director_phase (lines 429-452) ──

    def test_visual_director_phase_passes_research_paths(
        self, db_initialized, tmp_path,
    ):
        """Engine passes research_contract_path and research_brief_path."""
        orch = Orchestrator(db_path=db_initialized)
        research_output = {
            "sources": {
                "sources": [
                    {"url": "https://a.com"},
                    {"url": "https://b.com"},
                ],
            },
        }
        with patch.object(orch, "_run_visual_director") as mock_vd, \
             patch.object(orch, "_complete_agent"):
            mock_vd.return_value = {"status": "completed"}

            orch._run_visual_director_phase(
                get_connection(db_initialized), 1, "Topic",
                research_output, {"script": []}, "/out", "/cache",
            )

        _, kwargs = mock_vd.call_args
        assert "research_contract_path" in kwargs
        assert "research_brief_path" in kwargs

    def test_visual_director_phase_list_sources(
        self, db_initialized, tmp_path,
    ):
        """Engine handles list sources format with research paths."""
        orch = Orchestrator(db_path=db_initialized)
        research_output = {
            "sources": [
                {"url": "https://x.com"},
                {"url": "https://y.com"},
            ],
        }
        with patch.object(orch, "_run_visual_director") as mock_vd, \
             patch.object(orch, "_complete_agent"):
            mock_vd.return_value = {"status": "completed"}

            orch._run_visual_director_phase(
                get_connection(db_initialized), 1, "Topic",
                research_output, {"script": []}, "/out", "/cache",
            )

        _, kwargs = mock_vd.call_args
        assert "research_contract_path" in kwargs
        assert "research_brief_path" in kwargs

    def test_visual_director_phase_handles_none_sources(
        self, db_initialized, tmp_path,
    ):
        """Engine handles None sources with empty research paths."""
        orch = Orchestrator(db_path=db_initialized)
        research_output = {"sources": None}

        with patch.object(orch, "_run_visual_director") as mock_vd, \
             patch.object(orch, "_complete_agent"):
            mock_vd.return_value = {"status": "completed"}

            orch._run_visual_director_phase(
                get_connection(db_initialized), 1, "Topic",
                research_output, {"script": []}, "/out", "/cache",
            )

        _, kwargs = mock_vd.call_args
        assert kwargs.get("research_contract_path", "") == ""
        assert kwargs.get("research_brief_path", "") == ""

    # ── Pipeline exception handler (lines 386-389) ──

    def test_pipeline_exception_handler(self, db_initialized):
        """Top-level exception in run_pipeline returns FAILED status."""
        orch = Orchestrator(db_path=db_initialized)

        with patch.object(Orchestrator, "_run_safety") as mock_safety:
            mock_safety.return_value = {"status": "pass", "reason": "Safe"}
            # Make researcher raise an exception to hit the except block
            with patch.object(
                Orchestrator, "_run_researcher",
                side_effect=RuntimeError("unexpected crash"),
            ):
                result = orch.run_pipeline(topic="Test", niche="test")

        assert result["status"] == "failed"
        assert "unexpected crash" in result.get("error", "")
        assert result["job_id"] > 0
