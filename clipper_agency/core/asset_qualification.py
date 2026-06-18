"""Pre-Visual-Director asset-qualification boundary (PR 5 / Step 5).

Pure orchestration per ADR 0026 ("enforce contracts, do NOT rebuild"): lifts Visual
Director's existing candidate-scoring chain into a pre-VD service so candidates are
qualified *before* VD consumes them and source recovery runs *before* the text-card
fallback. No new agent, no new gate, no schema change.

See ``docs/plans/pr5-asset-qualification-design.md`` for the locked, codegraph-verified
design that drives this module.
"""

from __future__ import annotations

from typing import Any

from clipper_agency.config.schema import StoryBeat
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
