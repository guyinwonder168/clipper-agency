"""Tests for VisualDirectorAgent artifact persistence."""

import json
from pathlib import Path
from unittest import mock

import pytest

from clipper_agency.agents.visual_director import VisualDirectorAgent


SCENES = [
    {"scene": 1, "text": "Intro", "duration": 3},
    {"scene": 2, "text": "Body", "duration": 5},
]


def _setup_mocks(mocker):
    """Mock Pexels search and download for a happy path."""
    mocker.patch(
        "clipper_agency.services.pexels.PexelsService.search_videos",
        return_value=[
            {"id": 1, "video_files": [{"link": "https://pexels.mp4/1"}]},
            {"id": 2, "video_files": [{"link": "https://pexels.mp4/2"}]},
        ],
    )
    mocker.patch(
        "clipper_agency.services.pexels.PexelsService.download_video",
        side_effect=lambda url, base_dir, filename: f"{base_dir}/{filename}",
    )
    mocker.patch(
        "clipper_agency.services.ytdlp.YtDlpService.download",
        return_value=None,
    )


class TestVisualDirectorArtifacts:
    """Visual Director writes input/output, scene_plan, provenance to agent dir."""

    def test_persists_input_json(self, tmp_path, mocker):
        _setup_mocks(mocker)
        agent = VisualDirectorAgent()
        agent.execute(
            job_id=20,
            script=SCENES,
            topic="Test",
            source_urls=[],
            assets_cache=str(tmp_path),
        )

        input_file = tmp_path / "job_20" / "agents" / "visual_director" / "input.json"
        assert input_file.exists()
        data = json.loads(input_file.read_text())
        assert data["job_id"] == 20
        assert data["scene_count"] == 2
        assert data["topic"] == "Test"

    def test_persists_scene_plan_json(self, tmp_path, mocker):
        _setup_mocks(mocker)
        agent = VisualDirectorAgent()
        agent.execute(
            job_id=21,
            script=SCENES,
            topic="Test",
            source_urls=[],
            assets_cache=str(tmp_path),
        )

        plan_file = tmp_path / "job_21" / "agents" / "visual_director" / "scene_plan.json"
        assert plan_file.exists()
        data = json.loads(plan_file.read_text())
        assert len(data) == 2
        assert all("scene" in item for item in data)

    def test_persists_output_json(self, tmp_path, mocker):
        _setup_mocks(mocker)
        agent = VisualDirectorAgent()
        agent.execute(
            job_id=22,
            script=SCENES,
            topic="Test",
            source_urls=[],
            assets_cache=str(tmp_path),
        )

        output_file = tmp_path / "job_22" / "agents" / "visual_director" / "output.json"
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["status"] == "completed"
        assert len(data["assets"]) == 2

    def test_persists_provenance_json(self, tmp_path, mocker):
        _setup_mocks(mocker)
        agent = VisualDirectorAgent()
        agent.execute(
            job_id=23,
            script=SCENES,
            topic="Test",
            source_urls=[],
            assets_cache=str(tmp_path),
        )

        prov_file = tmp_path / "job_23" / "agents" / "visual_director" / "provenance.json"
        assert prov_file.exists()
        data = json.loads(prov_file.read_text())
        assert data["topic"] == "Test"
        assert data["pexels_results"] >= 0

    def test_assets_use_agent_scenes_subdir(self, tmp_path, mocker):
        _setup_mocks(mocker)
        agent = VisualDirectorAgent()
        result = agent.execute(
            job_id=24,
            script=SCENES,
            topic="Test",
            source_urls=[],
            assets_cache=str(tmp_path),
        )

        scenes_dir = tmp_path / "job_24" / "agents" / "visual_director" / "scenes"
        assert scenes_dir.exists()
        for asset in result["assets"]:
            if asset["path"]:
                assert "scenes" in asset["path"]

    def test_no_assets_cache_uses_output_dir_fallback(self, tmp_path, mocker):
        """Without assets_cache, still works using output_dir (backward compat)."""
        _setup_mocks(mocker)
        agent = VisualDirectorAgent()
        result = agent.execute(
            job_id=25,
            script=SCENES,
            topic="Test",
            source_urls=[],
            output_dir=str(tmp_path / "outputs"),
        )
        assert result["status"] == "completed"
        assert len(result["assets"]) == 2


class TestTreatmentPassthrough:
    """LLM plan treatment/duration/transition fields pass through to assets."""

    def test_execute_plan_includes_treatment_metadata(self, mocker):
        """LLM plan with treatment/duration/transition fields should pass through to assets."""
        plan = [
            {
                "scene_number": 1,
                "action": {"type": "text_card", "headline": "Test", "image_search": "test", "style": "news_card"},
                "fallback": None,
                "treatment": "hook_big_caption",
                "target_duration": 3,
                "transition_in": "hard_cut",
                "transition_out": "crossfade",
            },
            {
                "scene_number": 2,
                "action": {"type": "pexels_image", "search_query": "concert"},
                "fallback": None,
                "treatment": "ken_burns_zoom_in",
                "target_duration": 5,
                "transition_in": "crossfade",
                "transition_out": "crossfade",
            },
        ]
        agent = VisualDirectorAgent()
        mocker.patch.object(agent, "_execute_action", side_effect=[
            {"source": "text_card", "path": "", "headline": "Test", "style": "news_card"},
            {"source": "pexels_image", "path": "/tmp/scene_2_img.jpg"},
        ])

        assets = agent._execute_plan(plan, "/tmp/scenes")

        assert assets[0]["treatment"] == "hook_big_caption"
        assert assets[0]["target_duration"] == 3
        assert assets[0]["transition_in"] == "hard_cut"
        assert assets[0]["transition_out"] == "crossfade"
        assert assets[1]["treatment"] == "ken_burns_zoom_in"
        assert assets[1]["target_duration"] == 5

    def test_execute_plan_no_treatment_fields_still_works(self, mocker):
        """Plan without treatment fields still produces valid assets (backward compat)."""
        plan = [
            {
                "scene_number": 1,
                "action": {"type": "pexels_video", "search_query": "test"},
                "fallback": None,
            },
        ]
        agent = VisualDirectorAgent()
        mocker.patch.object(agent, "_execute_action", return_value={
            "source": "pexels_video", "path": "/tmp/scene_1.mp4"
        })

        assets = agent._execute_plan(plan, "/tmp/scenes")

        assert assets[0]["scene"] == 1
        assert assets[0]["source"] == "pexels_video"
        # Should NOT have treatment fields (backward compat)
        assert "treatment" not in assets[0]
