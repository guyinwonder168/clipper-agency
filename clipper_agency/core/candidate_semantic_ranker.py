"""Candidate portfolio semantic ranker — combines multimodal inspection with
visual relevance, cleanliness, and credibility to produce final rankings.

All functions are pure (no I/O, no side effects).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RankedCandidate:
    """A ranked candidate with final score and selection decision."""

    asset_id: str
    beat_id: str
    final_score: float
    decision: str  # "accept", "revise", "reject", "fallback_card"
    inspection: dict
    visual_relevance: dict
    cleanliness_score: float
    rank_reason: str


# Scoring weights
_INSPECTION_WEIGHT = 0.40
_RELEVANCE_WEIGHT = 0.30
_CLEANLINESS_WEIGHT = 0.15
_CREDIBILITY_WEIGHT = 0.15

# Decision thresholds
_ACCEPT_THRESHOLD = 0.60

# Inspection dimension keys
_INSPECTION_DIMS = ("person_match", "event_match", "claim_support", "visual_quality")

# Role priority (lower = better): evidence preferred over context
_ROLE_PRIORITY = {"evidence": 0, "context": 1}


def _mean_score(data: dict, keys: tuple[str, ...]) -> float:
    """Arithmetic mean of values for *keys* in *data*."""
    values = [data.get(k, 0.0) for k in keys]
    return sum(values) / len(values) if values else 0.0


def compute_final_score(
    inspection: dict,
    visual_relevance: dict,
    cleanliness_score: float = 1.0,
    credibility_weight: float = 0.15,
) -> float:
    """Combine inspection, visual relevance, cleanliness, and credibility.

    Default allocation: inspection 40%, visual_relevance 30%,
    cleanliness 15%, credibility 15%.  Adjusting *credibility_weight*
    rebalances the remaining three proportionally.

    Returns a float clamped to [0.0, 1.0].
    """
    insp_mean = _mean_score(inspection, _INSPECTION_DIMS)
    rel_mean = _mean_score(visual_relevance, _INSPECTION_DIMS)
    credibility = inspection.get("source_credibility", 0.0)

    # Redistribute non-credibility weights proportionally
    remaining = 1.0 - credibility_weight
    other_total = _INSPECTION_WEIGHT + _RELEVANCE_WEIGHT + _CLEANLINESS_WEIGHT
    scale = remaining / other_total if other_total > 0 else 0.0

    w_insp = _INSPECTION_WEIGHT * scale
    w_rel = _RELEVANCE_WEIGHT * scale
    w_clean = _CLEANLINESS_WEIGHT * scale

    raw = (
        w_insp * insp_mean
        + w_rel * rel_mean
        + w_clean * cleanliness_score
        + credibility_weight * credibility
    )
    return max(0.0, min(1.0, raw))


def apply_rejection_rules(
    candidate: dict,
    min_claim_support: float = 0.30,
    max_misleading_risk: float = 0.50,
) -> str | None:
    """Return rejection reason string if candidate fails hard rules, else None.

    Rules evaluated in order:
    1. misleading_risk > max → "HIGH_MISLEADING_RISK"
    2. claim_support < min  → "LOW_CLAIM_SUPPORT"
    3. low cleanliness + fullscreen → "DIRTY_FULLSCREEN"
    """
    insp = candidate.get("inspection", {})
    misl = insp.get("misleading_risk", 0.0)
    claim = insp.get("claim_support", 1.0)
    clean = candidate.get("cleanliness_score", 1.0)
    treatment = candidate.get("treatment", "")

    if misl > max_misleading_risk:
        return "HIGH_MISLEADING_RISK"
    if claim < min_claim_support:
        return "LOW_CLAIM_SUPPORT"
    if clean < 0.3 and treatment == "fullscreen":
        return "DIRTY_FULLSCREEN"
    return None


def _build_rank_reason(
    score: float,
    rejection: str | None,
    decision: str,
) -> str:
    """Produce a human-readable rank reason."""
    if rejection:
        return f"Rejected: {rejection} (score={score:.2f})"
    return f"{decision.upper()} (score={score:.2f})"


def rank_candidates(
    beat: dict,
    candidates: list[dict],
    min_claim_support: float = 0.30,
    max_misleading_risk: float = 0.50,
) -> list[RankedCandidate]:
    """Score, filter, and rank candidates for a beat.

    For each candidate the function:
    1. Checks rejection rules.
    2. Computes the final composite score.
    3. Assigns a decision (accept / revise / reject).

    Candidates are sorted by score descending; equal scores are broken by
    role priority (evidence > context).  If every candidate is rejected a
    synthetic ``fallback_card`` entry is appended.
    """
    ranked: list[RankedCandidate] = []

    for cand in candidates:
        insp = cand.get("inspection", {})
        rel = cand.get("visual_relevance", {})
        clean = cand.get("cleanliness_score", 1.0)

        rejection = apply_rejection_rules(
            cand,
            min_claim_support=min_claim_support,
            max_misleading_risk=max_misleading_risk,
        )
        score = compute_final_score(insp, rel, cleanliness_score=clean)

        if rejection:
            decision = "reject"
        elif score >= _ACCEPT_THRESHOLD:
            decision = "accept"
        else:
            decision = "revise"

        ranked.append(
            RankedCandidate(
                asset_id=cand.get("asset_id", ""),
                beat_id=cand.get("beat_id", beat.get("beat_id", "")),
                final_score=score,
                decision=decision,
                inspection=insp,
                visual_relevance=rel,
                cleanliness_score=clean,
                rank_reason=_build_rank_reason(score, rejection, decision),
            )
        )

    # Sort: highest score first; tiebreak by role priority
    def _sort_key(r: RankedCandidate) -> tuple:
        cand_match = next(
            (c for c in candidates if c.get("asset_id") == r.asset_id), {}
        )
        role = cand_match.get("role", "context")
        return (-r.final_score, _ROLE_PRIORITY.get(role, 99))

    ranked.sort(key=_sort_key)

    # Append fallback_card when ALL candidates are rejected
    if ranked and all(r.decision == "reject" for r in ranked):
        ranked.append(
            RankedCandidate(
                asset_id="fallback",
                beat_id=beat.get("beat_id", ""),
                final_score=0.0,
                decision="fallback_card",
                inspection={},
                visual_relevance={},
                cleanliness_score=0.0,
                rank_reason="All candidates rejected — fallback text card",
            )
        )

    return ranked


def select_best_candidate(
    ranked: list[RankedCandidate],
) -> RankedCandidate | None:
    """Return the first non-rejected candidate, or None."""
    for r in ranked:
        if r.decision != "reject":
            return r
    return None
