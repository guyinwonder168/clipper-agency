"""Tests for text collision geometry detection."""
import pytest
from clipper_agency.core.text_collision import (
    bbox_area,
    detect_source_text_density,
    detect_text_collisions,
    intersection_area,
    overlap_ratio,
)


class TestBboxArea:
    def test_normal_bbox(self):
        assert bbox_area([100, 200, 400, 500]) == 90000  # 300 * 300

    def test_zero_area(self):
        assert bbox_area([100, 200, 100, 200]) == 0

    def test_negative_dimensions_returns_zero(self):
        assert bbox_area([400, 500, 100, 200]) == 0


class TestIntersectionArea:
    def test_overlapping_bboxes(self):
        a = [100, 100, 400, 400]
        b = [200, 200, 500, 500]
        # overlap: [200,200]-[400,400] = 200*200 = 40000
        assert intersection_area(a, b) == 40000

    def test_non_overlapping_bboxes(self):
        a = [0, 0, 100, 100]
        b = [200, 200, 300, 300]
        assert intersection_area(a, b) == 0

    def test_contained_bbox(self):
        outer = [0, 0, 500, 500]
        inner = [100, 100, 200, 200]
        assert intersection_area(outer, inner) == 10000  # 100*100

    def test_touching_edges(self):
        a = [0, 0, 100, 100]
        b = [100, 100, 200, 200]
        assert intersection_area(a, b) == 0


class TestOverlapRatio:
    def test_partial_overlap(self):
        a = [0, 0, 200, 200]  # area 40000
        b = [100, 100, 300, 300]  # area 40000
        # intersection: [100,100]-[200,200] = 100*100 = 10000
        # min(40000, 40000) = 40000
        assert overlap_ratio(a, b) == pytest.approx(0.25)

    def test_no_overlap(self):
        a = [0, 0, 100, 100]
        b = [200, 200, 300, 300]
        assert overlap_ratio(a, b) == 0.0

    def test_zero_area_bbox(self):
        a = [50, 50, 50, 50]  # zero area
        b = [0, 0, 100, 100]
        assert overlap_ratio(a, b) == 0.0


class TestDetectTextCollisions:
    def test_overlap_ratio_detects_caption_collision_with_source_text(self):
        issues = detect_text_collisions(
            source_regions=[{"bbox": [100, 900, 900, 1100], "text": "SOURCE"}],
            generated_regions=[{"bbox": [120, 950, 880, 1150], "layer": "subtitle"}],
            thresholds={"subtitle_overlap_max": 0.20, "headline_overlap_max": 0.15},
        )
        assert issues
        assert issues[0].type == "SUBTITLE_SOURCE_TEXT_OVERLAP"

    def test_no_collision_returns_empty(self):
        issues = detect_text_collisions(
            source_regions=[{"bbox": [0, 0, 100, 100], "text": "FAR"}],
            generated_regions=[{"bbox": [500, 500, 600, 600], "layer": "subtitle"}],
            thresholds={"subtitle_overlap_max": 0.20, "headline_overlap_max": 0.15},
        )
        assert issues == []

    def test_headline_overlap_uses_headline_threshold(self):
        issues = detect_text_collisions(
            source_regions=[{"bbox": [100, 100, 500, 500], "text": "SRC"}],
            generated_regions=[{"bbox": [110, 110, 490, 490], "layer": "headline"}],
            thresholds={"subtitle_overlap_max": 0.20, "headline_overlap_max": 0.15},
        )
        assert issues
        assert issues[0].type == "HEADLINE_SOURCE_TEXT_OVERLAP"


class TestDetectSourceTextDensity:
    def test_source_text_density_warns_when_text_area_is_large(self):
        # source region covers 1080*600 = 648000, frame is 1080*1920 = 2073600
        # ratio = 648000/2073600 ≈ 0.3125 > 0.25 warning, > 0.40 reject? No, 0.3125 < 0.40
        # So severity should be "warning"
        issues = detect_source_text_density(
            source_regions=[{"bbox": [0, 0, 1080, 600], "text": "BIG"}],
            frame_size=(1080, 1920),
            warning_area_ratio=0.25,
            reject_area_ratio=0.40,
        )
        assert issues
        assert issues[0].type == "SOURCE_TEXT_DENSITY"
        assert issues[0].severity == "warning"

    def test_below_warning_threshold_returns_empty(self):
        # area = 100*100 = 10000, frame = 1080*1920 = 2073600, ratio ≈ 0.005
        issues = detect_source_text_density(
            source_regions=[{"bbox": [0, 0, 100, 100], "text": "SMALL"}],
            frame_size=(1080, 1920),
            warning_area_ratio=0.25,
            reject_area_ratio=0.40,
        )
        assert issues == []

    def test_density_at_reject_level(self):
        # area = 1080*1000 = 1080000, frame = 1080*1920 = 2073600, ratio ≈ 0.521 > 0.40
        issues = detect_source_text_density(
            source_regions=[{"bbox": [0, 0, 1080, 1000], "text": "HUGE"}],
            frame_size=(1080, 1920),
            warning_area_ratio=0.25,
            reject_area_ratio=0.40,
        )
        assert issues
        assert issues[0].type == "SOURCE_TEXT_DENSITY"
        assert issues[0].severity == "reject"
