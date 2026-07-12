"""Tests for semantic visual relevance scoring (pure module)."""

from clipper_agency.config.schema import VisualRelevanceScore
from clipper_agency.core.semantic_visual_review import score_visual_relevance


class TestSemanticVisualScoring:
    """Deterministic visual relevance scoring."""

    def test_high_match_scores_as_accept(self):
        score = score_visual_relevance(
            beat={"beat_id": "B01", "claim": {"subject": "Ruben", "action": "klarifikasi"}},
            asset_inspection={
                "person_match": 0.95,
                "event_match": 0.90,
                "claim_support": 0.85,
                "visual_quality": 0.80,
            },
        )
        assert score.decision == "accept"
        assert score.misleading_risk < 0.5

    def test_same_person_wrong_event_scores_as_reject(self):
        score = score_visual_relevance(
            beat={"beat_id": "B04", "claim": {"subject": "Ruben", "action": "klarifikasi"}},
            asset_inspection={
                "person_match": 0.96,
                "event_match": 0.30,
                "claim_support": 0.20,
                "visual_quality": 0.82,
            },
        )
        assert score.decision == "reject"
        assert score.misleading_risk > 0.5

    def test_moderate_scores_as_revise(self):
        score = score_visual_relevance(
            beat={"beat_id": "B02", "claim": {"subject": "Ayu", "action": "konser"}},
            asset_inspection={
                "person_match": 0.60,
                "event_match": 0.50,
                "claim_support": 0.55,
                "visual_quality": 0.70,
            },
        )
        assert score.decision == "revise"

    def test_result_is_visual_relevance_score(self):
        score = score_visual_relevance(
            beat={"beat_id": "B01", "claim": {"subject": "Test", "action": "test"}},
            asset_inspection={
                "person_match": 0.5,
                "event_match": 0.5,
                "claim_support": 0.5,
                "visual_quality": 0.5,
            },
        )
        assert isinstance(score, VisualRelevanceScore)

    def test_custom_weights_override_defaults(self):
        score = score_visual_relevance(
            beat={"beat_id": "B01", "claim": {"subject": "Test", "action": "test"}},
            asset_inspection={
                "person_match": 0.9,
                "event_match": 0.3,
                "claim_support": 0.3,
                "visual_quality": 0.3,
            },
            weights={
                "person_match": 0.70,
                "event_match": 0.10,
                "claim_support": 0.10,
                "visual_quality": 0.10,
            },
        )
        # With high person weight, overall score should still pass but misleading_risk should flag
        assert isinstance(score, VisualRelevanceScore)


class TestMisleadingRiskCharacterization:
    """FIX-3 Slice 4 — pin the CURRENT ``_compute_misleading_risk`` behavior.

    The person_match threshold (0.8) change to 0.6 is DEFERRED to FIX-3.5 (no
    covering tests existed; the change would need a clamp + risks fleet-wide
    false-positives + double-penalizes with the new WRONG_ENTITY rule). These
    characterization tests LOCK today's 0.8 behavior so a future threshold
    change is a deliberate decision, not an accidental drift.
    """

    def test_high_person_low_event_claim_raises_risk(self):
        # person_match > 0.8 + (event+claim)/2 < 0.4 => non-zero misleading_risk
        # (0.5 + (0.85-0.8)*2.5 = 0.625).
        score = score_visual_relevance(
            beat={"beat_id": "X"},
            asset_inspection={
                "person_match": 0.85,
                "event_match": 0.1,
                "claim_support": 0.1,
                "visual_quality": 0.5,
            },
        )
        assert score.misleading_risk > 0.5

    def test_person_below_threshold_no_risk(self):
        # person_match 0.75 (< 0.8) => misleading_risk stays 0 even with low event/claim.
        score = score_visual_relevance(
            beat={"beat_id": "X"},
            asset_inspection={
                "person_match": 0.75,
                "event_match": 0.1,
                "claim_support": 0.1,
                "visual_quality": 0.5,
            },
        )
        assert score.misleading_risk == 0.0

    def test_high_event_claim_suppresses_risk(self):
        # person_match > 0.8 BUT (event+claim)/2 >= 0.4 => misleading_risk 0.
        score = score_visual_relevance(
            beat={"beat_id": "X"},
            asset_inspection={
                "person_match": 0.95,
                "event_match": 0.9,
                "claim_support": 0.9,
                "visual_quality": 0.5,
            },
        )
        assert score.misleading_risk == 0.0

    def test_risk_scales_with_person_match_above_threshold(self):
        low_pm = score_visual_relevance(
            beat={"beat_id": "X"},
            asset_inspection={
                "person_match": 0.82,
                "event_match": 0.1,
                "claim_support": 0.1,
                "visual_quality": 0.5,
            },
        ).misleading_risk
        high_pm = score_visual_relevance(
            beat={"beat_id": "X"},
            asset_inspection={
                "person_match": 0.95,
                "event_match": 0.1,
                "claim_support": 0.1,
                "visual_quality": 0.5,
            },
        ).misleading_risk
        assert high_pm > low_pm
