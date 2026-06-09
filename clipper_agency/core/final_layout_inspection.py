"""Final layout inspection pipeline — wires OCR, face detection, generated text,
text collision, source text density, and safe-area checks into a single pass.

This is an INTEGRATION module that composes the adapters from Workers E-H and
the pure geometry functions from text_collision/safe_area.
"""

from __future__ import annotations

import json
from typing import Any

from clipper_agency.core.generated_text_manifest import regions_at_timestamp
from clipper_agency.core.safe_area import detect_safe_area_issues
from clipper_agency.core.text_collision import detect_source_text_density, detect_text_collisions

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

_DEFAULT_COLLISION_THRESHOLDS: dict[str, float] = {
    "subtitle_overlap_max": 0.20,
    "headline_overlap_max": 0.30,
    "watermark_overlap_max": 0.20,
    "cta_overlap_max": 0.30,
}

_DEFAULT_SAFE_AREA_CONFIG: dict[str, Any] = {
    "platform": "tiktok",
    "face_overlap_max": 0.15,
}

_DEFAULT_DENSITY_WARNING: float = 0.25
_DEFAULT_DENSITY_REJECT: float = 0.40

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_final_layout_inspection(
    frame_manifest: dict,
    generated_text_regions: list[dict],
    frame_size: tuple[int, int],
    ocr_adapter: Any = None,
    face_detector: Any = None,
    safe_area_config: dict | None = None,
) -> dict:
    """Run full final layout inspection on rendered frames.

    Iterates over every unique frame in *frame_manifest*, running OCR and
    face detection (when adapters are provided), then cross-referencing
    against *generated_text_regions* for text collision, source text
    density, and safe-area violations.

    Args:
        frame_manifest: Dict-ified ``FrameExtractionManifest`` with a
            ``frames`` key containing ``ExtractedFrame``-shaped dicts.
        generated_text_regions: Pre-built text region list from
            :func:`~clipper_agency.core.generated_text_manifest.build_generated_text_regions`.
        frame_size: ``(width, height)`` of the output video.
        ocr_adapter: Object with an ``inspect(image_path, timestamp_sec)``
            method returning ``OCRInspectionResult``.  Pass ``None`` to
            skip OCR entirely.
        face_detector: Object with a ``detect(image_path, timestamp_sec)``
            method returning ``FaceInspectionResult``.  Pass ``None`` to
            skip face detection.
        safe_area_config: Optional dict with ``platform`` (str) and
            ``face_overlap_max`` (float).  Falls back to TikTok defaults
            when omitted.

    Returns:
        dict with keys:

        - **text_collision** — list of ``TextCollisionIssue``-shaped dicts.
        - **safe_area** — list of ``SafeAreaIssue``-shaped dicts.
        - **ocr_summary** — aggregated OCR stats.
        - **face_summary** — aggregated face detection stats.
    """
    safe_cfg = dict(_DEFAULT_SAFE_AREA_CONFIG)
    if safe_area_config:
        safe_cfg.update(safe_area_config)

    frames: list[dict] = frame_manifest.get("frames", [])

    # Deduplicate by file path to avoid re-inspecting the same frame
    seen_paths: set[str] = set()
    unique_frames: list[dict] = []
    for f in frames:
        path = f.get("path", "")
        if path and path not in seen_paths:
            seen_paths.add(path)
            unique_frames.append(f)

    # ------------------------------------------------------------------
    # Per-frame inspection
    # ------------------------------------------------------------------
    all_collisions: list[dict] = []
    all_safe_area_issues: list[dict] = []
    ocr_frame_results: list[dict] = []
    face_frame_results: list[dict] = []

    for frame in unique_frames:
        timestamp_sec: float = frame["timestamp_sec"]
        frame_path: str = frame["path"]

        # --- OCR ---
        ocr_regions: list = []
        if ocr_adapter is not None:
            ocr_result = ocr_adapter.inspect(frame_path, timestamp_sec)
            ocr_regions = getattr(ocr_result, "regions", []) or []
            ocr_frame_results.append({
                "timestamp_sec": timestamp_sec,
                "path": frame_path,
                "region_count": len(ocr_regions),
            })

        # --- Face detection ---
        face_regions: list = []
        if face_detector is not None:
            face_result = face_detector.detect(frame_path, timestamp_sec)
            face_regions = getattr(face_result, "faces", []) or []
            face_frame_results.append({
                "timestamp_sec": timestamp_sec,
                "path": frame_path,
                "face_count": len(face_regions),
                "primary_faces": sum(1 for fg in face_regions if getattr(fg, "is_primary", False)),
            })

        # --- Active generated text regions at this timestamp ---
        active_generated = regions_at_timestamp(generated_text_regions, timestamp_sec)

        # --- Convert model objects to plain dicts for geometry functions ---
        source_regions: list[dict] = _ocr_regions_to_dicts(ocr_regions)
        face_dicts: list[dict] = _face_regions_to_dicts(face_regions)

        # --- Text collision (source text vs generated overlays) ---
        if source_regions and active_generated:
            issues = detect_text_collisions(
                source_regions, active_generated, _DEFAULT_COLLISION_THRESHOLDS,
            )
            all_collisions.extend(_issues_to_dicts(issues))

        # --- Source text density ---
        if source_regions:
            density_issues = detect_source_text_density(
                source_regions,
                frame_size,
                warning_area_ratio=_DEFAULT_DENSITY_WARNING,
                reject_area_ratio=_DEFAULT_DENSITY_REJECT,
            )
            all_collisions.extend(_issues_to_dicts(density_issues))

        # --- Safe area checks ---
        if active_generated or face_dicts:
            safe_issues = detect_safe_area_issues(
                generated_regions=active_generated,
                face_regions=face_dicts,
                frame_size=frame_size,
                platform=safe_cfg["platform"],
                face_overlap_max=safe_cfg["face_overlap_max"],
            )
            all_safe_area_issues.extend(_issues_to_dicts(safe_issues))

    # ------------------------------------------------------------------
    # Build aggregated summaries
    # ------------------------------------------------------------------
    ocr_summary = _build_ocr_summary(ocr_frame_results, [])
    # Rebuild face total across all frames
    face_summary = _build_face_summary(face_frame_results)

    return {
        "text_collision": all_collisions,
        "safe_area": all_safe_area_issues,
        "ocr_summary": ocr_summary,
        "face_summary": face_summary,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ocr_regions_to_dicts(regions: list) -> list[dict]:
    """Convert DetectedTextRegion model objects to plain dicts with ``bbox``."""
    result: list[dict] = []
    for region in regions:
        d = region.model_dump() if hasattr(region, "model_dump") else dict(region)
        result.append(d)
    return result


def _face_regions_to_dicts(faces: list) -> list[dict]:
    """Convert FaceRegion model objects to plain dicts with ``bbox``."""
    result: list[dict] = []
    for face in faces:
        d = face.model_dump() if hasattr(face, "model_dump") else dict(face)
        # Ensure "bbox" is available for safe_area checks
        if "bbox" not in d and hasattr(face, "bbox"):
            d["bbox"] = list(face.bbox)
        result.append(d)
    return result


def _issues_to_dicts(issues: list) -> list[dict]:
    """Convert Pydantic issue models to JSON-serializable dicts."""
    result: list[dict] = []
    for issue in issues:
        if hasattr(issue, "model_dump"):
            result.append(issue.model_dump())
        elif isinstance(issue, dict):
            result.append(issue)
        else:
            result.append(json.loads(json.dumps(issue, default=str)))
    return result


def _build_ocr_summary(frame_results: list[dict], _regions: list) -> dict:
    """Aggregate OCR statistics across all inspected frames."""
    total_regions = sum(r["region_count"] for r in frame_results)
    frames_with_text = sum(1 for r in frame_results if r["region_count"] > 0)
    return {
        "frames_inspected": len(frame_results),
        "frames_with_text": frames_with_text,
        "total_regions": total_regions,
        "avg_regions_per_frame": round(total_regions / len(frame_results), 2) if frame_results else 0.0,
    }


def _build_face_summary(frame_results: list[dict]) -> dict:
    """Aggregate face detection statistics across all inspected frames."""
    total_faces = sum(r["face_count"] for r in frame_results)
    total_primary = sum(r.get("primary_faces", 0) for r in frame_results)
    frames_with_faces = sum(1 for r in frame_results if r["face_count"] > 0)
    return {
        "frames_inspected": len(frame_results),
        "frames_with_faces": frames_with_faces,
        "total_faces": total_faces,
        "primary_faces": total_primary,
    }
