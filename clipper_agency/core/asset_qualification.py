"""Pre-Visual-Director asset-qualification boundary (PR 5 / Step 5).

Pure orchestration per ADR 0026 ("enforce contracts, do NOT rebuild"): lifts Visual
Director's existing candidate-scoring chain into a pre-VD service so candidates are
qualified *before* VD consumes them and source recovery runs *before* the text-card
fallback. No new agent, no new gate, no schema change.

See ``docs/plans/pr5-asset-qualification-design.md`` for the locked, codegraph-verified
design that drives this module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from clipper_agency.config.schema import AssetCandidate, StoryBeat
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

logger = logging.getLogger(__name__)

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
    (design §4). The real SP-bound adapter lands in SLICE 7; SLICE 3 consumes any
    injected ``discover_fn``.
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
# SLICE 2 + SLICE 3 — per-beat qualification orchestration.
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
    for the recovery stage and the SP discovery adapter; those land with SLICE 7 (the
    slice that consumes them via ``_build_sp_discovery_adapter``) and are omitted here
    to avoid unused-parameter issues (per-slice YAGNI).
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


def _score_candidates(
    candidates: list[Any],
    beat: StoryBeat,
    ctx: AssetQualificationContext,
) -> list[dict]:
    """Score a list of candidates via ``_score_candidate``, dropping None results."""
    scored: list[dict] = []
    for candidate in candidates:
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
    return scored


def _rank_and_select(
    beat: StoryBeat,
    scored: list[dict],
    min_claim_support: float,
    max_misleading_risk: float,
) -> tuple[list[dict], dict[str, str]]:
    """Rank scored candidates; return (qualified accept+revised in rank order, reject_reasons).

    ``reject_reasons`` is derived via the same ``apply_rejection_rules`` (identical
    args) that ``rank_candidates`` uses internally — single source of truth (DRY).
    """
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
    return qualified, reject_reasons


def _to_asset_candidate(item: Any) -> AssetCandidate:
    """Coerce one discovery result (dict or AssetCandidate) into an AssetCandidate."""
    if isinstance(item, AssetCandidate):
        return item
    return AssetCandidate(**item)


def _attempt_recovery(
    beat: StoryBeat,
    discover_fn: Callable[[list[str]], tuple[list[dict], list[dict]]],
    cycle: int,
) -> tuple[list[AssetCandidate], list[dict]]:
    """Named RECOVER stage — source recovery for a beat with zero qualified candidates.

    Builds expanded per-beat queries from ``beat.visual_must_show`` +
    ``beat.spoken_point`` and invokes ``discover_fn``, returning
    ``(new_candidates, provider_attempts)``. The caller bounds it to one cycle
    (``MAX_RECOVERY_CYCLES``); this function performs a single synchronous discovery
    pass — distinct from ADR 0023's post-Reviewer ``RepairPatch`` path (no
    ``RepairPlan``, no ``GATE_FAILURE_REPAIR_MAP``).
    """
    queries = [q for q in (beat.visual_must_show, beat.spoken_point) if q]
    new_dicts, provider_attempts = discover_fn(queries)
    # Best-effort coercion: a non-mapping discovery item (e.g. None / a bare string a
    # real provider can emit) is logged and skipped rather than aborting the whole pass.
    new_candidates: list[AssetCandidate] = []
    for item in new_dicts or []:
        try:
            new_candidates.append(_to_asset_candidate(item))
        except TypeError:
            logger.warning(
                "asset_qualification.recovery beat_id=%s skipping non-mapping item: %r",
                beat.beat_id,
                item,
            )
    logger.info(
        "asset_qualification.recovery beat_id=%s cycle=%s queries=%d candidates=%d",
        beat.beat_id,
        cycle,
        len(queries),
        len(new_candidates),
    )
    return new_candidates, list(provider_attempts or [])


def _qualify_beat(
    beat: StoryBeat,
    ctx: AssetQualificationContext,
    min_claim_support: float,
    max_misleading_risk: float,
) -> BeatQualificationResult:
    """Score → rank → (recover if zero qualified) → qualify one beat (design §7).

    Steps 1-3: score every candidate via ``_score_candidate`` (cache-key literals
    byte-identical to VD:759-766), rank via ``rank_candidates``, and if any ranked
    candidate is ``{accept, revise}`` return ``verdict='qualified'`` — no recovery,
    no text card.

    Step 4 (SLICE 3 — the Job #8 fix): when qualified is empty, run the RECOVER stage
    (``_attempt_recovery``) BEFORE any text-card fallback. If recovery yields a
    qualified candidate return ``verdict='recovered'``. This is the ordering VD lacks:
    VD's ``_apply_best_candidate`` goes straight to a text card on all-reject
    (visual_director.py:1117-1130) with zero recovery.

    Step 5 (SLICE 4 — terminal text-card fallback) is not yet implemented; if recovery
    does not qualify the beat (or is disabled), this fails loud (NotImplementedError)
    rather than silently emitting a text card.
    """
    scored = _score_candidates(beat.asset_candidates, beat, ctx)
    qualified, reject_reasons = _rank_and_select(
        beat, scored, min_claim_support, max_misleading_risk
    )

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

    # SLICE 3: RECOVER stage — recovery BEFORE the text-card fallback.
    # max_cycles is a 0/1 gate today (1 = one recovery pass, 0 = skip); _attempt_recovery
    # runs a single synchronous pass with no loop. SLICE 5 formalizes the bound — raising
    # MAX_RECOVERY_CYCLES alone would NOT add iteration until a loop is introduced there.
    recovery = ctx.recovery
    if (
        recovery is not None
        and recovery.enabled
        and recovery.discover_fn is not None
        and recovery.max_cycles > 0
    ):
        recovered_candidates, provider_attempts = _attempt_recovery(
            beat, recovery.discover_fn, cycle=0
        )
        recovered_scored = _score_candidates(recovered_candidates, beat, ctx)
        all_scored = scored + recovered_scored
        qualified, reject_reasons = _rank_and_select(
            beat, all_scored, min_claim_support, max_misleading_risk
        )
        if qualified:
            return BeatQualificationResult(
                beat_id=str(beat.beat_id),
                verdict="recovered",
                recovery_outcome="ran",
                recovery_attempts=1,
                qualified=qualified,
                scored=all_scored,
                reject_reasons=reject_reasons,
                fallback_card=None,
                provider_attempts_added=list(provider_attempts),
            )

    # SLICE 4: terminal text-card fallback (last resort) — not yet implemented.
    raise NotImplementedError(
        "SLICE 4: terminal text-card fallback not yet implemented for "
        f"beat_id={beat.beat_id!r} (recovery did not yield a qualified candidate)."
    )
