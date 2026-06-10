"""Rendered scene manifest — maps each composed scene to beat, timing, source, and caption regions.

Pure function builder with dependency injection. No FFmpeg, no API calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class RenderedSceneEntry(BaseModel):
    """A single rendered scene mapped to its beat, timing, source, and caption regions."""

    scene: str
    beat_id: str = ""
    start_sec: float
    end_sec: float
    source_path: str
    source_type: str = ""
    selected_asset_id: str | None = None
    caption_regions: list[dict] = Field(default_factory=list)


class RenderedSceneManifest(BaseModel):
    """Manifest of all rendered scenes from composer output."""

    entries: list[RenderedSceneEntry] = Field(default_factory=list)
    video_duration_sec: float = 0.0
    video_path: str = ""

    def scenes_at_timestamp(self, t: float) -> list[RenderedSceneEntry]:
        """Return all scene entries active at timestamp ``t``."""
        return [
            e for e in self.entries
            if e.start_sec <= t <= e.end_sec
        ]

    def beat_to_scenes(self, beat_id: str) -> list[RenderedSceneEntry]:
        """Return all scene entries mapped to a given beat ID."""
        return [e for e in self.entries if e.beat_id == beat_id]

    def to_json(self, path: str | Path) -> None:
        """Serialize manifest to a JSON file."""
        Path(path).write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @classmethod
    def from_json(cls, path: str | Path) -> RenderedSceneManifest:
        """Deserialize manifest from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)


def _match_text_regions(
    regions: list[dict],
    start_sec: float,
    end_sec: float,
) -> list[dict]:
    """Return text regions whose time range overlaps with [start_sec, end_sec]."""
    return [
        r for r in regions
        if r["timestamp_start_sec"] <= end_sec
        and r["timestamp_end_sec"] >= start_sec
    ]


def build_rendered_scene_manifest(
    scenes: list[dict],
    text_regions: list[dict],
    video_duration_sec: float,
    video_path: str,
) -> RenderedSceneManifest:
    """Build a manifest of rendered scenes from composer output data.

    Parameters
    ----------
    scenes : list[dict]
        Scene dicts with keys: scene, path, type, target_duration,
        beat_id, selected_asset_id.
    text_regions : list[dict]
        Text region dicts from ``build_generated_text_regions()``, each with
        ``timestamp_start_sec`` and ``timestamp_end_sec``.
    video_duration_sec : float
        Total rendered video duration in seconds.
    video_path : str
        Path to the rendered video file.

    Returns
    -------
    RenderedSceneManifest
    """
    entries: list[RenderedSceneEntry] = []
    cumulative = 0.0

    for scene in scenes:
        duration = float(scene.get("target_duration", 0.0))
        start = cumulative
        end = cumulative + duration
        cumulative = end

        captions = _match_text_regions(text_regions, start, end)

        entries.append(RenderedSceneEntry(
            scene=str(scene.get("scene", "")),
            beat_id=str(scene.get("beat_id", "")),
            start_sec=start,
            end_sec=end,
            source_path=str(scene.get("path", "")),
            source_type=str(scene.get("type", "")),
            selected_asset_id=scene.get("selected_asset_id"),
            caption_regions=captions,
        ))

    return RenderedSceneManifest(
        entries=entries,
        video_duration_sec=video_duration_sec,
        video_path=video_path,
    )
