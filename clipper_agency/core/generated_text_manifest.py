"""Generated text region manifest — persists composer text overlay coordinates for reviewer collision checks."""
from __future__ import annotations


# Fractional bounding box constants per position (relative to frame dimensions).
# Values derived from the canonical 1080×1920 portrait example: [120, 1480, 960, 1740].
_POSITION_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "bottom": {
        "x_fraction": (0.11, 0.89),
        "y_fraction": (0.77, 0.91),
    },
    "top": {
        "x_fraction": (0.11, 0.89),
        "y_fraction": (0.05, 0.19),
    },
    "center": {
        "x_fraction": (0.11, 0.89),
        "y_fraction": (0.43, 0.57),
    },
}


def _caption_to_region(
    caption: dict,
    offset_sec: float,
    frame_size: tuple[int, int],
    layer: str = "subtitle",
) -> dict:
    """Convert a single caption overlay into a text region entry."""
    bounds = _POSITION_BOUNDS.get(caption.get("position", "bottom"), _POSITION_BOUNDS["bottom"])
    fw, fh = frame_size
    x1 = int(bounds["x_fraction"][0] * fw)
    x2 = int(bounds["x_fraction"][1] * fw)
    y1 = int(bounds["y_fraction"][0] * fh)
    y2 = int(bounds["y_fraction"][1] * fh)

    return {
        "timestamp_start_sec": round(caption["start_seconds"] + offset_sec, 3),
        "timestamp_end_sec": round(caption["end_seconds"] + offset_sec, 3),
        "layer": layer,
        "bbox": [x1, y1, x2, y2],
        "text": caption["text"],
    }


# Layer-specific bounding box fractions (x_left,x_right), (y_top,y_bottom).
_LAYER_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "headline": {
        "x_fraction": (0.11, 0.89),
        "y_fraction": (0.25, 0.40),
    },
    "watermark": {
        "x_fraction": (0.70, 0.95),
        "y_fraction": (0.03, 0.12),
    },
    "cta": {
        "x_fraction": (0.20, 0.80),
        "y_fraction": (0.65, 0.76),
    },
}


def _kind_to_layer(kind: str) -> str:
    """Map a VisualOverlay kind string to a manifest layer name."""
    kind_lower = kind.lower()
    if "watermark" in kind_lower:
        return "watermark"
    if "cta" in kind_lower:
        return "cta"
    return "headline"


def _overlay_to_region(
    overlay: dict,
    offset_sec: float,
    frame_size: tuple[int, int],
) -> dict:
    """Convert a VisualOverlay dict into a text region entry."""
    layer = _kind_to_layer(overlay.get("kind", "lower_third"))
    bounds = _LAYER_BOUNDS.get(layer, _LAYER_BOUNDS["headline"])
    fw, fh = frame_size
    x1 = int(bounds["x_fraction"][0] * fw)
    x2 = int(bounds["x_fraction"][1] * fw)
    y1 = int(bounds["y_fraction"][0] * fh)
    y2 = int(bounds["y_fraction"][1] * fh)

    start = overlay.get("start_seconds", 0.0) + offset_sec
    raw_end = overlay.get("end_seconds")
    end = start if raw_end is None else raw_end + offset_sec

    return {
        "timestamp_start_sec": round(start, 3),
        "timestamp_end_sec": round(end, 3),
        "layer": layer,
        "bbox": [x1, y1, x2, y2],
        "text": overlay.get("text", ""),
    }


def build_generated_text_regions(render_plan: dict, frame_size: tuple[int, int]) -> list[dict]:
    """Given a render plan (from Composer) and frame dimensions,
    produce a list of text region entries with bounding boxes.

    Each entry has: timestamp_start_sec, timestamp_end_sec, layer, bbox, text
    bbox format: [x1, y1, x2, y2] in pixel coordinates
    """
    regions: list[dict] = []
    scenes = render_plan.get("scenes", [])
    cumulative_offset = 0.0

    for scene in scenes:
        for caption in scene.get("captions", []):
            regions.append(_caption_to_region(caption, cumulative_offset, frame_size))
        for overlay in scene.get("overlays", []):
            regions.append(_overlay_to_region(overlay, cumulative_offset, frame_size))
        cumulative_offset += scene.get("duration_seconds", 0.0)

    return regions


def regions_at_timestamp(regions: list[dict], timestamp_sec: float) -> list[dict]:
    """Return all text regions active at a given timestamp."""
    return [
        r for r in regions
        if r["timestamp_start_sec"] <= timestamp_sec <= r["timestamp_end_sec"]
    ]
