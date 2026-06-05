"""Tests for subtitle_engine — build_subtitle_overlays, build_hook_overlay, validate_tiktok_output."""

import pytest

from clipper_agency.rendering.contracts import CaptionOverlay
from clipper_agency.rendering.subtitle_engine import (
    build_hook_overlay,
    build_subtitle_overlays,
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
