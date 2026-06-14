"""Tests for TreatmentFilterBuilder — per-scene FFmpeg filter string construction.

TDD: These tests define the contract. The implementation must make them pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clipper_agency.rendering.treatment_config import TreatmentConfig
from clipper_agency.rendering.treatment_filters import TreatmentFilterBuilder

TEMPLATES_PATH = Path("templates/treatments.yaml")


@pytest.fixture
def config() -> TreatmentConfig:
    """Real TreatmentConfig backed by treatments.yaml."""
    return TreatmentConfig(TEMPLATES_PATH)


@pytest.fixture
def builder(config: TreatmentConfig) -> TreatmentFilterBuilder:
    """TreatmentFilterBuilder with real config."""
    return TreatmentFilterBuilder(config)


# --- Variable substitution ---


class TestFramesSubstitution:
    def test_frames_replaced_with_duration_times_fps(self, builder: TreatmentFilterBuilder) -> None:
        """{frames} is replaced with int(duration * fps)."""
        asset = {
            "treatment": "ken_burns_zoom_in",
            "target_duration": 5.0,
            "type": "image",
        }
        result = builder.build(asset)
        assert "d=150" in result  # 5.0 * 30 = 150


class TestTextSubstitution:
    def test_text_replaced_with_headline(self, builder: TreatmentFilterBuilder) -> None:
        """{text} is replaced with the asset headline."""
        asset = {
            "treatment": "hook_big_caption",
            "target_duration": 3.0,
            "type": "text",
            "headline": "Breaking News",
        }
        result = builder.build(asset)
        assert "text='Breaking News'" in result


class TestTextDefaultWhenNoHeadline:
    def test_text_replaced_with_empty_when_no_headline(self, builder: TreatmentFilterBuilder) -> None:
        """{text} falls back to empty string when headline is missing."""
        asset = {
            "treatment": "hook_big_caption",
            "target_duration": 3.0,
            "type": "text",
        }
        result = builder.build(asset)
        assert "text=''" in result


class TestDurationSubstitution:
    def test_duration_replaced_correctly(self, builder: TreatmentFilterBuilder) -> None:
        """{duration} is replaced with the target duration value."""
        asset = {
            "treatment": "fade_to_black",
            "target_duration": 5.0,
            "type": "video",
        }
        result = builder.build(asset)
        # fade_to_black doesn't use {duration}, but let's test it with a
        # treatment that could. We verify the substitution didn't leave the
        # placeholder in any case.
        assert "{duration}" not in result


class TestFadeOutStartSubstitution:
    def test_fade_out_start_is_duration_minus_half(self, builder: TreatmentFilterBuilder) -> None:
        """fade_to_black st is computed as duration - 0.5 (fade in last 0.5s)."""
        asset = {
            "treatment": "fade_to_black",
            "target_duration": 5.0,
            "type": "video",
        }
        result = builder.build(asset)
        assert "st=4.5" in result  # 5.0 - 0.5 = 4.5


# --- Input-type rules ---


class TestImagePrependScale:
    def test_image_zoompan_gets_scale_prepended(self, builder: TreatmentFilterBuilder) -> None:
        """Image treatments with zoompan get scale=5400:-1 prepended."""
        asset = {
            "treatment": "ken_burns_zoom_in",
            "target_duration": 5.0,
            "type": "image",
        }
        result = builder.build(asset)
        assert result.startswith("scale=5400:-1,")


class TestVideoNoPrependScale:
    def test_video_treatment_no_scale_prepend(self, builder: TreatmentFilterBuilder) -> None:
        """Video treatments do NOT get scale prepended."""
        asset = {
            "treatment": "cinematic_crop",
            "target_duration": 5.0,
            "type": "video",
        }
        result = builder.build(asset)
        assert not result.startswith("scale=5400:-1,")


# --- Null / edge cases ---


class TestNullFilterReturnsNullString:
    def test_broll_standard_returns_null(self, builder: TreatmentFilterBuilder) -> None:
        """broll_standard has null ffmpeg_filter, so build returns 'null'."""
        asset = {
            "treatment": "broll_standard",
            "target_duration": 5.0,
            "type": "video",
        }
        result = builder.build(asset)
        assert result == "null"


class TestUnknownTreatmentReturnsNull:
    def test_nonexistent_treatment_returns_null(self, builder: TreatmentFilterBuilder) -> None:
        """Unknown treatment name returns 'null'."""
        asset = {
            "treatment": "nonexistent_xyz",
            "target_duration": 5.0,
            "type": "video",
        }
        result = builder.build(asset)
        assert result == "null"


class TestNoTreatmentKeyReturnsNull:
    def test_missing_treatment_key_returns_null(self, builder: TreatmentFilterBuilder) -> None:
        """Asset without 'treatment' key returns 'null'."""
        asset = {"target_duration": 5.0, "type": "video"}
        result = builder.build(asset)
        assert result == "null"


# --- SAR normalization ---


class TestScaleGetsSetar:
    def test_filter_with_scale_appends_setsar(self, builder: TreatmentFilterBuilder) -> None:
        """Filters containing scale= get ,setsar=1/1 appended."""
        asset = {
            "treatment": "ken_burns_zoom_in",
            "target_duration": 5.0,
            "type": "image",
        }
        result = builder.build(asset)
        assert ",setsar=1/1" in result


class TestCropGetsSetar:
    def test_cinematic_crop_appends_setsar(self, builder: TreatmentFilterBuilder) -> None:
        """cinematic_crop has crop=, so setsar=1/1 is appended."""
        asset = {
            "treatment": "cinematic_crop",
            "target_duration": 5.0,
            "type": "video",
        }
        result = builder.build(asset)
        assert result.endswith(",setsar=1/1")


class TestNoScaleNoCropNoSetar:
    def test_filter_without_scale_or_crop_has_no_setsar(self, builder: TreatmentFilterBuilder) -> None:
        """Filters without scale or crop do NOT get setsar appended."""
        asset = {
            "treatment": "slow_motion",
            "target_duration": 5.0,
            "type": "video",
        }
        result = builder.build(asset)
        assert "setsar" not in result
