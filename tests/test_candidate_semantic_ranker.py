"""Tests for candidate_semantic_ranker — pure function ranking module."""

from __future__ import annotations

import pytest

from clipper_agency.core.candidate_semantic_ranker import (
    RankedCandidate,
    apply_rejection_rules,
    compute_final_score,
    rank_candidates,
    select_best_candidate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inspection(
    person_match: float = 0.7,
    event_match: float = 0.7,
    claim_support: float = 0.7,
    visual_quality: float = 0.7,
    misleading_risk: float = 0.1,
    source_credibility: float = 0.7,
) -> dict:
    return {
        "person_match": person_match,
        "event_match": event_match,
        "claim_support": claim_support,
        "visual_quality": visual_quality,
        "misleading_risk": misleading_risk,
        "source_credibility": source_credibility,
    }


def _make_visual_relevance(
    person_match: float = 0.7,
    event_match: float = 0.7,
    claim_support: float = 0.7,
    visual_quality: float = 0.7,
    misleading_risk: float = 0.1,
) -> dict:
    return {
        "person_match": person_match,
        "event_match": event_match,
        "claim_support": claim_support,
        "visual_quality": visual_quality,
        "misleading_risk": misleading_risk,
    }


def _make_candidate(
    asset_id: str = "asset_1",
    beat_id: str = "beat_1",
    role: str = "evidence",
    treatment: str = "picture_in_picture",
    cleanliness_score: float = 0.9,
    inspection: dict | None = None,
    visual_relevance: dict | None = None,
) -> dict:
    return {
        "asset_id": asset_id,
        "beat_id": beat_id,
        "role": role,
        "treatment": treatment,
        "cleanliness_score": cleanliness_score,
        "inspection": inspection or _make_inspection(),
        "visual_relevance": visual_relevance or _make_visual_relevance(),
    }


# ---------------------------------------------------------------------------
# compute_final_score
# ---------------------------------------------------------------------------


class TestComputeFinalScore:
    """Tests for compute_final_score pure function."""

    def test_higher_score_for_better_inputs(self) -> None:
        """Better inspection + relevance → higher final score."""
        low = compute_final_score(
            _make_inspection(person_match=0.3, event_match=0.3, claim_support=0.3, visual_quality=0.3),
            _make_visual_relevance(person_match=0.3, event_match=0.3, claim_support=0.3, visual_quality=0.3),
            cleanliness_score=0.3,
        )
        high = compute_final_score(
            _make_inspection(person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9),
            _make_visual_relevance(person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9),
            cleanliness_score=0.9,
        )
        assert high > low

    def test_returns_zero_for_all_zero_inputs(self) -> None:
        """All-zero inputs produce a final score of 0.0."""
        score = compute_final_score(
            _make_inspection(person_match=0, event_match=0, claim_support=0, visual_quality=0, source_credibility=0),
            _make_visual_relevance(person_match=0, event_match=0, claim_support=0, visual_quality=0),
            cleanliness_score=0.0,
        )
        assert score == 0.0

    def test_penalizes_low_cleanliness(self) -> None:
        """Lower cleanliness reduces the final score."""
        clean = compute_final_score(
            _make_inspection(),
            _make_visual_relevance(),
            cleanliness_score=1.0,
        )
        dirty = compute_final_score(
            _make_inspection(),
            _make_visual_relevance(),
            cleanliness_score=0.2,
        )
        assert clean > dirty

    def test_incorporates_credibility_weight(self) -> None:
        """Credibility weight affects final score."""
        high_cred = compute_final_score(
            _make_inspection(source_credibility=1.0),
            _make_visual_relevance(),
            cleanliness_score=1.0,
            credibility_weight=0.5,
        )
        low_cred = compute_final_score(
            _make_inspection(source_credibility=0.0),
            _make_visual_relevance(),
            cleanliness_score=1.0,
            credibility_weight=0.5,
        )
        assert high_cred > low_cred

    def test_score_bounded_zero_to_one(self) -> None:
        """Score is always in [0.0, 1.0]."""
        score = compute_final_score(
            _make_inspection(person_match=1.0, event_match=1.0, claim_support=1.0, visual_quality=1.0, source_credibility=1.0),
            _make_visual_relevance(person_match=1.0, event_match=1.0, claim_support=1.0, visual_quality=1.0),
            cleanliness_score=1.0,
        )
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# apply_rejection_rules
# ---------------------------------------------------------------------------


class TestApplyRejectionRules:
    """Tests for apply_rejection_rules pure function."""

    def test_returns_none_for_clean_candidate(self) -> None:
        """Clean candidate passes rejection rules."""
        candidate = _make_candidate(
            inspection=_make_inspection(claim_support=0.7, misleading_risk=0.1),
            cleanliness_score=0.9,
        )
        assert apply_rejection_rules(candidate) is None

    def test_rejects_high_misleading_risk(self) -> None:
        """High misleading_risk triggers HIGH_MISLEADING_RISK rejection."""
        candidate = _make_candidate(
            inspection=_make_inspection(misleading_risk=0.8),
        )
        result = apply_rejection_rules(candidate)
        assert result == "HIGH_MISLEADING_RISK"

    def test_rejects_low_claim_support(self) -> None:
        """Low claim_support triggers LOW_CLAIM_SUPPORT rejection."""
        candidate = _make_candidate(
            inspection=_make_inspection(claim_support=0.1, misleading_risk=0.1),
        )
        result = apply_rejection_rules(candidate)
        assert result == "LOW_CLAIM_SUPPORT"

    def test_rejects_dirty_fullscreen(self) -> None:
        """Low cleanliness + fullscreen treatment triggers DIRTY_FULLSCREEN."""
        candidate = _make_candidate(
            treatment="fullscreen",
            cleanliness_score=0.2,
            inspection=_make_inspection(claim_support=0.7, misleading_risk=0.1),
        )
        result = apply_rejection_rules(candidate)
        assert result == "DIRTY_FULLSCREEN"

    def test_dirty_but_not_fullscreen_passes(self) -> None:
        """Low cleanliness with non-fullscreen treatment does NOT reject."""
        candidate = _make_candidate(
            treatment="picture_in_picture",
            cleanliness_score=0.2,
            inspection=_make_inspection(claim_support=0.7, misleading_risk=0.1),
        )
        assert apply_rejection_rules(candidate) is None


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------


class TestRankCandidates:
    """Tests for rank_candidates pure function."""

    def test_sorts_by_score_descending(self) -> None:
        """Candidates are sorted by final_score, highest first."""
        beat = {"beat_id": "b1"}
        low = _make_candidate(
            asset_id="low",
            inspection=_make_inspection(person_match=0.3, event_match=0.3, claim_support=0.3, visual_quality=0.3),
            visual_relevance=_make_visual_relevance(person_match=0.3, event_match=0.3, claim_support=0.3, visual_quality=0.3),
        )
        high = _make_candidate(
            asset_id="high",
            inspection=_make_inspection(person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9),
            visual_relevance=_make_visual_relevance(person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9),
        )
        result = rank_candidates(beat, [low, high])
        assert len(result) == 2
        assert result[0].final_score >= result[1].final_score
        assert result[0].asset_id == "high"

    def test_marks_rejected_candidates(self) -> None:
        """Rejected candidates get decision='reject'."""
        beat = {"beat_id": "b1"}
        bad = _make_candidate(
            asset_id="bad",
            inspection=_make_inspection(misleading_risk=0.9),
        )
        good = _make_candidate(
            asset_id="good",
            inspection=_make_inspection(misleading_risk=0.1),
        )
        result = rank_candidates(beat, [bad, good])
        rejected = [r for r in result if r.asset_id == "bad"]
        assert len(rejected) == 1
        assert rejected[0].decision == "reject"

    def test_adds_fallback_when_all_rejected(self) -> None:
        """When all candidates are rejected, a fallback_card is appended."""
        beat = {"beat_id": "b1"}
        bad = _make_candidate(
            asset_id="bad",
            inspection=_make_inspection(misleading_risk=0.9, claim_support=0.1),
        )
        result = rank_candidates(beat, [bad])
        assert any(r.decision == "fallback_card" for r in result)

    def test_prefers_evidence_over_context_tiebreak(self) -> None:
        """When scores are equal, evidence role ranks above context role."""
        beat = {"beat_id": "b1"}
        evidence = _make_candidate(
            asset_id="evidence",
            role="evidence",
            inspection=_make_inspection(person_match=0.5, event_match=0.5, claim_support=0.5, visual_quality=0.5),
            visual_relevance=_make_visual_relevance(person_match=0.5, event_match=0.5, claim_support=0.5, visual_quality=0.5),
        )
        context = _make_candidate(
            asset_id="context",
            role="context",
            inspection=_make_inspection(person_match=0.5, event_match=0.5, claim_support=0.5, visual_quality=0.5),
            visual_relevance=_make_visual_relevance(person_match=0.5, event_match=0.5, claim_support=0.5, visual_quality=0.5),
        )
        result = rank_candidates(beat, [context, evidence])
        # Same score, but evidence should come first
        assert result[0].asset_id == "evidence"

    def test_single_good_candidate_accepted(self) -> None:
        """A single good candidate gets decision='accept'."""
        beat = {"beat_id": "b1"}
        good = _make_candidate(
            inspection=_make_inspection(person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9),
            visual_relevance=_make_visual_relevance(person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9),
        )
        result = rank_candidates(beat, [good])
        assert len(result) == 1
        assert result[0].decision == "accept"

    def test_no_fallback_when_some_accepted(self) -> None:
        """No fallback card when at least one candidate is accepted."""
        beat = {"beat_id": "b1"}
        bad = _make_candidate(
            asset_id="bad",
            inspection=_make_inspection(misleading_risk=0.9),
        )
        good = _make_candidate(
            asset_id="good",
            inspection=_make_inspection(misleading_risk=0.1),
        )
        result = rank_candidates(beat, [bad, good])
        assert not any(r.decision == "fallback_card" for r in result)


# ---------------------------------------------------------------------------
# select_best_candidate
# ---------------------------------------------------------------------------


class TestSelectBestCandidate:
    """Tests for select_best_candidate pure function."""

    def test_returns_first_non_rejected(self) -> None:
        """Returns the first non-rejected candidate."""
        ranked = [
            RankedCandidate("a1", "b1", 0.9, "accept", {}, {}, 0.9, "good"),
            RankedCandidate("a2", "b1", 0.7, "accept", {}, {}, 0.7, "ok"),
        ]
        result = select_best_candidate(ranked)
        assert result is not None
        assert result.asset_id == "a1"

    def test_skips_rejected_returns_next(self) -> None:
        """Skips rejected candidates and returns next best."""
        ranked = [
            RankedCandidate("a1", "b1", 0.9, "reject", {}, {}, 0.9, "bad"),
            RankedCandidate("a2", "b1", 0.7, "accept", {}, {}, 0.7, "ok"),
        ]
        result = select_best_candidate(ranked)
        assert result is not None
        assert result.asset_id == "a2"

    def test_returns_none_for_empty_list(self) -> None:
        """Empty list returns None."""
        assert select_best_candidate([]) is None

    def test_returns_none_when_all_rejected(self) -> None:
        """All rejected list returns None (fallback_card is not a reject)."""
        ranked = [
            RankedCandidate("a1", "b1", 0.1, "reject", {}, {}, 0.1, "bad"),
        ]
        assert select_best_candidate(ranked) is None
