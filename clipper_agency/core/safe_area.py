"""Pure geometry helpers for safe-area and face-text overlap detection.

All functions are side-effect-free with no external dependencies so that
parallel worker batches remain independent.
"""

from __future__ import annotations

from clipper_agency.config.schema import SafeAreaIssue

# ---------------------------------------------------------------------------
# Bounding-box helpers
# ---------------------------------------------------------------------------

Bbox = list[int]  # [x1, y1, x2, y2]


def _intersection_area(a: Bbox, b: Bbox) -> float:
    """Return the area of intersection between two [x1,y1,x2,y2] boxes."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return float((x2 - x1) * (y2 - y1))


def _area(box: Bbox) -> float:
    return float((box[2] - box[0]) * (box[3] - box[1]))


# ---------------------------------------------------------------------------
# Platform unsafe zones
# ---------------------------------------------------------------------------

def tiktok_unsafe_zones(frame_size: tuple[int, int]) -> list[dict]:
    """Return TikTok unsafe zones for *frame_size* (width, height).

    Zones (1080x1920 reference):
      - **top_interaction**: username / like / comment buttons (~top 8 %).
      - **bottom_caption**: platform caption / description area (~bottom 21 %).
    """
    w, h = frame_size
    top_h = int(h * 0.08)  # ~154 px
    bottom_h = int(h * 0.21)  # ~403 px
    return [
        {"bbox": [0, 0, w, top_h], "label": "top_interaction"},
        {"bbox": [0, h - bottom_h, w, h], "label": "bottom_caption"},
    ]


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

_PLATFORM_ZONE_FN = {
    "tiktok": tiktok_unsafe_zones,
}


def _check_zone_overlaps(
    rbox: Bbox,
    rarea: float,
    region: dict,
    unsafe_zones: list[dict],
) -> list[SafeAreaIssue]:
    """Return platform-unsafe-zone issues for a single region (max one)."""
    for zone in unsafe_zones:
        inter = _intersection_area(rbox, zone["bbox"])
        ratio = inter / rarea
        if ratio > 0.15:
            return [SafeAreaIssue(
                type="PLATFORM_UNSAFE_ZONE",
                severity="reject",
                detail=f"{region.get('layer', 'unknown')} overlaps {zone['label']}",
                overlap_ratio=round(ratio, 4),
            )]
    return []


def _check_face_overlaps(
    rbox: Bbox,
    region: dict,
    face_regions: list[dict],
    face_overlap_max: float,
) -> list[SafeAreaIssue]:
    """Return face-text overlap issues for a single region."""
    issues: list[SafeAreaIssue] = []
    for face in face_regions:
        fbox: Bbox = face["bbox"]
        inter = _intersection_area(rbox, fbox)
        if inter == 0:
            continue
        face_area = _area(fbox)
        if face_area == 0:
            continue
        ratio = inter / face_area
        if ratio > face_overlap_max:
            issues.append(SafeAreaIssue(
                type="FACE_TEXT_OVERLAP",
                severity="reject",
                detail=f"{region.get('layer', 'unknown')} overlaps face",
                overlap_ratio=round(ratio, 4),
            ))
    return issues


def detect_safe_area_issues(
    generated_regions: list[dict],
    face_regions: list[dict],
    frame_size: tuple[int, int],
    platform: str,
    face_overlap_max: float,
) -> list[SafeAreaIssue]:
    """Check *generated_regions* against platform unsafe zones and face regions.

    Returns a list of :class:`SafeAreaIssue` instances (empty when everything
    is within safe bounds).
    """
    zone_fn = _PLATFORM_ZONE_FN.get(platform)
    unsafe_zones: list[dict] = zone_fn(frame_size) if zone_fn else []

    issues: list[SafeAreaIssue] = []
    for region in generated_regions:
        rbox: Bbox = region["bbox"]
        rarea = _area(rbox)
        if rarea == 0:
            continue
        issues.extend(_check_zone_overlaps(rbox, rarea, region, unsafe_zones))
        issues.extend(_check_face_overlaps(rbox, region, face_regions, face_overlap_max))
    return issues
