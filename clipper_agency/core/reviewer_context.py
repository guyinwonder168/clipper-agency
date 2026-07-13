"""Reviewer context builder — assembles full context for timestamp-level semantic review.

Pure functions with dependency injection. No file I/O, no API calls, no FFmpeg.
All data is passed as parameters. Optional data (e.g. rendered_scene_manifest from
Worker Q) gracefully handled as None, producing partial context with clear indicators.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SceneBeatMapping(BaseModel):
    """Maps a rendered scene to its matched story beats via temporal overlap."""

    scene_index: int
    scene_start_sec: float
    scene_end_sec: float
    matched_beat_ids: list[int] = Field(default_factory=list)
    overlap_type: str = "none"  # "midpoint" | "range_overlap" | "none" | "mixed"
    # FIX-4 (ADR 0030): the VLM-depicted subject_name for this scene's asset,
    # threaded from the rendered scene manifest entry so the reviewer's per-scene
    # entity-vs-beat gate can fire without zipping mappings against entries.
    subject_name: str = ""


class ReviewContextBundle(BaseModel):
    """Full context bundle for the reviewer agent's semantic review."""

    story_beats: list[dict] = Field(default_factory=list)
    word_timestamps: list[dict] = Field(default_factory=list)
    visual_diagnostics: dict | None = None
    rendered_scene_manifest: dict | None = None
    composer_diagnostics: dict | None = None
    caption: str | None = None
    thumbnail_path: str | None = None
    package_metadata: dict | None = None
    audio_duration_sec: float = 0.0
    video_duration_sec: float = 0.0
    beat_timeline: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_beat_time_ranges(
    story_beats: list[dict],
    word_timestamps: list[dict],
    audio_duration_sec: float,
) -> list[tuple[float, float]]:
    """Derive (start_sec, end_sec) for each beat from word timestamps.

    If beats have explicit start_sec/end_sec, use those.
    If word_timestamps are available, chunk them evenly across beats.
    Otherwise, divide audio_duration evenly across beats.
    """
    if not story_beats:
        return []

    # Check for explicit time ranges in beat data
    explicit = all("start_sec" in b and "end_sec" in b for b in story_beats)
    if explicit:
        return [(b["start_sec"], b["end_sec"]) for b in story_beats]

    # Distribute word timestamps evenly across beats
    if word_timestamps:
        n_beats = len(story_beats)
        words_per_beat = max(1, len(word_timestamps) // n_beats)
        ranges: list[tuple[float, float]] = []
        for i in range(n_beats):
            start_idx = i * words_per_beat
            end_idx = start_idx + words_per_beat if i < n_beats - 1 else len(word_timestamps)
            chunk = word_timestamps[start_idx:end_idx]
            if chunk:
                ranges.append((chunk[0]["start"], chunk[-1]["end"]))
            else:
                ranges.append((0.0, 0.0))
        return ranges

    # Even distribution by audio duration
    if audio_duration_sec > 0:
        n = len(story_beats)
        seg = audio_duration_sec / n
        return [(i * seg, (i + 1) * seg) for i in range(n)]

    return [(0.0, 0.0)] * len(story_beats)


def _midpoint(start: float, end: float) -> float:
    """Return the midpoint of a time range."""
    return (start + end) / 2.0


def _ranges_overlap(
    a_start: float,
    a_end: float,
    b_start: float,
    b_end: float,
) -> bool:
    """Check if two time ranges overlap (inclusive boundaries)."""
    return a_start <= b_end and b_start <= a_end


def _classify_overlap(overlap_types: set[str]) -> str:
    """Classify the overall overlap type for a scene-beat mapping."""
    if not overlap_types:
        return "none"
    if overlap_types == {"midpoint"}:
        return "midpoint"
    if overlap_types == {"range_overlap"}:
        return "range_overlap"
    return "mixed"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_review_context_bundle(**kwargs: Any) -> ReviewContextBundle:
    """Assemble a ReviewContextBundle from passed-in data.

    Pure function — all data injected as kwargs. Unknown kwargs are silently
    ignored for forward compatibility.
    """
    valid_fields = ReviewContextBundle.model_fields
    filtered = {k: v for k, v in kwargs.items() if k in valid_fields}
    return ReviewContextBundle(**filtered)


def _match_scene_to_beats(
    scene_start: float,
    scene_end: float,
    beat_ranges: list[tuple[float, float]],
    beat_ids: list[int],
) -> tuple[list[int], str]:
    """Find beats matching a scene via midpoint containment or range overlap."""
    matched: list[int] = []
    overlap_types: set[str] = set()

    for beat_idx, (b_start, b_end) in enumerate(beat_ranges):
        beat_mid = _midpoint(b_start, b_end)
        has_midpoint = scene_start <= beat_mid <= scene_end
        has_overlap = _ranges_overlap(scene_start, scene_end, b_start, b_end)

        if has_midpoint:
            overlap_types.add("midpoint")
        if has_overlap:
            overlap_types.add("range_overlap")

        if has_midpoint or has_overlap:
            matched.append(beat_ids[beat_idx])

    return matched, _classify_overlap(overlap_types)


def map_scenes_to_beats(
    manifest_entries: list[dict],
    story_beats: list[dict],
    word_timestamps: list[dict],
    audio_duration_sec: float = 0.0,
    beat_time_ranges: list[tuple[float, float]] | None = None,
) -> list[SceneBeatMapping]:
    """Map rendered scenes to story beats using temporal overlap.

    Each manifest entry should have ``start_sec`` and ``end_sec``.
    Optionally ``scene_index`` (defaults to list position).

    Overlap detection uses two strategies:
      - **midpoint**: beat midpoint falls within scene range
      - **range_overlap**: beat time range overlaps scene time range

    When ``beat_time_ranges`` is provided (from canonical timeline),
    it takes precedence over the even-chunking derivation.
    """
    if not manifest_entries:
        return []

    if beat_time_ranges is not None:
        beat_ranges = beat_time_ranges
    else:
        beat_ranges = _derive_beat_time_ranges(
            story_beats,
            word_timestamps,
            audio_duration_sec,
        )
    beat_ids = [b.get("beat_id", i) for i, b in enumerate(story_beats)]

    mappings: list[SceneBeatMapping] = []
    for idx, entry in enumerate(manifest_entries):
        scene_start = entry.get("start_sec", 0.0)
        scene_end = entry.get("end_sec", 0.0)
        matched, overlap_type = _match_scene_to_beats(
            scene_start,
            scene_end,
            beat_ranges,
            beat_ids,
        )
        mappings.append(
            SceneBeatMapping(
                scene_index=entry.get("scene_index", idx),
                scene_start_sec=scene_start,
                scene_end_sec=scene_end,
                matched_beat_ids=matched,
                overlap_type=overlap_type,
                # FIX-4 (ADR 0030): carry the rendered scene's subject_name so the
                # reviewer's entity-vs-beat gate has it without a parallel zip.
                subject_name=str(entry.get("subject_name") or ""),
            )
        )

    return mappings


def _find_scene_entry(
    scenes: list[dict],
    scene_index: int,
) -> dict | None:
    """Find a scene entry by scene_index from the scenes list.

    Falls back to list position when entries lack an explicit ``scene_index``
    field: ``RenderedSceneEntry`` serializes without one (only scene, beat_id,
    start_sec, end_sec, ...), and ``map_scenes_to_beats`` already maps by
    position. Without this fallback the per-scene semantic context stays blind
    for real Composer manifests (Codex P2 on RC-9).
    """
    for s in scenes:
        if s.get("scene_index") == scene_index:
            return s
    if 0 <= scene_index < len(scenes):
        return scenes[scene_index]
    return None


def _find_mapping(
    mappings: list[SceneBeatMapping],
    scene_index: int,
) -> SceneBeatMapping | None:
    """Find a SceneBeatMapping by scene_index."""
    for m in mappings:
        if m.scene_index == scene_index:
            return m
    return None


def _filter_words_in_range(
    word_timestamps: list[dict],
    start_sec: float,
    end_sec: float,
) -> list[dict]:
    """Return word timestamps overlapping the given time range."""
    return [wt for wt in word_timestamps if wt["start"] < end_sec and wt["end"] > start_sec]


def get_semantic_review_context(
    bundle: ReviewContextBundle,
    scene_index: int,
) -> dict[str, Any]:
    """Extract context for a specific scene for semantic review.

    Returns a dict containing: scene info, matched beats, word timestamps
    within the scene's time range, visual diagnostics, and beat data.
    Handles missing/None optional data gracefully.
    """
    manifest = bundle.rendered_scene_manifest
    # RenderedSceneManifest serializes scene entries under "entries"
    # (see core/rendered_scene_manifest.py). Reading "scenes" would always
    # yield an empty list and blind the semantic review.
    scenes = manifest.get("entries", []) if manifest else []

    scene_entry = _find_scene_entry(scenes, scene_index)
    scene_start = scene_entry.get("start_sec", 0.0) if scene_entry else None
    scene_end = scene_entry.get("end_sec", 0.0) if scene_entry else None

    # Build canonical beat time ranges from timeline if available (ADR 0020)
    beat_time_ranges = None
    if bundle.beat_timeline:
        beat_time_ranges = [(e["start_sec"], e["end_sec"]) for e in bundle.beat_timeline]

    mappings = map_scenes_to_beats(
        scenes,
        bundle.story_beats,
        bundle.word_timestamps,
        bundle.audio_duration_sec,
        beat_time_ranges=beat_time_ranges,
    )
    matched_mapping = _find_mapping(mappings, scene_index)
    matched_beat_ids = matched_mapping.matched_beat_ids if matched_mapping else []
    matched_beats = [b for b in bundle.story_beats if b.get("beat_id") in matched_beat_ids]

    scene_words = (
        _filter_words_in_range(bundle.word_timestamps, scene_start, scene_end)
        if scene_start is not None and scene_end is not None
        else []
    )

    return {
        "scene_index": scene_index,
        "scene_start_sec": scene_start,
        "scene_end_sec": scene_end,
        "matched_beats": matched_beat_ids,
        "beat_data": matched_beats,
        "word_timestamps": scene_words,
        "visual_diagnostics": bundle.visual_diagnostics,
        "audio_duration_sec": bundle.audio_duration_sec,
        "video_duration_sec": bundle.video_duration_sec,
    }
