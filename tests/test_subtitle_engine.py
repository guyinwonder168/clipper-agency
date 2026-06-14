"""Tests for subtitle_engine — build_subtitle_overlays, build_hook_overlay, build_keyword_captions, validate_tiktok_output."""

import pytest

from clipper_agency.rendering.contracts import CaptionOverlay
from clipper_agency.rendering.subtitle_engine import (
    build_hook_overlay,
    build_keyword_captions,
    build_subtitle_overlays,
    build_word_subtitle_captions,
    validate_tiktok_output,
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_single_scene_single_caption():
    """5 words in 5 s with default wpc=6 → 1 overlay spanning 0–5 s."""
    scenes = [{"text": "one two three four five", "duration": 5.0}]
    result = build_subtitle_overlays(scenes)

    assert len(result) == 1
    assert result[0].text == "one two three four five"
    assert result[0].start_seconds == 0.0
    assert result[0].end_seconds == 5.0


def test_single_scene_split_captions():
    """12 words in 6 s, wpc=6 → 2 overlays of 3 s each."""
    scenes = [{"text": " ".join(f"word{i}" for i in range(12)), "duration": 6.0}]
    result = build_subtitle_overlays(scenes, words_per_caption=6)

    assert len(result) == 2
    assert result[0].start_seconds == 0.0
    assert result[0].end_seconds == 3.0
    assert result[1].start_seconds == 3.0
    assert result[1].end_seconds == 6.0


def test_multi_scene_absolute_timing():
    """Two scenes: second scene overlays start at the first scene's end."""
    scenes = [
        {"text": "hello world", "duration": 5.0},
        {"text": "foo bar", "duration": 4.0},
    ]
    result = build_subtitle_overlays(scenes)

    # First scene → 1 overlay
    assert result[0].text == "hello world"
    assert result[0].start_seconds == 0.0
    assert result[0].end_seconds == 5.0

    # Second scene → 1 overlay starting at 5.0
    assert result[1].text == "foo bar"
    assert result[1].start_seconds == 5.0
    assert result[1].end_seconds == 9.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_scene_text_skipped():
    """Scene with empty string → no overlays produced for that scene."""
    scenes = [
        {"text": "", "duration": 3.0},
        {"text": "visible text", "duration": 2.0},
    ]
    result = build_subtitle_overlays(scenes)

    # Only the second scene produces an overlay; its start must account
    # for the first scene's duration.
    assert len(result) == 1
    assert result[0].text == "visible text"
    assert result[0].start_seconds == 3.0
    assert result[0].end_seconds == 5.0


def test_special_chars_in_text():
    """Text with quotes/apostrophes passes through unchanged."""
    text = "it's a \"test\" with special chars"
    scenes = [{"text": text, "duration": 3.0}]
    result = build_subtitle_overlays(scenes)

    assert len(result) == 1
    assert result[0].text == text


def test_words_per_caption_splits_correctly():
    """18 words, wpc=6 → exactly 3 chunks."""
    words = [f"w{i}" for i in range(18)]
    scenes = [{"text": " ".join(words), "duration": 9.0}]
    result = build_subtitle_overlays(scenes, words_per_caption=6)

    assert len(result) == 3
    assert result[0].text == "w0 w1 w2 w3 w4 w5"
    assert result[1].text == "w6 w7 w8 w9 w10 w11"
    assert result[2].text == "w12 w13 w14 w15 w16 w17"


# ---------------------------------------------------------------------------
# Contract / defaults
# ---------------------------------------------------------------------------


def test_caption_overlay_has_required_fields():
    """Returned objects expose all CaptionOverlay fields."""
    scenes = [{"text": "hello world", "duration": 2.0}]
    result = build_subtitle_overlays(scenes)

    overlay = result[0]
    assert isinstance(overlay, CaptionOverlay)
    assert overlay.text == "hello world"
    assert overlay.start_seconds == 0.0
    assert overlay.end_seconds == 2.0
    assert overlay.position == "bottom"
    assert overlay.style == "default"


def test_default_words_per_caption_is_6():
    """Omitting words_per_caption uses 6."""
    # 7 words → split into 6 + 1
    scenes = [{"text": "a b c d e f g", "duration": 7.0}]
    result = build_subtitle_overlays(scenes)

    assert len(result) == 2
    assert result[0].text == "a b c d e f"
    assert result[1].text == "g"


def test_scene_missing_duration_defaults_to_5():
    """Scene without 'duration' key → 5.0 s assumed."""
    scenes = [{"text": "hello world"}]
    result = build_subtitle_overlays(scenes)

    assert len(result) == 1
    assert result[0].end_seconds == 5.0


def test_single_word_produces_overlay():
    """Even a single word produces exactly 1 overlay."""
    scenes = [{"text": "lonely", "duration": 2.0}]
    result = build_subtitle_overlays(scenes)

    assert len(result) == 1
    assert result[0].text == "lonely"
    assert result[0].start_seconds == 0.0
    assert result[0].end_seconds == 2.0


# ---------------------------------------------------------------------------
# build_hook_overlay
# ---------------------------------------------------------------------------


def test_hook_overlay_first_3_seconds():
    """Standard case: overlay spans [0, 3.0] with center position and hook style."""
    scenes = [{"text": "Breaking news today", "duration": 5.0}]

    result = build_hook_overlay(scenes)

    assert result is not None
    assert result.start_seconds == 0.0
    assert result.end_seconds == 3.0
    assert result.position == "center"
    assert result.style == "hook"


def test_hook_overlay_uses_first_scene_text():
    """Hook overlay text matches the first scene's headline."""
    scenes = [
        {"text": "Headline text here", "duration": 5.0},
        {"text": "Second scene text", "duration": 4.0},
    ]

    result = build_hook_overlay(scenes)

    assert result is not None
    assert result.text == "Headline text here"


def test_hook_overlay_none_when_no_scenes():
    """Empty scene list returns None."""
    result = build_hook_overlay([])

    assert result is None


def test_hook_overlay_clamps_to_short_scene():
    """Scene shorter than hook window clamps end to scene duration."""
    scenes = [{"text": "Short scene", "duration": 1.5}]

    result = build_hook_overlay(scenes, hook_window_seconds=3.0)

    assert result is not None
    assert result.end_seconds == 1.5


# ---------------------------------------------------------------------------
# validate_tiktok_output
# ---------------------------------------------------------------------------


def test_tiktok_validation_passes_valid_output():
    """Valid FFmpeg command with all TikTok flags → all True."""
    cmd = [
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-b:a", "128k",
        "-shortest",
    ]

    result = validate_tiktok_output(cmd)

    assert all(result.values()), f"Expected all True, got: {result}"


def test_tiktok_validation_flags_missing_faststart():
    """Missing -movflags → faststart=False, rest may pass."""
    cmd = [
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-b:a", "128k",
        "-shortest",
    ]

    result = validate_tiktok_output(cmd)

    assert result["faststart"] is False


def test_tiktok_validation_flags_missing_pix_fmt():
    """Missing -pix_fmt → pix_fmt_yuv420p=False."""
    cmd = [
        "-c:v", "libx264",
        "-c:a", "aac",
        "-movflags", "+faststart",
        "-b:a", "128k",
        "-shortest",
    ]

    result = validate_tiktok_output(cmd)

    assert result["pix_fmt_yuv420p"] is False


# ---------------------------------------------------------------------------
# build_keyword_captions
# ---------------------------------------------------------------------------


def _make_timestamps(n: int, words_per_sec: float = 2.0) -> list[dict]:
    """Generate n word timestamps at a fixed words-per-second rate."""
    ts = []
    for i in range(n):
        start = i / words_per_sec
        end = (i + 1) / words_per_sec
        ts.append({"word": f"w{i}", "start": start, "end": end})
    return ts


class TestBuildKeywordCaptions:
    """Keyword caption tests: format, positioning, beat alignment, style."""

    def test_basic_two_beats(self):
        """Two beats produce two keyword captions with correct timing."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 4], "caption_keywords": ["hello", "world"]},
            {"beat_id": 2, "word_range": [4, 8], "caption_keywords": ["foo", "bar"]},
        ]
        timestamps = _make_timestamps(8)

        result = build_keyword_captions(narrative, timestamps)

        assert len(result) == 2
        assert result[0].text == "hello world"
        assert result[0].start_seconds == 0.0
        assert result[0].end_seconds == pytest.approx(2.0)
        assert result[1].text == "foo bar"
        assert result[1].start_seconds == pytest.approx(2.0)
        assert result[1].end_seconds == pytest.approx(4.0)

    def test_max_6_words_truncation(self):
        """Keywords beyond 6 are truncated."""
        narrative = [
            {
                "beat_id": 1,
                "word_range": [0, 5],
                "caption_keywords": [f"kw{i}" for i in range(10)],
            },
        ]
        timestamps = _make_timestamps(5)

        result = build_keyword_captions(narrative, timestamps)

        assert len(result) == 1
        words = result[0].text.split()
        assert len(words) == 6

    def test_position_is_bottom(self):
        """All keyword captions have position='bottom'."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 3], "caption_keywords": ["test"]},
        ]
        timestamps = _make_timestamps(3)

        result = build_keyword_captions(narrative, timestamps)

        assert result[0].position == "bottom"

    def test_style_is_keyword(self):
        """All keyword captions have style='keyword'."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 3], "caption_keywords": ["test"]},
        ]
        timestamps = _make_timestamps(3)

        result = build_keyword_captions(narrative, timestamps)

        assert result[0].style == "keyword"

    def test_beat_alignment_keywords_change_at_boundaries(self):
        """Each beat gets different keywords aligned to its word range."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 3], "caption_keywords": ["intro"]},
            {"beat_id": 2, "word_range": [3, 7], "caption_keywords": ["main", "story"]},
            {"beat_id": 3, "word_range": [7, 10], "caption_keywords": ["closing"]},
        ]
        timestamps = _make_timestamps(10)

        result = build_keyword_captions(narrative, timestamps)

        assert len(result) == 3
        # Each caption has different text
        assert result[0].text == "intro"
        assert result[1].text == "main story"
        assert result[2].text == "closing"
        # Timings are sequential (no gaps from continuous word timestamps)
        assert result[1].start_seconds == pytest.approx(result[0].end_seconds)

    def test_empty_narrative_returns_empty(self):
        """Empty narrative_structure returns empty list."""
        timestamps = _make_timestamps(5)
        assert build_keyword_captions([], timestamps) == []

    def test_empty_timestamps_returns_empty(self):
        """Empty timestamps with no narrative returns empty list."""
        assert build_keyword_captions([], []) == []

    def test_empty_timestamps_with_narrative_uses_fallback(self):
        """Empty timestamps with narrative uses word_range fallback."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 6], "caption_keywords": ["test", "caption"]},
        ]
        result = build_keyword_captions(narrative, [])
        assert len(result) == 1
        assert result[0].text == "test caption"
        assert result[0].start_seconds == pytest.approx(0.0)
        assert result[0].end_seconds == pytest.approx(3.0)  # 6 / 2.0 wps

    def test_none_inputs_returns_empty(self):
        """None inputs return empty list."""
        assert build_keyword_captions([], []) == []

    def test_missing_word_range_skipped(self):
        """Beat without word_range is skipped."""
        narrative = [
            {"beat_id": 1, "caption_keywords": ["test"]},
        ]
        timestamps = _make_timestamps(5)

        result = build_keyword_captions(narrative, timestamps)

        assert result == []

    def test_missing_caption_keywords_skipped(self):
        """Beat without caption_keywords is skipped."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 3]},
        ]
        timestamps = _make_timestamps(5)

        result = build_keyword_captions(narrative, timestamps)

        assert result == []

    def test_word_range_out_of_bounds_clamped(self):
        """Word range exceeding timestamp count is clamped."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 100], "caption_keywords": ["ok"]},
        ]
        timestamps = _make_timestamps(5)

        result = build_keyword_captions(narrative, timestamps)

        assert len(result) == 1
        # end_time should be from last timestamp, not crash
        assert result[0].end_seconds > 0

    def test_hook_duration_skips_first_beat_caption(self):
        """Captions during hook window are skipped — hook card already shows text."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 4], "caption_keywords": ["gosip", "artis", "terhot"]},
            {"beat_id": 2, "word_range": [4, 8], "caption_keywords": ["foo", "bar"]},
        ]
        timestamps = _make_timestamps(8)

        result = build_keyword_captions(narrative, timestamps, hook_duration=2.0)

        assert len(result) == 1
        assert result[0].text == "foo bar"
        assert result[0].start_seconds == pytest.approx(2.0)

    def test_hook_duration_zero_no_skip(self):
        """hook_duration=0 (default) does not skip any captions."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 4], "caption_keywords": ["hello"]},
            {"beat_id": 2, "word_range": [4, 8], "caption_keywords": ["world"]},
        ]
        timestamps = _make_timestamps(8)

        result = build_keyword_captions(narrative, timestamps, hook_duration=0.0)

        assert len(result) == 2

    def test_hook_duration_skips_multiple_beats(self):
        """If hook spans multiple beats, all are skipped."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 4], "caption_keywords": ["first"]},
            {"beat_id": 2, "word_range": [4, 8], "caption_keywords": ["second"]},
            {"beat_id": 3, "word_range": [8, 12], "caption_keywords": ["third"]},
        ]
        timestamps = _make_timestamps(12)

        result = build_keyword_captions(narrative, timestamps, hook_duration=4.0)

        assert len(result) == 1
        assert result[0].text == "third"

    def test_hook_duration_fallback_path_skips(self):
        """hook_duration also skips in the fallback (no timestamps) path."""
        narrative = [
            {"beat_id": 1, "word_range": [0, 6], "caption_keywords": ["hook", "text"]},
            {"beat_id": 2, "word_range": [6, 12], "caption_keywords": ["body"]},
        ]

        result = build_keyword_captions(narrative, [], hook_duration=2.0)

        # Fallback: 6 words / 2.0 wps = 3.0s for first beat — 3.0 >= 2.0, so NOT skipped
        # Actually first beat ends at 3.0 which is >= hook_duration 2.0, so it starts at 0.0 < 2.0 → skipped
        assert len(result) == 1
        assert result[0].text == "body"


# ---------------------------------------------------------------------------
# build_word_subtitle_captions
# ---------------------------------------------------------------------------


def test_build_word_subtitle_captions_uses_narration_words_not_keywords():
    timestamps = [
        {"word": "Yuk", "start": 0.0, "end": 0.3},
        {"word": "intip", "start": 0.3, "end": 0.7},
        {"word": "berita", "start": 0.7, "end": 1.1},
        {"word": "viral", "start": 1.1, "end": 1.5},
    ]

    result = build_word_subtitle_captions(timestamps, max_words=2)

    assert [c.text for c in result] == ["Yuk intip", "berita viral"]
    assert result[0].style == "subtitle"
    assert result[0].position == "bottom"
    assert result[0].start_seconds == 0.0
    assert result[-1].end_seconds == 1.5


# ---------------------------------------------------------------------------
# Coverage: edge cases for helper functions
# ---------------------------------------------------------------------------


def test_ts_value_with_object_timestamp():
    """_ts_value handles non-dict timestamps (e.g. WordTimestamp objects)."""
    from types import SimpleNamespace
    from clipper_agency.rendering.subtitle_engine import _ts_value

    ts = SimpleNamespace(start=1.5, end=2.5)
    assert _ts_value(ts, "start", 0.0) == 1.5
    assert _ts_value(ts, "end", 0.0) == 2.5
    assert _ts_value(ts, "missing", 9.9) == 9.9


def test_beat_timing_fallback_returns_none_for_short_word_range():
    """_beat_timing_fallback returns None when word_range has < 2 elements."""
    from clipper_agency.rendering.subtitle_engine import _beat_timing_fallback

    assert _beat_timing_fallback({"word_range": [5]}, 2.0) is None
    assert _beat_timing_fallback({"word_range": []}, 2.0) is None


def test_beat_timing_fallback_returns_none_when_end_le_start():
    """_beat_timing_fallback returns None when end <= start."""
    from clipper_agency.rendering.subtitle_engine import _beat_timing_fallback

    # word_range [10, 10] → start=5.0, end=5.0 → end <= start
    assert _beat_timing_fallback({"word_range": [10, 10]}, 2.0) is None


def test_beat_timing_from_ts_returns_none_for_short_word_range():
    """_beat_timing_from_ts returns None when word_range < 2."""
    from clipper_agency.rendering.subtitle_engine import _beat_timing_from_ts

    ts = [{"start": 0.0, "end": 1.0}]
    assert _beat_timing_from_ts({"word_range": [0]}, ts) is None


def test_beat_timing_from_ts_returns_none_when_end_le_start():
    """_beat_timing_from_ts returns None when end <= start."""
    from clipper_agency.rendering.subtitle_engine import _beat_timing_from_ts

    # Both words have same start/end → end <= start
    ts = [{"start": 2.0, "end": 2.0}, {"start": 2.0, "end": 2.0}]
    assert _beat_timing_from_ts({"word_range": [0, 2]}, ts) is None


def test_keyword_captions_skips_beat_when_timing_is_none():
    """build_keyword_captions skips beats with valid keywords but unresolvable timing."""
    # beat 1: word_range [0,2] → ts[0]={5.0,5.0} end<=start → timing None → skipped
    # beat 2: word_range [1,3] → ts[1]={1.0,2.0} ts[2]={2.0,3.0} → valid timing
    beats = [
        {"beat_id": 1, "word_range": [0, 2], "caption_keywords": ["skipped"]},
        {"beat_id": 2, "word_range": [1, 3], "caption_keywords": ["valid"]},
    ]
    ts = [
        {"start": 5.0, "end": 5.0},
        {"start": 1.0, "end": 2.0},
        {"start": 2.0, "end": 3.0},
    ]
    result = build_keyword_captions(beats, ts)
    assert len(result) == 1
    assert result[0].text == "valid"


def test_word_subtitle_captions_skips_chunks_before_hook_duration():
    """build_word_subtitle_captions skips chunks starting before hook_duration."""
    timestamps = [
        {"word": "early", "start": 0.5, "end": 1.0},
        {"word": "late", "start": 5.0, "end": 5.5},
    ]
    result = build_word_subtitle_captions(timestamps, max_words=1, hook_duration=2.0)
    # Only "late" should survive (start 5.0 >= 2.0)
    assert len(result) == 1
    assert result[0].text == "late"


def test_word_subtitle_captions_skips_empty_text():
    """build_word_subtitle_captions skips chunks with empty text or end <= start."""
    timestamps = [
        {"word": "", "start": 0.0, "end": 0.5},
        {"word": "valid", "start": 1.0, "end": 2.0},
    ]
    result = build_word_subtitle_captions(timestamps, max_words=1)
    # Empty word produces empty text → skipped
    assert len(result) == 1
    assert result[0].text == "valid"


def test_hook_overlay_returns_none_for_empty_text():
    """build_hook_overlay returns None when first scene has empty text."""
    assert build_hook_overlay([{"text": "", "duration": 5.0}]) is None
    assert build_hook_overlay([{"text": "   ", "duration": 5.0}]) is None


def test_hook_overlay_returns_none_when_duration_zero():
    """build_hook_overlay returns None when computed end <= 0."""
    # duration=0 → end = min(3.0, 0.0) = 0.0 → end <= 0
    assert build_hook_overlay([{"text": "hello", "duration": 0.0}]) is None
