"""Pure normalization functions for OCR-detected text regions.

No I/O, no OCR library dependencies. All functions are pure."""

from clipper_agency.config.schema import DetectedTextRegion


def normalize_text_region(
    text: str,
    confidence: float,
    bbox: list[int],
    frame_size: tuple[int, int],
    timestamp_sec: float,
) -> DetectedTextRegion:
    """Normalize raw OCR detection into a DetectedTextRegion with computed zone and area_ratio.

    Args:
        text: Detected text string (may be empty for low-confidence regions).
        confidence: OCR confidence score [0, 1].
        bbox: Bounding box [x1, y1, x2, y2] in pixel coordinates.
        frame_size: (width, height) of the frame.
        timestamp_sec: Timestamp in seconds within the video.

    Returns:
        DetectedTextRegion with computed area_ratio and zone.
    """
    width, height = frame_size
    x1, y1, x2, y2 = bbox

    bbox_area = (x2 - x1) * (y2 - y1)
    frame_area = width * height
    area_ratio = bbox_area / frame_area if frame_area > 0 else 0.0

    vertical_center = (y1 + y2) / 2
    if vertical_center < height / 3:
        zone = "top"
    elif vertical_center > 2 * height / 3:
        zone = "bottom"
    else:
        zone = "middle"

    return DetectedTextRegion(
        text=text,
        confidence=confidence,
        bbox=bbox,
        frame_size=frame_size,
        timestamp_sec=timestamp_sec,
        area_ratio=area_ratio,
        zone=zone,
    )


def filter_text_regions(
    regions: list[DetectedTextRegion],
    min_confidence: float = 0.6,
    large_area_ratio: float = 0.20,
) -> list[DetectedTextRegion]:
    """Filter text regions by confidence and area.

    Keeps regions that either:
    - Have confidence >= min_confidence, OR
    - Have area_ratio >= large_area_ratio (possible embedded text/watermarks)

    Args:
        regions: List of normalized text regions.
        min_confidence: Minimum confidence threshold.
        large_area_ratio: Area ratio threshold for "possible text" override.

    Returns:
        Filtered list of text regions.
    """
    return [
        r
        for r in regions
        if r.confidence >= min_confidence or r.area_ratio >= large_area_ratio
    ]
