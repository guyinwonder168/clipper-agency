"""Narrative coverage contract validator (ADR 0030 / FIX-1).

Pure domain logic: no I/O, no logging, no orchestrator coupling. The
validator asserts that ``narrative_structure`` word_range indices fully
cover ``[0, word_count-1]`` (contiguously, in-bounds). When the uncovered
tail is below a tolerance fraction of the word count, it performs an
in-place repair by extending the final beat's end to the last index.

This is the source-of-truth gate twin to ``clipper_agency.core.beat_timeline``
(the consumer that produced the job_18 mega-beat). Keeping it in ``core/``
gives the orchestrator gate (``GateNarrativeCoverage``) a clean import
without an orchestrator->agents layering inversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NarrativeCoverageResult:
    """Outcome of validating narrative_structure word coverage.

    ``ok`` is True iff the structure is non-empty, fully in-bounds,
    contiguous, and covers [0, word_count-1] (after in-place tail repair
    when eligible).

    ``repaired_structure`` is a NEW list of beat dicts (caller inputs are
    never mutated) when in-place repair was applied, else None. Even on
    failure it stays None — failure never fabricates beats.
    """

    ok: bool
    reason: str
    repaired_structure: list[dict[str, Any]] | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _is_real_int(value: Any) -> bool:
    """True for ints but not bools (Python bools are ints)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _coverage_outcome(
    ordered: list[dict[str, Any]],
    word_count: int,
    last_idx: int,
    reordered: bool,
    tail_tolerance: float,
) -> NarrativeCoverageResult:
    """Decide the coverage outcome for an already bounds/contiguity/head-gap
    validated + sorted structure. Extracted from validate_narrative_coverage
    to keep that function under SonarCloud S3776 cognitive-complexity 15."""
    last_end = ordered[-1]["word_range"][1]
    tail_words = last_idx - last_end

    if tail_words == 0:
        if reordered:
            # Full coverage but beats were out of order — persist the sorted
            # order so the Composer (iterates narrative_structure as given)
            # and the canonical timeline agree (Codex P2).
            return NarrativeCoverageResult(
                True,
                "covered_after_reorder",
                [dict(b) for b in ordered],
                {
                    "word_count": word_count,
                    "beat_count": len(ordered),
                    "reordered": True,
                },
            )
        return NarrativeCoverageResult(
            True,
            "covered",
            None,
            {"word_count": word_count, "beat_count": len(ordered)},
        )

    # In-place repair is eligible only for a tail STRICTLY below the tolerance
    # fraction (default <5%). Compare the ACTUAL fraction tail_words /
    # word_count — not a floored integer count — so a 3-word tail on a 76-word
    # script (3.9% < 5%) is repaired while exactly-5% (e.g. 5/100) hard-fails.
    tail_fraction = tail_words / word_count
    if 0 < tail_fraction < tail_tolerance:
        repaired = [dict(b) for b in ordered]
        # Provenance: mark the gate-fabricated range so downstream consumers
        # can distinguish an LLM-emitted range from one the gate extended.
        repaired[-1]["word_range"] = [repaired[-1]["word_range"][0], last_idx]
        repaired[-1]["word_range_repaired"] = True
        repaired[-1]["word_range_original_end"] = last_end
        return NarrativeCoverageResult(
            True,
            "covered_after_tail_repair",
            repaired,
            {
                "word_count": word_count,
                "beat_count": len(ordered),
                "reordered": reordered,
                "tail_words": tail_words,
                "tail_tolerance": tail_tolerance,
                "tail_fraction": round(tail_fraction, 4),
                "repaired_final_beat_id": repaired[-1].get("beat_id"),
                "repaired_original_end": last_end,
            },
        )

    return NarrativeCoverageResult(
        False,
        "narrative_not_covered",
        None,
        {
            "violation_type": "uncovered_tail",
            "tail_words": tail_words,
            "tail_tolerance": tail_tolerance,
            "tail_fraction": round(tail_fraction, 4),
            "word_count": word_count,
            "last_end": last_end,
        },
    )


def validate_narrative_coverage(
    narrative_structure: list[dict[str, Any]],
    word_count: int,
    tail_tolerance: float = 0.05,
) -> NarrativeCoverageResult:
    """Validate that ``narrative_structure`` word_range union covers
    ``[0, word_count-1]`` contiguously and in-bounds.

    Returns a :class:`NarrativeCoverageResult`. Inputs are never mutated.
    See module docstring for the algorithm.
    """
    # 1. EMPTY / DEGENERATE
    if word_count <= 0 or not narrative_structure:
        return NarrativeCoverageResult(
            False,
            "narrative_not_covered",
            None,
            {
                "violation_type": "empty",
                "word_count": word_count,
                "beat_count": len(narrative_structure),
            },
        )

    last_idx = word_count - 1

    # 2. EXTRACT + BOUNDS
    for i, beat in enumerate(narrative_structure):
        wr = beat.get("word_range")
        if (
            not isinstance(wr, (list, tuple))
            or len(wr) != 2
            or not _is_real_int(wr[0])
            or not _is_real_int(wr[1])
            or wr[0] > wr[1]
            or wr[0] < 0
            or wr[1] > last_idx
        ):
            return NarrativeCoverageResult(
                False,
                "narrative_not_covered",
                None,
                {
                    "violation_type": "out_of_bounds",
                    "beat_index": i,
                    "word_range": list(wr) if isinstance(wr, (list, tuple)) else None,
                    "word_count": word_count,
                },
            )

    # 3. SORT + CONTIGUITY (and 4. head coverage)
    ordered = sorted(narrative_structure, key=lambda b: b["word_range"][0])
    # Detect out-of-order input. The canonical timeline sorts by word_range[0]
    # anyway, but the Composer iterates narrative_structure in its GIVEN order
    # (_align_assets_to_narrative_beats), so an out-of-order structure would
    # align visuals against the wrong narration. Persist the sorted order when
    # the input wasn't already chronological (Codex P2).
    reordered = [b["word_range"][0] for b in ordered] != [
        b["word_range"][0] for b in narrative_structure
    ]
    for i in range(len(ordered) - 1):
        end_a = ordered[i]["word_range"][1]
        start_b = ordered[i + 1]["word_range"][0]
        if end_a + 1 != start_b:
            return NarrativeCoverageResult(
                False,
                "narrative_not_covered",
                None,
                {
                    "violation_type": "non_contiguous",
                    "beat_index_a": i,
                    "beat_index_b": i + 1,
                    "end_a": end_a,
                    "start_b": start_b,
                },
            )

    if ordered[0]["word_range"][0] != 0:
        # Contiguous within itself but does not start at word 0 -> head gap.
        return NarrativeCoverageResult(
            False,
            "narrative_not_covered",
            None,
            {
                "violation_type": "non_contiguous",
                "head_gap": True,
                "start": ordered[0]["word_range"][0],
                "word_count": word_count,
            },
        )

    # 5. COVERAGE + TAIL REPAIR + REORDER DECISION (extracted into
    # _coverage_outcome to keep this function under SonarCloud S3776
    # cognitive-complexity 15).
    return _coverage_outcome(ordered, word_count, last_idx, reordered, tail_tolerance)
