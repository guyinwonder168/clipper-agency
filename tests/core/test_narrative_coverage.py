"""Tests for the narrative coverage contract validator (ADR 0030 / FIX-1).

Pure-domain logic: no LLM, no agent, no orchestrator coupling. The validator
asserts that ``narrative_structure`` word_range indices fully cover
``[0, word_count-1]`` (contiguously, in-bounds) and can perform an in-place
tail repair when the uncovered tail is below tolerance.
"""

from clipper_agency.core.narrative_coverage import (
    NarrativeCoverageResult,
    validate_narrative_coverage,
)

# ── job_18 frozen fixture (the regression that motivated FIX-1) ──

JOB18_BEATS = [
    {"beat_id": 1, "word_range": [0, 2]},
    {"beat_id": 2, "word_range": [3, 8]},
    {"beat_id": 3, "word_range": [9, 12]},
    {"beat_id": 4, "word_range": [13, 15]},
    {"beat_id": 5, "word_range": [16, 19]},
    {"beat_id": 6, "word_range": [20, 23]},
]


def test_job18_frozen_fixture_hard_fails_no_repair():
    res = validate_narrative_coverage(JOB18_BEATS, word_count=76)
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "uncovered_tail"
    assert res.details["tail_words"] == 52
    assert res.details["tolerance_words"] == 3  # floor(76 * 0.05)
    assert res.details["word_count"] == 76
    assert res.details["last_end"] == 23


# ── happy paths ──


def test_full_coverage_passes():
    res = validate_narrative_coverage(
        [{"word_range": [0, 9]}, {"word_range": [10, 19]}], word_count=20
    )
    assert res.ok is True
    assert res.reason == "covered"
    assert res.repaired_structure is None
    assert res.details["word_count"] == 20
    assert res.details["beat_count"] == 2


def test_single_beat_full_coverage_passes():
    res = validate_narrative_coverage([{"word_range": [0, 19]}], word_count=20)
    assert res.ok is True
    assert res.reason == "covered"
    assert res.details["beat_count"] == 1


def test_single_word_single_beat_passes():
    res = validate_narrative_coverage([{"word_range": [0, 0]}], word_count=1)
    assert res.ok is True
    assert res.reason == "covered"


# ── in-place tail repair ──


def test_eligible_tail_repaired_in_place():
    orig = [{"word_range": [0, 49]}, {"word_range": [50, 97]}]
    res = validate_narrative_coverage(orig, word_count=100)
    assert res.ok is True
    assert res.reason == "covered_after_tail_repair"
    assert res.repaired_structure is not None
    # ONLY the final beat end changed; first beat unchanged; no new beats.
    # The repaired final beat carries provenance markers so downstream
    # consumers can tell a gate-fabricated range from an LLM-emitted one.
    assert res.repaired_structure == [
        {"word_range": [0, 49]},
        {
            "word_range": [50, 99],
            "word_range_repaired": True,
            "word_range_original_end": 97,
        },
    ]
    assert res.details["tail_words"] == 2
    assert res.details["tolerance_words"] == 5  # floor(100 * 0.05)
    assert res.details["repaired_original_end"] == 97


def test_input_not_mutated_by_repair():
    orig = [{"word_range": [0, 49]}, {"word_range": [50, 97]}]
    validate_narrative_coverage(orig, word_count=100)
    assert orig[1]["word_range"] == [50, 97]
    assert orig[0]["word_range"] == [0, 49]


def test_tail_tolerance_zero_disables_repair():
    res = validate_narrative_coverage([{"word_range": [0, 97]}], word_count=100, tail_tolerance=0.0)
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "uncovered_tail"
    assert res.details["tail_words"] == 2
    assert res.details["tolerance_words"] == 0


# ── hard fails (no repair) ──


def test_out_of_bounds_index_hard_fails():
    res = validate_narrative_coverage(
        [{"word_range": [0, 9]}, {"word_range": [10, 25]}], word_count=20
    )
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "out_of_bounds"
    assert res.details["beat_index"] == 1
    assert res.details["word_range"] == [10, 25]
    assert res.details["word_count"] == 20


def test_non_contiguous_gap_hard_fails():
    res = validate_narrative_coverage(
        [{"word_range": [0, 4]}, {"word_range": [7, 19]}], word_count=20
    )
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "non_contiguous"
    assert res.details["beat_index_a"] == 0
    assert res.details["beat_index_b"] == 1
    assert res.details["end_a"] == 4
    assert res.details["start_b"] == 7


def test_overlap_treated_as_non_contiguous():
    res = validate_narrative_coverage(
        [{"word_range": [0, 8]}, {"word_range": [5, 19]}], word_count=20
    )
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "non_contiguous"


def test_head_gap_fails_even_when_tail_ok():
    res = validate_narrative_coverage([{"word_range": [3, 19]}], word_count=20)
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "non_contiguous"
    assert res.details["head_gap"] is True


def test_empty_narrative_hard_fails():
    res = validate_narrative_coverage([], word_count=76)
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "empty"
    assert res.details["word_count"] == 76
    assert res.details["beat_count"] == 0


def test_word_count_zero_hard_fails():
    res = validate_narrative_coverage([{"word_range": [0, 0]}], word_count=0)
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "empty"
    assert res.details["word_count"] == 0


def test_malformed_word_range_hard_fails():
    res = validate_narrative_coverage([{"word_range": [0]}, {"word_range": [1, 9]}], word_count=20)
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "out_of_bounds"
    assert res.details["beat_index"] == 0


def test_reversed_word_range_hard_fails():
    # start > end is caught by the bounds check.
    res = validate_narrative_coverage(
        [{"word_range": [5, 0]}, {"word_range": [6, 19]}], word_count=20
    )
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "out_of_bounds"


def test_bool_index_rejected():
    # Python bools are ints; the validator must reject them explicitly.
    res = validate_narrative_coverage([{"word_range": [True, 19]}], word_count=20)
    assert res.ok is False
    assert res.reason == "narrative_not_covered"
    assert res.repaired_structure is None
    assert res.details["violation_type"] == "out_of_bounds"


# ── result dataclass shape ──


def test_result_dataclass_defaults():
    r = NarrativeCoverageResult(ok=True, reason="covered")
    assert r.repaired_structure is None
    assert r.details == {}
