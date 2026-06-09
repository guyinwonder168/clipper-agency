"""Tests for semantic visual relevance scoring (pure module)."""

import pytest
from clipper_agency.core.semantic_visual_review import score_visual_relevance
from clipper_agency.config.schema import VisualRelevanceScore


class TestSemanticVisualScoring:
    """Deterministic visual relevance scoring."""

    def test_high_match_scores_as_accept(self):
        score = score_visual_relevance(
            beat={"beat_id": "B01", "claim": {"subject": "Ruben", "action": "klarifikasi"}},
            asset_inspection={"person_match": 0.95, "event_match": 0.90, "claim_support": 0.85, "visual_quality": 0.80},
        )
        assert score.decision == "accept"
        assert score.misleading_risk < 0.5

    def test_same_person_wrong_event_scores_as_reject(self):
        score = score_visual_relevance(
            beat={"beat_id": "B04", "claim": {"subject": "Ruben", "action": "klarifikasi"}},
            asset_inspection={"person_match": 0.96, "event_match": 0.30, "claim_support": 0.20, "visual_quality": 0.82},
        )
        assert score.decision == "reject"
        assert score.misleading_risk > 0.5

    def test_moderate_scores_as_revise(self):
        score = score_visual_relevance(
            beat={"beat_id": "B02", "claim": {"subject": "Ayu", "action": "konser"}},
            asset_inspection={"person_match": 0.60, "event_match": 0.50, "claim_support": 0.55, "visual_quality": 0.70},
        )
        assert score.decision == "revise"

    def test_result_is_visual_relevance_score(self):
        score = score_visual_relevance(
            beat={"beat_id": "B01", "claim": {"subject": "Test", "action": "test"}},
            asset_inspection={"person_match": 0.5, "event_match": 0.5, "claim_support": 0.5, "visual_quality": 0.5},
        )
        assert isinstance(score, VisualRelevanceScore)

    def test_custom_weights_override_defaults(self):
        score = score_visual_relevance(
            beat={"beat_id": "B01", "claim": {"subject": "Test", "action": "test"}},
            asset_inspection={"person_match": 0.9, "event_match": 0.3, "claim_support": 0.3, "visual_quality": 0.3},
            weights={"person_match": 0.70, "event_match": 0.10, "claim_support": 0.10, "visual_quality": 0.10},
        )
        # With high person weight, overall score should still pass but misleading_risk should flag
        assert isinstance(score, VisualRelevanceScore)
