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
from datetime import UTC, datetime
from typing import Any

from clipper_agency.config.schema import AssetCandidate, StoryBeat
from clipper_agency.core.candidate_semantic_ranker import (
    apply_rejection_rules,
    compute_final_score,
    rank_candidates,
)
from clipper_agency.core.clip_window import KeywordOverlapWindowSelector
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
# Follow-up (PR 5+, design §8): extract compute_candidate_cache_key(candidate,
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

# PR 8 — cost-optimization knobs (resolve the job_11 rejection storm).
# Pre-VLM keyword-overlap skip gate (option 1): a candidate with ZERO textual
# overlap to the beat is almost certainly irrelevant (job_11: thousands of VLM
# calls, ~all claim_support=0.00). Skip the expensive inspection entirely.
# 0.0 = skip ONLY on literally-zero overlap (minimal recall risk); cached
# candidates are never re-decided (see _score_candidate).
_PREFILTER_MIN_OVERLAP: float = 0.0
# RECOVER cap (option 9): one all-reject beat can no longer flood N fresh VLM
# inspections — only the top MAX_RECOVERED_PER_BEAT recovered candidates are scored.
MAX_RECOVERED_PER_BEAT: int = 8
_WINDOW_SELECTOR = KeywordOverlapWindowSelector()


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
    if cached is None:
        # PR 8 (option 1) — pre-VLM keyword-overlap skip gate. A candidate with
        # zero textual overlap to the beat is almost certainly irrelevant (the
        # job_11 storm: thousands of Gemini VLM calls, ~all claim_support=0.00).
        # Skip the expensive inspection entirely. Threshold 0.0 = skip ONLY on
        # zero overlap (minimal recall risk); cached candidates are never
        # re-decided (the cached branch below returns regardless of overlap).
        overlap = _WINDOW_SELECTOR.relevance_score(candidate.model_dump(), beat)
        if overlap <= _PREFILTER_MIN_OVERLAP:
            logger.info(
                "asset_qualification.prefilter beat_id=%s asset_id=%s overlap=%.2f "
                "<= %.2f — skipping VLM inspection (LOW_KEYWORD_OVERLAP)",
                beat.beat_id,
                asset_id,
                overlap,
                _PREFILTER_MIN_OVERLAP,
            )
            return None
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
    inspector: Callable[..., dict | None] | None,
) -> dict | None:
    """Run a multimodal inspection on a cache miss by delegating to the injected inspector.

    Per ADR 0027 (SLICE 6 decision), rather than verbatim-lifting
    ``VD._run_multimodal_inspection`` (visual_director.py:895-952) — which would
    duplicate ~140 lines of OCR/face/enhanced ML machinery (ADR 0026 "do not rebuild"
    tension) and risk the two inspection paths drifting under the same cache key
    (design §12 HIGHEST risk) — this delegates to an injected callable that the engine
    seam binds to ``VisualDirectorAgent._run_multimodal_inspection``. That bound method
    has signature ``(candidate, beat, job_id, cache_dir, cache_key, agent_dir) -> dict | None``
    and returns ``None`` on its own internal exceptions, so this function just forwards
    the call. Frame ownership stays in VD (no double extraction) and the cached output is
    byte-identical to VD's (no cache-namespace drift, no double-VLM). The module still
    imports neither ``visual_director`` nor ``segment_producer`` (the inspector is
    injected, like ``RecoveryPolicy.discover_fn``).

    Returns ``None`` when no inspector is configured (candidate cannot be inspected →
    rejected downstream by ``_score_candidate``). The engine seam injects an inspector
    for cache-miss capability.
    """
    if inspector is None:
        logger.warning(
            "asset_qualification: cache miss for %s but no inspector injected; "
            "candidate cannot be inspected and will be rejected.",
            getattr(candidate, "url", candidate),
        )
        return None
    return inspector(candidate, beat, job_id, cache_dir, cache_key, agent_dir)


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


def build_qualification_report(
    job_id: int,
    results: list[BeatQualificationResult],
) -> dict:
    """Pure serializer → ``qualification_report.json`` (design §5).

    A plain-dict transform over the already-built ``BeatQualificationResult``
    list — no new schema, no I/O (the engine seam writes it via ``write_json``).
    ``top_score`` reuses the ranker's own ``compute_final_score`` so the report
    and the ranking decision share one score definition (DRY).
    """
    beats_report: list[dict] = []
    providers_added = 0
    for r in results:
        top_asset_id: str | None = None
        top_score = 0.0
        if r.qualified:
            top = r.qualified[0]
            top_asset_id = top.get("asset_id")
            top_score = round(
                compute_final_score(
                    top.get("inspection", {}),
                    top.get("visual_relevance", {}),
                    top.get("cleanliness_score", 1.0),
                ),
                4,
            )
        providers_added += len(r.provider_attempts_added)
        beats_report.append(
            {
                "beat_id": r.beat_id,
                "verdict": r.verdict,
                "recovery_outcome": r.recovery_outcome,
                "qualified_count": len(r.qualified),
                "recovery_attempts": r.recovery_attempts,
                "reject_reasons": dict(r.reject_reasons),
                "top_asset_id": top_asset_id,
                "top_score": top_score,
            }
        )
    summary = {
        "total_beats": len(results),
        "qualified_beats": sum(1 for r in results if r.verdict == "qualified"),
        "recovered_beats": sum(1 for r in results if r.verdict == "recovered"),
        "text_card_last_resort_beats": sum(
            1 for r in results if r.verdict == "exhausted_text_card"
        ),
        "providers_attempted_added": providers_added,
    }
    return {
        "job_id": job_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "beats": beats_report,
    }


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


def _build_sp_discovery_adapter(
    sp: Any,
    topic: str,
    entities: list,
    config: Any,
    beats: list[dict] | None = None,
) -> Callable[[list[str]], tuple[list[dict], list[dict]]]:
    """Curry Segment Producer discovery into the recovery ``discover_fn`` (design §4 [V1]).

    Binds ``(sp, topic, entities, config, beats)`` and returns a callable matching the
    recovery contract ``Callable[queries -> (candidate_dicts, attempts)]``. It reuses SP's
    EXISTING discovery primitives — ``_discover_multi_source_assets`` (instance method) +
    ``_build_asset_candidates_from_sources`` (@staticmethod) — so this module imports
    NEITHER ``segment_producer`` NOR ``visual_director`` (``sp`` is an opaque object; the
    import cycle is broken by injection, like ``RecoveryPolicy.discover_fn`` and the
    inspector).

    The ``queries`` argument is accepted for contract parity with the recovery stage
    (which expands per-beat queries from ``visual_must_show`` / ``spoken_point``) but is
    not forwarded: ``_discover_multi_source_assets`` builds its own search queries from the
    curried ``beats`` (the failing beat is in that set), and recovered candidates are
    re-scored against the failing beat by ``_qualify_beat`` — so targeting is handled by
    re-scoring, not by the discovery query. ``_distribute_candidates_to_beats`` is
    intentionally NOT called: recovery needs a flat candidate pool to re-score, not a
    per-beat reassignment (KISS — distributing then re-flattening would be dead work).
    """

    def discover_fn(_queries: list[str]) -> tuple[list[dict], list[dict]]:
        sources, attempts = sp._discover_multi_source_assets(topic, entities, config, beats=beats)
        candidate_dicts = sp._build_asset_candidates_from_sources(sources=sources)
        return candidate_dicts, attempts

    return discover_fn


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


def _build_fallback_card(beat: StoryBeat) -> dict:
    """Build the terminal text-card fallback.

    Mirrors VD._apply_best_candidate's fallback shape (visual_director.py:1126-1130)
    so the engine seam / VD consume a consistent text-card dict. A shared
    ``build_fallback_card()`` across both sites is a later cleanup (design §8).
    """
    return {
        "type": "text_card",
        "headline": (beat.overlay_text or f"Beat {beat.beat_id}")[:60],
        "style": "news_card",
    }


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

    Step 5 (SLICE 4 — terminal text-card fallback): if recovery does not qualify the
    beat (or is disabled / has no discover_fn), return ``verdict='exhausted_text_card'``
    with ``recovery_outcome`` in {'exhausted', 'no_fn'} and a ``fallback_card`` — the
    ONLY path that emits a text card, and only as a last resort.
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
    # runs a single synchronous pass with no loop. SLICE 5 pins the bound with a test.
    scored_pool = scored
    reject_reasons_pool = reject_reasons
    provider_attempts: list[dict] = []
    recovery_attempted = False
    recovery = ctx.recovery
    if (
        recovery is not None
        and recovery.enabled
        and recovery.discover_fn is not None
        and recovery.max_cycles > 0
    ):
        recovery_attempted = True
        recovered_candidates, provider_attempts = _attempt_recovery(
            beat, recovery.discover_fn, cycle=0
        )
        # PR 8 (option 9) — bound the number of recovered candidates scored so one
        # all-reject beat can't flood MAX_RECOVERED_PER_BEAT+ fresh VLM inspections.
        # Rank by cheap keyword-overlap relevance to THIS failing beat BEFORE
        # capping (Codex P2#1): recovery discovery returns candidates in provider
        # order, so the most relevant ones could land past the cap and regress the
        # beat to a text card despite recovery finding usable candidates.
        recovered_candidates = sorted(
            recovered_candidates,
            key=lambda c: _WINDOW_SELECTOR.relevance_score(c.model_dump(), beat),
            reverse=True,
        )
        if len(recovered_candidates) > MAX_RECOVERED_PER_BEAT:
            logger.info(
                "asset_qualification.recovery beat_id=%s capping recovered %d -> %d "
                "(ranked by keyword overlap)",
                beat.beat_id,
                len(recovered_candidates),
                MAX_RECOVERED_PER_BEAT,
            )
            recovered_candidates = recovered_candidates[:MAX_RECOVERED_PER_BEAT]
        recovered_scored = _score_candidates(recovered_candidates, beat, ctx)
        scored_pool = scored + recovered_scored
        qualified, reject_reasons_pool = _rank_and_select(
            beat, scored_pool, min_claim_support, max_misleading_risk
        )
        if qualified:
            return BeatQualificationResult(
                beat_id=str(beat.beat_id),
                verdict="recovered",
                recovery_outcome="ran",
                recovery_attempts=1,
                qualified=qualified,
                scored=scored_pool,
                reject_reasons=reject_reasons_pool,
                fallback_card=None,
                provider_attempts_added=list(provider_attempts),
            )

    # SLICE 4: terminal text-card fallback — the ONLY path that emits a text card,
    # and only as a last resort after qualification (and recovery, if enabled) fail.
    return BeatQualificationResult(
        beat_id=str(beat.beat_id),
        verdict="exhausted_text_card",
        recovery_outcome="exhausted" if recovery_attempted else "no_fn",
        recovery_attempts=1 if recovery_attempted else 0,
        qualified=[],
        scored=scored_pool,
        reject_reasons=reject_reasons_pool,
        fallback_card=_build_fallback_card(beat),
        provider_attempts_added=list(provider_attempts),
    )
