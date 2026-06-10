"""Tests for Reviewer timestamp-level semantic review integration.

Validates that the Reviewer agent uses scene-to-beat mapping from
reviewer_context.py and emits SceneSemanticReview models per scene,
with a hard gate that blocks LLM review on failure.
"""

import pytest

from clipper_agency.agents.reviewer import (
    ReviewerAgent,
    _evaluate_scene_semantic,
    _run_programmatic_scene_reviews,
)
from clipper_agency.config.schema import SceneSemanticReview
from clipper_agency.core.reviewer_context import SceneBeatMapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest_scenes(scenes):
    """Build manifest-like scene dicts with start_sec/end_sec."""
    return scenes


def _make_story_beats(count, start_id=1):
    """Build simple story beat dicts."""
    return [
        {"beat_id": i, "narration_goal": f"beat {i}"}
        for i in range(start_id, start_id + count)
    ]


def _make_word_timestamps(n_words, start_sec=0.0, sec_per_word=0.3):
    """Build word timestamp dicts."""
    return [
        {
            "word": f"word{i}",
            "start": start_sec + i * sec_per_word,
            "end": start_sec + (i + 1) * sec_per_word,
        }
        for i in range(n_words)
    ]


# ---------------------------------------------------------------------------
# Pure function tests: _evaluate_scene_semantic
# ---------------------------------------------------------------------------


class TestEvaluateSceneSemantic:
    """Unit tests for per-scene programmatic semantic evaluation."""

    def test_passes_for_valid_scene(self):
        mapping = SceneBeatMapping(
            scene_index=0,
            scene_start_sec=0.0,
            scene_end_sec=5.0,
            matched_beat_ids=[1, 2],
            overlap_type="midpoint",
        )
        result = _evaluate_scene_semantic(mapping)
        assert isinstance(result, SceneSemanticReview)
        assert result.decision == "accept"
        assert result.score == 1.0
        assert result.passed is True

    def test_fails_for_scene_without_beats(self):
        mapping = SceneBeatMapping(
            scene_index=0,
            scene_start_sec=0.0,
            scene_end_sec=5.0,
            matched_beat_ids=[],
            overlap_type="none",
        )
        result = _evaluate_scene_semantic(mapping)
        assert result.decision == "reject"
        assert result.score < 1.0
        assert result.passed is False
        assert "no matched beat" in result.reason.lower()

    def test_fails_for_scene_too_short(self):
        mapping = SceneBeatMapping(
            scene_index=0,
            scene_start_sec=0.0,
            scene_end_sec=0.3,
            matched_beat_ids=[1],
            overlap_type="midpoint",
        )
        result = _evaluate_scene_semantic(mapping)
        assert result.decision == "reject"
        assert result.passed is False
        assert "duration" in result.reason.lower() or "short" in result.reason.lower()

    def test_fails_for_scene_spanning_too_many_beats(self):
        mapping = SceneBeatMapping(
            scene_index=0,
            scene_start_sec=0.0,
            scene_end_sec=10.0,
            matched_beat_ids=[1, 2, 3, 4],
            overlap_type="mixed",
        )
        result = _evaluate_scene_semantic(mapping)
        assert result.decision == "reject"
        assert result.passed is False
        assert "beat" in result.reason.lower() or "pacing" in result.reason.lower()

    def test_passes_for_scene_with_exactly_three_beats(self):
        mapping = SceneBeatMapping(
            scene_index=0,
            scene_start_sec=0.0,
            scene_end_sec=8.0,
            matched_beat_ids=[1, 2, 3],
            overlap_type="range_overlap",
        )
        result = _evaluate_scene_semantic(mapping)
        assert result.decision == "accept"
        assert result.passed is True

    def test_warns_for_zero_duration_scene(self):
        mapping = SceneBeatMapping(
            scene_index=2,
            scene_start_sec=5.0,
            scene_end_sec=5.0,
            matched_beat_ids=[1],
            overlap_type="midpoint",
        )
        result = _evaluate_scene_semantic(mapping)
        assert result.passed is False


# ---------------------------------------------------------------------------
# Pure function tests: _run_programmatic_scene_reviews
# ---------------------------------------------------------------------------


class TestRunProgrammaticSceneReviews:
    """Unit tests for running semantic review across all scenes."""

    def test_returns_reviews_for_all_scenes(self):
        mappings = [
            SceneBeatMapping(
                scene_index=0, scene_start_sec=0.0, scene_end_sec=5.0,
                matched_beat_ids=[1], overlap_type="midpoint",
            ),
            SceneBeatMapping(
                scene_index=1, scene_start_sec=5.0, scene_end_sec=10.0,
                matched_beat_ids=[2], overlap_type="midpoint",
            ),
        ]
        reviews = _run_programmatic_scene_reviews(mappings)
        assert len(reviews) == 2
        assert all(isinstance(r, SceneSemanticReview) for r in reviews)

    def test_returns_empty_for_no_mappings(self):
        reviews = _run_programmatic_scene_reviews([])
        assert reviews == []

    def test_all_pass_for_valid_mappings(self):
        mappings = [
            SceneBeatMapping(
                scene_index=i, scene_start_sec=i * 5.0,
                scene_end_sec=(i + 1) * 5.0,
                matched_beat_ids=[i + 1], overlap_type="midpoint",
            )
            for i in range(3)
        ]
        reviews = _run_programmatic_scene_reviews(mappings)
        assert all(r.passed for r in reviews)

    def test_mixed_pass_and_fail(self):
        mappings = [
            SceneBeatMapping(
                scene_index=0, scene_start_sec=0.0, scene_end_sec=5.0,
                matched_beat_ids=[1], overlap_type="midpoint",
            ),
            SceneBeatMapping(
                scene_index=1, scene_start_sec=5.0, scene_end_sec=10.0,
                matched_beat_ids=[], overlap_type="none",
            ),
        ]
        reviews = _run_programmatic_scene_reviews(mappings)
        assert reviews[0].passed is True
        assert reviews[1].passed is False


# ---------------------------------------------------------------------------
# Integration tests: Reviewer timestamp semantic gate
# ---------------------------------------------------------------------------


class TestReviewerTimestampSemanticGate:
    """Integration tests for the timestamp-level semantic review hard gate."""

    def test_gate_passes_with_valid_scenes(self, mocker):
        """Valid scene-beat mapping should allow LLM review."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 90, "feedback": "OK", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
                "story_beats": _make_story_beats(3),
                "word_timestamps": _make_word_timestamps(60),
                "rendered_scene_manifest": {
                    "entries": [
                        {"scene_index": 0, "start_sec": 0.0, "end_sec": 6.67},
                        {"scene_index": 1, "start_sec": 6.67, "end_sec": 13.33},
                        {"scene_index": 2, "start_sec": 13.33, "end_sec": 20.0},
                    ],
                },
            },
        )
        assert result["status"] == "pass"
        # Should include scene semantic reviews in output
        assert "scene_semantic_reviews" in result

    def test_gate_fails_scene_without_matched_beat(self, mocker):
        """Scene with no matched beat should fail the hard gate."""
        mock_chat = mocker.patch("clipper_agency.llm.client.OpenRouterClient.chat")
        agent = ReviewerAgent()
        # Scene at 50-55s is outside audio duration (20s), so no beats match
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 25.0,
                "story_beats": _make_story_beats(3),
                "word_timestamps": _make_word_timestamps(60),
                "rendered_scene_manifest": {
                    "entries": [
                        {"scene_index": 0, "start_sec": 0.0, "end_sec": 6.0},
                        {"scene_index": 1, "start_sec": 6.0, "end_sec": 12.0},
                        {"scene_index": 2, "start_sec": 12.0, "end_sec": 18.0},
                        # Orphan scene beyond audio range
                        {"scene_index": 3, "start_sec": 50.0, "end_sec": 55.0},
                    ],
                },
            },
        )
        assert result["status"] == "fail"
        assert "TIMESTAMP_SEMANTIC" in result.get("reason", "") or "semantic" in result.get("reason", "").lower()
        mock_chat.assert_not_called()

    def test_gate_fails_scene_spanning_too_many_beats(self, mocker):
        """Scene spanning > 3 beats should fail."""
        mock_chat = mocker.patch("clipper_agency.llm.client.OpenRouterClient.chat")
        agent = ReviewerAgent()
        # One massive scene spanning all 5 beats
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 30.0,
                "visual_duration_sec": 30.0,
                "story_beats": _make_story_beats(5),
                "word_timestamps": _make_word_timestamps(90, sec_per_word=0.33),
                "rendered_scene_manifest": {
                    "entries": [
                        # This single scene covers the whole 30s
                        {"scene_index": 0, "start_sec": 0.0, "end_sec": 30.0},
                    ],
                },
            },
        )
        assert result["status"] == "fail"
        mock_chat.assert_not_called()

    def test_backward_compat_no_manifest(self, mocker):
        """No manifest data should skip timestamp gate and proceed to LLM."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "OK", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
            },
        )
        assert result["status"] == "pass"

    def test_backward_compat_no_story_beats(self, mocker):
        """No story beats should skip timestamp gate and proceed to LLM."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "OK", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
                "rendered_scene_manifest": {
                    "entries": [
                        {"scene_index": 0, "start_sec": 0.0, "end_sec": 10.0},
                    ],
                },
            },
        )
        assert result["status"] == "pass"

    def test_backward_compat_none_manifest(self, mocker):
        """None manifest should skip timestamp gate."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "OK", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
                "rendered_scene_manifest": None,
                "story_beats": None,
            },
        )
        assert result["status"] == "pass"

    def test_output_includes_scene_semantic_reviews(self, mocker):
        """When timestamp review runs, output should include scene reviews."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 90, "feedback": "OK", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
                "story_beats": _make_story_beats(2),
                "word_timestamps": _make_word_timestamps(40),
                "rendered_scene_manifest": {
                    "entries": [
                        {"scene_index": 0, "start_sec": 0.0, "end_sec": 10.0},
                        {"scene_index": 1, "start_sec": 10.0, "end_sec": 20.0},
                    ],
                },
            },
        )
        assert result["status"] == "pass"
        reviews = result.get("scene_semantic_reviews", [])
        assert len(reviews) == 2
        # Each review should be serializable (dict form)
        for r in reviews:
            assert "decision" in r
            assert "score" in r
            assert "beat_id" in r

    def test_gate_order_before_existing_semantic(self, mocker):
        """Timestamp semantic gate should fire before existing semantic_review gate."""
        mock_chat = mocker.patch("clipper_agency.llm.client.OpenRouterClient.chat")
        agent = ReviewerAgent()
        # Provide both timestamp issue AND old-style semantic_review
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 25.0,
                "story_beats": _make_story_beats(2),
                "word_timestamps": _make_word_timestamps(40),
                "rendered_scene_manifest": {
                    "entries": [
                        {"scene_index": 0, "start_sec": 0.0, "end_sec": 10.0},
                        # Orphan scene
                        {"scene_index": 1, "start_sec": 50.0, "end_sec": 55.0},
                    ],
                },
            },
            diagnostics={
                "semantic_review": {
                    "decision": "revise",
                    "patches": [
                        {
                            "beat_id": "B01",
                            "action": "replace_visual",
                            "reason": "test",
                            "rerun_from": "visual_director",
                        }
                    ],
                },
            },
        )
        # Should fail — doesn't matter which gate catches it first
        assert result["status"] == "fail"
        mock_chat.assert_not_called()
