"""Pre-Visual-Director asset-qualification boundary (PR 5 / Step 5).

Pure orchestration per ADR 0026 ("enforce contracts, do NOT rebuild"): lifts Visual
Director's existing candidate-scoring chain into a pre-VD service so candidates are
qualified *before* VD consumes them and source recovery runs *before* the text-card
fallback. No new agent, no new gate, no schema change.

See ``docs/plans/pr5-asset-qualification-design.md`` for the locked, codegraph-verified
design that drives this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from clipper_agency.config.schema import StoryBeat
from clipper_agency.core.candidate_semantic_ranker import (
    apply_rejection_rules,
    rank_candidates,
)
from clipper_agency.core.inspection_cache import (
    compute_asset_content_hash,
    compute_cache_key,
    lookup,
)
from clipper_agency.core.semantic_visual_review import score_visual_relevance

# ---------------------------------------------------------------------------
# Cache-key convention — MUST stay byte-identical to VD._score_one_candidate
# (visual_director.py:759-766). tests/core/test_asset_qualification.py SLICE 1 is
# the hard merge gate enforcing this; do not change these values without also
# updating VD's inline literals (or, preferably, see the follow-up below).
#
# TODO(PR 5 follow-up, design §8): extract compute_candidate_cache_key(candidate,
# beat) into clipper_agency/core/inspection_cache.py and call it from BOTH Visual
# Director and this module. One definition removes this drift risk by construction
# and collapses the SLICE 1 gate to a trivial single-caller test. Deferred per the
# locked §8 "keep VD as-is" minimal-blast-radius decision.
# ---------------------------------------------------------------------------
_CACHE_MODEL = "multimodal"
_CACHE_PROMPT_VERSION = "1.0"
_CACHE_EVIDENCE_CONTRACT_HASH = ""

# Recovery bound (design §7 / §12): one recovery cycle per failing beat — prevents
# an unbounded discovery loop. SLICE 5 pins the bound behavior.
MAX_RECOVERY_CYCLES: int = 1


# ---------------------------------------------------------------------------
# Contract types (module-local, NOT promoted to config/schema.py — YAGNI/DRY).
# See design doc §5.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryPolicy:
    """Source-recovery policy for a beat with zero qualified candidates.

    ``discover_fn`` is an opaque ``Callable`` (bound to Segment Producer discovery by
    the orchestrator via ``_build_sp_discovery_adapter``) so this module imports
    NEITHER ``segment_producer`` NOR ``visual_director`` — breaking the import cycle
    (design §4). Recovery itself lands in SLICE 3.
    """

    enabled: bool = True
    max_cycles: int = MAX_RECOVERY_CYCLES
    discover_fn: Callable[[list[str]], tuple[list[dict], list[dict]]] | None = None


@dataclass(frozen=True)
class AssetQualificationContext:
    """Per-job invariants bundled for ``_qualify_beat`` (the >5-scalar rule, §5).

    The per-beat ``StoryBeat`` is passed separately to ``_qualify_beat`` (it varies
    each beat); this context holds the values that are constant across every beat in
    one qualification pass.
    """

    job_id: int
    cache_dir: str
    agent_dir: str
    inspector: Any
    recovery: RecoveryPolicy | None
    plan_item: dict | None = None


@dataclass(frozen=True)
class BeatQualificationResult:
    """Outcome of qualifying one beat's candidate pool (design §5)."""

    beat_id: str
    verdict: str  # 'qualified' | 'recovered' | 'exhausted_text_card'
    recovery_outcome: str  # 'none' | 'ran' | 'exhausted' | 'no_fn'
    recovery_attempts: int
    qualified: list[dict] = field(default_factory=list)
    scored: list[dict] = field(default_factory=list)
    reject_reasons: dict[str, str] = field(default_factory=dict)
    fallback_card: dict | None = None
    provider_attempts_added: list[dict] = field(default_factory=list)


def _score_candidate(
    candidate: Any,
    beat: StoryBeat,
    plan_item: dict | None,
    job_id: int,
    cache_dir: str,
    agent_dir: str,
    inspector: Any = None,
) -> dict | None:
    """Score a single candidate using cache or multimodal inspection.

    Verbatim lift of ``VisualDirectorAgent._score_one_candidate``
    (visual_director.py:748-803) with the ``self.*`` dependencies removed: the
    multimodal inspection is delegated to the module-level ``_run_inspection`` and
    cleanliness to ``_score_cleanliness``. The cache-key literals are byte-identical
    to VD:759-766 (enforced by SLICE 1) so the pre-VD pass and VD share one cache
    namespace and VLM is never spent twice on the same candidate.
    """
    asset_id = f"{candidate.type}_{candidate.url[:40]}"
    cache_key = compute_cache_key(
        asset_path=candidate.url,
        asset_hash=compute_asset_content_hash(candidate),
        beat_claim=beat.spoken_point,
        evidence_contract_hash=_CACHE_EVIDENCE_CONTRACT_HASH,
        model=_CACHE_MODEL,
        prompt_version=_CACHE_PROMPT_VERSION,
    )
    cached = lookup(cache_dir, cache_key) if cache_dir else None
    inspection = cached or _run_inspection(
        candidate, beat, job_id, cache_dir, cache_key, agent_dir, inspector
    )
    if inspection is None:
        return None

    rel = score_visual_relevance(
        beat={"beat_id": beat.beat_id, "claim": beat.spoken_point},
        asset_inspection=inspection,
    )
    return {
        "asset_id": asset_id,
        "beat_id": str(beat.beat_id),
        "role": beat.role,
        "treatment": (plan_item or {}).get("treatment", ""),
        "inspection": inspection,
        "visual_relevance": {
            "person_match": rel.person_match,
            "event_match": rel.event_match,
            "claim_support": rel.claim_support,
            "visual_quality": rel.visual_quality,
        },
        "cleanliness_score": _score_cleanliness(inspection),
        "candidate": candidate,
        "inspection_diag": {
            "beat_id": beat.beat_id,
            "asset_id": asset_id,
            "decision": inspection.get("decision", "unknown"),
            "from_cache": cached is not None,
        },
    }


def _score_cleanliness(inspection: dict) -> float:
    """Cleanliness proxy — identical dead-``_inspection_metrics`` behavior.

    Verbatim lift of ``VisualDirectorAgent._compute_cleanliness_score``
    (visual_director.py:805): returns the inspection's ``visual_quality``. VD's
    version also consults a ``self._inspection_metrics`` map keyed by
    ``candidate.url``, but that map is dead in production (never populated), so
    neither the candidate parameter nor the lookup is reproduced here. No new
    heuristics (design §3 / §13 — the win comes from recovery ordering, not better
    rejection).
    """
    return inspection.get("visual_quality", 0.5)


def _run_inspection(
    candidate: Any,
    beat: StoryBeat,
    job_id: int,
    cache_dir: str,
    cache_key: str,
    agent_dir: str,
    inspector: Any,
) -> dict | None:
    """Run a multimodal inspection on a cache miss.

    SLICE 6 will implement this as the verbatim lift of
    ``VD._run_multimodal_inspection`` (visual_director.py:895-952): frame extraction
    via the same ``_extract_candidate_frames`` path VD uses (frame ownership stays in
    VD — no double extraction), ``inspect_asset``, ``store()`` only when
    ``decision != 'error'``, and ``None`` on exception.

    Reached only on a cache miss, so SLICE 1 (cache-key parity, which forces cache
    hits) never exercises it. It fails loudly if invoked before SLICE 6 lands rather
    than silently returning ``None`` and rejecting every candidate. The message
    reports the full request context so an unexpected miss during slices 1-5 is
    easy to diagnose.
    """
    raise NotImplementedError(
        "SLICE 6: _run_inspection (verbatim lift of VD._run_multimodal_inspection) "
        f"is not yet implemented for candidate={candidate.url!r} beat_id={beat.beat_id!r} "
        f"job_id={job_id!r} cache_dir={cache_dir!r} cache_key={cache_key!r} "
        f"agent_dir={agent_dir!r} inspector={type(inspector).__name__}."
    )


# ---------------------------------------------------------------------------
# SLICE 2 — per-beat qualification orchestration (public entry).
# ---------------------------------------------------------------------------


def qualify_research_candidates(
    research_output: dict,
    job_id: int,
    cache_dir: str,
    agent_dir: str,
    *,
    inspector: Any = None,
    recovery: RecoveryPolicy | None = None,
    min_claim_support: float = 0.30,
    max_misleading_risk: float = 0.50,
) -> list[BeatQualificationResult]:
    """Pre-VD qualification boundary — public entry (design §4).

    Parses each ``research_output['story_beats']`` entry into a ``StoryBeat`` and
    qualifies it via ``_qualify_beat``, returning one ``BeatQualificationResult`` per
    beat. The orchestrator's engine seam uses the results to rewrite the candidate
    pool Visual Director receives and to write ``qualification_report.json``.

    The locked design (§4) also accepts ``sp`` / ``config`` / ``topic`` / ``entities``
    for the recovery stage and the SP discovery adapter; those land with SLICE 3 /
    SLICE 7 (the slices that consume them) and are omitted here to avoid
    unused-parameter issues (per-slice YAGNI).
    """
    story_beats_raw: list[dict] = (
        research_output.get("story_beats", []) if isinstance(research_output, dict) else []
    )
    ctx = AssetQualificationContext(
        job_id=job_id,
        cache_dir=cache_dir,
        agent_dir=agent_dir,
        inspector=inspector,
        recovery=recovery,
        plan_item=None,
    )
    results: list[BeatQualificationResult] = []
    for beat_dict in story_beats_raw:
        beat = StoryBeat(**beat_dict)
        results.append(_qualify_beat(beat, ctx, min_claim_support, max_misleading_risk))
    return results


def _qualify_beat(
    beat: StoryBeat,
    ctx: AssetQualificationContext,
    min_claim_support: float,
    max_misleading_risk: float,
) -> BeatQualificationResult:
    """Score → rank → qualify one beat's candidate pool (design §7 steps 1-3).

    Scores every candidate via ``_score_candidate`` (cache-key literals byte-identical
    to VD:759-766), ranks via ``candidate_semantic_ranker.rank_candidates``, and if any
    ranked candidate is ``{accept, revise}`` returns ``verdict='qualified'`` with the
    accept+revised scored dicts in rank order, populated ``reject_reasons`` for the
    rejects, and NO recovery / text card.

    The zero-qualified path (all reject / empty pool) is the recovery-before-text-card
    fix and lands in SLICE 3; until then it fails loud (NotImplementedError) rather
    than silently emitting a text card — which is the exact Job #8 bug this boundary
    exists to fix.
    """
    scored: list[dict] = []
    for candidate in beat.asset_candidates:
        scored_one = _score_candidate(
            candidate,
            beat,
            ctx.plan_item,
            ctx.job_id,
            ctx.cache_dir,
            ctx.agent_dir,
            ctx.inspector,
        )
        if scored_one:
            scored.append(scored_one)

    ranked = rank_candidates(
        {"beat_id": str(beat.beat_id)}, scored, min_claim_support, max_misleading_risk
    )

    reject_reasons: dict[str, str] = {}
    for scored_one in scored:
        reason = apply_rejection_rules(
            scored_one,
            min_claim_support=min_claim_support,
            max_misleading_risk=max_misleading_risk,
        )
        if reason:
            reject_reasons[scored_one["asset_id"]] = reason

    scored_by_id = {s["asset_id"]: s for s in scored}
    qualified = [scored_by_id[r.asset_id] for r in ranked if r.decision in ("accept", "revise")]

    if qualified:
        return BeatQualificationResult(
            beat_id=str(beat.beat_id),
            verdict="qualified",
            recovery_outcome="none",
            recovery_attempts=0,
            qualified=qualified,
            scored=scored,
            reject_reasons=reject_reasons,
            fallback_card=None,
            provider_attempts_added=[],
        )

    raise NotImplementedError(
        "SLICE 3: recovery-before-text-card not yet implemented for "
        f"beat_id={beat.beat_id!r} (zero of {len(scored)} candidate(s) qualified)."
    )
