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

# FIX-3 Slice 3 — a candidate depicting a person (person_match >= this) on an
# entity-binding beat that the VLM could NOT name (no subject_name) cannot be
# entity-verified, so it is never accepted (downgraded to "revise").
_PERSON_PRESENT = 0.5

# FIX-3 Slice 2 — entity-binding overlap thresholds. Documented in ADR 0030.
# Rule C (char-set Jaccard) is the transliteration/alias fallback; min token
# length 5 + ratio 0.75 keeps it from over-matching short unrelated names
# (verified: "Jennifer Coppen" vs "sarwendah" scores 0.25 — no match).
_ENTITY_JACCARD_THRESHOLD = 0.75
_ENTITY_MIN_TOKEN_LEN = 4
_ENTITY_FUZZY_MIN_LEN = 5

# Inspection dimension keys
_INSPECTION_DIMS = ("person_match", "event_match", "claim_support", "visual_quality")

# Role priority (lower = better): evidence preferred over context
_ROLE_PRIORITY = {"evidence": 0, "context": 1}


# ---------------------------------------------------------------------------
# FIX-3 Slice 2 — entity-binding helpers (pure, no I/O).
# Expected entities are derived from the beat's spoken_point + visual_must_show;
# the VLM-emitted subject_name must overlap one of them or the candidate is a
# wrong-entity mismatch (job_18: a Sarwendah beat got a Jennifer Coppen image).
# ---------------------------------------------------------------------------

# Frequent Indonesian + English words filtered out of free-text entity
# derivation. Extra junk tokens are HARMLESS (they only give subject_name more
# overlap chances); the costly failure is MISSING the true entity, so this set
# is intentionally small — recall over precision.
_ENTITY_STOPWORDS = frozenset(
    {
        # Indonesian
        "yang",
        "dan",
        "di",
        "ke",
        "dari",
        "untuk",
        "pada",
        "dengan",
        "ini",
        "itu",
        "atau",
        "karena",
        "juga",
        "akan",
        "tidak",
        "udah",
        "sudah",
        "kalau",
        "bahwa",
        "oleh",
        "agar",
        "bisa",
        "ada",
        "adalah",
        "saya",
        "kami",
        "kita",
        "mereka",
        "dia",
        # English
        "and",
        "the",
        "for",
        "with",
        "was",
        "has",
        "have",
        "this",
        "that",
        "from",
    }
)


def _normalize_token(token: str) -> str:
    """Lowercase + strip non-alpha (handles accents/diacritics + punctuation)."""
    return "".join(c for c in token.lower() if c.isalpha())


def derive_expected_entities(
    spoken_point: str,
    visual_must_show: str = "",
) -> list[str]:
    """Derive candidate entity-name tokens from a beat's text fields.

    ``visual_must_show`` is hand-written (curated): trust alpha tokens >= min
    length that are not stopwords. ``spoken_point`` is free-text narration:
    additionally require a leading uppercase letter as a proper-noun signal so
    common words don't pollute the set. Returns a de-duplicated list
    (visual_must_show tokens first, then spoken_point).

    Tuned for RECALL: an extra junk token only gives ``subject_name`` another
    harmless overlap attempt, while a MISSED true entity causes a false
    WRONG_ENTITY reject. Non-person beats (no curated field, no capitalized
    proper noun) naturally yield an empty list, which makes the WRONG_ENTITY
    rule a no-op for them.
    """
    entities: list[str] = []
    seen: set[str] = set()

    def _consider(token: str, curated: bool) -> None:
        norm = _normalize_token(token)
        if len(norm) < _ENTITY_MIN_TOKEN_LEN or norm in _ENTITY_STOPWORDS:
            return
        if not curated and not token[:1].isupper():
            return
        if norm not in seen:
            seen.add(norm)
            entities.append(norm)

    for token in (visual_must_show or "").split():
        _consider(token, curated=True)
    for token in (spoken_point or "").split():
        _consider(token, curated=False)
    return entities


def _expected_entity_matches(exp: str, subj_tokens: list[str]) -> bool:
    """Does one normalized expected entity (len >= 4) match any subject token?

    Rule A — exact token membership. Rule B — bidirectional substring (>= 4,
    catches aliases/transliteration like "sarwenda" in "sarwendah"). Rule C —
    char-set Jaccard >= 0.75 for both tokens >= 5 (spelling-drift fallback).
    """
    if exp in subj_tokens:
        return True
    for st in subj_tokens:
        if len(st) < _ENTITY_MIN_TOKEN_LEN:
            continue
        if exp in st or st in exp:
            return True
        if len(exp) >= _ENTITY_FUZZY_MIN_LEN and len(st) >= _ENTITY_FUZZY_MIN_LEN:
            inter = len(set(exp) & set(st))
            union = len(set(exp) | set(st))
            if union and inter / union >= _ENTITY_JACCARD_THRESHOLD:
                return True
    return False


def entity_overlap(subject_name: str, expected: list[str]) -> bool:
    """True if ``subject_name`` plausibly matches any of the ``expected`` entities."""
    if not subject_name or not expected:
        return False
    subj_tokens = [t for t in (_normalize_token(s) for s in subject_name.split()) if t]
    if not subj_tokens:
        return False
    for exp_raw in expected:
        exp = _normalize_token(exp_raw)
        if len(exp) < _ENTITY_MIN_TOKEN_LEN:
            continue
        if _expected_entity_matches(exp, subj_tokens):
            return True
    return False


def _mean_score(data: dict, keys: tuple[str, ...]) -> float:
    """Arithmetic mean of values for *keys* in *data*."""
    values = [data.get(k, 0.0) for k in keys]
    return sum(values) / len(values) if values else 0.0


def compute_final_score(
    inspection: dict,
    visual_relevance: dict,
    cleanliness_score: float = 1.0,
    credibility_weight: float = _CREDIBILITY_WEIGHT,
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
    0. entity-binding (FIX-3): expected_entities set + subject_name present +
       no name overlap → "WRONG_ENTITY"
    1. misleading_risk > max → "HIGH_MISLEADING_RISK"
    2. claim_support < min  → "LOW_CLAIM_SUPPORT"
    3. low cleanliness + fullscreen → "DIRTY_FULLSCREEN"

    Rule 0 is a no-op when ``expected_entities`` is absent (non-person beats or
    undecorated fixtures), preserving backward compatibility.
    """
    insp = candidate.get("inspection", {})

    # FIX-3 Slice 2 — wrong-entity binding check (most specific, first).
    expected = candidate.get("expected_entities", [])
    subject = insp.get("subject_name", "")
    if expected and subject and not entity_overlap(subject, expected):
        return "WRONG_ENTITY"

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
    note: str = "",
) -> str:
    """Produce a human-readable rank reason."""
    reason = (
        f"Rejected: {rejection} (score={score:.2f})"
        if rejection
        else f"{decision.upper()} (score={score:.2f})"
    )
    return f"{reason} — {note}" if note else reason


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

        note = ""
        if rejection:
            decision = "reject"
        elif score >= _ACCEPT_THRESHOLD:
            decision = "accept"
        else:
            decision = "revise"

        # FIX-3 Slice 3 — a person-depicting asset on an entity-binding beat
        # whose subject the VLM could not name cannot be entity-verified: never
        # accept it, downgrade to revise so a verifiable candidate (or the
        # fallback/recover path) wins instead. Gated on expected_entities so
        # non-person / undecorated beats are unaffected.
        if (
            decision == "accept"
            and cand.get("expected_entities")
            and insp.get("person_match", 0.0) >= _PERSON_PRESENT
            and not insp.get("subject_name")
        ):
            decision = "revise"
            note = "person depicted but subject_name missing — cannot verify entity binding"

        ranked.append(
            RankedCandidate(
                asset_id=cand.get("asset_id", ""),
                beat_id=cand.get("beat_id", beat.get("beat_id", "")),
                final_score=score,
                decision=decision,
                inspection=insp,
                visual_relevance=rel,
                cleanliness_score=clean,
                rank_reason=_build_rank_reason(score, rejection, decision, note),
            )
        )

    # Sort: highest score first; tiebreak by role priority
    def _sort_key(r: RankedCandidate) -> tuple:
        cand_match = next((c for c in candidates if c.get("asset_id") == r.asset_id), {})
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
