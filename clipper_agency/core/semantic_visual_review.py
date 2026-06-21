"""Pure semantic visual-relevance scorer — no VLM calls, no I/O.

Deterministic weighted scoring function that combines per-dimension
inspection scores (person_match, event_match, claim_support, visual_quality)
into a single ``VisualRelevanceScore`` with an accept/revise/reject decision
and misleading-risk flag.

All inputs are injectable for testability.
"""

from __future__ import annotations

from clipper_agency.config.schema import VisualRelevanceScore

# Weight for the temporal_match signal the VLM returns.
# Defaults to 0.0 so wiring the signal in is byte-identical to the prior
# behavior (the term cannot move the score). Raising this weight is a separate
# follow-up gated on PR 13 confirming temporal_match correlates with review
# outcomes (RC-4). This constant IS the knob: it is injected into
# DEFAULT_WEIGHTS below so raising it actually enables temporal weighting.
_TEMPORAL_MATCH_WEIGHT = 0.0

DEFAULT_WEIGHTS: dict[str, float] = {
    "person_match": 0.20,
    "event_match": 0.25,
    "claim_support": 0.25,
    "visual_quality": 0.30,
    "temporal_match": _TEMPORAL_MATCH_WEIGHT,
}

# Decision thresholds
_ACCEPT_THRESHOLD = 0.6
_REVISE_FLOOR = 0.4
_MISLEADING_HARD = 0.7
_MISLEADING_SOFT = 0.5

# Dimensions summed into the weighted score. temporal_match is appended so the
# VLM's temporal signal is now READ (previously discarded) but cannot move the
# score until its weight is raised above 0.0.
_SCORED_DIMENSIONS = (
    "person_match",
    "event_match",
    "claim_support",
    "visual_quality",
    "temporal_match",
)


def _compute_misleading_risk(
    person_match: float, event_match: float, claim_support: float
) -> float:
    """High person match + low event/claim support → misleading risk."""
    if person_match > 0.8 and (event_match + claim_support) / 2 < 0.4:
        return 0.5 + (person_match - 0.8) * 2.5
    return 0.0


def _weighted_score(
    inspection: dict[str, float],
    weights: dict[str, float],
) -> float:
    """Sum of weighted dimension scores.

    ``temporal_match`` is summed with a default weight of 0.0
    (``DEFAULT_WEIGHTS["temporal_match"] = _TEMPORAL_MATCH_WEIGHT = 0.0``), so
    the term is READ but cannot move the score until that weight is raised.
    This preserves the prior behavior exactly (RC-4).
    """
    return sum(weights.get(dim, 0.0) * inspection.get(dim, 0.0) for dim in _SCORED_DIMENSIONS)


def score_visual_relevance(
    beat: dict,
    asset_inspection: dict[str, float],
    weights: dict[str, float] | None = None,
) -> VisualRelevanceScore:
    """Score visual relevance of an asset against a story beat.

    Parameters
    ----------
    beat:
        Story beat dict (``beat_id``, ``claim``).  Passed through for
        traceability — not used in the scoring formula itself.
    asset_inspection:
        Per-dimension floats: ``person_match``, ``event_match``,
        ``claim_support``, ``visual_quality``.  ``temporal_match`` is also read
        but contributes 0.0 by default (see ``_TEMPORAL_MATCH_WEIGHT``).
    weights:
        Optional weight override per dimension.  Falls back to
        ``DEFAULT_WEIGHTS``.  ``temporal_match`` defaults to weight 0.0 unless
        explicitly overridden here.

    Returns
    -------
    VisualRelevanceScore
        Deterministic accept / revise / reject decision with detail.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS

    person_match = asset_inspection.get("person_match", 0.0)
    event_match = asset_inspection.get("event_match", 0.0)
    claim_support = asset_inspection.get("claim_support", 0.0)
    visual_quality = asset_inspection.get("visual_quality", 0.0)

    misleading_risk = _compute_misleading_risk(person_match, event_match, claim_support)
    combined = _weighted_score(asset_inspection, w)

    # Decision logic
    if combined >= _ACCEPT_THRESHOLD and misleading_risk < _MISLEADING_SOFT:
        decision = "accept"
        detail = f"Score {combined:.2f} meets threshold"
    elif combined < _REVISE_FLOOR or misleading_risk >= _MISLEADING_HARD:
        decision = "reject"
        reason = "low score" if combined < _REVISE_FLOOR else "high misleading risk"
        detail = f"{reason} (combined={combined:.2f}, misleading={misleading_risk:.2f})"
    else:
        decision = "revise"
        detail = f"Borderline (combined={combined:.2f}, misleading={misleading_risk:.2f})"

    return VisualRelevanceScore(
        decision=decision,
        misleading_risk=misleading_risk,
        person_match=person_match,
        event_match=event_match,
        claim_support=claim_support,
        visual_quality=visual_quality,
        detail=detail,
    )
