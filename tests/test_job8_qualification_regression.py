"""SLICE 12 — Job #8 golden regression: qualification + recovery reduces text-cards (M < N).

HARD merge gate for PR 5 (design §9 [V6]). Proves the Job #8 fix end-to-end at the
qualification boundary: with source recovery running BEFORE the text-card fallback, fewer
beats degrade to text cards than the all-reject baseline.

Per [V6]:
* Uses the REAL frozen Job #8 research contract (``research_contract.json`` — 8 beats with
  their real candidates), copied hermetically into ``tests/fixtures/job8/``.
* RE-DERIVES the baseline N inline via mocked REJECT inspections — it does NOT read the
  expected count from ``vd_output.json`` (which encodes the old rejection logic).
* Hermetic: the multimodal inspector and SP discovery are mocked (no OpenRouter / Pexels /
  YouTube / FFmpeg).

The text-card count is measured at the qualification boundary (``verdict ==
'exhausted_text_card'``). Reducing exhausted beats reduces VD's text-card fallbacks for the
direction that carries the fix: a ``recovered`` beat reaches VD with a real candidate that
re-scores as a cache-hit accept (SLICE 1 parity) and re-ranks to accept via
``_apply_best_candidate`` (VD source unmodified — SLICE 14). The reverse direction
(exhausted verdict -> VD text card) is NOT mechanically enforced today: VD skips
``_apply_best_candidate`` for empty-candidate beats and the ``qualification_text_card`` stamp
is unread by VD (a design §8 follow-up), so this gate deliberately proves the headline
criterion at the boundary that drives the win, without claiming a word-for-word VD-output
equivalence or needing a brittle full-VD.execute/FFmpeg harness.

Placement note: lives in ``tests/`` (not ``tests/integration/`` per design §10) deliberately,
with no ``integration`` marker, so it runs in the offline suite as a real HARD gate rather
than being skipped by the standard ``-m "not integration"`` pre-PR filter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clipper_agency.agents.segment_producer import SegmentProducerAgent
from clipper_agency.core import asset_qualification

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "job8"


def _load_research_output() -> dict[str, Any]:
    """Load the frozen Job #8 research contract as a research_output dict."""
    contract = json.loads((FIXTURE_DIR / "research_contract.json").read_text())
    return {
        "story_beats": contract.get("story_beats", []),
        "asset_candidates": contract.get("asset_candidates", []),
        "entities": contract.get("entities", []),
        "topic": contract.get("topic", ""),
    }


def _reject_inspection() -> dict:
    """Inspection that fails the HIGH_MISLEADING_RISK hard rule → rejected."""
    return {
        "decision": "reject",
        "person_match": 0.1,
        "event_match": 0.1,
        "claim_support": 0.2,
        "visual_quality": 0.2,
        "misleading_risk": 0.8,
        "source_credibility": 0.1,
    }


def _accept_inspection() -> dict:
    """Inspection that clears every rejection rule and the accept threshold."""
    return {
        "decision": "accept",
        "person_match": 0.9,
        "event_match": 0.85,
        "claim_support": 0.9,
        "visual_quality": 0.8,
        "misleading_risk": 0.1,
        "source_credibility": 0.8,
    }


def _make_inspector():
    """Inspector that REJECTS the original Job #8 candidates and ACCEPTS recovered ones.

    Recovered candidates are marked by a ``good`` URL segment (the mocked SP discovery
    returns sources with such URLs). This re-derives the rejection baseline inline rather
    than reading it from vd_output.json.
    """

    def inspector(
        candidate: Any,
        beat: Any,
        job_id: int,
        cache_dir: str,
        cache_key: str,
        agent_dir: str,
    ) -> dict:
        if "good" in getattr(candidate, "url", ""):
            return _accept_inspection()
        return _reject_inspection()

    return inspector


def _text_card_count(results: list[asset_qualification.BeatQualificationResult]) -> int:
    return sum(1 for r in results if r.verdict == "exhausted_text_card")


class TestJob8QualificationRegression:
    """SLICE 12 HARD merge gate — recovery reduces text-card fallbacks below baseline."""

    def test_recovery_reduces_text_cards_below_baseline(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        research_output = _load_research_output()
        story_beats = research_output["story_beats"]
        assert story_beats, "Job #8 fixture must have story_beats"
        cache_dir = str(tmp_path / "inspection_cache")
        inspector = _make_inspector()

        # ── Baseline N: recovery DISABLED. Every beat's real candidates reject (mocked) →
        #    every beat exhausts (harsher than the real ~7/8 rejection — a conservative
        #    baseline re-derived inline, NOT read from vd_output.json).
        results_baseline = asset_qualification.qualify_research_candidates(
            research_output, 8, cache_dir, "/agent", inspector=inspector, recovery=None
        )
        n_baseline = _text_card_count(results_baseline)
        assert n_baseline > 0, "baseline must have rejecting beats for the test to be meaningful"

        # ── Qualified M: recovery ENABLED. The mocked SP discovery returns a fresh
        #    "good" candidate for each failing beat → recovered (accept) instead of a text card.
        monkeypatch.setattr(
            SegmentProducerAgent,
            "_discover_multi_source_assets",
            lambda self, topic, entities, config, beats=None: (
                [{"url": "https://good-recovered.example/clip.mp4", "source_type": "tiktok_clip"}],
                [{"provider": "youtube", "query": "recovery", "result_count": 1}],
            ),
        )
        sp = SegmentProducerAgent()
        discover_fn = asset_qualification._build_sp_discovery_adapter(
            sp,
            research_output["topic"],
            research_output["entities"],
            object(),  # config is opaque to discovery (only keys are read, none mocked here)
            beats=story_beats,
        )
        recovery = asset_qualification.RecoveryPolicy(
            enabled=True, max_cycles=1, discover_fn=discover_fn
        )
        results_qualified = asset_qualification.qualify_research_candidates(
            research_output, 8, cache_dir, "/agent", inspector=inspector, recovery=recovery
        )
        m_qualified = _text_card_count(results_qualified)
        recovered = sum(1 for r in results_qualified if r.verdict == "recovered")

        # THE HARD GATE: source-recovery-before-text-card strictly reduces text-card fallbacks.
        assert m_qualified < n_baseline, (
            f"recovery did not reduce text-card fallbacks: M={m_qualified} >= N={n_baseline}"
        )
        # And at least one beat was genuinely rescued (recovered), not merely re-rejected.
        assert recovered > 0, "recovery rescued no beat — the fix is inert"
        # Positive evidence the rescued candidates are the SP-discovery output (good URLs),
        # not accidentally-accepted originals: every recovered beat's top candidate is "good".
        assert all(
            "good-recovered" in r.qualified[0]["candidate"].url
            for r in results_qualified
            if r.verdict == "recovered"
        ), "a recovered beat was not rescued by the SP-discovery candidate"
