"""SLICE 1 — cache-key parity hard gate for the pre-VD asset-qualification boundary.

Guards PR 5's #1 risk (design doc §12: "Cache-key literal drift — forks cache
namespace, re-spends VLM"). Both ``asset_qualification._score_candidate`` and
``VD._score_one_candidate`` route through the SHARED
``inspection_cache.compute_candidate_cache_key(candidate, spoken_point,
visual_must_show, visual_must_not_show)`` (the design §8 follow-up, now landed), so
the two sites cannot drift on the six cache-key inputs by construction. This test
spies on the shared helper and asserts both call sites pass identical
candidate/beat args, and that the helper's convention (model, prompt_version,
evidence-contract hash) is pinned.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.config.schema import AssetCandidate, BeatFallback, StoryBeat
from clipper_agency.core import asset_qualification, inspection_cache
from clipper_agency.core.inspection_cache import compute_candidate_cache_key

# ---------------------------------------------------------------------------
# Fixtures (mirror tests/agents/test_visual_director_candidate_inspection.py)
# ---------------------------------------------------------------------------


def _make_candidate(
    ctype: str = "tiktok_clip",
    url: str = "https://example.com/clip1.mp4",
    # Reason tokens overlap the default beat's keywords (spoken_point="Point N",
    # visual_must_show="Point N", narration_goal="Beat N") so cache-miss tests
    # exercise the inspection path instead of being skipped by the PR 8
    # pre-VLM keyword-overlap gate (which skips only on ZERO overlap).
    reason: str = "test point visual beat candidate",
) -> AssetCandidate:
    return AssetCandidate(type=ctype, url=url, reason=reason)


def _make_fallback(**overrides: Any) -> BeatFallback:
    defaults: dict[str, Any] = {"type": "text_card", "headline": "Card", "image_search": ""}
    defaults.update(overrides)
    return BeatFallback(**defaults)


def _make_beat(beat_id: int = 1, **overrides: Any) -> StoryBeat:
    defaults: dict[str, Any] = {
        "beat_id": beat_id,
        "role": "evidence",
        "narration_goal": f"Beat {beat_id}",
        "spoken_point": f"Point {beat_id}",
        "safe_wording": f"Safe {beat_id}",
        # FIX-3 round-3: visual_must_show is the AUTHORITATIVE entity-binding
        # source, so the placeholder visual contract is aligned with the
        # depicted subject_name ("Point N") — otherwise the spurious "visual"
        # entity would reject every placeholder candidate as WRONG_ENTITY.
        "visual_must_show": f"Point {beat_id}",
        "visual_must_not_show": "",
        "overlay_text": f"Overlay {beat_id}",
        "caption_keywords": [],
        "asset_candidates": [],
        "fallback": _make_fallback(headline=f"Card {beat_id}"),
        "risk_note": "",
    }
    defaults.update(overrides)
    return StoryBeat(**defaults)


def _make_plan_item(beat_id: int = 1) -> dict:
    return {
        "scene_number": beat_id,
        "beat_id": beat_id,
        "role": "evidence",
        "treatment": "broll_standard",
    }


def _cached_inspection() -> dict:
    """A valid cached inspection dict (cache-hit path skips the inspection call)."""
    return {
        "decision": "accept",
        "subject_name": "Point 1",
        "person_match": 0.9,
        "event_match": 0.85,
        "claim_support": 0.9,
        "visual_quality": 0.8,
        "misleading_risk": 0.1,
    }


class TestCacheKeyParityWithVisualDirector:
    """SLICE 1 HARD MERGE GATE.

    ``asset_qualification._score_candidate`` and ``VD._score_one_candidate`` must
    compute a byte-identical inspection-cache key for the same ``(candidate, beat)``,
    else the pre-VD qualification pass and VD fork the cache namespace and VLM is
    re-spent (a silent cost regression with no error signal — §12 HIGHEST risk).
    """

    def test_cache_key_matches_vd_convention(self) -> None:
        cand = _make_candidate()
        beat = _make_beat()
        plan_item = _make_plan_item()
        cached = _cached_inspection()

        vd_calls: list[tuple[Any, ...]] = []
        aq_calls: list[tuple[Any, ...]] = []
        real_helper = inspection_cache.compute_candidate_cache_key

        def vd_spy(*args: Any) -> str:
            vd_calls.append(args)
            return real_helper(*args)

        def aq_spy(*args: Any) -> str:
            aq_calls.append(args)
            return real_helper(*args)

        agent = VisualDirectorAgent()

        # Force a cache hit on both paths so _run_multimodal_inspection / _run_inspection
        # are never reached — this test isolates the compute_candidate_cache_key call.
        with (
            patch(
                "clipper_agency.agents.visual_director.compute_candidate_cache_key",
                vd_spy,
            ),
            patch("clipper_agency.agents.visual_director.lookup", return_value=cached),
        ):
            vd_result = agent._score_one_candidate(
                cand, beat, plan_item, 1, "/tmp/cache", "/tmp/agent"
            )

        with (
            patch(
                "clipper_agency.core.asset_qualification.compute_candidate_cache_key",
                aq_spy,
            ),
            patch("clipper_agency.core.asset_qualification.lookup", return_value=cached),
        ):
            aq_result = asset_qualification._score_candidate(
                cand, beat, plan_item, 1, "/tmp/cache", "/tmp/agent", inspector=None
            )

        # Both paths must have invoked the shared helper exactly once.
        assert vd_calls, "VD._score_one_candidate did not call compute_candidate_cache_key"
        assert aq_calls, (
            "asset_qualification._score_candidate did not call compute_candidate_cache_key"
        )

        # 1) Arg-equality: catches ANY drift on candidate or beat field source. This is
        #    the primary gate — both must pass (candidate, spoken_point,
        #    visual_must_show, visual_must_not_show) in the same order.
        assert vd_calls == aq_calls
        assert vd_calls[0] == (
            cand,
            beat.spoken_point,
            beat.visual_must_show,
            beat.visual_must_not_show,
        )

        # 2) Byte-identity: both derive the same digest from the same args.
        assert real_helper(*vd_calls[0]) == real_helper(*aq_calls[0])

        # 3) Pin the shared helper's convention so a future edit to the helper's
        #    constants (model / prompt_version / evidence-contract hash) trips this
        #    gate. prompt_version=1.1 invalidates pre-FIX-3 caches; the evidence
        #    hash is non-empty (FIX-3 added visual_must_show/_not_show to the prompt).
        from clipper_agency.core.inspection_cache import (
            CANDIDATE_CACHE_MODEL,
            CANDIDATE_CACHE_PROMPT_VERSION,
            compute_evidence_contract_hash,
        )
        from clipper_agency.core.inspection_cache import (
            compute_cache_key as _low,
        )

        key = real_helper(*vd_calls[0])
        # The helper's convention is observable by re-running the low-level key with
        # the documented literals — assert they reproduce the helper output.
        assert (
            _low(
                asset_path=cand.url,
                asset_hash=inspection_cache.compute_asset_content_hash(cand),
                beat_claim=beat.spoken_point,
                evidence_contract_hash=compute_evidence_contract_hash(
                    beat.visual_must_show, beat.visual_must_not_show
                ),
                model=CANDIDATE_CACHE_MODEL,
                prompt_version=CANDIDATE_CACHE_PROMPT_VERSION,
            )
            == key
        )
        assert CANDIDATE_CACHE_PROMPT_VERSION == "1.1"
        # Evidence-contract hash is NON-empty once visual fields are present.
        assert compute_evidence_contract_hash(beat.visual_must_show, "") != ""

        # Sanity: the cache-hit path completed end-to-end on both scorers.
        assert vd_result is not None
        assert aq_result is not None


class TestScoreCandidateNoneInspection:
    """Cover the ``inspection is None`` branch (faithful lift of VD:776-777).

    A None inspection means the candidate could not be scored; ``_score_candidate``
    returns None so the ranker rejects it. (SLICE 6 gives ``_run_inspection`` a real
    None-return-on-exception path; here it is patched.)
    """

    def test_returns_none_when_inspection_yields_none(self) -> None:
        cand = _make_candidate()
        beat = _make_beat()
        with (
            patch("clipper_agency.core.asset_qualification.lookup", return_value=None),
            patch(
                "clipper_agency.core.asset_qualification._run_inspection",
                return_value=None,
            ),
        ):
            result = asset_qualification._score_candidate(
                cand, beat, _make_plan_item(), 1, "/tmp/cache", "/tmp/agent", inspector=None
            )
        assert result is None


class TestRunInspectionDelegates:
    """SLICE 6 — ``_run_inspection`` delegates to the injected inspector.

    Per ADR 0027, rather than verbatim-lifting ``VD._run_multimodal_inspection`` (which
    would duplicate ~140 lines of OCR/face/enhanced ML machinery and risk cache-namespace
    drift), ``_run_inspection`` delegates to an injected callable the engine seam binds to
    ``VisualDirectorAgent._run_multimodal_inspection``. This reuses VD's EXACT inspection
    (same cached output → no double-VLM, no drift) and keeps frame ownership in VD.
    """

    def test_delegates_to_inspector_and_returns_result(self) -> None:
        cand = _make_candidate()
        beat = _make_beat()
        sentinel = {"decision": "accept", "person_match": 0.9}
        received: dict[str, Any] = {}

        def inspector(
            candidate: Any,
            beat_arg: Any,
            job_id: int,
            cache_dir: str,
            cache_key: str,
            agent_dir: str,
        ) -> dict:
            received["candidate"] = candidate
            received["beat"] = beat_arg
            received["job_id"] = job_id
            received["cache_key"] = cache_key
            received["agent_dir"] = agent_dir
            return sentinel

        result = asset_qualification._run_inspection(cand, beat, 1, "/c", "k", "/a", inspector)

        assert result is sentinel  # returns the inspector's result unchanged
        assert received["candidate"] is cand
        assert received["beat"] is beat
        assert received["job_id"] == 1
        assert received["cache_key"] == "k"
        assert received["agent_dir"] == "/a"

    def test_returns_none_when_no_inspector(self) -> None:
        """No inspector injected → graceful None (candidate rejected downstream), not a crash."""
        result = asset_qualification._run_inspection(
            _make_candidate(), _make_beat(), 1, "/c", "k", "/a", None
        )
        assert result is None


# ---------------------------------------------------------------------------
# SLICE 2 — happy-path qualified set (accept + revised)
#
# Drives the public entry ``qualify_research_candidates`` + ``_qualify_beat``:
# score every candidate (cache-hit) → rank via ``rank_candidates`` → if any
# candidate is {accept, revise} the beat is ``verdict='qualified'`` with no
# recovery and no text card. The recovery-before-text-card path is SLICE 3;
# here it must NOT fire, and the not-qualified branch raises fail-loud
# (mirroring the SLICE 1 ``_run_inspection`` stub discipline).
# ---------------------------------------------------------------------------


def _high_inspection() -> dict:
    """Inspection that clears every rejection rule and the accept threshold (~0.84)."""
    return {
        "decision": "accept",
        "subject_name": "Point 1",
        "person_match": 0.9,
        "event_match": 0.85,
        "claim_support": 0.9,
        "visual_quality": 0.8,
        "misleading_risk": 0.1,
        "source_credibility": 0.8,
    }


def _low_inspection() -> dict:
    """Inspection that fails the HIGH_MISLEADING_RISK hard rule (misleading_risk=0.8)."""
    return {
        "decision": "reject",
        "subject_name": "Point 1",
        "person_match": 0.1,
        "event_match": 0.1,
        "claim_support": 0.2,
        "visual_quality": 0.2,
        "misleading_risk": 0.8,
        "source_credibility": 0.1,
    }


def _mid_inspection() -> dict:
    """Inspection scoring 'revise' (final ~0.54, below the 0.60 accept threshold)
    while clearing every rejection rule. Verifies rank order + the revise-qualified
    contract."""
    return {
        "decision": "revise",
        "subject_name": "Point 1",
        "person_match": 0.5,
        "event_match": 0.5,
        "claim_support": 0.6,
        "visual_quality": 0.5,
        "misleading_risk": 0.2,
        "source_credibility": 0.0,
    }


class TestQualifyBeatHappyPath:
    """SLICE 2 — accept-scoring candidates yield ``verdict='qualified'``.

    The pre-VD orchestration (score → rank → qualified-check) must assemble a
    ``BeatQualificationResult`` with the accept+revised candidates in rank order,
    populated ``reject_reasons`` for the rejects, and NO recovery / text card.
    """

    def test_accept_candidate_yields_qualified(self) -> None:
        cand = _make_candidate("tiktok_clip", "https://a.com/clip1.mp4")
        beat = _make_beat(beat_id=1, asset_candidates=[cand])
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir="/tmp/cache",
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=None,
            plan_item=None,
        )

        with patch(
            "clipper_agency.core.asset_qualification.lookup",
            return_value=_high_inspection(),
        ):
            result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        assert isinstance(result, asset_qualification.BeatQualificationResult)
        assert result.beat_id == "1"
        assert result.verdict == "qualified"
        assert result.recovery_outcome == "none"
        assert result.recovery_attempts == 0
        assert result.fallback_card is None
        assert len(result.qualified) == 1
        # Rank order preserved + the scored dict is the exact rank_candidates shape
        # (carries the live AssetCandidate for the engine-seam rewrite).
        assert result.qualified[0]["candidate"] is cand
        assert result.qualified[0]["candidate"].url == "https://a.com/clip1.mp4"
        assert len(result.scored) == 1
        assert result.reject_reasons == {}
        assert result.provider_attempts_added == []

    def test_mixed_accept_andreject_aggregates_qualified_set(self, tmp_path: Any) -> None:
        good = _make_candidate("tiktok_clip", "https://a.com/good.mp4")
        bad = _make_candidate("tiktok_clip", "https://b.com/bad.mp4")
        beat = _make_beat(beat_id=2, asset_candidates=[good, bad])
        cache_dir = str(tmp_path / "inspection_cache")

        # Pre-populate the REAL inspection cache per candidate (real cache keys,
        # matching _score_candidate's literals) so good→accept, bad→reject with
        # no compute_cache_key/lookup mocking. Mirrors the VD cache-test idiom and
        # implicitly re-verifies SLICE 1 cache-key parity.
        from clipper_agency.core.inspection_cache import store as cache_store

        for cand, insp in ((good, _high_inspection()), (bad, _low_inspection())):
            cache_store(
                cache_dir,
                compute_candidate_cache_key(
                    cand,
                    beat.spoken_point,
                    beat.visual_must_show,
                    beat.visual_must_not_show,
                ),
                insp,
            )

        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=None,
            plan_item=None,
        )
        result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        # The accept candidate qualifies the beat; the reject is recorded, not rendered.
        assert result.verdict == "qualified"
        assert len(result.qualified) == 1
        assert result.qualified[0]["candidate"] is good
        assert len(result.scored) == 2
        assert len(result.reject_reasons) == 1
        bad_id = f"tiktok_clip_{bad.url[:40]}"
        assert result.reject_reasons[bad_id] == "HIGH_MISLEADING_RISK"

    def test_uninspectable_candidate_is_skipped(self, tmp_path: Any) -> None:
        """A candidate whose inspection yields None is dropped — not fatal to the beat."""
        good = _make_candidate("tiktok_clip", "https://a.com/good.mp4")
        broken = _make_candidate("tiktok_clip", "https://x.com/broken.mp4")
        beat = _make_beat(beat_id=4, asset_candidates=[good, broken])
        cache_dir = str(tmp_path / "inspection_cache")

        # good hits the real cache (accept); broken misses cache and its
        # inspection yields None (patched) → _score_candidate returns None → skipped.
        from clipper_agency.core.inspection_cache import store as cache_store

        cache_store(
            cache_dir,
            compute_candidate_cache_key(
                good,
                beat.spoken_point,
                beat.visual_must_show,
                beat.visual_must_not_show,
            ),
            _high_inspection(),
        )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=None,
            plan_item=None,
        )
        with patch(
            "clipper_agency.core.asset_qualification._run_inspection",
            return_value=None,
        ):
            result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        assert result.verdict == "qualified"
        assert len(result.qualified) == 1
        assert result.qualified[0]["candidate"] is good
        # broken was dropped before ranking — it is absent from the scored set.
        assert len(result.scored) == 1

    def test_rank_order_two_qualified_candidates(self, tmp_path: Any) -> None:
        """The qualified list preserves rank order — highest score first.

        Two candidates both clear the qualified bar: one accept (high score), one
        revise (mid score). qualified[0] must be the higher-scoring accept. A
        single-accept test cannot verify this load-bearing contract; this one does.
        """
        high = _make_candidate("tiktok_clip", "https://a.com/high.mp4")
        mid = _make_candidate("tiktok_clip", "https://m.com/mid.mp4")
        beat = _make_beat(beat_id=6, asset_candidates=[high, mid])
        cache_dir = str(tmp_path / "inspection_cache")

        from clipper_agency.core.inspection_cache import store as cache_store

        for cand, insp in ((high, _high_inspection()), (mid, _mid_inspection())):
            cache_store(
                cache_dir,
                compute_candidate_cache_key(
                    cand,
                    beat.spoken_point,
                    beat.visual_must_show,
                    beat.visual_must_not_show,
                ),
                insp,
            )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=None,
            plan_item=None,
        )
        result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        assert result.verdict == "qualified"
        assert len(result.qualified) == 2
        # Rank order: the higher-scoring accept precedes the lower-scoring revise.
        assert result.qualified[0]["candidate"] is high
        assert result.qualified[1]["candidate"] is mid

    def test_revise_only_beat_is_qualified(self) -> None:
        """A beat whose only candidate scores 'revise' is still verdict='qualified'.

        Design §7 step 3 treats {accept, revise} as qualified. Note (design §8):
        VD._apply_best_candidate only RENDERS on decision=='accept'
        (visual_director.py:1104), so a revise-only 'qualified' beat may still
        render as a text card — VD retains that authority as defense-in-depth.
        This test pins the qualification verdict, not VD's render decision.
        """
        mid = _make_candidate("tiktok_clip", "https://m.com/mid.mp4")
        beat = _make_beat(beat_id=7, asset_candidates=[mid])
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir="/tmp/cache",
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=None,
            plan_item=None,
        )
        with patch(
            "clipper_agency.core.asset_qualification.lookup",
            return_value=_mid_inspection(),
        ):
            result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        assert result.verdict == "qualified"
        assert len(result.qualified) == 1
        assert result.qualified[0]["candidate"] is mid

    def test_exhausted_text_card_when_no_recovery(self) -> None:
        """SLICE 4 — all-reject with no recovery policy → terminal text-card fallback.

        recovery_outcome='no_fn' (recovery not configured); fallback_card mirrors
        VD's text-card shape; qualified is empty. This is the ONLY path that emits a
        text card — and it never fires silently (only after qualification fails).
        """
        cand = _make_candidate("tiktok_clip", "https://b.com/bad.mp4")
        beat = _make_beat(beat_id=3, asset_candidates=[cand])
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir="/tmp/cache",
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=None,
            plan_item=None,
        )

        with patch(
            "clipper_agency.core.asset_qualification.lookup",
            return_value=_low_inspection(),
        ):
            result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        assert result.verdict == "exhausted_text_card"
        assert result.recovery_outcome == "no_fn"
        assert result.recovery_attempts == 0
        assert result.qualified == []
        assert result.fallback_card is not None
        assert result.fallback_card["type"] == "text_card"
        assert (
            result.fallback_card["headline"] == (beat.overlay_text or f"Beat {beat.beat_id}")[:60]
        )
        assert result.fallback_card["style"] == "news_card"


# ---------------------------------------------------------------------------
# SLICE 3 — all-reject → source recovery BEFORE text card (the Job #8 fix).
#
# When a beat has zero qualified candidates, a RECOVER stage runs the injected
# discovery callable BEFORE any text-card fallback. If recovery yields a
# qualified candidate the beat is ``verdict='recovered'`` — never a text card.
# The terminal text-card fallback (recovery exhausted / disabled) is SLICE 4.
# ---------------------------------------------------------------------------


class TestQualifyBeatRecoveryBeforeTextCard:
    """SLICE 3 — recovery runs before the text-card fallback and can rescue a beat."""

    def test_recovery_rescues_all_reject_beat(self, tmp_path: Any) -> None:
        bad = _make_candidate("tiktok_clip", "https://b.com/bad.mp4")  # rejects
        rescued = _make_candidate("tiktok_clip", "https://r.com/rescued.mp4")  # accepts
        beat = _make_beat(beat_id=5, asset_candidates=[bad])
        cache_dir = str(tmp_path / "inspection_cache")

        # bad→low (rejects on the original pass); rescued→high (accepts after recovery).
        from clipper_agency.core.inspection_cache import store as cache_store

        for cand, insp in ((bad, _low_inspection()), (rescued, _high_inspection())):
            cache_store(
                cache_dir,
                compute_candidate_cache_key(
                    cand,
                    beat.spoken_point,
                    beat.visual_must_show,
                    beat.visual_must_not_show,
                ),
                insp,
            )

        discover_calls: list[list[str]] = []

        def discover_fn(queries: list[str]) -> tuple[list[dict], list[dict]]:
            discover_calls.append(list(queries))
            return (
                [{"type": "tiktok_clip", "url": rescued.url, "reason": "recovered"}],
                [{"provider": "youtube"}],
            )

        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=1, discover_fn=discover_fn
        )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=recovery,
            plan_item=None,
        )
        result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        # Recovery ran BEFORE any text card: discover_fn called once with the
        # expanded per-beat queries built from visual_must_show + spoken_point.
        assert len(discover_calls) == 1
        assert beat.visual_must_show in discover_calls[0]
        assert beat.spoken_point in discover_calls[0]
        # The beat was rescued — 'recovered', NOT a text card.
        assert result.verdict == "recovered"
        assert result.recovery_outcome == "ran"
        assert result.recovery_attempts == 1
        assert result.fallback_card is None
        assert len(result.qualified) == 1
        assert result.qualified[0]["candidate"].url == rescued.url
        assert len(result.provider_attempts_added) == 1
        assert result.provider_attempts_added[0]["provider"] == "youtube"

    def test_recovery_skips_malformed_discovery_items(self, tmp_path: Any) -> None:
        """A non-mapping discovery item is logged+skipped, not crash the whole pass."""
        bad = _make_candidate("tiktok_clip", "https://b.com/bad.mp4")
        rescued = _make_candidate("tiktok_clip", "https://r.com/rescued.mp4")
        beat = _make_beat(beat_id=9, asset_candidates=[bad])
        cache_dir = str(tmp_path / "inspection_cache")

        from clipper_agency.core.inspection_cache import store as cache_store

        for cand, insp in ((bad, _low_inspection()), (rescued, _high_inspection())):
            cache_store(
                cache_dir,
                compute_candidate_cache_key(
                    cand,
                    beat.spoken_point,
                    beat.visual_must_show,
                    beat.visual_must_not_show,
                ),
                insp,
            )

        # First discovery item is malformed (None); the valid one still rescues the beat.
        def discover_fn(_queries: list[str]) -> tuple[list, list[dict]]:
            return ([None, {"type": "tiktok_clip", "url": rescued.url, "reason": "r"}], [])

        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=1, discover_fn=discover_fn
        )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=recovery,
            plan_item=None,
        )
        result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        # The malformed None was skipped; the valid candidate rescued the beat.
        assert result.verdict == "recovered"
        assert len(result.qualified) == 1
        assert result.qualified[0]["candidate"].url == rescued.url

    def test_exhausted_text_card_when_recovery_yields_nothing(self, tmp_path: Any) -> None:
        """SLICE 4 — recovery ran but yielded no qualified candidate → terminal text card.

        recovery_outcome='exhausted', recovery_attempts=1; recovery WAS attempted
        (discover_fn called) before the fallback. The text card is the last resort.
        """
        bad = _make_candidate("tiktok_clip", "https://b.com/bad.mp4")
        still_bad = _make_candidate("tiktok_clip", "https://r.com/stillbad.mp4")
        beat = _make_beat(beat_id=10, asset_candidates=[bad])
        cache_dir = str(tmp_path / "inspection_cache")

        from clipper_agency.core.inspection_cache import store as cache_store

        for cand, insp in ((bad, _low_inspection()), (still_bad, _low_inspection())):
            cache_store(
                cache_dir,
                compute_candidate_cache_key(
                    cand,
                    beat.spoken_point,
                    beat.visual_must_show,
                    beat.visual_must_not_show,
                ),
                insp,
            )

        discover_calls: list[list[str]] = []

        def discover_fn(queries: list[str]) -> tuple[list[dict], list[dict]]:
            discover_calls.append(list(queries))
            # Recovery re-discovers a candidate that ALSO rejects.
            return (
                [{"type": "tiktok_clip", "url": still_bad.url, "reason": "r"}],
                [{"provider": "youtube"}],
            )

        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=1, discover_fn=discover_fn
        )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=recovery,
            plan_item=None,
        )
        result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        # Recovery was attempted (discover_fn called once) but still no qualified candidate.
        assert len(discover_calls) == 1
        assert result.verdict == "exhausted_text_card"
        assert result.recovery_outcome == "exhausted"
        assert result.recovery_attempts == 1
        assert result.qualified == []
        assert result.fallback_card is not None
        assert result.fallback_card["type"] == "text_card"
        assert result.fallback_card["style"] == "news_card"
        assert len(result.provider_attempts_added) == 1
        assert result.provider_attempts_added[0]["provider"] == "youtube"


# ---------------------------------------------------------------------------
# FIX-3 round-2 (codex) — unverifiable entity assets must trigger RECOVER, not
# silently qualify as 'revise' and skip recovery for the assets FIX-3 targets.
# ---------------------------------------------------------------------------


class TestUnverifiableEntityTriggersRecovery:
    """A person-depicting asset the VLM could NOT name on an entity-binding beat is
    excluded from ``qualified`` even though ``rank_candidates`` downgrades it to
    ``revise`` (not ``reject``). The ``revise`` verdict used to count as qualified,
    skipping RECOVER and silently falling back to a text card. Now RECOVER fires
    first (finding #4)."""

    def test_unverifiable_person_triggers_recover_not_qualified(self, tmp_path: Any) -> None:
        # Entity-binding beat: derive_expected_entities yields non-empty tokens
        # from visual_must_show + spoken_point (e.g. ["visual", "point"]).
        unverifiable = _make_candidate("tiktok_clip", "https://u.com/unverifiable.mp4")
        rescued = _make_candidate("tiktok_clip", "https://r.com/rescued.mp4")
        beat = _make_beat(beat_id=7, asset_candidates=[unverifiable])
        cache_dir = str(tmp_path / "inspection_cache")

        # unverifiable: person depicted (person_match >= 0.5), high claim (would
        # accept), but the VLM could not name the subject (subject_name=""). NOTE:
        # subject_name is the EMPTY STRING (key present), NOT absent — the stale-cache
        # guard only treats a MISSING key as stale, so this cache entry HITS, and the
        # is_unverifiable_entity_binding predicate (``not ""``) then excludes it.
        unverifiable_insp = {
            "decision": "accept",
            "subject_name": "",
            "person_match": 0.9,
            "event_match": 0.8,
            "claim_support": 0.9,
            "visual_quality": 0.8,
            "misleading_risk": 0.1,
            "source_credibility": 0.8,
        }
        # rescued: a clean non-person high-claim accept (recovery finds it).
        rescued_insp = {
            "decision": "accept",
            "subject_name": "",
            "person_match": 0.1,
            "event_match": 0.85,
            "claim_support": 0.9,
            "visual_quality": 0.8,
            "misleading_risk": 0.1,
            "source_credibility": 0.8,
        }
        from clipper_agency.core.inspection_cache import store as cache_store

        for cand, insp in (
            (unverifiable, unverifiable_insp),
            (rescued, rescued_insp),
        ):
            cache_store(
                cache_dir,
                compute_candidate_cache_key(
                    cand,
                    beat.spoken_point,
                    beat.visual_must_show,
                    beat.visual_must_not_show,
                ),
                insp,
            )

        discover_calls: list[list[str]] = []

        def discover_fn(queries: list[str]) -> tuple[list[dict], list[dict]]:
            discover_calls.append(list(queries))
            return (
                [{"type": "tiktok_clip", "url": rescued.url, "reason": "recovered"}],
                [{"provider": "youtube"}],
            )

        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=1, discover_fn=discover_fn
        )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=recovery,
            plan_item=None,
        )
        result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        # RECOVER ran (not a direct text-card fallback) — the missing-subject
        # candidate was excluded from qualified, leaving qualified empty pre-recovery.
        assert len(discover_calls) == 1
        assert result.verdict == "recovered"
        assert result.recovery_outcome == "ran"
        assert result.fallback_card is None
        # The rescued candidate is the one that qualified — NOT the unverifiable one.
        assert len(result.qualified) == 1
        assert result.qualified[0]["candidate"].url == rescued.url
        # The unverifiable candidate is recorded as an UNVERIFIABLE_ENTITY reject
        # (not silently accepted as 'revise').
        unverifiable_id = f"tiktok_clip_{unverifiable.url[:40]}"
        assert result.reject_reasons.get(unverifiable_id) == "UNVERIFIABLE_ENTITY"

    def test_unverifiable_person_without_recovery_falls_back_to_text_card(
        self, tmp_path: Any
    ) -> None:
        """Recovery disabled: the unverifiable candidate is still excluded from
        qualified, so the beat falls back to a text card (safe) rather than using
        the unverified person asset."""
        unverifiable = _make_candidate("tiktok_clip", "https://u.com/unverifiable2.mp4")
        beat = _make_beat(beat_id=8, asset_candidates=[unverifiable])
        cache_dir = str(tmp_path / "inspection_cache")

        unverifiable_insp = {
            "decision": "accept",
            "subject_name": "",
            "person_match": 0.9,
            "event_match": 0.8,
            "claim_support": 0.9,
            "visual_quality": 0.8,
            "misleading_risk": 0.1,
            "source_credibility": 0.8,
        }
        from clipper_agency.core.inspection_cache import store as cache_store

        cache_store(
            cache_dir,
            compute_candidate_cache_key(
                unverifiable,
                beat.spoken_point,
                beat.visual_must_show,
                beat.visual_must_not_show,
            ),
            unverifiable_insp,
        )

        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=None,  # recovery disabled
            plan_item=None,
        )
        result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        # Not qualified — the unverified person asset did NOT slip through as
        # 'revise'. Terminal text-card fallback (the safe outcome).
        assert result.verdict == "exhausted_text_card"
        assert result.qualified == []
        assert result.fallback_card is not None
        unverifiable_id = f"tiktok_clip_{unverifiable.url[:40]}"
        assert result.reject_reasons.get(unverifiable_id) == "UNVERIFIABLE_ENTITY"


# ---------------------------------------------------------------------------
# SLICE 5 — MAX_RECOVERY_CYCLES bound: recovery runs at most one pass (no loop).
#
# Recovery is structurally single-cycle (no while/for loop; max_cycles is a 0/1 gate).
# SLICE 4's recovery-exhausted test already pins the 1-cycle path (discover_fn called
# exactly once, recovery_attempts==1). This slice pins the 0-side of the gate.
# ---------------------------------------------------------------------------


class TestRecoveryBoundMaxOneCycle:
    """SLICE 5 — the recovery bound: max_cycles=0 skips recovery; =1 runs one pass."""

    def test_max_cycles_zero_skips_recovery(self, tmp_path: Any) -> None:
        """max_cycles=0 disables recovery — discover_fn is never called, no loop risk."""
        bad = _make_candidate("tiktok_clip", "https://b.com/bad.mp4")
        beat = _make_beat(beat_id=11, asset_candidates=[bad])
        cache_dir = str(tmp_path / "inspection_cache")

        from clipper_agency.core.inspection_cache import store as cache_store

        cache_store(
            cache_dir,
            compute_candidate_cache_key(
                bad,
                beat.spoken_point,
                beat.visual_must_show,
                beat.visual_must_not_show,
            ),
            _low_inspection(),
        )

        discover_calls: list[list[str]] = []

        def discover_fn(queries: list[str]) -> tuple[list[dict], list[dict]]:
            discover_calls.append(queries)
            return ([], [])

        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=0, discover_fn=discover_fn
        )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir=cache_dir,
            agent_dir="/tmp/agent",
            inspector=None,
            recovery=recovery,
            plan_item=None,
        )
        result = asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)

        assert discover_calls == []  # recovery skipped entirely
        assert result.recovery_attempts == 0
        assert result.recovery_outcome == "no_fn"
        assert result.verdict == "exhausted_text_card"


class TestToAssetCandidate:
    """``_to_asset_candidate`` coerces discovery results (dict OR model) to AssetCandidate."""

    def test_passes_through_existing_model(self) -> None:
        cand = _make_candidate()
        assert asset_qualification._to_asset_candidate(cand) is cand

    def test_coerces_dict(self) -> None:
        coerced = asset_qualification._to_asset_candidate(
            {"type": "tiktok_clip", "url": "https://x.com/c.mp4", "reason": "discovered"}
        )
        assert isinstance(coerced, AssetCandidate)
        assert coerced.url == "https://x.com/c.mp4"


class TestQualifyResearchCandidatesPublicEntry:
    """SLICE 2 — the public entry parses ``research_output['story_beats']`` into
    StoryBeats and qualifies each beat, returning one result per beat.
    """

    def test_parses_beats_and_qualifies_each(self) -> None:
        beat_a = _make_beat(
            beat_id=1, asset_candidates=[_make_candidate("tiktok_clip", "https://a.com/1.mp4")]
        )
        beat_b = _make_beat(
            beat_id=2, asset_candidates=[_make_candidate("tiktok_clip", "https://a.com/2.mp4")]
        )
        research_output = {"story_beats": [beat_a.model_dump(), beat_b.model_dump()]}

        with patch(
            "clipper_agency.core.asset_qualification.lookup",
            return_value=_high_inspection(),
        ):
            results = asset_qualification.qualify_research_candidates(
                research_output, 1, "/tmp/cache", "/tmp/agent"
            )

        assert len(results) == 2
        assert all(r.verdict == "qualified" for r in results)
        assert [r.beat_id for r in results] == ["1", "2"]
        assert all(len(r.qualified) == 1 for r in results)

    def test_empty_story_beats_returns_empty_list(self) -> None:
        results = asset_qualification.qualify_research_candidates(
            {"story_beats": []}, 1, "/tmp/cache", "/tmp/agent"
        )
        assert results == []


# ---------------------------------------------------------------------------
# SLICE 11 — qualification_report.json serializer (design §5).
#
# ``build_qualification_report`` is a PURE serializer over the already-built
# ``BeatQualificationResult`` list — no new schema, no I/O. The engine seam
# (SLICE 7) writes its output via ``write_json``. These tests pin the
# documented artifact shape (summary counts + per-beat verdict/top-asset rows)
# so the HARD verification gate ("qualification_report.json exists with the
# documented shape") is enforceable.
# ---------------------------------------------------------------------------


class TestStaleCacheReinspectionGuard:
    """FIX-3 R-1 — a cached inspection missing the ``subject_name`` key is treated
    as a cache MISS and re-inspected (self-healing on resume/retry after the FIX-3
    deploy, so Slice-3 doesn't mass-downgrade stale person-assets to 'revise')."""

    def _cache_key(self, cand: AssetCandidate, beat: StoryBeat) -> str:
        return compute_candidate_cache_key(
            cand,
            beat.spoken_point,
            beat.visual_must_show,
            beat.visual_must_not_show,
        )

    def test_stale_cache_triggers_reinspection(self, tmp_path: Any) -> None:
        from clipper_agency.core.inspection_cache import store as cache_store

        cand = _make_candidate()
        beat = _make_beat()
        cache_dir = str(tmp_path / "inspection_cache")
        # STALE: pre-FIX-3 inspection with NO subject_name key.
        stale = {
            "decision": "accept",
            "person_match": 0.9,
            "event_match": 0.85,
            "claim_support": 0.9,
            "visual_quality": 0.8,
            "misleading_risk": 0.1,
            "source_credibility": 0.8,
        }
        cache_store(cache_dir, self._cache_key(cand, beat), stale)

        fresh = dict(stale, subject_name="Point 1")
        mock_inspector = MagicMock(return_value=fresh)
        scored = asset_qualification._score_candidate(
            cand, beat, None, 1, cache_dir, "/tmp/agent", inspector=mock_inspector
        )
        assert scored is not None
        # Guard saw no subject_name -> treated as MISS -> inspector re-invoked.
        mock_inspector.assert_called_once()
        # The fresh (subject_name-bearing) inspection is what's recorded.
        assert scored["inspection"].get("subject_name") == "Point 1"
        # Decoration is attached (entity-binding parity). derive_expected_entities
        # binds AUTHORITATIVELY from visual_must_show ("Point N") — spoken_point
        # is a fallback only when visual_must_show yields no entities (FIX-3 r3).
        assert scored["expected_entities"] == [["point"]]

    def test_fresh_cache_skips_reinspection(self, tmp_path: Any) -> None:
        from clipper_agency.core.inspection_cache import store as cache_store

        cand = _make_candidate()
        beat = _make_beat()
        cache_dir = str(tmp_path / "inspection_cache")
        # FRESH: post-FIX-3 inspection WITH subject_name -> cache hit, no re-inspect.
        cache_store(cache_dir, self._cache_key(cand, beat), _high_inspection())

        mock_inspector = MagicMock(return_value=_high_inspection())
        scored = asset_qualification._score_candidate(
            cand, beat, None, 1, cache_dir, "/tmp/agent", inspector=mock_inspector
        )
        assert scored is not None
        mock_inspector.assert_not_called()


def _scored_dict(asset_id: str, quality: float = 0.9) -> dict:
    """A scored candidate dict in the exact ``_score_candidate`` output shape.

    ``compute_final_score`` reads ``inspection`` (mean of inspection dims +
    ``source_credibility``), ``visual_relevance`` (mean of relevance dims), and
    ``cleanliness_score`` — so all three are populated here.
    """
    return {
        "asset_id": asset_id,
        "beat_id": "1",
        "role": "evidence",
        "treatment": "broll_standard",
        "inspection": {
            "decision": "accept",
            "person_match": quality,
            "event_match": quality,
            "claim_support": quality,
            "visual_quality": quality,
            "misleading_risk": 0.1,
            "source_credibility": quality,
        },
        "visual_relevance": {
            "person_match": quality,
            "event_match": quality,
            "claim_support": quality,
            "visual_quality": quality,
        },
        "cleanliness_score": quality,
        "candidate": _make_candidate("tiktok_clip", f"https://x.com/{asset_id}.mp4"),
        "inspection_diag": {"beat_id": 1, "asset_id": asset_id, "from_cache": True},
    }


class TestBuildQualificationReport:
    """SLICE 11 — the report serializer shape (design §5)."""

    def test_report_shape_and_summary_counts(self) -> None:
        from clipper_agency.core.candidate_semantic_ranker import compute_final_score

        qualified = asset_qualification.BeatQualificationResult(
            beat_id="1",
            verdict="qualified",
            recovery_outcome="none",
            recovery_attempts=0,
            qualified=[_scored_dict("tiktok_clip_q1")],
            scored=[_scored_dict("tiktok_clip_q1")],
            reject_reasons={},
        )
        recovered = asset_qualification.BeatQualificationResult(
            beat_id="2",
            verdict="recovered",
            recovery_outcome="ran",
            recovery_attempts=1,
            qualified=[_scored_dict("tiktok_clip_r1")],
            scored=[_scored_dict("tiktok_clip_r1")],
            reject_reasons={},
            provider_attempts_added=[{"provider": "youtube"}, {"provider": "tavily"}],
        )
        exhausted = asset_qualification.BeatQualificationResult(
            beat_id="3",
            verdict="exhausted_text_card",
            recovery_outcome="exhausted",
            recovery_attempts=1,
            qualified=[],
            scored=[],
            reject_reasons={"tiktok_clip_bad": "HIGH_MISLEADING_RISK"},
            fallback_card={"type": "text_card", "headline": "X", "style": "news_card"},
            provider_attempts_added=[{"provider": "youtube"}],
        )

        report = asset_qualification.build_qualification_report(
            8, [qualified, recovered, exhausted]
        )

        # Top-level envelope
        assert report["job_id"] == 8
        assert isinstance(report["generated_at"], str) and report["generated_at"]
        assert report["summary"] == {
            "total_beats": 3,
            "qualified_beats": 1,
            "recovered_beats": 1,
            "text_card_last_resort_beats": 1,
            "providers_attempted_added": 3,  # 0 + 2 + 1
        }
        # Per-beat rows preserve input order and carry the documented fields.
        assert [b["beat_id"] for b in report["beats"]] == ["1", "2", "3"]
        row1 = report["beats"][0]
        assert row1["verdict"] == "qualified"
        assert row1["qualified_count"] == 1
        assert row1["top_asset_id"] == "tiktok_clip_q1"
        # top_score is the ranker's own final score (DRY — single source of truth).
        assert row1["top_score"] == round(
            compute_final_score(
                _scored_dict("tiktok_clip_q1")["inspection"],
                _scored_dict("tiktok_clip_q1")["visual_relevance"],
                _scored_dict("tiktok_clip_q1")["cleanliness_score"],
            ),
            4,
        )
        # The recovered beat shares the same top-score code path — pin it too.
        row2 = report["beats"][1]
        assert row2["verdict"] == "recovered"
        assert row2["top_asset_id"] == "tiktok_clip_r1"
        assert row2["top_score"] == round(
            compute_final_score(
                _scored_dict("tiktok_clip_r1")["inspection"],
                _scored_dict("tiktok_clip_r1")["visual_relevance"],
                _scored_dict("tiktok_clip_r1")["cleanliness_score"],
            ),
            4,
        )
        # The exhausted beat has no top asset.
        row3 = report["beats"][2]
        assert row3["verdict"] == "exhausted_text_card"
        assert row3["top_asset_id"] is None
        assert row3["top_score"] == 0.0
        assert row3["qualified_count"] == 0
        assert row3["reject_reasons"] == {"tiktok_clip_bad": "HIGH_MISLEADING_RISK"}

    def test_empty_results_summary_is_zero(self) -> None:
        report = asset_qualification.build_qualification_report(42, [])
        assert report["summary"] == {
            "total_beats": 0,
            "qualified_beats": 0,
            "recovered_beats": 0,
            "text_card_last_resort_beats": 0,
            "providers_attempted_added": 0,
        }
        assert report["beats"] == []


# ---------------------------------------------------------------------------
# SLICE 7 — SP discovery adapter (design §4 [V1]).
#
# ``_build_sp_discovery_adapter`` curries ``(sp, topic, entities, config, beats)``
# into the ``discover_fn`` callable the recovery stage calls. It reuses SP's
# existing discovery primitives (``_discover_multi_source_assets`` instance
# method + ``_build_asset_candidates_from_sources`` @staticmethod) — no
# reimplementation (ADR 0026 / DRY). The module imports NEITHER segment_producer
# NOR visual_director: ``sp`` is an opaque object whose methods are called.
# ---------------------------------------------------------------------------


class TestBuildSpDiscoveryAdapter:
    """SLICE 7 — the adapter curries SP discovery into the recovery ``discover_fn``."""

    def test_adapter_curries_and_calls_sp_discovery(self) -> None:
        sources = [{"url": "https://yt/1", "source_type": "tiktok_clip"}]
        attempts = [{"provider": "youtube", "query": "q", "result_count": 1}]
        recorded: dict[str, Any] = {}

        class FakeSP:
            def _discover_multi_source_assets(
                self, topic: str, entities: list, config: Any, beats: list | None = None
            ) -> tuple[list[dict], list[dict]]:
                recorded["topic"] = topic
                recorded["entities"] = entities
                recorded["config"] = config
                recorded["beats"] = beats
                return sources, attempts

            @staticmethod
            def _build_asset_candidates_from_sources(
                sources: list[dict] | None = None, **_: Any
            ) -> list[dict]:
                recorded["sources_passed"] = sources
                return [
                    {"type": "tiktok_clip", "url": s["url"], "reason": "x"} for s in (sources or [])
                ]

        beats = [{"beat_id": 1}]
        discover_fn = asset_qualification._build_sp_discovery_adapter(
            FakeSP(), "TOPIC", ["ent"], "CFG", beats=beats
        )

        # discover_fn accepts queries (recovery contract) but delegates query-building
        # to _discover_multi_source_assets, which builds its own from the curried beats.
        candidate_dicts, atts = discover_fn(["q1", "q2"])

        # The curried args reach SP discovery verbatim (incl. the failing beat set).
        assert recorded["topic"] == "TOPIC"
        assert recorded["entities"] == ["ent"]
        assert recorded["config"] == "CFG"
        assert recorded["beats"] == beats
        # The raw sources flow through the @staticmethod candidate transform.
        assert recorded["sources_passed"] == sources
        # Return shape matches the recovery contract: (candidate_dicts, attempts).
        assert len(candidate_dicts) == 1
        assert candidate_dicts[0]["url"] == "https://yt/1"
        assert atts == attempts

    def test_adapter_defaults_beats_none(self) -> None:
        """beats=None is a valid curry (SP discovery falls back to entity queries)."""
        recorded: dict[str, Any] = {}

        class FakeSP:
            def _discover_multi_source_assets(
                self, topic: str, entities: list, config: Any, beats: list | None = None
            ) -> tuple[list[dict], list[dict]]:
                recorded["beats"] = beats
                return [], [{"provider": "youtube"}]

            @staticmethod
            def _build_asset_candidates_from_sources(
                sources: list[dict] | None = None, **_: Any
            ) -> list[dict]:
                return []

        discover_fn = asset_qualification._build_sp_discovery_adapter(
            FakeSP(),
            "T",
            [],
            "C",  # beats omitted → None
        )
        candidate_dicts, atts = discover_fn(["q"])
        assert recorded["beats"] is None
        assert candidate_dicts == []
        assert len(atts) == 1


# ---------------------------------------------------------------------------
# SLICE 10 — VD hand-off transparency: 0 double-VLM.
#
# The 0-double-VLM property is a CONSEQUENCE of SLICE 1 cache-key parity + the seam
# feeding VD only pre-qualified (already-inspected) candidates: when VD re-scores such a
# candidate its ``lookup`` is a hit, so ``_run_multimodal_inspection`` is never invoked.
# This regression pins that behavioral cost outcome (distinct from SLICE 1's static
# cache-key parity assertion) so a future literal drift at either scorer fails loudly.
# ---------------------------------------------------------------------------


class TestZeroDoubleVlmHandoff:
    """SLICE 10 — VD re-inspection of a pre-qualified candidate is a cache hit."""

    def test_vd_reinspection_hits_cache_after_pre_vd_score(self, tmp_path: Any) -> None:
        from clipper_agency.agents.visual_director import VisualDirectorAgent
        from clipper_agency.core.inspection_cache import store as cache_store

        cand = _make_candidate("tiktok_clip", "https://a.com/shared.mp4")
        beat = _make_beat(beat_id=1)
        plan_item = _make_plan_item()
        cache_dir = str(tmp_path / "inspection_cache")
        inspection = _high_inspection()

        # Pre-VD pass: cache MISS -> inspect -> STORE under the shared cache key.
        def fake_inspect(
            candidate: Any,
            beat_arg: Any,
            job_id: int,
            cdir: str,
            cache_key: str,
            agent_dir: str,
            inspector: Any,
        ) -> dict:
            cache_store(cdir, cache_key, inspection)
            return inspection

        with (
            patch("clipper_agency.core.asset_qualification.lookup", return_value=None),
            patch(
                "clipper_agency.core.asset_qualification._run_inspection",
                side_effect=fake_inspect,
            ),
        ):
            aq_result = asset_qualification._score_candidate(
                cand, beat, plan_item, 1, cache_dir, "/agent", inspector=object()
            )
        assert aq_result is not None  # pre-VD pass scored + populated the cache

        # VD re-scores the SAME candidate/beat/cache_dir. Its lookup MUST hit the cache the
        # pre-VD pass populated, so VD's multimodal inspector is never invoked (0 double-VLM).
        agent = VisualDirectorAgent()
        with patch.object(
            agent,
            "_run_multimodal_inspection",
            side_effect=AssertionError("VLM re-spent on a pre-qualified candidate"),
        ) as mock_inspect:
            vd_result = agent._score_one_candidate(cand, beat, plan_item, 1, cache_dir, "/agent")

        assert mock_inspect.call_count == 0
        assert vd_result is not None
        assert vd_result["inspection_diag"]["from_cache"] is True


class TestPr8CostOptimization:
    """PR 8 — pre-VLM keyword-overlap skip gate (option 1) + RECOVER cap (option 9).

    Resolves the job_11 rejection storm: no cheap filter existed before the VLM, so
    every irrelevant candidate paid a full Gemini call. The skip gate drops zero-
    overlap candidates without inspection; the RECOVER cap bounds fresh inspections
    per all-reject beat.
    """

    def test_prefilter_skips_zero_overlap_without_vlm(self, tmp_path: Any) -> None:
        """Zero keyword-overlap candidate is skipped before the VLM (option 1)."""
        beat = _make_beat(beat_id=42, spoken_point="Mount Fuji sunrise climb")
        # 'basketball playoffs' shares NO tokens with the beat -> overlap 0.0.
        cand = _make_candidate(
            "tiktok_clip", "https://x.com/a", reason="basketball playoffs highlights"
        )
        inspector = MagicMock()
        result = asset_qualification._score_candidate(
            cand, beat, _make_plan_item(42), 1, "", str(tmp_path), inspector=inspector
        )
        assert result is None
        inspector.assert_not_called()  # VLM NOT spent on a zero-overlap candidate

    def test_prefilter_inspects_positive_overlap(self, tmp_path: Any) -> None:
        """Positive keyword-overlap candidate IS inspected (option 1 recall)."""
        beat = _make_beat(beat_id=42, spoken_point="Mount Fuji sunrise climb")
        cand = _make_candidate("tiktok_clip", "https://x.com/a", reason="Fuji summit at sunrise")
        inspector = MagicMock(return_value=_cached_inspection())
        result = asset_qualification._score_candidate(
            cand, beat, _make_plan_item(42), 1, "", str(tmp_path), inspector=inspector
        )
        assert result is not None
        inspector.assert_called_once()

    def test_prefilter_never_skips_cached_candidate(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cache hit bypasses the gate even at zero overlap (never re-decide cached)."""
        beat = _make_beat(beat_id=42, spoken_point="Mount Fuji climb")
        cand = _make_candidate(
            "tiktok_clip", "https://x.com/a", reason="basketball"
        )  # zero overlap
        monkeypatch.setattr(asset_qualification, "lookup", lambda d, k: _cached_inspection())
        inspector = MagicMock()
        result = asset_qualification._score_candidate(
            cand,
            beat,
            _make_plan_item(42),
            1,
            str(tmp_path),
            str(tmp_path),
            inspector=inspector,
        )
        assert result is not None  # scored from cache
        inspector.assert_not_called()

    def test_recovery_caps_recovered_candidates(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RECOVER scores at most MAX_RECOVERED_PER_BEAT recovered candidates (option 9)."""
        beat = _make_beat(beat_id=7, asset_candidates=[])  # nothing qualifies initially
        overflow = asset_qualification.MAX_RECOVERED_PER_BEAT + 5
        recovered = [
            _make_candidate("tiktok_clip", f"https://x.com/{i}", reason="Fuji climb")
            for i in range(overflow)
        ]

        def discover_fn(queries: list[str]) -> tuple[list[dict], list[dict]]:
            return (
                [{"type": c.type, "url": c.url, "reason": c.reason} for c in recovered],
                [],
            )

        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=1, discover_fn=discover_fn
        )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir="",
            agent_dir=str(tmp_path),
            inspector=None,
            recovery=recovery,
            plan_item=None,
        )

        scored_urls: list[str] = []

        def counting(candidate: Any, _beat: Any, *_a: Any, **_kw: Any) -> None:
            scored_urls.append(candidate.url)
            return None  # reject all -> beat exhausted, but we count recover scoring

        monkeypatch.setattr(asset_qualification, "_score_candidate", counting)
        asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)
        # 13 recovered -> capped to MAX_RECOVERED_PER_BEAT; beat.asset_candidates=[]
        # contributes 0, so scored_urls == the capped recover set only.
        assert len(scored_urls) == asset_qualification.MAX_RECOVERED_PER_BEAT

    def test_recovery_ranks_relevant_candidate_above_cap(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex P2#1: the most relevant recovered candidate is kept even when it
        lands past the cap in provider order (ranked by keyword overlap first)."""
        beat = _make_beat(beat_id=7, spoken_point="Mount Fuji sunrise climb")
        cap = asset_qualification.MAX_RECOVERED_PER_BEAT
        # `cap` zero-overlap candidates first, then ONE relevant candidate at the
        # tail — without rank-then-cap it would be sliced off and the beat would
        # regress to a text card despite recovery finding a usable candidate.
        irrelevant = [
            _make_candidate("tiktok_clip", f"https://x.com/irr/{i}", reason="basketball playoffs")
            for i in range(cap)
        ]
        relevant = _make_candidate(
            "tiktok_clip", "https://x.com/relevant", reason="Fuji sunrise summit"
        )

        def discover_fn(queries: list[str]) -> tuple[list[dict], list[dict]]:
            return (
                [
                    {"type": c.type, "url": c.url, "reason": c.reason}
                    for c in [*irrelevant, relevant]
                ],
                [],
            )

        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=1, discover_fn=discover_fn
        )
        ctx = asset_qualification.AssetQualificationContext(
            job_id=1,
            cache_dir="",
            agent_dir=str(tmp_path),
            inspector=None,
            recovery=recovery,
            plan_item=None,
        )

        scored_urls: list[str] = []

        def counting(candidate: Any, _beat: Any, *_a: Any, **_kw: Any) -> None:
            scored_urls.append(candidate.url)
            return None

        monkeypatch.setattr(asset_qualification, "_score_candidate", counting)
        asset_qualification._qualify_beat(beat, ctx, 0.30, 0.50)
        # Ranked by overlap, the relevant candidate outranks the zero-overlap ones,
        # so it is within the cap and gets scored.
        assert "https://x.com/relevant" in scored_urls
