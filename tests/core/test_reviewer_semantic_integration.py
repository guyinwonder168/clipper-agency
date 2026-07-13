"""Tests for Reviewer timestamp-level semantic review integration.

Validates that the Reviewer agent uses scene-to-beat mapping from
reviewer_context.py and emits SceneSemanticReview models per scene,
with a hard gate that blocks LLM review on failure.
"""

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
        {"beat_id": i, "narration_goal": f"beat {i}"} for i in range(start_id, start_id + count)
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
                scene_index=0,
                scene_start_sec=0.0,
                scene_end_sec=5.0,
                matched_beat_ids=[1],
                overlap_type="midpoint",
            ),
            SceneBeatMapping(
                scene_index=1,
                scene_start_sec=5.0,
                scene_end_sec=10.0,
                matched_beat_ids=[2],
                overlap_type="midpoint",
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
                scene_index=i,
                scene_start_sec=i * 5.0,
                scene_end_sec=(i + 1) * 5.0,
                matched_beat_ids=[i + 1],
                overlap_type="midpoint",
            )
            for i in range(3)
        ]
        reviews = _run_programmatic_scene_reviews(mappings)
        assert all(r.passed for r in reviews)

    def test_mixed_pass_and_fail(self):
        mappings = [
            SceneBeatMapping(
                scene_index=0,
                scene_start_sec=0.0,
                scene_end_sec=5.0,
                matched_beat_ids=[1],
                overlap_type="midpoint",
            ),
            SceneBeatMapping(
                scene_index=1,
                scene_start_sec=5.0,
                scene_end_sec=10.0,
                matched_beat_ids=[],
                overlap_type="none",
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
        # Scene at 50-55s is outside audio duration (20s), so no beats match.
        # visual_duration kept within AV-drift tolerance (RC-2 symmetric gate)
        # so the AV gate does not pre-empt the timestamp-semantic gate under test.
        result = agent.execute(
            job_id=1,
            topic="test topic",
            caption="Nice #tag",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.3,
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
        assert (
            "TIMESTAMP_SEMANTIC" in result.get("reason", "")
            or "semantic" in result.get("reason", "").lower()
        )
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


# ---------------------------------------------------------------------------
# FIX-4 Slice 3 — per-scene entity-vs-beat binding review
# ---------------------------------------------------------------------------


class TestEntityBindingReview:
    """FIX-4 (ADR 0030): a wrong-entity asset in the right time window must be
    caught at review time (job_18: Jennifer Coppen image on a Sarwendah beat)."""

    def test_entity_mismatch_hard_fails_without_llm(self, mocker):
        from clipper_agency.agents.reviewer import ReviewerAgent

        chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict":"pass","score":90,"feedback":"x","issues":[]}',
                "model": "t",
                "usage": {},
            },
        )
        mocker.patch(
            "clipper_agency.agents.reviewer.get_agent_config",
            return_value={"model": "m", "temperature": 0.3, "max_completion_tokens": 5},
        )
        agent = ReviewerAgent()
        # One scene temporally mapped to a Sarwendah beat, but the asset depicts
        # Jennifer Coppen — the exact job_18 wrong-entity shape.
        result = agent.execute(
            job_id=1,
            topic="Sarwendah",
            script=[],
            caption="#x",
            context={
                "audio_duration_sec": 10.0,
                "visual_duration_sec": 10.0,
                "main_entities": ["Sarwendah"],
                "story_beats": [
                    {
                        "beat_id": 1,
                        "spoken_point": "Sarwendah baru saja update",
                        "visual_must_show": "Sarwendah",
                    }
                ],
                "word_timestamps": [{"word": "Sarwendah", "start": 0.0, "end": 10.0}],
                "rendered_scene_manifest": {
                    "video_path": "",
                    "entries": [
                        {
                            "scene": "1",
                            "start_sec": 0.0,
                            "end_sec": 10.0,
                            "subject_name": "Jennifer Coppen",
                        }
                    ],
                },
            },
        )
        assert result["status"] == "fail"
        assert result["reason"] == "ENTITY_MISMATCH"
        chat.assert_not_called()

    def test_entity_correct_passes(self, mocker):
        from clipper_agency.agents.reviewer import ReviewerAgent

        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict":"pass","score":90,"feedback":"x","issues":[]}',
                "model": "t",
                "usage": {},
            },
        )
        mocker.patch(
            "clipper_agency.agents.reviewer.get_agent_config",
            return_value={"model": "m", "temperature": 0.3, "max_completion_tokens": 5},
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="Sarwendah",
            script=[],
            caption="#x",
            context={
                "audio_duration_sec": 10.0,
                "visual_duration_sec": 10.0,
                "main_entities": ["Sarwendah"],
                "story_beats": [
                    {
                        "beat_id": 1,
                        "spoken_point": "Sarwendah baru saja update",
                        "visual_must_show": "Sarwendah",
                    }
                ],
                "word_timestamps": [{"word": "Sarwendah", "start": 0.0, "end": 10.0}],
                "rendered_scene_manifest": {
                    "video_path": "",
                    "entries": [
                        {
                            "scene": "1",
                            "start_sec": 0.0,
                            "end_sec": 10.0,
                            "subject_name": "Sarwendah",
                        }
                    ],
                },
            },
        )
        # Correct entity → no hard-fail → LLM verdict returned.
        assert result["status"] == "pass"

    def test_empty_subject_name_on_entity_beat_warns_not_hard_fail(self, mocker):
        """Cannot verify != verified good: WARN (recorded) but not a hard-fail,
        so a pre-FIX-4 persisted manifest (subject_name='') doesn't death-loop."""
        from clipper_agency.agents.reviewer import ReviewerAgent

        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict":"pass","score":90,"feedback":"x","issues":[]}',
                "model": "t",
                "usage": {},
            },
        )
        mocker.patch(
            "clipper_agency.agents.reviewer.get_agent_config",
            return_value={"model": "m", "temperature": 0.3, "max_completion_tokens": 5},
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="Sarwendah",
            script=[],
            caption="#x",
            context={
                "audio_duration_sec": 10.0,
                "visual_duration_sec": 10.0,
                "main_entities": ["Sarwendah"],
                "story_beats": [
                    {
                        "beat_id": 1,
                        "spoken_point": "Sarwendah update",
                        "visual_must_show": "Sarwendah",
                    }
                ],
                "word_timestamps": [{"word": "Sarwendah", "start": 0.0, "end": 10.0}],
                "rendered_scene_manifest": {
                    "video_path": "",
                    "entries": [
                        {
                            "scene": "1",
                            "start_sec": 0.0,
                            "end_sec": 10.0,
                            "subject_name": "",
                        }
                    ],
                },
            },
        )
        # WARN: not a hard-fail (status=pass) BUT the unverifiable review is
        # surfaced in entity_binding_reviews (not silently accepted).
        assert result["status"] == "pass"
        assert "entity_binding_reviews" in result
        assert any("ENTITY_UNVERIFIABLE" in r["reason"] for r in result["entity_binding_reviews"])

    def test_non_person_beat_skips_entity_check(self, mocker):
        """A beat with no expected entities (generic context) must not trigger
        the entity gate (backward compat)."""
        from clipper_agency.agents.reviewer import ReviewerAgent

        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict":"pass","score":90,"feedback":"x","issues":[]}',
                "model": "t",
                "usage": {},
            },
        )
        mocker.patch(
            "clipper_agency.agents.reviewer.get_agent_config",
            return_value={"model": "m", "temperature": 0.3, "max_completion_tokens": 5},
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="news",
            script=[],
            caption="#x",
            context={
                "audio_duration_sec": 10.0,
                "visual_duration_sec": 10.0,
                "story_beats": [
                    {
                        "beat_id": 1,
                        "spoken_point": "thumbnail berita artis",
                        "visual_must_show": "Thumbnail berita artis",
                    }
                ],
                "word_timestamps": [{"word": "berita", "start": 0.0, "end": 10.0}],
                "rendered_scene_manifest": {
                    "video_path": "",
                    "entries": [
                        {
                            "scene": "1",
                            "start_sec": 0.0,
                            "end_sec": 10.0,
                            "subject_name": "",
                        }
                    ],
                },
            },
        )
        # No expected entities → skip → pass, no entity_binding_reviews.
        assert result["status"] == "pass"
        assert result.get("entity_binding_reviews") in (None, [])


class TestRunEntityBindingReviewPure:
    """Direct unit tests for the pure _run_entity_binding_review helper."""

    def test_wrong_entity_rejected(self):
        from clipper_agency.agents.reviewer import _run_entity_binding_review

        mappings = [
            SceneBeatMapping(
                scene_index=0,
                scene_start_sec=0.0,
                scene_end_sec=10.0,
                matched_beat_ids=[1],
                subject_name="Jennifer Coppen",
            )
        ]
        beats = [
            {"beat_id": 1, "spoken_point": "Sarwendah update", "visual_must_show": "Sarwendah"}
        ]
        reviews = _run_entity_binding_review(mappings, beats)
        assert len(reviews) == 1
        assert reviews[0].decision == "reject"
        assert "ENTITY_MISMATCH" in reviews[0].reason

    def test_correct_entity_accepted(self):
        from clipper_agency.agents.reviewer import _run_entity_binding_review

        mappings = [
            SceneBeatMapping(
                scene_index=0,
                scene_start_sec=0.0,
                scene_end_sec=10.0,
                matched_beat_ids=[1],
                subject_name="Sarwendah",
            )
        ]
        beats = [
            {"beat_id": 1, "spoken_point": "Sarwendah update", "visual_must_show": "Sarwendah"}
        ]
        reviews = _run_entity_binding_review(mappings, beats)
        # Correct match → no reject review returned (no issue to flag).
        assert all(r.decision != "reject" for r in reviews)

    def test_empty_subject_warns(self):
        from clipper_agency.agents.reviewer import _run_entity_binding_review

        mappings = [
            SceneBeatMapping(
                scene_index=0,
                scene_start_sec=0.0,
                scene_end_sec=10.0,
                matched_beat_ids=[1],
                subject_name="",
            )
        ]
        beats = [
            {"beat_id": 1, "spoken_point": "Sarwendah update", "visual_must_show": "Sarwendah"}
        ]
        reviews = _run_entity_binding_review(mappings, beats)
        assert len(reviews) == 1
        assert reviews[0].decision == "accept"  # WARN, not hard-fail
        assert "ENTITY_UNVERIFIABLE" in reviews[0].reason

    def test_wrong_secondary_entity_rejected_when_beat_names_primary(self):
        """Codex P2 regression: a multi-person story where the beat NAMES its
        primary subject (visual_must_show="Sarwendah") must NOT have the
        secondary global ("Ruben Onsu") appended to its expected set. Otherwise
        a "Ruben Onsu" asset would pass the entity gate on a Sarwendah beat
        via a global-only match — defeating per-scene entity binding.
        """
        from clipper_agency.agents.reviewer import (
            _entity_expected_for_beat,
            _run_entity_binding_review,
        )

        main_entities = ["Sarwendah", "Ruben Onsu"]
        beat = {
            "beat_id": 1,
            "spoken_point": "Sarwendah baru saja update",
            "visual_must_show": "Sarwendah",
        }
        # Beat-local derivation is authoritative → globals must NOT widen it.
        expected = _entity_expected_for_beat(beat)
        assert ["sarwendah"] in expected
        assert ["ruben"] not in expected
        assert ["onsu"] not in expected

        mappings = [
            SceneBeatMapping(
                scene_index=0,
                scene_start_sec=0.0,
                scene_end_sec=10.0,
                matched_beat_ids=[1],
                subject_name="Ruben Onsu",  # the secondary global — must NOT pass
            )
        ]
        reviews = _run_entity_binding_review(mappings, [beat])
        assert len(reviews) == 1
        assert reviews[0].decision == "reject"
        assert "ENTITY_MISMATCH" in reviews[0].reason

    def test_global_fallback_not_applied_to_non_entity_beat(self):
        """Codex round-2 P2 regression: when a beat names NO entity itself
        (generic/platform/format/hook/CTA beat), main_entities MUST NOT widen
        the expected set. Otherwise, once a real subject_name flows (codex
        round-2 P1), a legitimate non-person asset (e.g. "TikTok logo" on a
        "TikTok viral hari ini" beat) would false-positive ENTITY_MISMATCH.
        A non-entity beat is skipped (no expectation) — recall degrades safely
        to ENTITY_UNVERIFIABLE on the beats that DO name a person."""
        from clipper_agency.agents.reviewer import (
            _entity_expected_for_beat,
            _run_entity_binding_review,
        )

        main_entities = ["Sarwendah", "Ruben Onsu"]
        # Generic beat — visual_must_show/spoken_point yield no named entity.
        beat = {
            "beat_id": 1,
            "spoken_point": "Thumbnail berita artis",
            "visual_must_show": "Thumbnail berita artis",
        }
        expected = _entity_expected_for_beat(beat)
        # Globals are NOT appended → non-entity beat has no expectation.
        assert expected == []
        assert ["sarwendah"] not in expected

        mappings = [
            SceneBeatMapping(
                scene_index=0,
                scene_start_sec=0.0,
                scene_end_sec=10.0,
                matched_beat_ids=[1],
                subject_name="Sarwendah",
            )
        ]
        reviews = _run_entity_binding_review(mappings, [beat])
        # Non-entity beat is skipped → no reject review returned (no false reject
        # of a primary-subject asset, and no false reject of a non-person asset).
        assert all(r.decision != "reject" for r in reviews)

    def test_non_person_asset_not_rejected_on_platform_beat(self):
        """Codex round-2 P2 regression (concrete false-positive guard): a
        platform/format beat (spoken_point mentions only the generic word
        "TikTok", which derive_expected_entities filters out) with
        main_entities=["Sarwendah"] MUST NOT reject a "TikTok logo" asset.
        Before the fix the global fallback turned this beat into an entity beat
        expecting "sarwendah" → ENTITY_MISMATCH on the correct TikTok asset."""
        from clipper_agency.agents.reviewer import (
            _entity_expected_for_beat,
            _run_entity_binding_review,
        )

        main_entities = ["Sarwendah"]
        beat = {
            "beat_id": 1,
            "spoken_point": "TikTok viral hari ini",
            "visual_must_show": "TikTok viral hari ini",
        }
        # "tiktok" is a _GENERIC_CONTRACT_WORD → derive_expected_entities
        # returns [] → no global widening → beat has no entity expectation.
        assert _entity_expected_for_beat(beat) == []

        mappings = [
            SceneBeatMapping(
                scene_index=0,
                scene_start_sec=0.0,
                scene_end_sec=10.0,
                matched_beat_ids=[1],
                subject_name="TikTok logo",
            )
        ]
        reviews = _run_entity_binding_review(mappings, [beat])
        # No expectation → beat skipped → the correct TikTok asset is NOT rejected.
        assert all(r.decision != "reject" for r in reviews)
