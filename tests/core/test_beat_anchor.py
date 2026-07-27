"""Tests for the cue→word_range derivation helper (ADR 0030 / FIX-8).

Pure-domain logic: no LLM, no agent, no orchestrator coupling. The helper
tokenizes the voiceover, fuzzy-finds each ``start_cue`` inside it, and derives
contiguous ``[start, end]`` word ranges that fully cover ``[0, word_count-1]``.

Covers plan §7 cases 1-6.
"""

from clipper_agency.core.beat_anchor import DeriveResult, derive_word_ranges

# ── Plan §7 case 1: 101-word voiceover + 5 cues → 5 contiguous ranges ──

_VOICEOVER_101 = (
    # beat 1 (hook)
    "Halo guys hari ini gosip terbaru dari dunia seleb indonesia yang bikin heboh "
    # beat 2 (Anji)
    "pertama Anji ternyata resmi menikah lagi dengan Wina Natalia secara diam diam "
    "dan langsung bikin heboh karena nggak ada yang nyangka hubungan mereka cepat "
    # beat 3 (Raffi)
    "kedua Raffi Ahmad katanya lagi persiapin project besar bareng Nagita Slavina "
    "yang konon katanya bakal diumumkan secara resmi dalam beberapa minggu ke depan "
    # beat 4 (publik ramai — paraphrase cue)
    "ketiga publik ramai membahas gaya hidup mewah mereka yang bikin banyak orang "
    "kepo dan simulasi ikut ngomongin setiap hal kecil yang mereka bagikan online "
    # beat 5 (closing)
    "dan terakhir jangan lupa follow untuk update gosip setiap hari ya guys sampai "
    "jumpa di video selanjutnya see you next time bye bye"
)
# Token count: ~101 (per the plan). The tokenizer is the single source of
# truth; the tests below pin the band, not the exact figure.

_CUES_5 = [
    "Halo guys hari ini",  # beat 1 start
    "pertama Anji ternyata",  # beat 2 start
    "kedua Raffi Ahmad",  # beat 3 start
    "ketiga publik ramai",  # beat 4 start (paraphrase: voiceover has "membahas")
    "dan terakhir jangan lupa",  # beat 5 start
]


def test_plan_case1_happy_path_5_cues_cover_full_voiceover():
    res = derive_word_ranges(_VOICEOVER_101, _CUES_5)
    assert res.ok is True
    assert res.reason == "derived"
    assert len(res.word_ranges) == 5

    # Union must be exactly [0, word_count - 1], contiguous, in order.
    starts = [r[0] for r in res.word_ranges]
    ends = [r[1] for r in res.word_ranges]
    assert starts[0] == 0  # beat 0 always starts at 0
    assert starts == sorted(starts)  # monotonic
    for i in range(len(res.word_ranges) - 1):
        assert ends[i] == starts[i + 1] - 1  # contiguity
    # Final beat ends at the last token index.
    from clipper_agency.core.beat_anchor import _tokenize

    last_idx = len(_tokenize(_VOICEOVER_101)) - 1
    assert ends[-1] == last_idx
    # Plan claimed ~101 words; sanity-check the tokenizer agrees on the band.
    assert 95 <= last_idx + 1 <= 110


# ── Plan §7 case 2: paraphrase tolerance (cue wording ≠ voiceover wording) ──


def test_plan_case2_paraphrase_tolerance():
    """Cue ``Publik ramai bahas`` vs voiceover ``publik ramai membahas`` must
    fuzzy-match (Jaccard OR subsequence ≥ 0.6) so the beat is found."""
    voiceover = (
        "intro dummy filler kata pertama publik ramai membahas heboh kemudian kelanjutannya begini"
    )
    cues = ["publik ramai bahas"]
    res = derive_word_ranges(voiceover, cues)
    assert res.ok is True
    assert len(res.word_ranges) == 1
    # Single beat covers [0, len-1].
    from clipper_agency.core.beat_anchor import _tokenize

    n = len(_tokenize(voiceover))
    assert res.word_ranges[0] == [0, n - 1]


# ── Plan §7 case 3: cue not found → cue_not_found ──


def test_plan_case3_cue_not_found_fails_loud():
    voiceover = "satu dua tiga empat lima"
    cues = ["kosong sama sekali tidak ada"]
    res = derive_word_ranges(voiceover, cues)
    assert res.ok is False
    assert res.reason == "cue_not_found"
    assert res.word_ranges == []
    assert res.details["cue_index"] == 0


# ── Plan §7 case 4: cues out of order → cue_out_of_order ──


def test_plan_case4_cues_out_of_order_fails_loud():
    """Cue[1] matches an EARLIER voiceover position than cue[0] → cue_out_of_order
    (not cue_not_found)."""
    voiceover = "alpha beta gamma delta epsilon zeta eta theta"
    # alpha@0 ... gamma@2 ... delta@3 — cue[1] (delta) would land BEFORE cue[2] (gamma)
    # if we naively take the best match per cue. We craft cues whose best matches
    # are non-monotonic.
    cues = ["alpha beta", "delta epsilon", "gamma delta"]
    res = derive_word_ranges(voiceover, cues)
    assert res.ok is False
    assert res.reason == "cue_out_of_order"
    assert res.word_ranges == []


# ── Plan §7 case 5: single beat → [0, len-1] ──


def test_plan_case5_single_beat_covers_full_range():
    voiceover = "Halo guys selamat datang di channel gosip terbaru hari ini"
    cues = ["Halo guys selamat"]
    res = derive_word_ranges(voiceover, cues)
    assert res.ok is True
    from clipper_agency.core.beat_anchor import _tokenize

    n = len(_tokenize(voiceover))
    assert res.word_ranges == [[0, n - 1]]


# ── Plan §7 case 6: job_20 fixture (101 words, old mis-index) → derived correct ──


def test_plan_case6_job20_shape_derived_correct_and_passes_g7_defense_in_depth():
    """The job_20 failure mode: LLM emitted word_range union [0,94] for a 101-word
    voiceover (6-word uncovered tail). Derivation from cues MUST cover [0, 100]
    regardless of any LLM-supplied word_range, then the FIX-1 defense-in-depth
    validator passes too."""
    # Reuse the 101-word voiceover but feed start_cues; the helper must never
    # consult any LLM-emitted word_range.
    res = derive_word_ranges(_VOICEOVER_101, _CUES_5)
    assert res.ok is True
    # Build a narrative_structure from the derived ranges and run the existing
    # FIX-1 validator (kept as defense-in-depth per plan §3).
    from clipper_agency.core.beat_anchor import _tokenize
    from clipper_agency.core.narrative_coverage import validate_narrative_coverage

    word_count = len(_tokenize(_VOICEOVER_101))
    structure = [{"beat_id": i + 1, "word_range": r} for i, r in enumerate(res.word_ranges)]
    coverage = validate_narrative_coverage(structure, word_count=word_count)
    assert coverage.ok is True
    assert coverage.reason == "covered"  # exact coverage, no tail repair needed


# ── Determinism + immutability ──


def test_derivation_is_deterministic_across_calls():
    """Same inputs → same outputs (cache-key parity per plan §6)."""
    a = derive_word_ranges(_VOICEOVER_101, _CUES_5)
    b = derive_word_ranges(_VOICEOVER_101, _CUES_5)
    assert a.word_ranges == b.word_ranges
    assert a.reason == b.reason


def test_empty_voiceover_fails():
    res = derive_word_ranges("", ["cue"])
    assert res.ok is False
    assert res.reason == "cue_not_found"
    assert res.details["violation_type"] == "empty_voiceover"


def test_no_cues_fails():
    res = derive_word_ranges("satu dua tiga", [])
    assert res.ok is False
    assert res.reason == "cue_not_found"
    assert res.details["violation_type"] == "no_cues"


def test_empty_cue_string_fails():
    res = derive_word_ranges("satu dua tiga", ["", "satu dua"])
    assert res.ok is False
    assert res.reason == "cue_not_found"
    assert res.details["violation_type"] == "empty_cue"


def test_indonesian_punctuation_stripped_during_tokenization():
    """Punctuation must not break token matching; enclitics (nya/kah/lah) stay attached."""
    from clipper_agency.core.beat_anchor import _tokenize

    tokens = _tokenize("Halo, guys! Makanannya enak, ya kan?")
    assert "halo" in tokens
    assert "guys" in tokens
    # Enclitic stays attached to the host word — do NOT split into "makanan" + "nya".
    assert "makanannya" in tokens
    assert "makanan" not in tokens


def test_first_cue_not_at_position_zero_absorbs_intro_words():
    """Per plan §2: beat[0].start is ALWAYS 0 even if cue[0] matches later — intro
    words before the first cue are absorbed into beat 0."""
    # cue[0] only appears at position 2; beat[0] must still start at 0.
    voiceover = "intro words halo guys selamat datang"
    cues = ["halo guys selamat"]
    res = derive_word_ranges(voiceover, cues)
    assert res.ok is True
    assert res.word_ranges[0][0] == 0


def test_result_dataclass_defaults():
    r = DeriveResult(ok=True, reason="derived")
    assert r.word_ranges == []
    assert r.details == {}


def test_short_cue_below_min_token_count_still_matches_if_exact():
    """A 3-token exact-prefix cue must match at position 0 (the common case)."""
    voiceover = "alpha beta gamma delta epsilon"
    res = derive_word_ranges(voiceover, ["alpha beta gamma"])
    assert res.ok is True
    assert res.word_ranges[0] == [0, 4]  # covers full 5-token voiceover


# ── Review round-1 gap tests (pr-test-analyzer) ──


def test_tokenizer_consistency_derivation_matches_engine_word_count():
    """CRITICAL regression (review round-1): derive_word_ranges word_count MUST
    equal engine._word_count_for_coverage on Indonesian voiceovers carrying
    standalone punctuation (``...``, ``—``) and hyphenated tokens. A split()-based
    twin diverges and causes spurious out_of_bounds / uncovered_tail hard-fails.
    """
    from clipper_agency.core.beat_anchor import _tokenize, count_words
    from clipper_agency.orchestrator.engine import _word_count_for_coverage

    voiceover = "Halo guys ... ternyata Anji menikah — kata-kata mutiara, beneran!"
    derived_n = len(_tokenize(voiceover))
    engine_n = _word_count_for_coverage(voiceover)
    canonical_n = count_words(voiceover)
    # All three rulers agree (M == N end-to-end).
    assert derived_n == engine_n == canonical_n
    # Sanity: a naive split() would over-count the standalone ``...`` and ``—``.
    assert len(voiceover.split()) > derived_n


def test_duplicate_cues_fail_as_out_of_order():
    """Realistic LLM failure: reuse the same start_cue verbatim for two beats
    when the phrase appears only ONCE → cue_out_of_order (forward search can't
    find a 2nd occurrence; anywhere search confirms the phrase exists at/before
    the prev anchor, so it's an ordering defect, not a missing cue)."""
    voiceover = "alpha beta gamma delta epsilon zeta eta theta"
    res = derive_word_ranges(voiceover, ["alpha beta", "alpha beta"])
    assert res.ok is False
    assert res.reason == "cue_out_of_order"


def test_repeated_opening_phrase_resolves_to_distinct_anchors():
    """codex round-2 P1: two LEGITIMATE beats opening with the same 3-5 words
    (e.g. ``hari ini kita bahas`` reused as a hook) must each anchor on their
    OWN occurrence via forward search, not collapse onto the earliest match and
    falsely trip cue_out_of_order. Phrase appears twice → two distinct beats."""
    voiceover = "alpha beta gamma alpha beta delta epsilon zeta"
    res = derive_word_ranges(voiceover, ["alpha beta", "alpha beta"])
    assert res.ok is True
    assert len(res.word_ranges) == 2
    # beat 0 anchors on the 1st occurrence (pos 0), beat 1 on the 2nd (pos 3).
    ranges = res.word_ranges
    assert ranges[0][0] == 0
    assert ranges[1][0] == 3
    # Union covers the full voiceover.
    from clipper_agency.core.beat_anchor import _tokenize

    n = len(_tokenize(voiceover))
    assert ranges[-1][1] == n - 1


def test_verbatim_match_outranks_shuffled_same_token_set():
    """codex round-5 P2: a cue whose words appear EARLIER in a different order
    (``beta alpha``) must NOT win over a later verbatim match (``alpha beta``).
    Selection uses a (max, LCS) tuple so an ordered verbatim window outranks a
    same-token-set shuffled window on the LCS tiebreak."""
    from clipper_agency.core.beat_anchor import _find_best_position, _tokenize

    tokens = _tokenize("beta alpha gamma alpha beta delta")
    cue = _tokenize("alpha beta")
    pos, score = _find_best_position(tokens, cue, start_from=0)
    # Shuffled ``beta alpha`` sits at index 0; verbatim ``alpha beta`` at 3.
    assert pos == 3
    assert score >= 0.99


def test_overlapping_cues_rejected_as_out_of_order():
    """codex round-7 P1: a cue that begins INSIDE the previous cue's span
    (overlap) must be rejected as cue_out_of_order, not silently produce
    corrupted ranges. Forward search starts AFTER the previous cue's span."""
    voiceover = "alpha beta gamma delta epsilon"
    res = derive_word_ranges(voiceover, ["alpha beta gamma", "beta gamma delta"])
    assert res.ok is False
    assert res.reason == "cue_out_of_order"


def test_case_insensitive_cue_matching():
    """_tokenize lowercases both sides; mixed-case cues must match."""
    voiceover = "halo guys selamat datang di channel gosip"
    res = derive_word_ranges(voiceover, ["HALO Guys SELAMAT"])
    assert res.ok is True
    from clipper_agency.core.beat_anchor import _tokenize

    n = len(_tokenize(voiceover))
    assert res.word_ranges[0] == [0, n - 1]


def test_enclitic_cue_matches_end_to_end():
    """Enclitic-bearing cue (``makanannya``) must match the voiceover whole —
    the suffix never detaches, so a cue anchored on the enclitic token resolves."""
    voiceover = "makanannya enak banget kan murah sekali"
    res = derive_word_ranges(voiceover, ["makanannya enak", "murah sekali"])
    assert res.ok is True
    assert len(res.word_ranges) == 2
    # Union covers the full voiceover.
    from clipper_agency.core.beat_anchor import _tokenize

    n = len(_tokenize(voiceover))
    assert res.word_ranges[-1][1] == n - 1


def test_last_cue_at_voiceover_end_covers_short_closing_beat():
    """A closing beat whose cue anchors on the final 2 tokens still yields a
    valid (possibly short) range ending at len-1."""
    voiceover = "intro satu dua tiga empat lima tujuh bye bye"
    res = derive_word_ranges(voiceover, ["intro satu", "bye bye"])
    assert res.ok is True
    from clipper_agency.core.beat_anchor import _tokenize

    n = len(_tokenize(voiceover))
    assert res.word_ranges[-1] == [n - 2, n - 1]
