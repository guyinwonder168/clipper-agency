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

# FIX-3 Codex P2 #2 — decision sort priority (lower = better). An ``accept``
# must outrank a higher-scoring ``revise`` (the Slice-3 missing-subject
# downgrade) so ``select_best_candidate`` returns the verifiable accept and VD
# does not fall back past an acceptable asset.
_DECISION_SORT_PRIORITY = {"accept": 0, "revise": 1, "reject": 2, "fallback_card": 3}


# ---------------------------------------------------------------------------
# FIX-3 Slice 2 — entity-binding helpers (pure, no I/O).
# Expected entities are bound AUTHORITATIVELY from visual_must_show (spoken_point
# is a fallback ONLY when visual_must_show yields no named entities); the
# VLM-emitted subject_name must overlap one of them or the candidate is a
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

# FIX-3 Codex P2 #1 — generic media/news/category words that appear in a
# visual_must_show contract but are NOT named entities (e.g. Job 8's "Thumbnail
# berita artis dengan teks 'BERITA HARI INI'"). Even when capitalized (sentence
# start), these must NOT become expected entities — otherwise a real-person
# subject_name (e.g. "Raffi Ahmad") is falsely rejected as WRONG_ENTITY on a
# generic/context beat. The entity rule fires only when a real NAMED target
# (capitalized, non-generic) was derived.
_GENERIC_CONTRACT_WORDS = frozenset(
    {
        "thumbnail",
        "berita",
        "artis",
        "teks",
        "video",
        "gambar",
        "foto",
        "headline",
        "caption",
        "overlay",
        "update",
        "terbaru",
        "viral",
        "heboh",
        "gosip",
        "kabar",
        "berbagai",
        "beberapa",
        "kumpulan",
        "hari",
        "trending",
        "populer",
        "terpopuler",
        "koment",
        "bawah",
        "news",
        "story",
        "scene",
        "image",
        "picture",
        # FIX-3 Codex P2 (r3566760232, job8 fixture): generic hook/CTA narration
        # openers that are capitalized at sentence start but are NOT named
        # entities. Without these, a generic/context beat derives e.g. "halo" /
        # "reaksi" / "jangan" as expected entities and falsely rejects any real
        # person as WRONG_ENTITY -> unnecessary fallback cards. Adding more is
        # SAFE (only removes false entities; the only risk is dropping a real
        # entity that is a common word, which is rare for proper-name beats).
        # Indonesian hook/discourse openers + generic narration nouns:
        "halo",
        "reaksi",
        "jangan",
        "lihat",
        "simak",
        "tunggu",
        "cek",
        "yuk",
        "ayo",
        "nah",
        "wah",
        "wow",
        "sini",
        "perhatikan",
        "coba",
        "cobain",
        "padahal",
        "ternyata",
        "katanya",
        "begitu",
        "sekarang",
        "ingat",
        "bayangkan",
        "fakta",
        "rahasia",
        "momen",
        "aksi",
        "saksi",
        "kisah",
        "cerita",
        "detik",
        "drama",
        "skandal",
        "sensasi",
        # FIX-4 (ADR 0030) Slice 4: platform/format words that appear in
        # narration/contracts but are NOT named entities. Without these, a beat
        # whose spoken_point mentions "TikTok" derives "tiktok" as an expected
        # entity, and any TikTok-branded asset falsely matches — or worse, a
        # real-person asset is falsely rejected as WRONG_ENTITY. "viral" is
        # already present; the rest are new.
        "tiktok",
        "youtube",
        "ig",
        "instagram",
        "reels",
        "duet",
        "stitch",
        "fyp",
        "konten",
        "kreator",
    }
)


def _normalize_token(token: str) -> str:
    """Lowercase + strip non-alpha (handles accents/diacritics + punctuation)."""
    return "".join(c for c in token.lower() if c.isalpha())


def _entities_from_text(text: str) -> list[list[str]]:
    """Extract de-duplicated named-entity PHRASES from a single text field.

    Each phrase is a maximal run of consecutive proper-noun tokens (leading
    capital, length >= ``_ENTITY_MIN_TOKEN_LEN`` after normalization, not in
    ``_ENTITY_STOPWORDS`` / ``_GENERIC_CONTRACT_WORDS``). Phrase structure is
    preserved so ``entity_overlap`` can require a multi-token name (e.g.
    "Raffi Ahmad") to match as a UNIT — a single shared token ("ahmad" between
    expected "Raffi Ahmad" and subject "Ahmad Doe") must NOT accept a different
    person (FIX-4 Codex P2). Stopwords / generic terms / lowercase tokens break
    a phrase run, so "Sarwendah dan Ruben" yields two single-token phrases.
    """
    phrases: list[list[str]] = []
    current: list[str] = []
    for token in (text or "").split():
        norm = _normalize_token(token)
        kept = (
            len(norm) >= _ENTITY_MIN_TOKEN_LEN
            and norm not in _ENTITY_STOPWORDS
            and norm not in _GENERIC_CONTRACT_WORDS
            and token[:1].isupper()
        )
        if not kept:
            if current:
                phrases.append(current)
                current = []
            continue
        if norm not in current:
            current.append(norm)
    if current:
        phrases.append(current)
    seen: set[tuple[str, ...]] = set()
    deduped: list[list[str]] = []
    for phrase in phrases:
        key = tuple(phrase)
        if key not in seen:
            seen.add(key)
            deduped.append(phrase)
    return deduped


def derive_expected_entities(
    spoken_point: str,
    visual_must_show: str = "",
) -> list[list[str]]:
    """Derive candidate entity-name PHRASES from a beat's text fields.

    FIX-3 round-3 (Codex): ``visual_must_show`` is the AUTHORITATIVE
    entity-binding source. When it yields one or more named entities, those are
    returned ALONE — ``spoken_point`` names must NOT widen the binding set.
    Otherwise a beat about "Sarwendah" whose narration merely mentions "Jennifer
    Coppen" (a comparison/contrast) adds "jennifer"/"coppen" to the expected
    entities, and a Jennifer Coppen asset then PASSES the WRONG_ENTITY check —
    the exact job_18 wrong-person binding failure FIX-3 targets.

    ``spoken_point`` is consulted ONLY as a fallback when ``visual_must_show``
    yields zero entities (a generic/context contract like "Thumbnail berita
    artis"), where there is no authoritative binding to enforce. This preserves
    the recall-tuned behavior for beats that name their subject only in
    narration. Both fields require a leading capital (proper-noun signal) AND
    drop function words (``_ENTITY_STOPWORDS``) + generic media/category terms
    (``_GENERIC_CONTRACT_WORDS``).

    FIX-4 (Codex P2): returns PHRASES (``list[list[str]]``), not flat tokens, so
    multi-token names match as a unit. Tuned for RECALL on the named-entity
    subset: an extra junk phrase only gives ``subject_name`` another harmless
    overlap attempt, while a MISSED true entity causes a false WRONG_ENTITY.
    """
    binding = _entities_from_text(visual_must_show)
    if binding:
        return binding
    return _entities_from_text(spoken_point)


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


def _phrase_matches(phrase: list[str], subj_tokens: list[str], subj_set: set[str]) -> bool:
    """Does one expected entity PHRASE match the subject? (FIX-4 Codex P2.)

    Single-token phrase: lenient Rules A/B/C via ``_expected_entity_matches``
    (alias/transliteration tolerance + the Cristiano-Ronaldo/ronaldo case).
    Multi-token phrase: token-set Jaccard >= ``_ENTITY_JACCARD_THRESHOLD`` so a
    single shared token ("ahmad" between "Raffi Ahmad" and "Ahmad Doe") does NOT
    accept a different person. Tokens are normalized + filtered (generic words
    + sub-min-length noise dropped) defensively.
    """
    significant = [
        t
        for t in (_normalize_token(tok) for tok in phrase)
        if len(t) >= _ENTITY_MIN_TOKEN_LEN and t not in _GENERIC_CONTRACT_WORDS
    ]
    if not significant:
        return False
    if len(significant) == 1:
        return _expected_entity_matches(significant[0], subj_tokens)
    inter = len(subj_set & set(significant))
    union = len(subj_set | set(significant))
    return bool(union) and inter / union >= _ENTITY_JACCARD_THRESHOLD


def entity_overlap(subject_name: str, expected: list[list[str]]) -> bool:
    """True if ``subject_name`` plausibly matches any expected entity PHRASE.

    FIX-4 (Codex P2): ``expected`` is a list of phrases (``list[list[str]]``).
    Generic words are filtered out of each phrase (defense-in-depth) so a
    "TikTok" asset never matches a beat that merely mentions TikTok.
    """
    if not subject_name or not expected:
        return False
    subj_tokens = [t for t in (_normalize_token(s) for s in subject_name.split()) if t]
    if not subj_tokens:
        return False
    subj_set = set(subj_tokens)
    return any(_phrase_matches(p, subj_tokens, subj_set) for p in expected)


def is_unverifiable_entity_binding(candidate: dict) -> bool:
    """True when a person-depicting asset on an entity-binding beat cannot be verified.

    FIX-3 Slice 3: the VLM depicted a person (``person_match`` >=
    ``_PERSON_PRESENT``) on a beat that expects named entities
    (``expected_entities`` present), but could not name the subject (no
    ``subject_name``). Such a candidate can never be entity-verified, so:

    * ``rank_candidates`` downgrades it from ``accept`` to ``revise`` (VD never
      accepts an unverified person asset); and
    * the pre-VD asset-qualification path (``_rank_and_select``) EXCLUDES it from
      ``qualified`` so the RECOVER stage runs before a text-card fallback —
      otherwise the ``revise`` verdict would count as qualified and silently skip
      recovery for precisely the unverifiable entity assets FIX-3 targets.

    Pure predicate (no I/O); reads the scored-candidate dict shape produced by
    ``_score_candidate`` / ``_score_one_candidate``.
    """
    insp = candidate.get("inspection", {})
    return bool(
        candidate.get("expected_entities")
        and insp.get("person_match", 0.0) >= _PERSON_PRESENT
        and not insp.get("subject_name")
    )


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
        # non-person / undecorated beats are unaffected. The shared predicate is
        # also used by asset_qualification._rank_and_select to exclude these from
        # `qualified` (trigger RECOVER before a text-card fallback).
        if decision == "accept" and is_unverifiable_entity_binding(cand):
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

    # Sort: decision priority first (accept > revise > reject — Codex P2 #2: a
    # verified accept must outrank a higher-scoring Slice-3-downgraded revise so
    # VD does not fall back past an acceptable asset), then score, then role.
    def _sort_key(r: RankedCandidate) -> tuple:
        cand_match = next((c for c in candidates if c.get("asset_id") == r.asset_id), {})
        role = cand_match.get("role", "context")
        return (
            _DECISION_SORT_PRIORITY.get(r.decision, 99),
            -r.final_score,
            _ROLE_PRIORITY.get(role, 99),
        )

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
