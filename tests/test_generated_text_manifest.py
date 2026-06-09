"""Tests for generated text region manifest."""
import json

import pytest

from clipper_agency.core.generated_text_manifest import (
    build_generated_text_regions,
    regions_at_timestamp,
)


class TestBuildGeneratedTextRegions:
    """Tests for build_generated_text_regions()."""

    def test_returns_correct_structure_with_subtitle_region(self):
        """A render plan with one caption produces a single subtitle region."""
        render_plan = {
            "template_name": "test",
            "scenes": [
                {
                    "source_path": "/tmp/test.mp4",
                    "duration_seconds": 10.0,
                    "captions": [
                        {
                            "text": "Hello world",
                            "start_seconds": 4.0,
                            "end_seconds": 6.5,
                            "position": "bottom",
                            "style": "default",
                        }
                    ],
                    "overlays": [],
                    "transition": "cut",
                }
            ],
            "metadata": {},
        }
        frame_size = (1080, 1920)

        result = build_generated_text_regions(render_plan, frame_size)

        assert isinstance(result, list)
        assert len(result) == 1

        entry = result[0]
        assert entry["timestamp_start_sec"] == 4.0
        assert entry["timestamp_end_sec"] == 6.5
        assert entry["layer"] == "subtitle"
        assert entry["text"] == "Hello world"
        bbox = entry["bbox"]
        assert len(bbox) == 4
        # bbox should be within frame dimensions
        assert 0 <= bbox[0] <= frame_size[0]
        assert 0 <= bbox[1] <= frame_size[1]
        assert 0 <= bbox[2] <= frame_size[0]
        assert 0 <= bbox[3] <= frame_size[1]
        assert bbox[0] < bbox[2]  # x1 < x2
        assert bbox[1] < bbox[3]  # y1 < y2

    def test_multiple_subtitle_regions_across_time(self):
        """Captions in multiple scenes produce regions with cumulative offsets."""
        render_plan = {
            "template_name": "test",
            "scenes": [
                {
                    "source_path": "/tmp/a.mp4",
                    "duration_seconds": 5.0,
                    "captions": [
                        {"text": "First", "start_seconds": 1.0, "end_seconds": 3.0, "position": "bottom"},
                    ],
                    "overlays": [],
                    "transition": "cut",
                },
                {
                    "source_path": "/tmp/b.mp4",
                    "duration_seconds": 5.0,
                    "captions": [
                        {"text": "Second", "start_seconds": 1.0, "end_seconds": 3.0, "position": "bottom"},
                    ],
                    "overlays": [],
                    "transition": "cut",
                },
            ],
            "metadata": {},
        }
        frame_size = (1080, 1920)

        result = build_generated_text_regions(render_plan, frame_size)

        assert len(result) == 2
        assert result[0]["text"] == "First"
        assert result[0]["timestamp_start_sec"] == 1.0
        assert result[0]["timestamp_end_sec"] == 3.0
        assert result[1]["text"] == "Second"
        assert result[1]["timestamp_start_sec"] == 6.0  # 1.0 + 5.0 offset
        assert result[1]["timestamp_end_sec"] == 8.0    # 3.0 + 5.0 offset

    def test_different_layers_produce_distinct_entries(self):
        """Captions produce 'subtitle' entries; overlays produce 'headline' etc."""
        render_plan = {
            "template_name": "test",
            "scenes": [
                {
                    "source_path": "/tmp/test.mp4",
                    "duration_seconds": 10.0,
                    "captions": [
                        {"text": "Sub", "start_seconds": 2.0, "end_seconds": 4.0, "position": "bottom"},
                    ],
                    "overlays": [
                        {
                            "text": "Headline text",
                            "kind": "lower_third",
                            "start_seconds": 1.0,
                            "end_seconds": 5.0,
                        },
                        {
                            "text": "CTA button",
                            "kind": "cta",
                            "start_seconds": 3.0,
                            "end_seconds": 8.0,
                        },
                        {
                            "text": "Watermark logo",
                            "kind": "watermark",
                            "start_seconds": 0.0,
                            "end_seconds": 10.0,
                        },
                    ],
                    "transition": "cut",
                }
            ],
            "metadata": {},
        }
        frame_size = (1080, 1920)

        result = build_generated_text_regions(render_plan, frame_size)

        assert len(result) == 4

        layers = {r["layer"] for r in result}
        assert "subtitle" in layers
        assert "headline" in layers
        assert "watermark" in layers
        assert "cta" in layers

        # Verify each layer's entry has correct text
        layer_map = {r["layer"]: r for r in result}
        assert layer_map["subtitle"]["text"] == "Sub"
        assert layer_map["headline"]["text"] == "Headline text"
        assert layer_map["watermark"]["text"] == "Watermark logo"
        assert layer_map["cta"]["text"] == "CTA button"


class TestRegionsAtTimestamp:
    """Tests for regions_at_timestamp()."""

    @staticmethod
    def _make_regions() -> list[dict]:
        """Create a standard set of regions for timestamp query tests."""
        return [
            {"timestamp_start_sec": 2.0, "timestamp_end_sec": 5.0, "layer": "subtitle", "bbox": [0, 0, 100, 100], "text": "A"},
            {"timestamp_start_sec": 3.0, "timestamp_end_sec": 7.0, "layer": "headline", "bbox": [0, 0, 100, 100], "text": "B"},
            {"timestamp_start_sec": 6.0, "timestamp_end_sec": 9.0, "layer": "subtitle", "bbox": [0, 0, 100, 100], "text": "C"},
        ]

    def test_returns_only_active_regions(self):
        """Query at t=4 returns regions A and B (both active at t=4)."""
        regions = self._make_regions()
        result = regions_at_timestamp(regions, 4.0)
        texts = {r["text"] for r in result}
        assert texts == {"A", "B"}

    def test_returns_empty_list_for_inactive_timestamp(self):
        """Query at t=1 returns nothing (before any region)."""
        regions = self._make_regions()
        result = regions_at_timestamp(regions, 1.0)
        assert result == []

    def test_returns_multiple_overlapping_regions(self):
        """Query at t=3.0 captures regions A and B overlapping."""
        regions = self._make_regions()
        result = regions_at_timestamp(regions, 3.0)
        assert len(result) == 2
        texts = {r["text"] for r in result}
        assert texts == {"A", "B"}

    def test_inclusive_boundaries(self):
        """Start and end timestamps are inclusive."""
        regions = [
            {"timestamp_start_sec": 5.0, "timestamp_end_sec": 5.0, "layer": "subtitle", "bbox": [0, 0, 100, 100], "text": "X"},
        ]
        assert len(regions_at_timestamp(regions, 5.0)) == 1  # inclusive
        assert len(regions_at_timestamp(regions, 2.5)) == 0  # outside

    def test_after_end_exclusive(self):
        """Region is NOT active after its end timestamp (but still inclusive at end)."""
        regions = [
            {"timestamp_start_sec": 1.0, "timestamp_end_sec": 3.0, "layer": "subtitle", "bbox": [0, 0, 100, 100], "text": "Y"},
        ]
        assert len(regions_at_timestamp(regions, 3.0)) == 1  # at end boundary, inclusive
        assert len(regions_at_timestamp(regions, 3.1)) == 0  # after end

    def test_at_start_boundary_returns_region(self):
        """Region IS active at its start timestamp (inclusive)."""
        regions = [
            {"timestamp_start_sec": 2.0, "timestamp_end_sec": 4.0, "layer": "subtitle", "bbox": [0, 0, 100, 100], "text": "Z"},
        ]
        assert len(regions_at_timestamp(regions, 2.0)) == 1

    def test_empty_regions_list(self):
        """Empty input returns empty list."""
        assert regions_at_timestamp([], 5.0) == []


class TestEdgeCases:
    """Edge case tests for build_generated_text_regions()."""

    def test_empty_render_plan_returns_empty_list(self):
        """A render plan with no scenes returns an empty list."""
        result = build_generated_text_regions({"template_name": "test", "scenes": [], "metadata": {}}, (1080, 1920))
        assert result == []

    def test_missing_captions_and_overlays_keys(self):
        """Scenes without 'captions' or 'overlays' keys are handled gracefully."""
        render_plan = {
            "template_name": "test",
            "scenes": [{"source_path": "/tmp/a.mp4", "duration_seconds": 5.0, "transition": "cut"}],
            "metadata": {},
        }
        result = build_generated_text_regions(render_plan, (1080, 1920))
        assert result == []

    def test_bounding_boxes_within_frame_dimensions(self):
        """All bounding box coordinates must be within [0, frame_width/height]."""
        render_plan = {
            "template_name": "test",
            "scenes": [
                {
                    "source_path": "/tmp/test.mp4",
                    "duration_seconds": 10.0,
                    "captions": [
                        {"text": "Bottom", "start_seconds": 0.0, "end_seconds": 2.0, "position": "bottom"},
                        {"text": "Top", "start_seconds": 2.0, "end_seconds": 4.0, "position": "top"},
                        {"text": "Center", "start_seconds": 4.0, "end_seconds": 6.0, "position": "center"},
                    ],
                    "overlays": [],
                    "transition": "cut",
                }
            ],
            "metadata": {},
        }
        frame_size = (1080, 1920)

        result = build_generated_text_regions(render_plan, frame_size)

        for entry in result:
            bbox = entry["bbox"]
            assert 0 <= bbox[0] <= frame_size[0], f"x1 out of bounds: {bbox}"
            assert 0 <= bbox[1] <= frame_size[1], f"y1 out of bounds: {bbox}"
            assert 0 <= bbox[2] <= frame_size[0], f"x2 out of bounds: {bbox}"
            assert 0 <= bbox[3] <= frame_size[1], f"y2 out of bounds: {bbox}"
            assert bbox[0] < bbox[2], f"x1 >= x2: {bbox}"
            assert bbox[1] < bbox[3], f"y1 >= y2: {bbox}"

    def test_output_is_json_serializable(self):
        """Result must be safely serializable to JSON."""
        render_plan = {
            "template_name": "test",
            "scenes": [
                {
                    "source_path": "/tmp/test.mp4",
                    "duration_seconds": 10.0,
                    "captions": [
                        {"text": "Hi", "start_seconds": 1.0, "end_seconds": 2.0, "position": "bottom"},
                    ],
                    "overlays": [
                        {"text": "Head", "kind": "lower_third", "start_seconds": 0.0, "end_seconds": 5.0},
                    ],
                    "transition": "cut",
                }
            ],
            "metadata": {},
        }
        result = build_generated_text_regions(render_plan, (1080, 1920))
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        assert parsed == result

    def test_single_frame_region_start_equals_end(self):
        """A region where start equals end is handled (zero-length display)."""
        render_plan = {
            "template_name": "test",
            "scenes": [
                {
                    "source_path": "/tmp/test.mp4",
                    "duration_seconds": 10.0,
                    "captions": [
                        {"text": "Flash", "start_seconds": 5.0, "end_seconds": 5.0, "position": "bottom"},
                    ],
                    "overlays": [],
                    "transition": "cut",
                }
            ],
            "metadata": {},
        }
        result = build_generated_text_regions(render_plan, (1080, 1920))
        assert len(result) == 1
        assert result[0]["timestamp_start_sec"] == 5.0
        assert result[0]["timestamp_end_sec"] == 5.0
        # At exactly t=5, the region should be active (inclusive)
        assert len(regions_at_timestamp(result, 5.0)) == 1
