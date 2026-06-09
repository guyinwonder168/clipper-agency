"""Unit tests for reviewer context builder — pure logic, no I/O, no API calls."""

import pytest

from clipper_agency.core.reviewer_context import (
    ReviewContextBundle,
    SceneBeatMapping,
    build_review_context_bundle,
    get_semantic_review_context,
    map_scenes_to_beats,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_word_timestamps() -> list[dict]:
    """10 words spanning 0.0–10.0s, each word ~1s."""
    return [
        {"word": "hello", "start": 0.0, "end": 1.0},
        {"word": "world", "start": 1.0, "end": 2.0},
        {"word": "this", "start": 2.0, "end": 3.0},
        {"word": "is", "start": 3.0, "end": 4.0},
        {"word": "a", "start": 4.0, "end": 5.0},
        {"word": "test", "start": 5.0, "end": 6.0},
        {"word": "of", "start": 6.0, "end": 7.0},
        {"word": "the", "start": 7.0, "end": 8.0},
        {"word": "system", "start": 8.0, "end": 9.0},
        {"word": "now", "start": 9.0, "end": 10.0},
    ]


def _sample_story_beats() -> list[dict]:
    """3 beats: hook (0–3s), main (3–7s), closing (7–10s)."""
    return [
        {"beat_id": 0, "role": "hook", "narration_goal": "grab attention"},
        {"beat_id": 1, "role": "main_claim", "narration_goal": "deliver facts"},
        {"beat_id": 2, "role": "closing_cta", "narration_goal": "call to action"},
    ]


def _sample_manifest_entries() -> list[dict]:
    """4 scenes spanning 0–10s total."""
    return [
        {"scene_index": 0, "start_sec": 0.0, "end_sec": 2.5, "source": "clip_a.mp4"},
        {"scene_index": 1, "start_sec": 2.5, "end_sec": 5.0, "source": "clip_b.mp4"},
        {"scene_index": 2, "start_sec": 5.0, "end_sec": 7.5, "source": "photo_c.jpg"},
        {"scene_index": 3, "start_sec": 7.5, "end_sec": 10.0, "source": "card_d.png"},
    ]


# ---------------------------------------------------------------------------
# build_review_context_bundle
# ---------------------------------------------------------------------------


class TestBuildReviewContextBundleFull:
    """build_review_context_bundle with all fields populated."""

    def test_returns_review_context_bundle_instance(self):
        bundle = build_review_context_bundle(
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
            visual_diagnostics={"visual_coverage": {"status": "pass"}},
            rendered_scene_manifest={"scenes": _sample_manifest_entries()},
            composer_diagnostics={"render_time_sec": 12.5},
            caption="Check this out! #viral",
            thumbnail_path="/tmp/thumb.png",
            package_metadata={"format": "mp4", "size_mb": 5.2},
            audio_duration_sec=10.0,
            video_duration_sec=10.0,
        )
        assert isinstance(bundle, ReviewContextBundle)

    def test_all_fields_populated(self):
        bundle = build_review_context_bundle(
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
            visual_diagnostics={"status": "pass"},
            rendered_scene_manifest={"scenes": []},
            composer_diagnostics={},
            caption="test caption",
            thumbnail_path="/tmp/t.png",
            package_metadata={},
            audio_duration_sec=10.0,
            video_duration_sec=10.0,
        )
        assert len(bundle.story_beats) == 3
        assert len(bundle.word_timestamps) == 10
        assert bundle.visual_diagnostics is not None
        assert bundle.rendered_scene_manifest is not None
        assert bundle.composer_diagnostics is not None
        assert bundle.caption == "test caption"
        assert bundle.thumbnail_path == "/tmp/t.png"
        assert bundle.package_metadata is not None
        assert bundle.audio_duration_sec == 10.0
        assert bundle.video_duration_sec == 10.0


class TestBuildReviewContextBundlePartial:
    """build_review_context_bundle with optional fields as None."""

    def test_minimal_required_fields_only(self):
        bundle = build_review_context_bundle(
            story_beats=[],
            word_timestamps=[],
        )
        assert bundle.story_beats == []
        assert bundle.word_timestamps == []
        assert bundle.visual_diagnostics is None
        assert bundle.rendered_scene_manifest is None
        assert bundle.composer_diagnostics is None
        assert bundle.caption is None
        assert bundle.thumbnail_path is None
        assert bundle.package_metadata is None
        assert bundle.audio_duration_sec == 0.0
        assert bundle.video_duration_sec == 0.0

    def test_partial_data_mixed(self):
        bundle = build_review_context_bundle(
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
            caption="hello",
            audio_duration_sec=10.0,
        )
        assert len(bundle.story_beats) == 3
        assert bundle.caption == "hello"
        assert bundle.visual_diagnostics is None
        assert bundle.video_duration_sec == 0.0

    def test_extra_kwargs_ignored(self):
        """Unknown kwargs are silently ignored (forward-compat)."""
        bundle = build_review_context_bundle(
            story_beats=[],
            word_timestamps=[],
            future_field="something",
        )
        assert isinstance(bundle, ReviewContextBundle)


# ---------------------------------------------------------------------------
# map_scenes_to_beats
# ---------------------------------------------------------------------------


class TestMapScenesToBeatsBasic:
    """Basic scene-to-beat temporal mapping."""

    def test_returns_list_of_scene_beat_mapping(self):
        result = map_scenes_to_beats(
            manifest_entries=_sample_manifest_entries(),
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
        )
        assert isinstance(result, list)
        for mapping in result:
            assert isinstance(mapping, SceneBeatMapping)

    def test_correct_number_of_mappings(self):
        result = map_scenes_to_beats(
            manifest_entries=_sample_manifest_entries(),
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
        )
        assert len(result) == 4  # 4 manifest entries

    def test_each_mapping_has_required_fields(self):
        result = map_scenes_to_beats(
            manifest_entries=_sample_manifest_entries(),
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
        )
        for m in result:
            assert hasattr(m, "scene_index")
            assert hasattr(m, "scene_start_sec")
            assert hasattr(m, "scene_end_sec")
            assert hasattr(m, "matched_beat_ids")
            assert hasattr(m, "overlap_type")


class TestMapScenesToBeatsTemporalOverlap:
    """Temporal overlap logic: scene covers beat midpoint, range overlap."""

    def test_scene_covers_beat_midpoint(self):
        """Scene 0 (0–2.5s) should match beat 0 (words 0.0–3.0s, midpoint ~1.5s)."""
        result = map_scenes_to_beats(
            manifest_entries=[
                {"scene_index": 0, "start_sec": 0.0, "end_sec": 2.5},
            ],
            story_beats=[
                {"beat_id": 0, "role": "hook"},
            ],
            word_timestamps=[
                {"word": "hi", "start": 0.0, "end": 1.0},
                {"word": "there", "start": 1.0, "end": 2.0},
                {"word": "now", "start": 2.0, "end": 3.0},
            ],
        )
        assert len(result) == 1
        assert 0 in result[0].matched_beat_ids

    def test_scene_overlaps_beat_range(self):
        """Scene that overlaps beat range but midpoint is outside still matches."""
        result = map_scenes_to_beats(
            manifest_entries=[
                {"scene_index": 0, "start_sec": 0.0, "end_sec": 2.0},
                {"scene_index": 1, "start_sec": 2.0, "end_sec": 5.0},
            ],
            story_beats=[
                {"beat_id": 0, "role": "hook"},
            ],
            word_timestamps=[
                {"word": "a", "start": 0.0, "end": 1.5},
                {"word": "b", "start": 1.5, "end": 3.0},
                {"word": "c", "start": 3.0, "end": 4.0},
            ],
        )
        # Both scenes should match beat 0 since they overlap beat's word range
        all_matched = set()
        for m in result:
            all_matched.update(m.matched_beat_ids)
        assert 0 in all_matched

    def test_no_overlap_returns_empty_matched_beats(self):
        """Scene entirely outside beat range gets no matches."""
        result = map_scenes_to_beats(
            manifest_entries=[
                {"scene_index": 0, "start_sec": 0.0, "end_sec": 1.0},
            ],
            story_beats=[
                {"beat_id": 0, "role": "hook"},
            ],
            word_timestamps=[
                {"word": "a", "start": 5.0, "end": 6.0},
                {"word": "b", "start": 6.0, "end": 7.0},
            ],
        )
        assert result[0].matched_beat_ids == []
        assert result[0].overlap_type == "none"

    def test_single_scene_covers_all_beats(self):
        """One long scene should match all beats."""
        result = map_scenes_to_beats(
            manifest_entries=[
                {"scene_index": 0, "start_sec": 0.0, "end_sec": 10.0},
            ],
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
        )
        assert len(result) == 1
        assert set(result[0].matched_beat_ids) == {0, 1, 2}


class TestMapScenesToBeatsEdgeCases:
    """Edge cases: empty inputs, no overlap, no timestamps."""

    def test_empty_beats_returns_empty_mappings(self):
        result = map_scenes_to_beats(
            manifest_entries=_sample_manifest_entries(),
            story_beats=[],
            word_timestamps=_sample_word_timestamps(),
        )
        for m in result:
            assert m.matched_beat_ids == []

    def test_empty_manifest_returns_empty_list(self):
        result = map_scenes_to_beats(
            manifest_entries=[],
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
        )
        assert result == []

    def test_empty_word_timestamps_uses_even_distribution(self):
        """Without word timestamps, beats are distributed evenly by audio_duration."""
        result = map_scenes_to_beats(
            manifest_entries=[
                {"scene_index": 0, "start_sec": 0.0, "end_sec": 5.0},
            ],
            story_beats=[
                {"beat_id": 0, "role": "hook"},
                {"beat_id": 1, "role": "closing"},
            ],
            word_timestamps=[],
            audio_duration_sec=10.0,
        )
        assert len(result) == 1
        # Scene 0–5s should match beat 0 (0–5s in even distribution)
        assert 0 in result[0].matched_beat_ids

    def test_manifest_entry_without_scene_index_uses_position(self):
        """If scene_index is missing, use list position."""
        result = map_scenes_to_beats(
            manifest_entries=[
                {"start_sec": 0.0, "end_sec": 5.0},
            ],
            story_beats=[
                {"beat_id": 0, "role": "hook"},
            ],
            word_timestamps=[
                {"word": "hi", "start": 0.0, "end": 2.0},
            ],
        )
        assert result[0].scene_index == 0


# ---------------------------------------------------------------------------
# get_semantic_review_context
# ---------------------------------------------------------------------------


class TestGetSemanticReviewContext:
    """Extract context for a specific scene from the bundle."""

    def _full_bundle(self) -> ReviewContextBundle:
        return build_review_context_bundle(
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
            visual_diagnostics={"visual_coverage": {"status": "pass"}},
            rendered_scene_manifest={"scenes": _sample_manifest_entries()},
            composer_diagnostics={"render_time_sec": 12.5},
            caption="Check this out! #viral",
            thumbnail_path="/tmp/thumb.png",
            package_metadata={"format": "mp4"},
            audio_duration_sec=10.0,
            video_duration_sec=10.0,
        )

    def test_returns_dict(self):
        bundle = self._full_bundle()
        ctx = get_semantic_review_context(bundle, scene_index=0)
        assert isinstance(ctx, dict)

    def test_contains_scene_info(self):
        bundle = self._full_bundle()
        ctx = get_semantic_review_context(bundle, scene_index=1)
        assert "scene_index" in ctx
        assert ctx["scene_index"] == 1

    def test_contains_matched_beats(self):
        bundle = self._full_bundle()
        ctx = get_semantic_review_context(bundle, scene_index=0)
        assert "matched_beats" in ctx
        assert isinstance(ctx["matched_beats"], list)

    def test_contains_word_timestamps_for_range(self):
        bundle = self._full_bundle()
        ctx = get_semantic_review_context(bundle, scene_index=0)
        assert "word_timestamps" in ctx
        # Words in scene 0 range (0–2.5s)
        for wt in ctx["word_timestamps"]:
            assert wt["start"] < 2.5

    def test_contains_visual_diagnostics_when_available(self):
        bundle = self._full_bundle()
        ctx = get_semantic_review_context(bundle, scene_index=0)
        assert "visual_diagnostics" in ctx
        assert ctx["visual_diagnostics"] is not None

    def test_visual_diagnostics_none_when_missing(self):
        bundle = build_review_context_bundle(
            story_beats=_sample_story_beats(),
            word_timestamps=_sample_word_timestamps(),
        )
        ctx = get_semantic_review_context(bundle, scene_index=0)
        assert ctx["visual_diagnostics"] is None

    def test_scene_out_of_range_returns_partial(self):
        """Scene index beyond manifest still returns partial context."""
        bundle = self._full_bundle()
        ctx = get_semantic_review_context(bundle, scene_index=99)
        assert ctx["scene_index"] == 99
        assert ctx.get("scene_start_sec") is None

    def test_empty_bundle_returns_minimal_context(self):
        """Empty bundle returns minimal context without errors."""
        bundle = build_review_context_bundle(
            story_beats=[],
            word_timestamps=[],
        )
        ctx = get_semantic_review_context(bundle, scene_index=0)
        assert isinstance(ctx, dict)
        assert ctx["scene_index"] == 0

    def test_contains_beat_data_for_matched_beats(self):
        """Context includes full beat data for matched beats."""
        bundle = self._full_bundle()
        ctx = get_semantic_review_context(bundle, scene_index=0)
        assert "beat_data" in ctx
        for beat in ctx["beat_data"]:
            assert "beat_id" in beat
            assert "role" in beat
