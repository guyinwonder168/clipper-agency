"""Tests for rendered scene manifest — pure logic, no FFmpeg, no API calls."""

import json
import tempfile
from pathlib import Path

import pytest

from clipper_agency.core.rendered_scene_manifest import (
    RenderedSceneEntry,
    RenderedSceneManifest,
    build_rendered_scene_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_scenes() -> list[dict]:
    """Three scenes with cumulative timing."""
    return [
        {
            "scene": 1,
            "path": "/assets/clip_a.mp4",
            "type": "video",
            "target_duration": 5.0,
            "beat_id": "beat_0",
            "selected_asset_id": "asset_001",
        },
        {
            "scene": 2,
            "path": "/assets/photo_b.jpg",
            "type": "image",
            "target_duration": 4.0,
            "beat_id": "beat_1",
            "selected_asset_id": "asset_002",
        },
        {
            "scene": 3,
            "path": "/tmp/card_beat_2.mp4",
            "type": "generated_card",
            "target_duration": 6.0,
            "beat_id": "beat_2",
            "selected_asset_id": None,
        },
    ]


def _sample_text_regions() -> list[dict]:
    """Text regions spanning the three-scene timeline."""
    return [
        {
            "timestamp_start_sec": 1.0,
            "timestamp_end_sec": 3.0,
            "layer": "subtitle",
            "bbox": [100, 1500, 960, 1700],
            "text": "First caption",
        },
        {
            "timestamp_start_sec": 5.5,
            "timestamp_end_sec": 7.5,
            "layer": "subtitle",
            "bbox": [100, 1500, 960, 1700],
            "text": "Second caption",
        },
        {
            "timestamp_start_sec": 10.0,
            "timestamp_end_sec": 13.0,
            "layer": "headline",
            "bbox": [100, 500, 960, 700],
            "text": "Breaking news",
        },
    ]


def _build_manifest(
    scenes=None,
    text_regions=None,
    video_duration_sec=15.0,
    video_path="/output/job_1/video.mp4",
) -> RenderedSceneManifest:
    """Convenience wrapper for building a manifest with defaults."""
    return build_rendered_scene_manifest(
        scenes=scenes if scenes is not None else _sample_scenes(),
        text_regions=text_regions if text_regions is not None else _sample_text_regions(),
        video_duration_sec=video_duration_sec,
        video_path=video_path,
    )


# ---------------------------------------------------------------------------
# Test: Manifest creation
# ---------------------------------------------------------------------------


class TestBuildRenderedSceneManifest:
    """Tests for build_rendered_scene_manifest()."""

    def test_creates_manifest_with_correct_entry_count(self):
        manifest = _build_manifest()
        assert len(manifest.entries) == 3

    def test_first_scene_timing_starts_at_zero(self):
        manifest = _build_manifest()
        entry = manifest.entries[0]
        assert entry.start_sec == 0.0
        assert entry.end_sec == pytest.approx(5.0)

    def test_cumulative_timing_across_scenes(self):
        manifest = _build_manifest()
        assert manifest.entries[1].start_sec == pytest.approx(5.0)
        assert manifest.entries[1].end_sec == pytest.approx(9.0)
        assert manifest.entries[2].start_sec == pytest.approx(9.0)
        assert manifest.entries[2].end_sec == pytest.approx(15.0)

    def test_scene_fields_mapped_correctly(self):
        manifest = _build_manifest()
        e0 = manifest.entries[0]
        assert e0.scene == "1"
        assert e0.beat_id == "beat_0"
        assert e0.source_path == "/assets/clip_a.mp4"
        assert e0.source_type == "video"
        assert e0.selected_asset_id == "asset_001"

    def test_video_metadata_preserved(self):
        manifest = _build_manifest()
        assert manifest.video_duration_sec == 15.0
        assert manifest.video_path == "/output/job_1/video.mp4"

    def test_caption_regions_matched_to_scene_time_range(self):
        """Scene 1 spans [0,5); only text regions within that range appear."""
        manifest = _build_manifest()
        e0 = manifest.entries[0]
        # Region at [1.0, 3.0] falls within scene 0 [0.0, 5.0]
        assert len(e0.caption_regions) == 1
        assert e0.caption_regions[0]["text"] == "First caption"

    def test_scene_with_no_matching_regions(self):
        """Scene 2 spans [5,9); region [5.5,7.5] matches."""
        manifest = _build_manifest()
        e1 = manifest.entries[1]
        assert len(e1.caption_regions) == 1
        assert e1.caption_regions[0]["text"] == "Second caption"

    def test_empty_text_regions_produces_empty_caption_lists(self):
        manifest = _build_manifest(text_regions=[])
        for entry in manifest.entries:
            assert entry.caption_regions == []


# ---------------------------------------------------------------------------
# Test: scenes_at_timestamp()
# ---------------------------------------------------------------------------


class TestScenesAtTimestamp:
    """Tests for RenderedSceneManifest.scenes_at_timestamp()."""

    def test_returns_scene_at_start_of_video(self):
        manifest = _build_manifest()
        scenes = manifest.scenes_at_timestamp(0.0)
        assert len(scenes) == 1
        assert scenes[0].beat_id == "beat_0"

    def test_returns_scene_in_middle(self):
        manifest = _build_manifest()
        scenes = manifest.scenes_at_timestamp(6.0)
        assert len(scenes) == 1
        assert scenes[0].beat_id == "beat_1"

    def test_returns_empty_for_negative_timestamp(self):
        manifest = _build_manifest()
        assert manifest.scenes_at_timestamp(-1.0) == []

    def test_returns_empty_past_video_end(self):
        manifest = _build_manifest()
        assert manifest.scenes_at_timestamp(20.0) == []


# ---------------------------------------------------------------------------
# Test: beat_to_scenes()
# ---------------------------------------------------------------------------


class TestBeatToScenes:
    """Tests for RenderedSceneManifest.beat_to_scenes()."""

    def test_returns_correct_scene_for_known_beat(self):
        manifest = _build_manifest()
        scenes = manifest.beat_to_scenes("beat_1")
        assert len(scenes) == 1
        assert scenes[0].source_type == "image"

    def test_returns_empty_for_unknown_beat(self):
        manifest = _build_manifest()
        assert manifest.beat_to_scenes("beat_999") == []


# ---------------------------------------------------------------------------
# Test: JSON round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    """Tests for to_json() / from_json() serialization."""

    def test_round_trip_preserves_data(self):
        manifest = _build_manifest()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            manifest.to_json(path)
            loaded = RenderedSceneManifest.from_json(path)
            assert len(loaded.entries) == len(manifest.entries)
            assert loaded.video_duration_sec == manifest.video_duration_sec
            assert loaded.video_path == manifest.video_path

            for orig, rest in zip(manifest.entries, loaded.entries):
                assert orig.scene == rest.scene
                assert orig.beat_id == rest.beat_id
                assert orig.start_sec == pytest.approx(rest.start_sec)
                assert orig.end_sec == pytest.approx(rest.end_sec)
                assert orig.source_path == rest.source_path
                assert orig.source_type == rest.source_type
                assert orig.selected_asset_id == rest.selected_asset_id
        finally:
            Path(path).unlink(missing_ok=True)

    def test_round_trip_with_caption_regions(self):
        manifest = _build_manifest()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            manifest.to_json(path)
            loaded = RenderedSceneManifest.from_json(path)
            for orig, rest in zip(manifest.entries, loaded.entries):
                assert orig.caption_regions == rest.caption_regions
        finally:
            Path(path).unlink(missing_ok=True)

    def test_serialized_output_is_valid_json(self):
        manifest = _build_manifest()
        data = json.loads(manifest.model_dump_json())
        assert "entries" in data
        assert "video_duration_sec" in data
        assert "video_path" in data


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_manifest_with_no_scenes(self):
        manifest = build_rendered_scene_manifest(
            scenes=[],
            text_regions=[],
            video_duration_sec=0.0,
            video_path="",
        )
        assert len(manifest.entries) == 0
        assert manifest.scenes_at_timestamp(0.0) == []
        assert manifest.beat_to_scenes("any") == []

    def test_single_zero_duration_scene(self):
        scenes = [
            {
                "scene": 1,
                "path": "/assets/flash.jpg",
                "type": "image",
                "target_duration": 0.0,
                "beat_id": "beat_0",
                "selected_asset_id": None,
            },
        ]
        manifest = _build_manifest(scenes=scenes, video_duration_sec=0.0)
        assert len(manifest.entries) == 1
        assert manifest.entries[0].start_sec == 0.0
        assert manifest.entries[0].end_sec == 0.0

    def test_overlapping_timestamp_falls_in_correct_scene(self):
        """Two scenes with same beat_id — both returned by beat_to_scenes."""
        scenes = [
            {
                "scene": 1,
                "path": "/a.mp4",
                "type": "video",
                "target_duration": 3.0,
                "beat_id": "beat_0",
                "selected_asset_id": None,
            },
            {
                "scene": 2,
                "path": "/b.mp4",
                "type": "video",
                "target_duration": 3.0,
                "beat_id": "beat_0",
                "selected_asset_id": None,
            },
        ]
        manifest = _build_manifest(scenes=scenes, video_duration_sec=6.0)
        beat_scenes = manifest.beat_to_scenes("beat_0")
        assert len(beat_scenes) == 2

    def test_text_region_at_scene_boundary_included(self):
        """A text region whose start_sec equals scene end_sec is included."""
        scenes = [
            {
                "scene": 1,
                "path": "/a.mp4",
                "type": "video",
                "target_duration": 5.0,
                "beat_id": "beat_0",
                "selected_asset_id": None,
            },
        ]
        regions = [
            {
                "timestamp_start_sec": 5.0,
                "timestamp_end_sec": 5.0,
                "layer": "subtitle",
                "bbox": [0, 0, 100, 100],
                "text": "Boundary",
            },
        ]
        manifest = _build_manifest(
            scenes=scenes, text_regions=regions, video_duration_sec=5.0,
        )
        # Scene spans [0, 5], region at exactly 5.0 → included
        assert len(manifest.entries[0].caption_regions) == 1

    def test_missing_optional_fields_default_to_none(self):
        scenes = [
            {"scene": 1, "path": "/a.mp4", "target_duration": 2.0},
        ]
        manifest = _build_manifest(scenes=scenes, video_duration_sec=2.0)
        entry = manifest.entries[0]
        assert entry.beat_id == ""
        assert entry.source_type == ""
        assert entry.selected_asset_id is None
