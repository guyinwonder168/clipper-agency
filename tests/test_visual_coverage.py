"""Unit tests for visual coverage evaluator — pure logic, no FFmpeg."""

from clipper_agency.config.schema import VisualCoverageIssue, VisualCoverageResult
from clipper_agency.core.visual_coverage import evaluate_visual_coverage


def _default_thresholds(**overrides):
    """Build threshold dict with sensible defaults, allowing overrides."""
    defaults = {
        "black_frame_max_ms": 200,
        "empty_frame_max_ms": 300,
        "freeze_warning_ms": 1500,
        "final_visual_gap_max_ms": 200,
    }
    defaults.update(overrides)
    return defaults


class TestBlackFrameDetection:
    """BLACK_FRAME issues: hard-fail when any black segment exceeds threshold."""

    def test_fails_when_black_segment_exceeds_threshold(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.2,
            voiceover_duration_sec=21.0,
            black_segments=[(17.83, 18.10)],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 21.2)],
            thresholds=_default_thresholds(),
        )
        assert result.status == "fail"
        assert result.issues[0].type == "BLACK_FRAME"
        assert result.issues[0].severity == "hard_fail"
        assert result.issues[0].start_sec == 17.83
        assert result.issues[0].end_sec == 18.10

    def test_passes_when_black_segment_within_threshold(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[(5.0, 5.15)],  # 150ms < 200ms threshold
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        assert result.status == "pass"
        black_issues = [i for i in result.issues if i.type == "BLACK_FRAME"]
        assert len(black_issues) == 0

    def test_no_black_segments_passes(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        assert result.status == "pass"


class TestFinalVisualGap:
    """FINAL_VISUAL_GAP: hard-fail when last scene ends well before audio ends."""

    def test_fails_when_final_visual_ends_before_audio(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 20.6)],  # 400ms gap > 200ms threshold
            thresholds=_default_thresholds(),
        )
        assert result.status == "fail"
        assert result.issues[0].type == "FINAL_VISUAL_GAP"
        assert result.issues[0].severity == "hard_fail"

    def test_passes_when_final_visual_close_to_audio_end(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 20.9)],  # 100ms gap < 200ms threshold
            thresholds=_default_thresholds(),
        )
        gap_issues = [i for i in result.issues if i.type == "FINAL_VISUAL_GAP"]
        assert len(gap_issues) == 0

    def test_gap_calculated_against_voiceover_not_output(self):
        """Gap = voiceover_end - last_visual_end, not output_duration."""
        result = evaluate_visual_coverage(
            output_duration_sec=22.0,  # output longer than voiceover
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 20.6)],  # 400ms gap from voiceover end
            thresholds=_default_thresholds(),
        )
        gap_issues = [i for i in result.issues if i.type == "FINAL_VISUAL_GAP"]
        assert len(gap_issues) == 1
        assert gap_issues[0].severity == "hard_fail"


class TestEmptyFrameDetection:
    """EMPTY_FRAME: hard-fail when empty segments exceed threshold."""

    def test_fails_on_empty_segment_exceeding_threshold(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[(10.0, 10.5)],  # 500ms > 300ms threshold
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        assert result.status == "fail"
        empty_issues = [i for i in result.issues if i.type == "EMPTY_FRAME"]
        assert len(empty_issues) == 1
        assert empty_issues[0].severity == "hard_fail"
        assert empty_issues[0].start_sec == 10.0
        assert empty_issues[0].end_sec == 10.5

    def test_passes_on_empty_segment_within_threshold(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[(10.0, 10.2)],  # 200ms < 300ms threshold
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        empty_issues = [i for i in result.issues if i.type == "EMPTY_FRAME"]
        assert len(empty_issues) == 0


class TestFreezeDetection:
    """FREEZE_FRAME: warning-level issue when freeze exceeds threshold."""

    def test_warning_on_freeze_exceeding_threshold(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[(8.0, 10.0)],  # 2000ms > 1500ms threshold
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        freeze_issues = [i for i in result.issues if i.type == "FREEZE_FRAME"]
        assert len(freeze_issues) == 1
        assert freeze_issues[0].severity == "warning"
        # Warnings alone should NOT cause a hard fail
        assert result.status == "pass"

    def test_no_warning_when_freeze_within_threshold(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[(8.0, 9.3)],  # 1300ms < 1500ms threshold
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        freeze_issues = [i for i in result.issues if i.type == "FREEZE_FRAME"]
        assert len(freeze_issues) == 0


class TestDurationShort:
    """DURATION_SHORT: hard-fail when output is significantly shorter than voiceover."""

    def test_fails_when_output_much_shorter_than_voiceover(self):
        result = evaluate_visual_coverage(
            output_duration_sec=20.0,  # 1.0s shorter than voiceover
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 20.0)],
            thresholds=_default_thresholds(),
        )
        dur_issues = [i for i in result.issues if i.type == "DURATION_SHORT"]
        assert len(dur_issues) == 1
        assert dur_issues[0].severity == "hard_fail"

    def test_passes_when_output_slightly_shorter(self):
        result = evaluate_visual_coverage(
            output_duration_sec=20.6,  # 0.4s shorter, within tolerance
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 20.6)],
            thresholds=_default_thresholds(),
        )
        dur_issues = [i for i in result.issues if i.type == "DURATION_SHORT"]
        assert len(dur_issues) == 0

    def test_passes_when_output_equals_voiceover(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        dur_issues = [i for i in result.issues if i.type == "DURATION_SHORT"]
        assert len(dur_issues) == 0


class TestCoverageRatio:
    """Coverage ratio = visual_end / voiceover_duration (clamped to [0, 1])."""

    def test_full_coverage_ratio(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        assert result.coverage_ratio == 1.0

    def test_partial_coverage_ratio(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 18.9)],
            thresholds=_default_thresholds(),
        )
        expected = 18.9 / 21.0
        assert abs(result.coverage_ratio - expected) < 0.001

    def test_coverage_ratio_clamped_at_one(self):
        """If visual extends past voiceover, ratio is clamped to 1.0."""
        result = evaluate_visual_coverage(
            output_duration_sec=22.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 22.0)],
            thresholds=_default_thresholds(),
        )
        assert result.coverage_ratio == 1.0


class TestPassCase:
    """Full pass: all segments good, correct coverage_ratio, no issues."""

    def test_clean_pass_no_issues(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        assert result.status == "pass"
        assert result.issues == []
        assert result.coverage_ratio == 1.0
        assert result.output_duration_sec == 21.0
        assert result.voiceover_duration_sec == 21.0

    def test_return_type_is_visual_coverage_result(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[],
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        assert isinstance(result, VisualCoverageResult)


class TestMultipleIssues:
    """Multiple defects accumulate; any hard_fail => status=fail."""

    def test_multiple_hard_fail_issues(self):
        result = evaluate_visual_coverage(
            output_duration_sec=20.0,  # DURATION_SHORT (1.0s gap)
            voiceover_duration_sec=21.0,
            black_segments=[(5.0, 5.5)],  # BLACK_FRAME (500ms > 200ms)
            freeze_segments=[],
            empty_segments=[(10.0, 10.5)],  # EMPTY_FRAME (500ms > 300ms)
            scene_segments=[(0.0, 19.5)],  # FINAL_VISUAL_GAP
            thresholds=_default_thresholds(),
        )
        assert result.status == "fail"
        hard_fails = [i for i in result.issues if i.severity == "hard_fail"]
        assert len(hard_fails) >= 3

    def test_warning_only_still_passes(self):
        result = evaluate_visual_coverage(
            output_duration_sec=21.0,
            voiceover_duration_sec=21.0,
            black_segments=[],
            freeze_segments=[(8.0, 10.5)],  # FREEZE warning only
            empty_segments=[],
            scene_segments=[(0.0, 21.0)],
            thresholds=_default_thresholds(),
        )
        assert result.status == "pass"
        warnings = [i for i in result.issues if i.severity == "warning"]
        assert len(warnings) == 1
