"""Cue→word_range derivation helper (ADR 0030 / FIX-8).

Pure domain logic: no I/O, no logging, no orchestrator coupling. The helper
tokenizes the voiceover, fuzzy-finds each ``start_cue`` inside it, and derives
contiguous ``[start, end]`` word ranges that fully cover ``[0, word_count-1]``.

Why this exists (root cause): the LLM cannot reliably count its own words.
Empirically validated 2x (job_19 over-index, job_20 under-index). The fix is
the HeyGen HyperFrames industry pattern — TTS word timestamps are the source of
truth; the LLM identifies *semantic* boundaries (``start_cue`` = 3-5 first
words of each beat, copied verbatim from the voiceover) and CODE computes the
indices. Downstream consumers (``build_canonical_timeline``, Visual Director,
Composer, Reviewer) keep reading ``word_range`` — now derived, not emitted.

Algorithm (per plan §2):
    1. Tokenize voiceover: lowercase + strip Indonesian punctuation, keep
       enclitics (nya/kah/lah) attached to the host token.
    2. For each cue, fuzzy-find its best position in the voiceover using
       max(token-set Jaccard, LCS ratio) over a sliding window the size of
       the cue. Deterministic (best score wins; ties → lowest position).
    3. Assert cues are monotonically increasing in position.
    4. Derive ranges: beat[0].start=0, beat[i].start=cue[i] pos,
       beat[i].end=beat[i+1].start-1, last.end=len(tokens)-1.

Fail-loud on ``cue_not_found`` (a cue scored below ``MATCH_THRESHOLD``) or
``cue_out_of_order`` (positions not strictly increasing). Both route to the
Scriptwriter via the FIX-5 reason-based repair router.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Fuzzy-match threshold: max(Jaccard, LCS ratio) must reach this for a cue to
# be considered found. 0.6 tolerates a 1-word paraphrase in a 3-word cue
# (2/3 = 0.667 ≥ 0.6) while still rejecting a totally unrelated cue.
MATCH_THRESHOLD = 0.6

# Indonesian tokenizer: lowercase, strip punctuation that is NOT internal to a
# word. Hyphens/apostrophes BETWEEN word characters survive so Indonesian
# reduplication (``kata-kata``, ``anak-anak``) and possessives (``jang'an``)
# count as ONE token — matching the Voice Producer's whitespace ``split()``
# (so derived word_range indices align 1:1 with TTS timestamps). Leading,
# trailing, and standalone punctuation (``...``, ``—``) are stripped.
_PUNCT_RE = re.compile(r"(?<!\w)[^\w\s]+|[^\w\s]+(?!\w)", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace.

    Enclitic-bearing tokens (``makanannya``, ``baguskah``, ``diajah``) stay
    intact: punctuation is replaced with whitespace and the residual word is
    taken whole, so the suffix never detaches.
    """
    if not text:
        return []
    cleaned = _PUNCT_RE.sub(" ", text.lower())
    return [t for t in cleaned.split() if t]


def tokenize(text: str) -> list[str]:
    """Public canonical word tokenizer (the FIX-8 ruler).

    MUST be used by EVERY consumer of word indices — ``derive_word_ranges``
    (derivation), ``engine._word_count_for_coverage`` (G7 validation count),
    ``scriptwriter._word_count`` + ``_validate_output`` (cue-length) — so M == N
    end-to-end. A divergence here causes spurious ``out_of_bounds`` /
    ``uncovered_tail`` hard-fails on Indonesian voiceovers with ``...``/``—``/
    hyphenated tokens (job_19/20 root-cause class).
    """
    return _tokenize(text)


def count_words(text: str) -> int:
    """Canonical word count via :func:`tokenize`."""
    return len(_tokenize(text))


def _jaccard(a: set[str], b: set[str]) -> float:
    """Token-set Jaccard overlap. Order-independent."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _lcs_ratio(window: list[str], cue: list[str]) -> float:
    """Longest-common-subsequence length between ``window`` and ``cue``,
    normalized by ``len(cue)``.

    Captures ORDER similarity (the cue is supposed to be the first words of
    the beat, in order). O(n*m) — cue/window are 3-5 tokens, so this is cheap.
    """
    if not cue:
        return 0.0
    m, n = len(window), len(cue)
    # Single-row DP (rolling max) — keeps allocation tiny.
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        wi = window[i - 1]
        for j in range(1, n + 1):
            if wi == cue[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = prev[j] if prev[j] >= cur[j - 1] else cur[j - 1]
        prev = cur
    return prev[n] / len(cue)


def _find_best_position(
    tokens: list[str], cue_tokens: list[str], start_from: int = 0
) -> tuple[int, float]:
    """Find the index in ``tokens`` where ``cue_tokens`` best matches.

    Returns ``(best_position, best_score)``. Position is the start index of the
    match window. Ties broken by LOWEST position (deterministic).

    ``start_from`` constrains the search to positions ``>= start_from`` so that
    a cue whose phrase legitimately RECURS (two beats opening with the same
    3-5 words, e.g. ``hari ini kita bahas``) resolves to a LATER occurrence
    than the previous beat's anchor — instead of both collapsing onto the
    earliest match and falsely tripping ``cue_out_of_order`` (codex round-2 P1).

    When the voiceover is shorter than the cue, no full-size window exists —
    fall back to scoring the whole token list as one window.
    """
    if not cue_tokens:
        return start_from, 0.0
    cue_set = set(cue_tokens)
    window_size = len(cue_tokens)
    best_pos = start_from
    # Select by a (primary, tiebreak) tuple: primary = max(Jaccard, LCS) so a
    # paraphrased cue can still clear MATCH_THRESHOLD via whichever metric is
    # stronger; tiebreak = LCS (order-sensitive) so on a primary tie a VERBATIM
    # ordered window outranks a shuffled same-token-set window (codex round-5
    # P2 — cue ``a b c`` must not anchor on an earlier ``b a c``).
    best_key = (-1.0, -1.0)

    last_full_start = max(start_from, len(tokens) - window_size)
    for i in range(start_from, last_full_start + 1):
        window = tokens[i : i + window_size]
        j = _jaccard(set(window), cue_set)
        lcs = _lcs_ratio(window, cue_tokens)
        key = (max(j, lcs), lcs)
        if key > best_key:
            best_key = key
            best_pos = i

    return best_pos, max(0.0, best_key[0])


@dataclass(frozen=True)
class DeriveResult:
    """Outcome of ``derive_word_ranges``.

    ``ok`` is True iff every cue fuzzy-matched at or above
    :data:`MATCH_THRESHOLD` AND the match positions are strictly increasing.
    On success ``word_ranges`` carries one ``[start, end]`` pair per cue, in
    beat order, whose union is exactly ``[0, len(voiceover_tokens) - 1]``.

    On failure ``word_ranges`` is empty and ``reason`` is one of the stable
    routing tokens below (consumed by the FIX-5 reason-based repair router).
    """

    ok: bool
    reason: str
    word_ranges: list[list[int]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


# Stable machine reasons emitted in GateResult.data['reason'] on hard_fail.
# The FIX-5 repair router maps these to a Scriptwriter regen (cue failures are
# producer-side defects — the LLM emitted a cue that does not anchor in the
# voiceover it also wrote). Do not rename without updating the router map.
CUE_NOT_FOUND = "cue_not_found"
CUE_OUT_OF_ORDER = "cue_out_of_order"


def derive_word_ranges(voiceover_text: str, cues: list[str]) -> DeriveResult:
    """Derive contiguous ``[start, end]`` word ranges for each beat from its
    ``start_cue``.

    See module docstring for the algorithm. Inputs are never mutated. Pure and
    deterministic (cache-key parity per plan §6 — same ``(voiceover, cues)``
    always yields the same ranges).

    Args:
        voiceover_text: The full continuous voiceover (single source of truth
            for word indices).
        cues: Ordered list of ``start_cue`` phrases (3-5 first words of each
            beat, as emitted by the Scriptwriter).

    Returns:
        A :class:`DeriveResult`. ``ok=True`` with ``word_ranges`` populated on
        success; ``ok=False`` with an empty ``word_ranges`` and a stable
        ``reason`` (``cue_not_found`` / ``cue_out_of_order``) on failure.
    """
    # 1. Tokenize voiceover (the ruler for all word indices).
    tokens = _tokenize(voiceover_text)
    if not tokens:
        return DeriveResult(
            ok=False,
            reason=CUE_NOT_FOUND,
            details={"violation_type": "empty_voiceover"},
        )
    if not cues:
        return DeriveResult(
            ok=False,
            reason=CUE_NOT_FOUND,
            details={
                "violation_type": "no_cues",
                "word_count": len(tokens),
            },
        )

    # 2. Find best position for each cue. Search FORWARD from the previous
    #    cue's anchor (start_from = prev+1) so a phrase that legitimately
    #    RECURS (two beats opening with the same words, e.g. ``hari ini kita
    #    bahas``) resolves to its NEXT occurrence rather than collapsing onto
    #    the earliest match and falsely tripping out-of-order (codex round-2
    #    P1). On forward-search failure, re-search the WHOLE voiceover to
    #    distinguish cue_out_of_order (phrase exists but at/before the prev
    #    anchor) from cue_not_found (phrase genuinely absent).
    positions: list[int] = []
    for i, cue in enumerate(cues):
        # Coerce non-string cues at the boundary (LLM may emit None/int).
        cue_str = cue if isinstance(cue, str) else ("" if cue is None else str(cue))
        cue_tokens = _tokenize(cue_str)
        if not cue_tokens:
            return DeriveResult(
                ok=False,
                reason=CUE_NOT_FOUND,
                details={
                    "violation_type": "empty_cue",
                    "cue_index": i,
                    "word_count": len(tokens),
                },
            )
        prev = positions[-1] if positions else -1
        fwd_pos, fwd_score = _find_best_position(tokens, cue_tokens, start_from=prev + 1)
        if fwd_score >= MATCH_THRESHOLD:
            positions.append(fwd_pos)
            continue
        # Forward search failed. Is the cue present EARLIER (out of order) or
        # genuinely absent (not found)? Search anywhere to tell them apart.
        any_pos, any_score = _find_best_position(tokens, cue_tokens, start_from=0)
        if any_score >= MATCH_THRESHOLD:
            return DeriveResult(
                ok=False,
                reason=CUE_OUT_OF_ORDER,
                details={
                    "violation_type": "out_of_order",
                    "cue_index": i,
                    "prev_pos": prev,
                    "this_pos": any_pos,
                    "word_count": len(tokens),
                },
            )
        return DeriveResult(
            ok=False,
            reason=CUE_NOT_FOUND,
            details={
                "violation_type": "cue_not_matched",
                "cue_index": i,
                "cue": cue,
                "best_score": round(max(fwd_score, any_score), 4),
                "threshold": MATCH_THRESHOLD,
                "word_count": len(tokens),
            },
        )

    # 4. Derive word_ranges. beat[0].start=0 (per plan §2 — intro words
    #    before the first cue are absorbed into beat 0); beat[i].end =
    #    beat[i+1].start - 1; last.end = len(tokens) - 1.
    word_ranges: list[list[int]] = []
    last_idx = len(tokens) - 1
    for i in range(len(positions)):
        start = 0 if i == 0 else positions[i]
        end = (positions[i + 1] - 1) if i + 1 < len(positions) else last_idx
        word_ranges.append([start, end])

    return DeriveResult(
        ok=True,
        reason="derived",
        word_ranges=word_ranges,
        details={
            "word_count": len(tokens),
            "beat_count": len(cues),
            "positions": positions,
        },
    )
