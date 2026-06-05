"""Per-scene FFmpeg filter string builder from treatment definitions.

Pure functions on immutable data — no side effects, no I/O.
Given an asset dict and a TreatmentConfig, produces the FFmpeg filter
string for that scene's treatment with all variables substituted.
"""

from __future__ import annotations

from clipper_agency.rendering.treatment_config import TreatmentConfig


class TreatmentFilterBuilder:
    """Build per-scene FFmpeg filter strings from treatment definitions."""

    def __init__(self, config: TreatmentConfig) -> None:
        self._config = config

    def build(self, asset: dict, start_time: float = 0.0) -> str:
        """Build FFmpeg filter string for one scene's treatment.

        Args:
            asset: Dict with keys like "treatment", "target_duration",
                   "headline", "type".
            start_time: Cumulative offset for time-based filters.

        Returns:
            FFmpeg filter string, or "null" for no treatment.
        """
        treatment_name = asset.get("treatment")
        if not treatment_name:
            return "null"

        treatment = self._config.get_treatment(treatment_name)
        if not treatment or treatment.ffmpeg_filter is None:
            return "null"

        duration = float(asset.get("target_duration", 5.0))
        fps = self._config.target_fps
        text = asset.get("headline", "")

        filter_str = treatment.ffmpeg_filter
        filter_str = filter_str.replace("{frames}", str(int(duration * fps)))
        filter_str = filter_str.replace("{text}", text)
        filter_str = filter_str.replace("{duration}", str(duration))
        filter_str = filter_str.replace("{start_time}", str(start_time))

        input_type = asset.get("type", treatment.input_type)

        # Image + zoompan: prepend scale for pixel room
        if input_type == "image" and "zoompan" in filter_str:
            filter_str = f"scale=5400:-1,{filter_str}"

        # After scale/crop: append setsar=1/1 to prevent SAR distortion
        if "scale=" in filter_str or "crop=" in filter_str:
            filter_str = f"{filter_str},setsar=1/1"

        return filter_str
