"""Pure geometry functions for text collision detection."""
from __future__ import annotations

from clipper_agency.config.schema import TextCollisionIssue


def bbox_area(bbox: list[int]) -> float:
    """Calculate axis-aligned bounding box area. Zero/negative dims → 0."""
    width = max(0, bbox[2] - bbox[0])
    height = max(0, bbox[3] - bbox[1])
    return float(width * height)


def intersection_area(a: list[int], b: list[int]) -> float:
    """Intersection area of two axis-aligned bounding boxes."""
    x_overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    y_overlap = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return float(x_overlap * y_overlap)


def overlap_ratio(a: list[int], b: list[int]) -> float:
    """Overlap ratio: intersection / min(area_a, area_b)."""
    inter = intersection_area(a, b)
    min_area = min(bbox_area(a), bbox_area(b))
    if min_area == 0:
        return 0.0
    return inter / min_area


def detect_text_collisions(
    source_regions: list[dict],
    generated_regions: list[dict],
    thresholds: dict[str, float],
) -> list[TextCollisionIssue]:
    """Detect collisions between source text and generated overlays."""
    issues: list[TextCollisionIssue] = []
    for gen in generated_regions:
        layer = gen.get("layer", "subtitle")
        threshold_key = f"{layer}_overlap_max"
        threshold = thresholds.get(threshold_key, 0.20)
        for src in source_regions:
            ratio = overlap_ratio(src["bbox"], gen["bbox"])
            if ratio > threshold:
                issues.append(
                    TextCollisionIssue(
                        type=f"{layer.upper()}_SOURCE_TEXT_OVERLAP",
                        severity="warning",
                        detail=f"Overlap ratio {ratio:.2f} exceeds threshold {threshold}",
                        overlap_ratio=ratio,
                    )
                )
    return issues


def detect_source_text_density(
    source_regions: list[dict],
    frame_size: tuple[int, int],
    warning_area_ratio: float = 0.25,
    reject_area_ratio: float = 0.40,
) -> list[TextCollisionIssue]:
    """Check if source text covers too much of the frame."""
    frame_area = frame_size[0] * frame_size[1]
    if frame_area == 0:
        return []
    total_text_area = sum(bbox_area(r["bbox"]) for r in source_regions)
    ratio = total_text_area / frame_area
    if ratio >= reject_area_ratio:
        return [
            TextCollisionIssue(
                type="SOURCE_TEXT_DENSITY",
                severity="reject",
                detail=f"Source text covers {ratio:.1%} of frame (reject>{reject_area_ratio:.0%})",
                overlap_ratio=ratio,
            )
        ]
    if ratio >= warning_area_ratio:
        return [
            TextCollisionIssue(
                type="SOURCE_TEXT_DENSITY",
                severity="warning",
                detail=f"Source text covers {ratio:.1%} of frame (warning>{warning_area_ratio:.0%})",
                overlap_ratio=ratio,
            )
        ]
    return []
