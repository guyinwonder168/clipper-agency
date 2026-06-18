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


class TestRunInspectionStub:
    """SLICE 1 skeleton: ``_run_inspection`` is a stub until SLICE 6 lands.

    Pins that a cache miss currently fails loudly (NotImplementedError) rather than
    silently returning None and rejecting every candidate. SLICE 6 replaces this test
    with real inspection behavior.
    """

    def test_raises_not_implemented(self) -> None:
        import pytest

        with pytest.raises(NotImplementedError):
            asset_qualification._run_inspection(
                _make_candidate(),
                _make_beat(),
                1,
                "/tmp/cache",
                "key",
                "/tmp/agent",
                inspector=None,
            )
