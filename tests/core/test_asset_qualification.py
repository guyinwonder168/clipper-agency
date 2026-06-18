"""SLICE 1 — cache-key parity hard gate for the pre-VD asset-qualification boundary.

Guards PR 5's #1 risk (design doc §12: "Cache-key literal drift — forks cache
namespace, re-spends VLM"). The new ``asset_qualification._score_candidate`` is a
verbatim lift of ``VD._score_one_candidate`` (visual_director.py:748-803); VD's copy
is KEPT AS-IS (design §8). Two textually-distinct call sites of ``compute_cache_key``
therefore coexist after PR 5 with zero compile-time coupling. This test fails the
merge if the lifted copy drifts from VD's convention on any of the six cache-key
inputs.

NOTE: a strictly-better follow-up (design §8) is to extract a shared
``inspection_cache.compute_candidate_cache_key(candidate, beat)`` called by BOTH
sites, removing this risk by construction. Until that follow-up PR lands, this gate
IS the contract.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.config.schema import AssetCandidate, BeatFallback, StoryBeat
from clipper_agency.core import asset_qualification, inspection_cache
from clipper_agency.core.inspection_cache import compute_cache_key

# ---------------------------------------------------------------------------
# Fixtures (mirror tests/agents/test_visual_director_candidate_inspection.py)
# ---------------------------------------------------------------------------


def _make_candidate(
    ctype: str = "tiktok_clip",
    url: str = "https://example.com/clip1.mp4",
    reason: str = "test candidate",
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
        "visual_must_show": f"Visual {beat_id}",
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

        vd_kwargs: dict[str, Any] = {}
        aq_kwargs: dict[str, Any] = {}
        real_compute = inspection_cache.compute_cache_key

        def vd_spy(**kwargs: Any) -> str:
            vd_kwargs.update(kwargs)
            return real_compute(**kwargs)

        def aq_spy(**kwargs: Any) -> str:
            aq_kwargs.update(kwargs)
            return real_compute(**kwargs)

        agent = VisualDirectorAgent()

        # Force a cache hit on both paths so _run_multimodal_inspection / _run_inspection
        # are never reached — this test isolates the compute_cache_key call only.
        with (
            patch("clipper_agency.agents.visual_director.compute_cache_key", vd_spy),
            patch("clipper_agency.agents.visual_director.lookup", return_value=cached),
        ):
            vd_result = agent._score_one_candidate(
                cand, beat, plan_item, 1, "/tmp/cache", "/tmp/agent"
            )

        with (
            patch("clipper_agency.core.asset_qualification.compute_cache_key", aq_spy),
            patch("clipper_agency.core.asset_qualification.lookup", return_value=cached),
        ):
            aq_result = asset_qualification._score_candidate(
                cand, beat, plan_item, 1, "/tmp/cache", "/tmp/agent", inspector=None
            )

        # Both paths must have invoked compute_cache_key exactly once.
        assert vd_kwargs, "VD._score_one_candidate did not call compute_cache_key"
        assert aq_kwargs, "asset_qualification._score_candidate did not call compute_cache_key"

        # 1) Kwarg-equality: catches ANY drift on any of the 6 inputs (literal value,
        #    field source, or hash computation). This is the primary gate.
        assert vd_kwargs == aq_kwargs

        # 2) Digest-equality: order-sensitive belt-and-suspenders. compute_cache_key
        #    joins inputs in fixed positional order, so this is implied by #1, but it
        #    documents the byte-identity intent directly.
        assert compute_cache_key(**vd_kwargs) == compute_cache_key(**aq_kwargs)

        # 3) Pin the VD convention explicitly so a future edit to VD:759-766 literals
        #    also trips this gate — not only edits to the lifted copy.
        assert vd_kwargs["model"] == "multimodal"
        assert vd_kwargs["prompt_version"] == "1.0"
        assert vd_kwargs["evidence_contract_hash"] == ""
        assert vd_kwargs["asset_path"] == cand.url
        assert vd_kwargs["beat_claim"] == beat.spoken_point
        # Independently pin asset_hash so a simultaneous bug at BOTH call sites
        # (e.g. both hashing the wrong object) cannot false-pass the parity check.
        assert vd_kwargs["asset_hash"] == inspection_cache.compute_asset_content_hash(cand)

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
                compute_cache_key(
                    asset_path=cand.url,
                    asset_hash=inspection_cache.compute_asset_content_hash(cand),
                    beat_claim=beat.spoken_point,
                    evidence_contract_hash="",
                    model="multimodal",
                    prompt_version="1.0",
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
            compute_cache_key(
                asset_path=good.url,
                asset_hash=inspection_cache.compute_asset_content_hash(good),
                beat_claim=beat.spoken_point,
                evidence_contract_hash="",
                model="multimodal",
                prompt_version="1.0",
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
                compute_cache_key(
                    asset_path=cand.url,
                    asset_hash=inspection_cache.compute_asset_content_hash(cand),
                    beat_claim=beat.spoken_point,
                    evidence_contract_hash="",
                    model="multimodal",
                    prompt_version="1.0",
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
                compute_cache_key(
                    asset_path=cand.url,
                    asset_hash=inspection_cache.compute_asset_content_hash(cand),
                    beat_claim=beat.spoken_point,
                    evidence_contract_hash="",
                    model="multimodal",
                    prompt_version="1.0",
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
                compute_cache_key(
                    asset_path=cand.url,
                    asset_hash=inspection_cache.compute_asset_content_hash(cand),
                    beat_claim=beat.spoken_point,
                    evidence_contract_hash="",
                    model="multimodal",
                    prompt_version="1.0",
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
                compute_cache_key(
                    asset_path=cand.url,
                    asset_hash=inspection_cache.compute_asset_content_hash(cand),
                    beat_claim=beat.spoken_point,
                    evidence_contract_hash="",
                    model="multimodal",
                    prompt_version="1.0",
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
            compute_cache_key(
                asset_path=bad.url,
                asset_hash=inspection_cache.compute_asset_content_hash(bad),
                beat_claim=beat.spoken_point,
                evidence_contract_hash="",
                model="multimodal",
                prompt_version="1.0",
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
