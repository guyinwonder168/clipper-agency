"""Tests for Visual Director candidate inspection integration.

Validates _inspect_and_select_candidates, _do_inspect_and_select, and related
helpers with mocked multimodal client and deterministic fixtures.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.config.schema import (
    AssetCandidate,
    BeatFallback,
    StoryBeat,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _make_agent() -> VisualDirectorAgent:
    return VisualDirectorAgent()


def _make_candidate(
    ctype: str = "tiktok_clip",
    url: str = "https://example.com/clip1.mp4",
    reason: str = "test candidate",
) -> AssetCandidate:
    return AssetCandidate(type=ctype, url=url, reason=reason)


def _make_fallback(**overrides: Any) -> BeatFallback:
    defaults = {"type": "text_card", "headline": "Card", "image_search": ""}
    defaults.update(overrides)
    return BeatFallback(**defaults)


def _make_beat(
    beat_id: int = 1,
    role: str = "evidence",
    candidates: list[AssetCandidate] | None = None,
    **overrides: Any,
) -> StoryBeat:
    defaults = {
        "beat_id": beat_id,
        "role": role,
        "narration_goal": f"Beat {beat_id}",
        "spoken_point": f"Point {beat_id}",
        "safe_wording": f"Safe {beat_id}",
        "visual_must_show": f"Visual {beat_id}",
        "visual_must_not_show": "",
        "overlay_text": f"Overlay {beat_id}",
        "caption_keywords": [],
        "asset_candidates": candidates or [],
        "fallback": _make_fallback(headline=f"Card {beat_id}"),
        "risk_note": "",
    }
    defaults.update(overrides)
    return StoryBeat(**defaults)


def _make_plan_item(
    beat_id: int = 1,
    action: dict | None = None,
) -> dict:
    return {
        "scene_number": beat_id,
        "beat_id": beat_id,
        "role": "evidence",
        "treatment": "broll_standard",
        "action": action or {"type": "text_card", "headline": "Default"},
        "fallback": {"type": "text_card", "headline": "Fallback"},
    }


def _high_inspection() -> dict:
    return {
        "decision": "accept",
        "person_match": 0.9,
        "event_match": 0.85,
        "claim_support": 0.9,
        "visual_quality": 0.8,
        "misleading_risk": 0.1,
        "source_credibility": 0.8,
    }


def _low_inspection() -> dict:
    return {
        "decision": "reject",
        "person_match": 0.1,
        "event_match": 0.1,
        "claim_support": 0.2,
        "visual_quality": 0.2,
        "misleading_risk": 0.8,
        "source_credibility": 0.1,
    }


# ---------------------------------------------------------------------------
# 1. test_inspect_candidates_selects_best
# ---------------------------------------------------------------------------


class TestInspectCandidatesSelectsBest:
    """Candidate A scores high, B scores low -> A is selected."""

    @patch(
        "clipper_agency.agents.visual_director.lookup",
        return_value=None,
    )
    @patch(
        "clipper_agency.agents.visual_director.store",
    )
    @patch(
        "clipper_agency.llm.multimodal_client.MultimodalInspectionClient",
    )
    @patch(
        "clipper_agency.llm.client.OpenRouterClient",
    )
    def test_selects_high_scoring_candidate(
        self,
        mock_openrouter: MagicMock,
        mock_inspector_cls: MagicMock,
        mock_store: MagicMock,
        mock_lookup: MagicMock,
    ) -> None:
        agent = _make_agent()
        cand_a = _make_candidate("tiktok_clip", "https://a.com/clip1.mp4")
        cand_b = _make_candidate("tiktok_clip", "https://b.com/clip2.mp4")
        beat = _make_beat(candidates=[cand_a, cand_b])
        plan = [_make_plan_item()]

        mock_inspector = MagicMock()
        mock_inspector_cls.return_value = mock_inspector

        def _inspect_side_effect(**kwargs: Any) -> dict:
            asset_id = kwargs.get("asset_id", "")
            if "a.com" in asset_id:
                return _high_inspection()
            return _low_inspection()

        mock_inspector.inspect_asset.side_effect = _inspect_side_effect

        updated_plan, inspections = agent._do_inspect_and_select(
            plan, [beat], 1, "/tmp/agent_dir",
        )

        action = updated_plan[0]["action"]
        assert action["type"] == "tiktok_clip"
        assert "a.com" in action.get("source_url", "")
        assert len(inspections) == 2


# ---------------------------------------------------------------------------
# 2. test_inspect_candidates_fallback_when_all_rejected
# ---------------------------------------------------------------------------


class TestInspectCandidatesFallbackAllRejected:
    """All candidates rejected -> original action preserved."""

    @patch(
        "clipper_agency.agents.visual_director.lookup",
        return_value=None,
    )
    @patch(
        "clipper_agency.agents.visual_director.store",
    )
    def test_preserves_original_action(
        self,
        mock_store: MagicMock,
        mock_lookup: MagicMock,
    ) -> None:
        agent = _make_agent()
        cand = _make_candidate("tiktok_clip", "https://bad.com/clip.mp4")
        beat = _make_beat(candidates=[cand])
        original_action = {"type": "text_card", "headline": "Original"}
        plan = [_make_plan_item(action=original_action)]

        with patch.object(
            agent, "_run_multimodal_inspection", return_value=_low_inspection(),
        ):
            updated_plan, inspections = agent._do_inspect_and_select(
                plan, [beat], 1, "/tmp/agent_dir",
            )

        # Original action should remain since all candidates rejected
        assert updated_plan[0]["action"]["type"] == "text_card"
        assert updated_plan[0]["action"]["headline"] == "Original"
        assert len(inspections) == 1


# ---------------------------------------------------------------------------
# 3. test_inspect_candidates_skipped_on_error
# ---------------------------------------------------------------------------


class TestInspectCandidatesSkippedOnError:
    """Inspection raises exception -> plan unchanged, no crash."""

    def test_outer_catches_exception(self) -> None:
        agent = _make_agent()
        plan = [_make_plan_item()]
        beat = _make_beat(candidates=[_make_candidate()])

        with patch.object(
            agent,
            "_do_inspect_and_select",
            side_effect=RuntimeError("boom"),
        ):
            updated_plan, inspections = agent._inspect_and_select_candidates(
                plan, [beat], 1, "/tmp/agent_dir",
            )

        assert updated_plan is plan
        assert inspections == []


# ---------------------------------------------------------------------------
# 4. test_inspect_candidates_uses_cache
# ---------------------------------------------------------------------------


class TestInspectCandidatesUsesCache:
    """Second call with same cache key uses cached result."""

    def test_uses_cached_result(self, tmp_path: Any) -> None:
        agent = _make_agent()
        cand = _make_candidate("tiktok_clip", "https://cached.com/clip.mp4")
        beat = _make_beat(candidates=[cand])
        plan = [_make_plan_item()]

        # Pre-populate cache at the correct path (_do_inspect_and_select
        # computes cache_dir = agent_dir + "/inspection_cache")
        from clipper_agency.core.inspection_cache import compute_cache_key, store as cache_store

        agent_dir = str(tmp_path / "agent_dir")
        cache_dir = f"{agent_dir}/inspection_cache"
        cache_key = compute_cache_key(
            asset_path=cand.url,
            asset_hash="",
            beat_claim=beat.spoken_point,
            evidence_contract_hash="",
            model="multimodal",
            prompt_version="1.0",
        )
        cached_result = _high_inspection()
        cache_store(cache_dir, cache_key, cached_result)

        with patch.object(
            agent, "_run_multimodal_inspection", return_value=None,
        ) as mock_run:
            updated_plan, inspections = agent._do_inspect_and_select(
                plan, [beat], 1, agent_dir,
            )

        # Cache should have been used, _run_multimodal_inspection NOT called
        mock_run.assert_not_called()
        # The action should be updated with the high-scoring candidate
        action = updated_plan[0]["action"]
        assert action["type"] == "tiktok_clip"


# ---------------------------------------------------------------------------
# 5. test_inspect_candidates_empty_beats
# ---------------------------------------------------------------------------


class TestInspectCandidatesEmptyBeats:
    """No asset candidates -> plan unchanged."""

    def test_no_candidates_no_change(self) -> None:
        agent = _make_agent()
        beat = _make_beat(candidates=[])
        plan = [_make_plan_item()]
        original_action = dict(plan[0]["action"])

        updated_plan, inspections = agent._do_inspect_and_select(
            plan, [beat], 1, "/tmp/agent_dir",
        )

        assert updated_plan[0]["action"] == original_action
        assert inspections == []


# ---------------------------------------------------------------------------
# 6. test_output_includes_candidate_inspections
# ---------------------------------------------------------------------------


class TestOutputIncludesCandidateInspections:
    """execute() output dict includes candidate_inspections field."""

    def test_output_has_field(self) -> None:
        agent = _make_agent()

        with patch.object(
            agent, "_run_beat_driven_planning",
            return_value=([_make_plan_item()], []),
        ):
            output = agent.execute(
                job_id=1,
                story_beats=[{"beat_id": 1}],
                timestamps=[{"word": "test", "start": 0.0, "end": 0.5}],
            )

        assert "candidate_inspections" in output
        assert isinstance(output["candidate_inspections"], list)


# ---------------------------------------------------------------------------
# 7. test_inspection_not_called_when_no_candidates
# ---------------------------------------------------------------------------


class TestInspectionNotCalledWhenNoCandidates:
    """Multimodal client should NOT be called when beats have no candidates."""

    @patch(
        "clipper_agency.agents.visual_director.lookup",
        return_value=None,
    )
    def test_client_not_called(self, mock_lookup: MagicMock) -> None:
        agent = _make_agent()
        beat = _make_beat(candidates=[])
        plan = [_make_plan_item()]

        with patch.object(
            agent, "_run_multimodal_inspection",
        ) as mock_run:
            agent._do_inspect_and_select(
                plan, [beat], 1, "/tmp/agent_dir",
            )

        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 8. test_candidate_to_action_mappings
# ---------------------------------------------------------------------------


class TestCandidateToAction:
    """Verify _candidate_to_action produces correct action dicts."""

    def test_tiktok_clip_action(self) -> None:
        beat = _make_beat()
        cand = _make_candidate("tiktok_clip", "https://tiktok.com/clip1")
        action = VisualDirectorAgent._candidate_to_action(cand, beat)
        assert action["type"] == "tiktok_clip"
        assert action["source_url"] == "https://tiktok.com/clip1"

    def test_screenshot_action(self) -> None:
        beat = _make_beat()
        cand = _make_candidate("screenshot", "https://img.com/pic.jpg")
        action = VisualDirectorAgent._candidate_to_action(cand, beat)
        assert action["type"] == "pexels_image"
        assert action["source_url"] == "https://img.com/pic.jpg"

    def test_photo_action(self) -> None:
        beat = _make_beat()
        cand = _make_candidate("photo", "https://photos.com/img.jpg")
        action = VisualDirectorAgent._candidate_to_action(cand, beat)
        assert action["type"] == "pexels_image"

    def test_unknown_type_text_card(self) -> None:
        beat = _make_beat(overlay_text="Some Headline")
        cand = _make_candidate("unknown_type", "")
        action = VisualDirectorAgent._candidate_to_action(cand, beat)
        assert action["type"] == "text_card"


# ---------------------------------------------------------------------------
# 9. test_execute_initializes_candidate_inspections
# ---------------------------------------------------------------------------


class TestExecuteInitializesInspections:
    """_candidate_inspections is initialized at start of execute()."""

    def test_initialized_empty(self) -> None:
        agent = _make_agent()
        # Simulate a previous run that left stale data
        agent._candidate_inspections = [{"stale": True}]

        with patch.object(
            agent, "_run_beat_driven_planning",
            return_value=([_make_plan_item()], []),
        ):
            output = agent.execute(
                job_id=1,
                story_beats=[{"beat_id": 1}],
                timestamps=[{"word": "test", "start": 0.0, "end": 0.5}],
            )

        # After execute, _candidate_inspections should be fresh
        assert output.get("candidate_inspections") == []


# ---------------------------------------------------------------------------
# 10. test_extract_candidate_frames_image_type
# ---------------------------------------------------------------------------


class TestExtractCandidateFramesImageType:
    """_extract_candidate_frames downloads image and returns local path."""

    def test_downloads_photo(self, tmp_path: Any) -> None:
        agent = _make_agent()
        cand = _make_candidate("photo", "https://example.com/photo.jpg")
        agent_dir = str(tmp_path / "agent_dir")

        with patch.object(agent, "_download_image_frame", return_value=["/fake/path.jpg"]):
            paths = agent._extract_candidate_frames(cand, agent_dir)

        assert paths == ["/fake/path.jpg"]

    def test_downloads_screenshot(self, tmp_path: Any) -> None:
        agent = _make_agent()
        cand = _make_candidate("screenshot", "https://example.com/screen.png")
        agent_dir = str(tmp_path / "agent_dir")

        with patch.object(agent, "_download_image_frame", return_value=["/fake/screen.png"]):
            paths = agent._extract_candidate_frames(cand, agent_dir)

        assert paths == ["/fake/screen.png"]


# ---------------------------------------------------------------------------
# 11. test_extract_candidate_frames_video_type
# ---------------------------------------------------------------------------


class TestExtractCandidateFramesVideoType:
    """_extract_candidate_frames downloads video and extracts frame."""

    def test_downloads_and_extracts(self, tmp_path: Any) -> None:
        agent = _make_agent()
        cand = _make_candidate("tiktok_clip", "https://tiktok.com/clip1")
        agent_dir = str(tmp_path / "agent_dir")

        with patch.object(agent, "_download_video_frame", return_value=["/fake/frame.jpg"]):
            paths = agent._extract_candidate_frames(cand, agent_dir)

        assert paths == ["/fake/frame.jpg"]


# ---------------------------------------------------------------------------
# 12. test_extract_candidate_frames_text_types
# ---------------------------------------------------------------------------


class TestExtractCandidateFramesTextTypes:
    """_extract_candidate_frames returns empty for text types."""

    def test_text_card(self) -> None:
        agent = _make_agent()
        cand = _make_candidate("text_card", "")
        paths = agent._extract_candidate_frames(cand, "/tmp/agent_dir")
        assert paths == []

    def test_text_overlay(self) -> None:
        agent = _make_agent()
        cand = _make_candidate("text_overlay", "")
        paths = agent._extract_candidate_frames(cand, "/tmp/agent_dir")
        assert paths == []


# ---------------------------------------------------------------------------
# 13. test_extract_candidate_frames_no_agent_dir
# ---------------------------------------------------------------------------


class TestExtractCandidateFramesNoAgentDir:
    """Returns empty when agent_dir is empty (graceful degradation)."""

    def test_empty_agent_dir(self) -> None:
        agent = _make_agent()
        cand = _make_candidate("photo", "https://example.com/photo.jpg")
        paths = agent._extract_candidate_frames(cand, "")
        assert paths == []


# ---------------------------------------------------------------------------
# 14. test_download_image_frame_success
# ---------------------------------------------------------------------------


class TestDownloadImageFrameSuccess:
    """_download_image_frame downloads and saves image."""

    def test_downloads_image(self, tmp_path: Any) -> None:
        import httpx

        agent = _make_agent()
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24  # minimal PNG-ish data

        with patch("httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = fake_image
            mock_resp.raise_for_status = MagicMock()
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            paths = agent._download_image_frame(
                "https://example.com/photo.jpg", frames_dir,
            )

        assert len(paths) == 1
        assert paths[0].endswith(".jpg")
        from pathlib import Path as P
        assert P(paths[0]).parent == frames_dir


# ---------------------------------------------------------------------------
# 15. test_download_image_frame_error_returns_empty
# ---------------------------------------------------------------------------


class TestDownloadImageFrameError:
    """_download_image_frame returns [] on download error."""

    def test_http_error(self, tmp_path: Any) -> None:
        agent = _make_agent()
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = Exception("network error")
            mock_client_cls.return_value = mock_client

            paths = agent._download_image_frame(
                "https://bad.com/photo.jpg", frames_dir,
            )

        assert paths == []


# ---------------------------------------------------------------------------
# 16. test_run_multimodal_inspection_uses_frame_paths
# ---------------------------------------------------------------------------


class TestRunMultimodalInspectionUsesFramePaths:
    """_run_multimodal_inspection passes frame_paths from helper."""

    @patch(
        "clipper_agency.agents.visual_director.store",
    )
    def test_photo_gets_frames(self, mock_store: MagicMock) -> None:
        agent = _make_agent()
        cand = _make_candidate("photo", "https://example.com/img.jpg")
        beat = _make_beat()
        plan_item = _make_plan_item()

        with patch.object(
            agent, "_extract_candidate_frames", return_value=["/fake/frame.jpg"],
        ), patch(
            "clipper_agency.llm.multimodal_client.MultimodalInspectionClient",
        ) as mock_cls, patch(
            "clipper_agency.llm.client.OpenRouterClient",
        ):
            mock_inspector = MagicMock()
            mock_inspector.inspect_asset.return_value = _high_inspection()
            mock_cls.return_value = mock_inspector

            agent._run_multimodal_inspection(
                cand, beat, plan_item, 1, "/tmp/cache", "key", agent_dir="/tmp/agent",
            )

        call_kwargs = mock_inspector.inspect_asset.call_args
        assert call_kwargs.kwargs.get("frame_paths") == ["/fake/frame.jpg"]
