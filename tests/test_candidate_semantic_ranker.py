"""Tests for candidate_semantic_ranker — pure function ranking module."""

from __future__ import annotations

import pytest

from clipper_agency.core.candidate_semantic_ranker import (
    RankedCandidate,
    apply_rejection_rules,
    compute_final_score,
    derive_expected_entities,
    entity_overlap,
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
            _make_inspection(
                person_match=0.3, event_match=0.3, claim_support=0.3, visual_quality=0.3
            ),
            _make_visual_relevance(
                person_match=0.3, event_match=0.3, claim_support=0.3, visual_quality=0.3
            ),
            cleanliness_score=0.3,
        )
        high = compute_final_score(
            _make_inspection(
                person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9
            ),
            _make_visual_relevance(
                person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9
            ),
            cleanliness_score=0.9,
        )
        assert high > low

    def test_returns_zero_for_all_zero_inputs(self) -> None:
        """All-zero inputs produce a final score of 0.0."""
        score = compute_final_score(
            _make_inspection(
                person_match=0,
                event_match=0,
                claim_support=0,
                visual_quality=0,
                source_credibility=0,
            ),
            _make_visual_relevance(
                person_match=0, event_match=0, claim_support=0, visual_quality=0
            ),
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
            _make_inspection(
                person_match=1.0,
                event_match=1.0,
                claim_support=1.0,
                visual_quality=1.0,
                source_credibility=1.0,
            ),
            _make_visual_relevance(
                person_match=1.0, event_match=1.0, claim_support=1.0, visual_quality=1.0
            ),
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
            inspection=_make_inspection(
                person_match=0.3, event_match=0.3, claim_support=0.3, visual_quality=0.3
            ),
            visual_relevance=_make_visual_relevance(
                person_match=0.3, event_match=0.3, claim_support=0.3, visual_quality=0.3
            ),
        )
        high = _make_candidate(
            asset_id="high",
            inspection=_make_inspection(
                person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9
            ),
            visual_relevance=_make_visual_relevance(
                person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9
            ),
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
            inspection=_make_inspection(
                person_match=0.5, event_match=0.5, claim_support=0.5, visual_quality=0.5
            ),
            visual_relevance=_make_visual_relevance(
                person_match=0.5, event_match=0.5, claim_support=0.5, visual_quality=0.5
            ),
        )
        context = _make_candidate(
            asset_id="context",
            role="context",
            inspection=_make_inspection(
                person_match=0.5, event_match=0.5, claim_support=0.5, visual_quality=0.5
            ),
            visual_relevance=_make_visual_relevance(
                person_match=0.5, event_match=0.5, claim_support=0.5, visual_quality=0.5
            ),
        )
        result = rank_candidates(beat, [context, evidence])
        # Same score, but evidence should come first
        assert result[0].asset_id == "evidence"

    def test_single_good_candidate_accepted(self) -> None:
        """A single good candidate gets decision='accept'."""
        beat = {"beat_id": "b1"}
        good = _make_candidate(
            inspection=_make_inspection(
                person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9
            ),
            visual_relevance=_make_visual_relevance(
                person_match=0.9, event_match=0.9, claim_support=0.9, visual_quality=0.9
            ),
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


# ---------------------------------------------------------------------------
# FIX-3 — entity-binding (WRONG_ENTITY rule + helpers + missing-subject downgrade)
# ---------------------------------------------------------------------------


def _entity_candidate(
    subject_name: str = "",
    expected_entities: list[str] | list[list[str]] | None = None,
    person_match: float = 0.9,
    claim_support: float = 0.9,
    misleading_risk: float = 0.1,
    asset_id: str = "asset_1",
) -> dict:
    """Build a scored-candidate dict carrying the FIX-3 entity-binding fields.

    FIX-4 (Codex P2): ``expected_entities`` is stored as PHRASES
    (``list[list[str]]``) to match the phrase-aware ``entity_overlap``. Accepts
    flat tokens (``["sarwendah"]``) for backward-compat and wraps each into a
    single-token phrase; multi-token phrases (``[["raffi","ahmad"]]``) pass through.
    """
    raw = expected_entities or []
    phrases = [[t] if isinstance(t, str) else list(t) for t in raw]
    return {
        "asset_id": asset_id,
        "beat_id": "b1",
        "role": "evidence",
        "treatment": "picture_in_picture",
        "cleanliness_score": 0.9,
        "expected_entities": phrases,
        "inspection": {
            "person_match": person_match,
            "event_match": 0.9,
            "claim_support": claim_support,
            "visual_quality": 0.9,
            "misleading_risk": misleading_risk,
            "source_credibility": 0.9,
            "subject_name": subject_name,
        },
        "visual_relevance": {
            "person_match": person_match,
            "event_match": 0.9,
            "claim_support": claim_support,
            "visual_quality": 0.9,
        },
    }


class TestEntityBindingRejection:
    """FIX-3 — WRONG_ENTITY rejection at apply_rejection_rules (job_18 fix)."""

    def test_wrong_entity_rejected(self) -> None:
        """job_18 case: a Sarwendah beat got a Jennifer Coppen image -> rejected."""
        candidate = _entity_candidate(
            subject_name="Jennifer Coppen",
            expected_entities=["sarwendah"],
        )
        assert apply_rejection_rules(candidate) == "WRONG_ENTITY"

    def test_correct_entity_not_rejected(self) -> None:
        """Subject name overlapping the expected entity passes."""
        candidate = _entity_candidate(
            subject_name="Sarwendah",
            expected_entities=["sarwendah"],
        )
        assert apply_rejection_rules(candidate) is None

    def test_alias_transliteration_tolerated(self) -> None:
        """Sarwenda (no trailing h) vs sarwendah — substring alias match, not rejected."""
        candidate = _entity_candidate(
            subject_name="Sarwenda",
            expected_entities=["sarwendah"],
        )
        assert apply_rejection_rules(candidate) is None

    def test_missing_subject_name_skips_wrong_entity(self) -> None:
        """Empty subject_name => WRONG_ENTITY rule no-op (Slice 3 handles via revise)."""
        candidate = _entity_candidate(
            subject_name="",
            expected_entities=["sarwendah"],
        )
        assert apply_rejection_rules(candidate) is None

    def test_no_expected_entities_is_noop(self) -> None:
        """Backward compat: undecorated candidate never triggers WRONG_ENTITY."""
        candidate = _entity_candidate(
            subject_name="Anyone",
            expected_entities=[],
        )
        # Remove the key entirely to prove absence (not just empty) is safe too.
        del candidate["expected_entities"]
        assert apply_rejection_rules(candidate) is None

    def test_wrong_entity_takes_precedence(self) -> None:
        """WRONG_ENTITY is checked first (most specific), before misleading_risk."""
        candidate = _entity_candidate(
            subject_name="Jennifer Coppen",
            expected_entities=["sarwendah"],
            misleading_risk=0.9,
            claim_support=0.1,
        )
        assert apply_rejection_rules(candidate) == "WRONG_ENTITY"


class TestVisualMustShowAuthoritativeBinding:
    """FIX-3 round-3 (Codex) — visual_must_show is the authoritative binding
    source; a person merely MENTIONED in spoken_point must not widen the binding
    set and let a wrong-person asset pass WRONG_ENTITY (job_18 failure mode)."""

    def test_mentioned_person_excluded_when_visual_must_show_names_target(self) -> None:
        """visual_must_show='Sarwendah' is authoritative; 'Jennifer Coppen'
        appearing only in spoken_point must NOT enter the binding set."""
        ents = derive_expected_entities(
            spoken_point="Sarwendah berbeda dengan Jennifer Coppen",
            visual_must_show="Sarwendah",
        )
        assert ["sarwendah"] in ents
        assert ["jennifer"] not in ents
        assert ["coppen"] not in ents

    def test_wrong_person_from_spoken_point_rejected(self) -> None:
        """End-to-end job_18 case: an asset whose subject_name is the merely-
        mentioned person is rejected as WRONG_ENTITY because the binding set
        comes from visual_must_show alone."""
        expected = derive_expected_entities(
            spoken_point="Sarwendah berbeda dengan Jennifer Coppen",
            visual_must_show="Sarwendah",
        )
        candidate = _entity_candidate(
            subject_name="Jennifer Coppen",
            expected_entities=expected,
        )
        assert apply_rejection_rules(candidate) == "WRONG_ENTITY"

    def test_correct_visual_must_show_target_passes(self) -> None:
        """Sanity: the authoritative target itself is still accepted."""
        expected = derive_expected_entities(
            spoken_point="Sarwendah berbeda dengan Jennifer Coppen",
            visual_must_show="Sarwendah",
        )
        candidate = _entity_candidate(
            subject_name="Sarwendah",
            expected_entities=expected,
        )
        assert apply_rejection_rules(candidate) is None

    def test_spoken_point_fallback_when_visual_must_show_generic(self) -> None:
        """Recall preserved: when visual_must_show is a generic contract (no
        named entities), spoken_point names are used so a beat that names its
        subject only in narration still gets entity binding."""
        ents = derive_expected_entities(
            spoken_point="Sarwendah baru saja update",
            visual_must_show="Thumbnail berita artis",
        )
        assert ["sarwendah"] in ents


class TestEntityOverlap:
    """FIX-3 — entity_overlap pure helper (the alias/fuzzy matching core)."""

    def test_exact_token_match(self) -> None:
        assert entity_overlap("Sarwendah", [["sarwendah"]]) is True

    def test_case_insensitive(self) -> None:
        assert entity_overlap("sarwendah", [["SARWENDAH"]]) is True

    def test_substring_alias(self) -> None:
        """sarwenda is a substring of sarwendah (transliteration tolerance)."""
        assert entity_overlap("Sarwenda", [["sarwendah"]]) is True

    def test_jennifer_not_sarwendah(self) -> None:
        """The load-bearing safety case: different celebrity must NOT match."""
        assert entity_overlap("Jennifer Coppen", [["sarwendah"]]) is False

    def test_multi_word_subject_token_match(self) -> None:
        assert entity_overlap("Cristiano Ronaldo", [["ronaldo"]]) is True

    def test_empty_inputs(self) -> None:
        assert entity_overlap("", [["x"]]) is False
        assert entity_overlap("x", []) is False

    def test_short_expected_entity_ignored(self) -> None:
        """Expected tokens shorter than 4 chars are skipped (kills 'wen'-style noise)."""
        assert entity_overlap("Jo", [["jo"]]) is False

    # --- FIX-4 Slice 5: multi-token phrase-level matching ---

    def test_full_name_phrase_exact_match(self) -> None:
        """FIX-4 Slice 5: a full-name phrase matches as a single expected entry."""
        assert entity_overlap("Jennifer Coppen", [["jennifer", "coppen"]]) is True

    def test_alias_substring_tolerance(self) -> None:
        """Sarwendah/Sarwenda alias tolerance (transliteration)."""
        assert entity_overlap("Sarwendah", [["sarwenda"]]) is True

    def test_different_full_name_no_match(self) -> None:
        """The load-bearing safety case at the phrase level."""
        assert entity_overlap("Jennifer Coppen", [["sarwendah"]]) is False

    def test_multi_token_shared_token_no_match(self) -> None:
        """FIX-4 Codex P2: a single shared token of a multi-token name must NOT
        accept a different person. Subject "Ahmad Doe" shares "ahmad" with the
        expected full name "Raffi Ahmad" — must be rejected (token-set Jaccard
        1/3 = 0.33 < 0.75). Before the phrase refactor the flat per-token
        matcher Rule-A-matched on "ahmad" and false-accepted."""
        assert entity_overlap("Ahmad Doe", [["raffi", "ahmad"]]) is False
        assert entity_overlap("Raffi Ahmad", [["raffi", "ahmad"]]) is True


class TestGenericPlatformWordsFiltered:
    """FIX-4 Slice 4: platform/format words must never count as entity matches
    and must never be derived as expected entities (a 'TikTok' asset must not
    match a beat whose spoken_point merely mentions TikTok)."""

    @pytest.mark.parametrize(
        "word",
        [
            "tiktok",
            "youtube",
            "ig",
            "instagram",
            "reels",
            "duet",
            "stitch",
            "fyp",
            "konten",
            "kreator",
        ],
    )
    def test_platform_word_not_derived_as_entity(self, word: str) -> None:
        ents = derive_expected_entities(
            spoken_point=f"{word.capitalize()} viral hari ini",
            visual_must_show="",
        )
        assert not any(word.lower() in p for p in ents), f"{word} should be filtered as generic"

    def test_platform_word_does_not_count_as_overlap(self) -> None:
        """entity_overlap filters generic words from the expected set so they
        can never count as a match (defense-in-depth over derivation)."""
        assert entity_overlap("tiktok", [["tiktok"]]) is False

    def test_beat_with_only_platform_words_yields_no_entities(self) -> None:
        ents = derive_expected_entities(
            spoken_point="Tiktok viral fyp",
            visual_must_show="",
        )
        assert ents == []


class TestDeriveExpectedEntities:
    """FIX-3 — derive_expected_entities pure helper."""

    def test_capitalized_visual_must_show_token(self) -> None:
        # Named entities are capitalized (proper nouns); a lowercase token is
        # treated as a generic contract word, not an entity.
        ents = derive_expected_entities(spoken_point="", visual_must_show="Sarwendah")
        assert ["sarwendah"] in ents

    def test_generic_visual_must_show_yields_no_entity(self) -> None:
        # Codex P2 #1: a generic contract (Job 8 "Thumbnail berita artis dengan
        # teks 'BERITA HARI INI'") must NOT derive entities -> the WRONG_ENTITY
        # rule stays a no-op so a real person (Raffi Ahmad) isn't falsely
        # rejected on a generic/context beat.
        ents = derive_expected_entities(
            spoken_point="",
            visual_must_show="Thumbnail berita artis dengan teks 'BERITA HARI INI'",
        )
        assert ents == []

    def test_generic_hook_narration_yields_no_entity(self) -> None:
        # Codex P2 (r3566760232, job8 fixture): capitalized generic hook/CTA
        # openers (Halo/Reaksi/Jangan/Simak/Ternyata/...) in narration must NOT
        # derive entities -> a real person isn't falsely rejected as WRONG_ENTITY
        # on a context beat. Regresses the pre-fix behavior where these slipped
        # through (they're capitalized sentence-start words but not proper nouns).
        ents = derive_expected_entities(
            spoken_point="Halo guys! Simak Reaksi ini. Ternyata Jangan lupa ya.",
            visual_must_show="",
        )
        assert ents == [], f"expected no entities, got {ents}"

    def test_spoken_point_requires_capitalization(self) -> None:
        """Lowercase spoken narration words are treated as noise and dropped."""
        ents = derive_expected_entities(spoken_point="kemarin dia ke pasar")
        assert ents == []

    def test_capitalized_spoken_token_kept(self) -> None:
        ents = derive_expected_entities(spoken_point="Sarwendah baru saja update")
        assert ["sarwendah"] in ents
        assert ["baru"] not in ents

    def test_stopwords_dropped(self) -> None:
        ents = derive_expected_entities(spoken_point="Yang Dari Dengan")
        assert ents == []

    def test_dedup_across_fields(self) -> None:
        ents = derive_expected_entities(spoken_point="Sarwendah", visual_must_show="sarwendah")
        assert sum(1 for p in ents if "sarwendah" in p) == 1

    def test_duplicate_token_within_field_deduped(self) -> None:
        """A repeated capitalized token within ONE field is de-duplicated."""
        ents = derive_expected_entities(spoken_point="", visual_must_show="Sarwendah Sarwendah")
        assert ents == [["sarwendah"]]

    def test_empty_inputs(self) -> None:
        assert derive_expected_entities("", "") == []


class TestMissingSubjectDowngrade:
    """FIX-3 Slice 3 — person depicted + no subject_name + entity beat => revise."""

    def test_accept_downgraded_to_revise(self) -> None:
        beat = {"beat_id": "b1"}
        cand = _entity_candidate(
            subject_name="",
            expected_entities=["sarwendah"],
            person_match=0.9,
        )
        result = rank_candidates(beat, [cand])
        assert result[0].decision == "revise"
        assert "subject_name missing" in result[0].rank_reason

    def test_accept_kept_when_subject_overlaps(self) -> None:
        beat = {"beat_id": "b1"}
        cand = _entity_candidate(
            subject_name="Sarwendah",
            expected_entities=["sarwendah"],
            person_match=0.9,
        )
        result = rank_candidates(beat, [cand])
        assert result[0].decision == "accept"

    def test_no_downgrade_without_expected_entities(self) -> None:
        """Backward compat: undecorated candidate stays accept (entity binding off)."""
        beat = {"beat_id": "b1"}
        cand = _entity_candidate(subject_name="", expected_entities=[], person_match=0.9)
        del cand["expected_entities"]
        result = rank_candidates(beat, [cand])
        assert result[0].decision == "accept"

    def test_no_downgrade_when_person_match_low(self) -> None:
        """A non-person asset (person_match < 0.5) is not entity-checked."""
        beat = {"beat_id": "b1"}
        cand = _entity_candidate(
            subject_name="",
            expected_entities=["sarwendah"],
            person_match=0.3,
        )
        result = rank_candidates(beat, [cand])
        assert result[0].decision == "accept"


class TestWrongEntityFallback:
    """FIX-3 — all-wrong-entity beat yields the fallback_card path."""

    def test_all_wrong_entity_appends_fallback(self) -> None:
        beat = {"beat_id": "b1"}
        wrong = _entity_candidate(
            subject_name="Jennifer Coppen",
            expected_entities=["sarwendah"],
            asset_id="wrong",
        )
        result = rank_candidates(beat, [wrong])
        assert result[0].decision == "reject"
        assert any(r.decision == "fallback_card" for r in result)


class TestAcceptPreferredOverRevise:
    """FIX-3 Codex P2 #2 — a verified ``accept`` must outrank a higher-scoring
    Slice-3-downgraded ``revise`` so ``select_best_candidate`` returns the
    verifiable asset and VD does not fall back past it."""

    def test_accept_outranks_higher_score_revise(self) -> None:
        beat = {"beat_id": "b1"}
        verified = _entity_candidate(
            subject_name="Sarwendah",
            expected_entities=["sarwendah"],
            person_match=0.69,
            asset_id="verified",
        )
        unnamed = _entity_candidate(
            subject_name="",
            expected_entities=["sarwendah"],
            person_match=0.94,
            asset_id="unnamed",
        )
        result = rank_candidates(beat, [unnamed, verified])
        # unnamed is downgraded accept->revise (high score, no subject_name);
        # verified stays accept (lower score, subject overlaps). accept must
        # sort FIRST despite the lower score.
        assert result[0].asset_id == "verified"
        assert result[0].decision == "accept"
        assert result[1].decision == "revise"
        # select_best_candidate returns the accept, not the higher-score revise.
        best = select_best_candidate(result)
        assert best is not None
        assert best.asset_id == "verified"
