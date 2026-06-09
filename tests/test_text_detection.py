"""Unit tests for text detection normalization — TDD RED phase."""

from clipper_agency.config.schema import DetectedTextRegion
from clipper_agency.core.text_detection import filter_text_regions, normalize_text_region


class TestNormalizeTextRegion:
    """Tests for normalize_text_region pure function."""

    def test_computes_area_ratio_and_zone_middle(self):
        region = normalize_text_region(
            text="INI ALASAN RUBEN",
            confidence=0.96,
            bbox=[80, 980, 990, 1220],
            frame_size=(1080, 1920),
            timestamp_sec=4.5,
        )

        assert region.text == "INI ALASAN RUBEN"
        assert region.zone == "middle"
        assert region.area_ratio > 0

    def test_computes_area_ratio_correctly(self):
        """area_ratio = bbox_area / (width * height)."""
        region = normalize_text_region(
            text="test",
            confidence=0.9,
            bbox=[0, 0, 540, 960],
            frame_size=(1080, 1920),
            timestamp_sec=1.0,
        )

        expected_area_ratio = (540 * 960) / (1080 * 1920)
        assert abs(region.area_ratio - expected_area_ratio) < 1e-6

    def test_zone_top(self):
        """Vertical center in top third → zone 'top'."""
        region = normalize_text_region(
            text="TOP TEXT",
            confidence=0.9,
            bbox=[0, 0, 1080, 400],
            frame_size=(1080, 1920),
            timestamp_sec=0.0,
        )

        # vertical_center = (0 + 400) / 2 = 200, height/3 = 640 → top
        assert region.zone == "top"

    def test_zone_bottom(self):
        """Vertical center in bottom third → zone 'bottom'."""
        region = normalize_text_region(
            text="BOTTOM TEXT",
            confidence=0.9,
            bbox=[0, 1500, 1080, 1800],
            frame_size=(1080, 1920),
            timestamp_sec=2.0,
        )

        # vertical_center = (1500 + 1800) / 2 = 1650, 2*height/3 = 1280 → bottom
        assert region.zone == "bottom"

    def test_zone_middle_boundary(self):
        """Vertical center between top/bottom thirds → zone 'middle'."""
        region = normalize_text_region(
            text="MID TEXT",
            confidence=0.8,
            bbox=[0, 700, 1080, 1000],
            frame_size=(1080, 1920),
            timestamp_sec=3.0,
        )

        # vertical_center = 850, height/3=640, 2*height/3=1280 → middle
        assert region.zone == "middle"

    def test_preserves_all_fields(self):
        """All input fields pass through unchanged."""
        region = normalize_text_region(
            text="hello",
            confidence=0.75,
            bbox=[10, 20, 100, 200],
            frame_size=(1080, 1920),
            timestamp_sec=5.5,
        )

        assert region.text == "hello"
        assert region.confidence == 0.75
        assert region.bbox == [10, 20, 100, 200]
        assert region.frame_size == (1080, 1920)
        assert region.timestamp_sec == 5.5

    def test_returns_detected_text_region_type(self):
        region = normalize_text_region(
            text="x",
            confidence=0.5,
            bbox=[0, 0, 10, 10],
            frame_size=(1080, 1920),
            timestamp_sec=0.0,
        )

        assert isinstance(region, DetectedTextRegion)


class TestFilterTextRegions:
    """Tests for filter_text_regions pure function."""

    def test_keeps_large_low_confidence_possible_text(self):
        """Large-area low-confidence regions survive (watermarks/embedded text)."""
        region = normalize_text_region(
            text="",
            confidence=0.35,
            bbox=[0, 500, 1080, 1000],
            frame_size=(1080, 1920),
            timestamp_sec=1.0,
        )

        assert filter_text_regions([region], min_confidence=0.6, large_area_ratio=0.20) == [region]

    def test_removes_small_low_confidence(self):
        """Small low-confidence regions are filtered out."""
        region = normalize_text_region(
            text="noise",
            confidence=0.2,
            bbox=[100, 100, 120, 120],
            frame_size=(1080, 1920),
            timestamp_sec=1.0,
        )

        assert filter_text_regions([region], min_confidence=0.6, large_area_ratio=0.20) == []

    def test_keeps_high_confidence(self):
        """Regions with confidence >= min_confidence always kept."""
        region = normalize_text_region(
            text="CONFIDENT",
            confidence=0.85,
            bbox=[100, 100, 200, 200],
            frame_size=(1080, 1920),
            timestamp_sec=1.0,
        )

        assert filter_text_regions([region], min_confidence=0.6, large_area_ratio=0.20) == [region]

    def test_keeps_exact_min_confidence(self):
        """Edge case: confidence == min_confidence is kept."""
        region = normalize_text_region(
            text="EDGE",
            confidence=0.6,
            bbox=[100, 100, 200, 200],
            frame_size=(1080, 1920),
            timestamp_sec=1.0,
        )

        assert filter_text_regions([region], min_confidence=0.6, large_area_ratio=0.20) == [region]

    def test_empty_list_returns_empty(self):
        assert filter_text_regions([], min_confidence=0.6, large_area_ratio=0.20) == []

    def test_mixed_regions_filters_correctly(self):
        """Mix of high-conf, large-area, and noise — only first two survive."""
        high_conf = normalize_text_region(
            text="GOOD",
            confidence=0.9,
            bbox=[0, 0, 100, 100],
            frame_size=(1080, 1920),
            timestamp_sec=0.0,
        )
        large_area = normalize_text_region(
            text="",
            confidence=0.1,
            bbox=[0, 0, 1080, 960],
            frame_size=(1080, 1920),
            timestamp_sec=1.0,
        )
        noise = normalize_text_region(
            text="x",
            confidence=0.1,
            bbox=[0, 0, 50, 50],
            frame_size=(1080, 1920),
            timestamp_sec=2.0,
        )

        result = filter_text_regions([high_conf, large_area, noise], min_confidence=0.6, large_area_ratio=0.20)
        assert result == [high_conf, large_area]

    def test_default_parameters(self):
        """filter_text_regions works with default params."""
        region = normalize_text_region(
            text="OK",
            confidence=0.7,
            bbox=[0, 0, 100, 100],
            frame_size=(1080, 1920),
            timestamp_sec=0.0,
        )

        assert filter_text_regions([region]) == [region]
