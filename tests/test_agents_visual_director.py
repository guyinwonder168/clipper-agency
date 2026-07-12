"""Tests for Visual Director agent — OCR/face wiring (Worker B) + source cleanliness (Worker C)."""

from __future__ import annotations

from unittest.mock import MagicMock

from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.config.schema import StoryBeat

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(url: str = "https://example.com/vid1.mp4", ctype: str = "tiktok_clip"):
    """Create a minimal AssetCandidate-like object."""
    c = MagicMock()
    c.url = url
    c.type = ctype
    c.source = "pexels"
    c.reason = "test"
    return c


def _make_beat(beat_id: int = 1, spoken_point: str = "Test point") -> StoryBeat:
    return StoryBeat(
        beat_id=beat_id,
        role="evidence",
        narration_goal="Test narration goal",
        spoken_point=spoken_point,
        safe_wording=spoken_point,
        visual_must_show="anything",
        visual_must_not_show="",
        overlay_text="Test",
        caption_keywords=["test"],
        asset_candidates=[],
        fallback={"type": "text_card", "headline": "Test", "image_search": "test"},
    )


def _make_agent() -> VisualDirectorAgent:
    agent = VisualDirectorAgent()
    # Initialize the metrics dict that execute() normally sets
    agent._inspection_metrics = {}
    agent._runtime_inspection_enabled = False  # disable enhanced pipeline in unit tests
    return agent


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestSourceCleanlinessWiring:
    """Worker C — source cleanliness scoring affects candidate ranking."""

    def test_cleanliness_score_computed_from_ocr_metrics(self, mocker):
        """score_source_cleanliness must be called with actual OCR metrics when available."""

        agent = _make_agent()
        candidate = _make_candidate(url="https://example.com/clean.mp4")
        beat = _make_beat()

        # Simulate metrics stored by Worker A/B
        agent._inspection_metrics["https://example.com/clean.mp4"] = {
            "ocr_text_area_ratio": 0.25,
            "has_logo": True,
            "logo_coverage_ratio": 0.05,
            "safe_crop_available": True,
            "face_obstructed": False,
            "resolution": (1920, 1080),
            "has_burned_captions": False,
        }

        inspection = {"visual_quality": 0.7, "decision": "accept"}

        mock_cleanliness = mocker.patch(
            "clipper_agency.core.source_cleanliness.score_source_cleanliness",
            return_value={
                "cleanliness_score": 0.65,
                "issues": ["BURNED_CAPTION"],
                "fullscreen_allowed": True,
                "allowed_treatments": ["picture_in_picture", "fullscreen"],
            },
        )

        result = agent._compute_cleanliness_score(candidate, inspection)

        mock_cleanliness.assert_called_once_with(
            ocr_text_area_ratio=0.25,
            has_logo=True,
            logo_coverage_ratio=0.05,
            safe_crop_available=True,
            face_obstructed=False,
            resolution=(1920, 1080),
            has_burned_captions=False,
        )
        assert result == 0.65

    def test_clean_score_affects_ranking(self, mocker):
        """Dirty sources (burned captions) should rank lower than clean sources."""

        # We test this through the ranker integration:
        # A candidate with low cleanliness should get a lower final score
        from clipper_agency.core.candidate_semantic_ranker import compute_final_score

        insp = {
            "person_match": 0.8,
            "event_match": 0.8,
            "claim_support": 0.8,
            "visual_quality": 0.8,
        }
        rel = {"person_match": 0.8, "event_match": 0.8, "claim_support": 0.8, "visual_quality": 0.8}

        clean_score = compute_final_score(insp, rel, cleanliness_score=1.0)
        dirty_score = compute_final_score(insp, rel, cleanliness_score=0.3)

        assert dirty_score < clean_score

    def test_cleanliness_fallback_when_no_metrics(self, mocker):
        """When OCR/face disabled, cleanliness falls back to visual_quality from inspection."""

        agent = _make_agent()
        # No metrics stored — empty dict
        candidate = _make_candidate(url="https://example.com/nometric.mp4")
        inspection = {"visual_quality": 0.6, "decision": "accept"}

        mock_cleanliness = mocker.patch(
            "clipper_agency.core.source_cleanliness.score_source_cleanliness",
        )

        result = agent._compute_cleanliness_score(candidate, inspection)

        # Should NOT call score_source_cleanliness — no metrics available
        mock_cleanliness.assert_not_called()
        # Should fall back to inspection's visual_quality
        assert result == 0.6

    def test_cleanliness_failure_is_graceful(self, mocker):
        """score_source_cleanliness exception must not crash — falls back to default."""

        agent = _make_agent()
        candidate = _make_candidate(url="https://example.com/fail.mp4")
        inspection = {"visual_quality": 0.5, "decision": "accept"}

        # Simulate metrics present but score_source_cleanliness raises
        agent._inspection_metrics["https://example.com/fail.mp4"] = {
            "ocr_text_area_ratio": 0.1,
        }

        mocker.patch(
            "clipper_agency.core.source_cleanliness.score_source_cleanliness",
            side_effect=ValueError("boom"),
        )

        result = agent._compute_cleanliness_score(candidate, inspection)

        # Must not raise — falls back to visual_quality
        assert result == 0.5

    def test_score_one_candidate_uses_cleanliness(self, mocker):
        """_score_one_candidate must put _compute_cleanliness_score result in scored dict."""

        agent = _make_agent()
        candidate = _make_candidate()
        beat = _make_beat()

        # Mock everything _score_one_candidate calls
        mocker.patch(
            "clipper_agency.agents.visual_director.compute_candidate_cache_key",
            return_value="key1",
        )
        mocker.patch(
            "clipper_agency.agents.visual_director.lookup",
            return_value=None,
        )
        mocker.patch.object(
            agent,
            "_run_multimodal_inspection",
            return_value={"visual_quality": 0.7, "decision": "accept"},
        )
        mocker.patch(
            "clipper_agency.agents.visual_director.score_visual_relevance",
        )
        # Make score_visual_relevance return something with attributes
        mock_rel = MagicMock()
        mock_rel.person_match = 0.8
        mock_rel.event_match = 0.8
        mock_rel.claim_support = 0.8
        mock_rel.visual_quality = 0.8
        mocker.patch(
            "clipper_agency.agents.visual_director.score_visual_relevance",
            return_value=mock_rel,
        )

        # Mock _compute_cleanliness_score to return a specific value
        mocker.patch.object(
            agent,
            "_compute_cleanliness_score",
            return_value=0.42,
        )

        result = agent._score_one_candidate(
            candidate,
            beat,
            plan_item={"treatment": "fullscreen"},
            job_id=1,
            cache_dir="/tmp/cache",
        )

        assert result is not None
        assert result["cleanliness_score"] == 0.42


class TestVisualDirectorLLMTracing:
    """Batch 4 — LLM trace wiring for VisualDirectorAgent planning calls."""

    def test_plan_with_llm_uses_traced_chat_when_writer_configured(self, mocker):
        writer = object()
        mock_traced = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat_traced",
            return_value={
                "content": '{"scenes": [{"scene_number": 1}]}',
                "model": "test",
                "usage": {},
            },
        )

        result = VisualDirectorAgent(trace_writer=writer)._plan_with_llm(
            scenes=[],
            compact_data={},
            job_id=15,
        )

        assert result == [{"scene_number": 1}]
        mock_traced.assert_called_once()
        assert mock_traced.call_args.kwargs["job_id"] == 15
        assert mock_traced.call_args.kwargs["agent"] == "visual_director"
        assert mock_traced.call_args.kwargs["task"] == "plan_scenes"

    def test_plan_with_llm_uses_plain_chat_when_writer_is_none(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"scenes": [{"scene_number": 1}]}',
                "model": "test",
                "usage": {},
            },
        )
        mock_traced = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat_traced",
        )

        result = VisualDirectorAgent(trace_writer=None)._plan_with_llm(
            scenes=[],
            compact_data={},
            job_id=16,
        )

        assert result == [{"scene_number": 1}]
        mock_chat.assert_called_once()
        mock_traced.assert_not_called()


# ---------------------------------------------------------------------------
# Worker B — OCR and face detection wiring
# ---------------------------------------------------------------------------


class TestOCRandFaceWiring:
    """Worker B — OCR and face detection run on extracted keyframes."""

    def test_ocr_runs_on_extracted_keyframes(self, mocker, tmp_path):
        """PaddleOCRAdapter.inspect must be called for each frame when ocr.enabled."""
        agent = _make_agent()
        candidate = _make_candidate(url="https://example.com/vid1.mp4")
        beat = _make_beat()

        # Mock frame extraction to return 2 frames
        mocker.patch.object(
            agent,
            "_extract_candidate_frames",
            return_value=["/tmp/frame1.jpg", "/tmp/frame2.jpg"],
        )

        # Mock OCR adapter — returns text regions
        mock_ocr_result = MagicMock()
        mock_ocr_result.regions = [MagicMock(text="Hello"), MagicMock(text="World")]
        mock_ocr_cls = mocker.patch(
            "clipper_agency.core.ocr_adapter.PaddleOCRAdapter",
        )
        mock_ocr_instance = mock_ocr_cls.return_value
        mock_ocr_instance.inspect.return_value = mock_ocr_result

        # Mock face detection as disabled
        mocker.patch(
            "clipper_agency.agents.visual_director._is_face_enabled",
            return_value=False,
        )

        # Mock multimodal client
        mock_inspector = mocker.patch(
            "clipper_agency.llm.multimodal_client.MultimodalInspectionClient",
        )
        mock_inspector.return_value.inspect_asset.return_value = {
            "decision": "accept",
            "visual_quality": 0.8,
        }
        mocker.patch("clipper_agency.llm.client.OpenRouterClient")
        mocker.patch("clipper_agency.agents.visual_director.store")

        # Mock config to enable OCR
        mocker.patch(
            "clipper_agency.agents.visual_director._is_ocr_enabled",
            return_value=True,
        )

        agent._run_multimodal_inspection(
            candidate,
            beat,
            1,
            "/tmp/cache",
            "key",
            agent_dir="/tmp/agent",
        )

        # PaddleOCRAdapter.inspect called twice — once per frame
        assert mock_ocr_instance.inspect.call_count == 2

        # inspect_asset called with aggregated ocr_text
        call_kwargs = mock_inspector.return_value.inspect_asset.call_args.kwargs
        assert call_kwargs["ocr_text"] == "Hello World Hello World"

    def test_face_detection_runs_when_enabled(self, mocker, tmp_path):
        """MediaPipeFaceDetector.detect must be called when face_detection.enabled."""
        agent = _make_agent()
        candidate = _make_candidate(url="https://example.com/vid1.mp4")
        beat = _make_beat()

        mocker.patch.object(
            agent,
            "_extract_candidate_frames",
            return_value=["/tmp/frame1.jpg"],
        )

        # Mock face detector
        mock_face_result = MagicMock()
        mock_face_result.faces = [MagicMock(bbox=[10, 20, 100, 200], confidence=0.95)]
        mock_face_cls = mocker.patch(
            "clipper_agency.core.face_adapter.MediaPipeFaceDetector",
        )
        mock_face_instance = mock_face_cls.return_value
        mock_face_instance.detect.return_value = mock_face_result

        # Mock OCR as disabled
        mocker.patch(
            "clipper_agency.agents.visual_director._is_ocr_enabled",
            return_value=False,
        )

        mocker.patch(
            "clipper_agency.agents.visual_director._is_face_enabled",
            return_value=True,
        )

        # Mock multimodal client
        mocker.patch(
            "clipper_agency.llm.multimodal_client.MultimodalInspectionClient",
        ).return_value.inspect_asset.return_value = {
            "decision": "accept",
            "visual_quality": 0.8,
        }
        mocker.patch("clipper_agency.llm.client.OpenRouterClient")
        mocker.patch("clipper_agency.agents.visual_director.store")

        agent._face_data = {}
        agent._run_multimodal_inspection(
            candidate,
            beat,
            1,
            "/tmp/cache",
            "key",
            agent_dir="/tmp/agent",
        )

        # MediaPipeFaceDetector.detect called once
        mock_face_instance.detect.assert_called_once_with("/tmp/frame1.jpg", 0.0)

        # Face data stored on agent
        assert "https://example.com/vid1.mp4" in agent._face_data

    def test_ocr_skipped_when_disabled(self, mocker, tmp_path):
        """PaddleOCRAdapter must NOT be created when ocr.enabled=False."""
        agent = _make_agent()
        candidate = _make_candidate(url="https://example.com/vid1.mp4")
        beat = _make_beat()

        mocker.patch.object(
            agent,
            "_extract_candidate_frames",
            return_value=["/tmp/frame1.jpg"],
        )

        mocker.patch(
            "clipper_agency.agents.visual_director._is_ocr_enabled",
            return_value=False,
        )
        mocker.patch(
            "clipper_agency.agents.visual_director._is_face_enabled",
            return_value=False,
        )

        mock_ocr_cls = mocker.patch(
            "clipper_agency.core.ocr_adapter.PaddleOCRAdapter",
        )

        mocker.patch(
            "clipper_agency.llm.multimodal_client.MultimodalInspectionClient",
        ).return_value.inspect_asset.return_value = {
            "decision": "accept",
            "visual_quality": 0.8,
        }
        mocker.patch("clipper_agency.llm.client.OpenRouterClient")
        mocker.patch("clipper_agency.agents.visual_director.store")

        agent._run_multimodal_inspection(
            candidate,
            beat,
            1,
            "/tmp/cache",
            "key",
            agent_dir="/tmp/agent",
        )

        mock_ocr_cls.assert_not_called()

    def test_face_skipped_when_disabled(self, mocker, tmp_path):
        """MediaPipeFaceDetector must NOT be created when face_detection.enabled=False."""
        agent = _make_agent()
        candidate = _make_candidate(url="https://example.com/vid1.mp4")
        beat = _make_beat()

        mocker.patch.object(
            agent,
            "_extract_candidate_frames",
            return_value=["/tmp/frame1.jpg"],
        )

        mocker.patch(
            "clipper_agency.agents.visual_director._is_ocr_enabled",
            return_value=False,
        )
        mocker.patch(
            "clipper_agency.agents.visual_director._is_face_enabled",
            return_value=False,
        )

        mock_face_cls = mocker.patch(
            "clipper_agency.core.face_adapter.MediaPipeFaceDetector",
        )

        mocker.patch(
            "clipper_agency.llm.multimodal_client.MultimodalInspectionClient",
        ).return_value.inspect_asset.return_value = {
            "decision": "accept",
            "visual_quality": 0.8,
        }
        mocker.patch("clipper_agency.llm.client.OpenRouterClient")
        mocker.patch("clipper_agency.agents.visual_director.store")

        agent._run_multimodal_inspection(
            candidate,
            beat,
            1,
            "/tmp/cache",
            "key",
            agent_dir="/tmp/agent",
        )

        mock_face_cls.assert_not_called()

    def test_ocr_failure_is_graceful(self, mocker, tmp_path):
        """OCR exception must not crash — ocr_text falls back to empty string."""
        agent = _make_agent()
        candidate = _make_candidate(url="https://example.com/vid1.mp4")
        beat = _make_beat()

        mocker.patch.object(
            agent,
            "_extract_candidate_frames",
            return_value=["/tmp/frame1.jpg"],
        )

        mocker.patch(
            "clipper_agency.agents.visual_director._is_ocr_enabled",
            return_value=True,
        )
        mocker.patch(
            "clipper_agency.agents.visual_director._is_face_enabled",
            return_value=False,
        )

        # OCR adapter raises
        mock_ocr_cls = mocker.patch(
            "clipper_agency.core.ocr_adapter.PaddleOCRAdapter",
        )
        mock_ocr_cls.return_value.inspect.side_effect = RuntimeError("OCR crash")

        mock_inspect_asset = mocker.patch(
            "clipper_agency.llm.multimodal_client.MultimodalInspectionClient",
        ).return_value.inspect_asset
        mock_inspect_asset.return_value = {
            "decision": "accept",
            "visual_quality": 0.8,
        }
        mocker.patch("clipper_agency.llm.client.OpenRouterClient")
        mocker.patch("clipper_agency.agents.visual_director.store")

        result = agent._run_multimodal_inspection(
            candidate,
            beat,
            1,
            "/tmp/cache",
            "key",
            agent_dir="/tmp/agent",
        )

        # Must not crash — returns result with empty ocr_text
        assert result is not None
        call_kwargs = mock_inspect_asset.call_args.kwargs
        assert call_kwargs["ocr_text"] == ""
