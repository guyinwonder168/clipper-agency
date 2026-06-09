"""Pure visual-coverage evaluator — no FFmpeg, no I/O.

Consumes pre-detected segment tuples and threshold config, returns a
``VisualCoverageResult`` with pass/fail status, coverage ratio, and any
issues found.  All inputs are injectable for testability.
"""

from clipper_agency.config.schema import VisualCoverageIssue, VisualCoverageResult

# Hard-fail issue types
_HARD_FAIL_TYPES = frozenset({
    "DURATION_SHORT",
    "BLACK_FRAME",
    "EMPTY_FRAME",
    "MISSING_SCENE",
    "FINAL_VISUAL_GAP",
    "DECODE_FAILURE",
})

_MS_TO_SEC = 0.001
_DURATION_SHORT_TOLERANCE_SEC = 0.5


def _check_black_segments(
    black_segments: list[tuple[float, float]],
    max_ms: int,
) -> list[VisualCoverageIssue]:
    """Flag black frames that exceed the max duration threshold."""
    issues: list[VisualCoverageIssue] = []
    max_sec = max_ms * _MS_TO_SEC
    for start, end in black_segments:
        if (end - start) > max_sec:
            issues.append(VisualCoverageIssue(
                type="BLACK_FRAME",
                start_sec=start,
                end_sec=end,
                severity="hard_fail",
                detail=f"Black segment {((end - start) * 1000):.0f}ms > {max_ms}ms",
            ))
    return issues


def _check_empty_segments(
    empty_segments: list[tuple[float, float]],
    max_ms: int,
) -> list[VisualCoverageIssue]:
    """Flag empty frames that exceed the max duration threshold."""
    issues: list[VisualCoverageIssue] = []
    max_sec = max_ms * _MS_TO_SEC
    for start, end in empty_segments:
        if (end - start) > max_sec:
            issues.append(VisualCoverageIssue(
                type="EMPTY_FRAME",
                start_sec=start,
                end_sec=end,
                severity="hard_fail",
                detail=f"Empty segment {((end - start) * 1000):.0f}ms > {max_ms}ms",
            ))
    return issues


def _check_freeze_segments(
    freeze_segments: list[tuple[float, float]],
    warning_ms: int,
) -> list[VisualCoverageIssue]:
    """Flag freeze frames exceeding threshold as warnings."""
    issues: list[VisualCoverageIssue] = []
    warn_sec = warning_ms * _MS_TO_SEC
    for start, end in freeze_segments:
        if (end - start) > warn_sec:
            issues.append(VisualCoverageIssue(
                type="FREEZE_FRAME",
                start_sec=start,
                end_sec=end,
                severity="warning",
                detail=f"Freeze segment {((end - start) * 1000):.0f}ms > {warning_ms}ms",
            ))
    return issues


def _check_final_visual_gap(
    scene_segments: list[tuple[float, float]],
    voiceover_duration_sec: float,
    max_gap_ms: int,
) -> list[VisualCoverageIssue]:
    """Flag when last scene ends well before voiceover ends."""
    if not scene_segments:
        return []
    visual_end = max(end for _, end in scene_segments)
    gap_sec = voiceover_duration_sec - visual_end
    max_gap_sec = max_gap_ms * _MS_TO_SEC
    if gap_sec > max_gap_sec:
        return [VisualCoverageIssue(
            type="FINAL_VISUAL_GAP",
            start_sec=visual_end,
            end_sec=voiceover_duration_sec,
            severity="hard_fail",
            detail=f"Visual ends at {visual_end:.2f}s, voiceover at {voiceover_duration_sec:.2f}s — gap {gap_sec * 1000:.0f}ms > {max_gap_ms}ms",
        )]
    return []


def _check_duration_short(
    output_duration_sec: float,
    voiceover_duration_sec: float,
) -> list[VisualCoverageIssue]:
    """Flag when output is significantly shorter than voiceover."""
    diff = voiceover_duration_sec - output_duration_sec
    if diff > _DURATION_SHORT_TOLERANCE_SEC:
        return [VisualCoverageIssue(
            type="DURATION_SHORT",
            start_sec=output_duration_sec,
            end_sec=voiceover_duration_sec,
            severity="hard_fail",
            detail=f"Output {output_duration_sec:.2f}s is {diff:.2f}s shorter than voiceover {voiceover_duration_sec:.2f}s",
        )]
    return []


def _compute_coverage_ratio(
    scene_segments: list[tuple[float, float]],
    voiceover_duration_sec: float,
) -> float:
    """Coverage ratio = last visual end / voiceover duration, clamped to [0, 1]."""
    if not scene_segments or voiceover_duration_sec <= 0:
        return 0.0
    visual_end = max(end for _, end in scene_segments)
    ratio = visual_end / voiceover_duration_sec
    return min(ratio, 1.0)


def evaluate_visual_coverage(
    output_duration_sec: float,
    voiceover_duration_sec: float,
    black_segments: list[tuple[float, float]],
    freeze_segments: list[tuple[float, float]],
    empty_segments: list[tuple[float, float]],
    scene_segments: list[tuple[float, float]],
    thresholds: dict[str, int],
) -> VisualCoverageResult:
    """Evaluate visual coverage of rendered output against quality thresholds.

    Pure function — all detector inputs passed as args, no I/O.
    Returns ``VisualCoverageResult`` with pass/fail and any issues.
    """
    issues: list[VisualCoverageIssue] = []

    issues.extend(_check_black_segments(
        black_segments, thresholds.get("black_frame_max_ms", 200),
    ))
    issues.extend(_check_empty_segments(
        empty_segments, thresholds.get("empty_frame_max_ms", 300),
    ))
    issues.extend(_check_freeze_segments(
        freeze_segments, thresholds.get("freeze_warning_ms", 1500),
    ))
    issues.extend(_check_final_visual_gap(
        scene_segments, voiceover_duration_sec,
        thresholds.get("final_visual_gap_max_ms", 200),
    ))
    issues.extend(_check_duration_short(
        output_duration_sec, voiceover_duration_sec,
    ))

    has_hard_fail = any(i.severity == "hard_fail" for i in issues)
    coverage_ratio = _compute_coverage_ratio(scene_segments, voiceover_duration_sec)

    return VisualCoverageResult(
        status="fail" if has_hard_fail else "pass",
        output_duration_sec=output_duration_sec,
        voiceover_duration_sec=voiceover_duration_sec,
        coverage_ratio=coverage_ratio,
        issues=issues,
    )
