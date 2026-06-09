"""Tests for empty and uniform frame quality detection."""

from clipper_agency.core.frame_quality import (
    compute_frame_variance,
    detect_empty_segments,
    is_empty_or_uniform_frame,
)


class TestComputeFrameVariance:
    """Tests for compute_frame_variance()."""

    def test_black_frame_has_zero_variance(self):
        """Pure black pixels have no brightness variation."""
        image = [[[0, 0, 0] for _ in range(4)] for _ in range(4)]

        variance = compute_frame_variance(image)

        assert variance == 0.0

    def test_non_uniform_photo_like_frame_has_variance(self):
        """Mixed pixel values produce measurable variation."""
        image = [
            [[0, 0, 0], [50, 50, 50]],
            [[150, 150, 150], [255, 255, 255]],
        ]

        variance = compute_frame_variance(image)

        assert variance > 0.0


class TestIsEmptyOrUniformFrame:
    """Tests for is_empty_or_uniform_frame()."""

    def test_detects_pure_black_frame(self):
        """Pure black frame is treated as empty."""
        image = [[[0, 0, 0] for _ in range(8)] for _ in range(8)]

        assert is_empty_or_uniform_frame(image, threshold=1.0) is True

    def test_detects_solid_color_frame(self):
        """Any solid color frame is treated as uniform."""
        image = [[[128, 128, 128] for _ in range(8)] for _ in range(8)]

        assert is_empty_or_uniform_frame(image, threshold=1.0) is True

    def test_does_not_detect_normal_photo_like_frame(self):
        """A frame with varied pixel values is not empty or uniform."""
        image = [
            [[10, 20, 30], [80, 90, 100], [140, 150, 160]],
            [[40, 50, 60], [110, 120, 130], [170, 180, 190]],
            [[70, 80, 90], [130, 140, 150], [220, 230, 240]],
        ]

        assert is_empty_or_uniform_frame(image, threshold=1.0) is False


class TestDetectEmptySegments:
    """Tests for detect_empty_segments()."""

    def test_consecutive_empty_frames_merge_into_intervals(self):
        """Nearby empty frames merge while non-empty frames split intervals."""
        black = [[[0, 0, 0] for _ in range(4)] for _ in range(4)]
        solid = [[[200, 200, 200] for _ in range(4)] for _ in range(4)]
        varied = [
            [[0, 0, 0], [60, 60, 60]],
            [[180, 180, 180], [255, 255, 255]],
        ]
        sampled_frames = [
            (0.0, black),
            (0.5, solid),
            (1.0, varied),
            (2.0, black),
            (2.4, solid),
        ]

        intervals = detect_empty_segments(sampled_frames, max_gap_sec=0.6)

        assert intervals == [(0.0, 0.5), (2.0, 2.4)]

    def test_gap_larger_than_max_gap_splits_empty_intervals(self):
        """Empty frames separated by too much time become separate intervals."""
        black = [[[0, 0, 0] for _ in range(4)] for _ in range(4)]
        sampled_frames = [(0.0, black), (1.0, black)]

        intervals = detect_empty_segments(sampled_frames, max_gap_sec=0.5)

        assert intervals == [(0.0, 0.0), (1.0, 1.0)]
