"""Tests for source cleanliness scoring — determines asset suitability for fullscreen/treatments."""

from clipper_agency.core.source_cleanliness import score_source_cleanliness


class TestCleanSource:
    """Clean source (no issues) returns perfect score and all treatments."""

    def test_clean_source_returns_score_1_and_fullscreen_allowed(self):
        result = score_source_cleanliness()

        assert result["cleanliness_score"] == 1.0
        assert result["fullscreen_allowed"] is True
        assert result["issues"] == []

    def test_clean_source_allows_all_treatments(self):
        result = score_source_cleanliness()

        assert set(result["allowed_treatments"]) == {
            "fullscreen",
            "picture_in_picture",
            "replace_asset",
            "cropped_fullscreen",
            "text_card_fallback",
        }

    def test_default_parameters_produce_clean_result(self):
        """Default parameters (no text, no logo, HD resolution) → clean."""
        result = score_source_cleanliness()

        assert result["cleanliness_score"] == 1.0
        assert result["fullscreen_allowed"] is True


class TestBurnedCaption:
    """High OCR text area ratio triggers BURNED_CAPTION issue."""

    def test_high_ocr_triggers_burned_caption_and_penalizes_fullscreen(self):
        result = score_source_cleanliness(ocr_text_area_ratio=0.25)

        assert "BURNED_CAPTION" in result["issues"]
        assert result["cleanliness_score"] < 1.0
        # Fullscreen is penalized but still allowed for burned captions alone
        assert result["fullscreen_allowed"] is True

    def test_ocr_at_boundary_does_not_trigger(self):
        """Exactly 0.20 does NOT trigger — must exceed threshold."""
        result = score_source_cleanliness(ocr_text_area_ratio=0.20)

        assert "BURNED_CAPTION" not in result["issues"]
        assert result["fullscreen_allowed"] is True

    def test_ocr_just_above_boundary_triggers(self):
        """0.21 exceeds 0.20 threshold — triggers BURNED_CAPTION."""
        result = score_source_cleanliness(ocr_text_area_ratio=0.21)

        assert "BURNED_CAPTION" in result["issues"]


class TestDominantLogo:
    """Logo with > 15% coverage triggers DOMINANT_LOGO and bans fullscreen."""

    def test_dominant_logo_bans_fullscreen(self):
        result = score_source_cleanliness(
            has_logo=True,
            logo_coverage_ratio=0.20,
        )

        assert "DOMINANT_LOGO" in result["issues"]
        assert result["fullscreen_allowed"] is False
        assert result["cleanliness_score"] < 1.0

    def test_dominant_logo_at_boundary_does_not_trigger(self):
        """Exactly 0.15 coverage is not dominant — MINOR_LOGO instead."""
        result = score_source_cleanliness(
            has_logo=True,
            logo_coverage_ratio=0.15,
        )

        assert "DOMINANT_LOGO" not in result["issues"]


class TestMinorLogo:
    """Logo with ≤ 15% coverage triggers MINOR_LOGO."""

    def test_minor_logo_with_safe_crop_allows_cropped_fullscreen(self):
        result = score_source_cleanliness(
            has_logo=True,
            logo_coverage_ratio=0.05,
            safe_crop_available=True,
        )

        assert "MINOR_LOGO" in result["issues"]
        assert "cropped_fullscreen" in result["allowed_treatments"]
        # Fullscreen allowed with crop
        assert result["fullscreen_allowed"] is True

    def test_minor_logo_without_safe_crop_bans_fullscreen(self):
        result = score_source_cleanliness(
            has_logo=True,
            logo_coverage_ratio=0.10,
            safe_crop_available=False,
        )

        assert "MINOR_LOGO" in result["issues"]
        assert result["fullscreen_allowed"] is False

    def test_minor_logo_without_safe_crop_no_cropped_fullscreen(self):
        result = score_source_cleanliness(
            has_logo=True,
            logo_coverage_ratio=0.10,
            safe_crop_available=False,
        )

        assert "cropped_fullscreen" not in result["allowed_treatments"]


class TestFaceObstruction:
    """Face obstruction triggers FACE_OBSTRUCTION issue."""

    def test_face_obstruction_triggers_issue(self):
        result = score_source_cleanliness(face_obstructed=True)

        assert "FACE_OBSTRUCTION" in result["issues"]
        assert result["cleanliness_score"] < 1.0

    def test_face_obstruction_avoids_fullscreen(self):
        result = score_source_cleanliness(face_obstructed=True)

        assert result["fullscreen_allowed"] is False


class TestLowResolution:
    """Resolution below 720p triggers LOW_RESOLUTION."""

    def test_low_resolution_triggers_issue(self):
        result = score_source_cleanliness(resolution=(640, 480))

        assert "LOW_RESOLUTION" in result["issues"]
        assert result["cleanliness_score"] < 1.0

    def test_low_resolution_still_allows_fullscreen(self):
        """Low resolution penalizes score but does not ban fullscreen."""
        result = score_source_cleanliness(resolution=(640, 480))

        assert result["fullscreen_allowed"] is True

    def test_resolution_at_720p_threshold_does_not_trigger(self):
        """(1280, 720) is the minimum acceptable — no LOW_RESOLUTION."""
        result = score_source_cleanliness(resolution=(1280, 720))

        assert "LOW_RESOLUTION" not in result["issues"]

    def test_resolution_below_720p_height_triggers(self):
        """Any height below 720 triggers LOW_RESOLUTION."""
        result = score_source_cleanliness(resolution=(1280, 719))

        assert "LOW_RESOLUTION" in result["issues"]

    def test_resolution_below_720p_width_triggers(self):
        """Any width below 1280 triggers LOW_RESOLUTION."""
        result = score_source_cleanliness(resolution=(1279, 720))

        assert "LOW_RESOLUTION" in result["issues"]


class TestMultipleIssues:
    """Multiple issues accumulate and drive score lower than a single issue."""

    def test_multiple_issues_drive_score_lower_than_single(self):
        single = score_source_cleanliness(ocr_text_area_ratio=0.25)

        multi = score_source_cleanliness(
            ocr_text_area_ratio=0.25,
            has_logo=True,
            logo_coverage_ratio=0.20,
            resolution=(640, 480),
        )

        assert len(multi["issues"]) > len(single["issues"])
        assert multi["cleanliness_score"] < single["cleanliness_score"]

    def test_multiple_issues_report_all_issue_codes(self):
        result = score_source_cleanliness(
            ocr_text_area_ratio=0.30,
            has_logo=True,
            logo_coverage_ratio=0.25,
            face_obstructed=True,
            resolution=(320, 240),
        )

        expected_issues = {
            "BURNED_CAPTION",
            "DOMINANT_LOGO",
            "FACE_OBSTRUCTION",
            "LOW_RESOLUTION",
        }
        assert set(result["issues"]) == expected_issues


class TestScoreBounds:
    """Cleanliness score is always in the range [0.0, 1.0]."""

    def test_score_never_exceeds_one(self):
        result = score_source_cleanliness()
        assert result["cleanliness_score"] <= 1.0

    def test_score_never_below_zero(self):
        result = score_source_cleanliness(
            ocr_text_area_ratio=0.50,
            has_logo=True,
            logo_coverage_ratio=0.80,
            face_obstructed=True,
            resolution=(160, 120),
        )
        assert result["cleanliness_score"] >= 0.0


class TestReplaceAssetGuarantee:
    """replace_asset is always available when fullscreen is banned."""

    def test_replace_asset_present_when_fullscreen_banned_by_dominant_logo(self):
        result = score_source_cleanliness(
            has_logo=True,
            logo_coverage_ratio=0.20,
        )

        assert result["fullscreen_allowed"] is False
        assert "replace_asset" in result["allowed_treatments"]

    def test_replace_asset_present_when_fullscreen_banned_by_face_obstruction(self):
        result = score_source_cleanliness(face_obstructed=True)

        assert result["fullscreen_allowed"] is False
        assert "replace_asset" in result["allowed_treatments"]

    def test_replace_asset_present_when_fullscreen_banned_by_minor_logo(self):
        result = score_source_cleanliness(
            has_logo=True,
            logo_coverage_ratio=0.10,
            safe_crop_available=False,
        )

        assert result["fullscreen_allowed"] is False
        assert "replace_asset" in result["allowed_treatments"]


class TestOutputSchema:
    """Output dict contains all required keys."""

    REQUIRED_KEYS = {
        "cleanliness_score",
        "issues",
        "fullscreen_allowed",
        "allowed_treatments",
    }

    def test_output_contains_all_required_keys(self):
        result = score_source_cleanliness()
        assert set(result.keys()) == self.REQUIRED_KEYS

    def test_issues_is_list(self):
        result = score_source_cleanliness(ocr_text_area_ratio=0.25)
        assert isinstance(result["issues"], list)

    def test_allowed_treatments_is_list(self):
        result = score_source_cleanliness()
        assert isinstance(result["allowed_treatments"], list)

    def test_cleanliness_score_is_float(self):
        result = score_source_cleanliness()
        assert isinstance(result["cleanliness_score"], float)

    def test_fullscreen_allowed_is_bool(self):
        result = score_source_cleanliness()
        assert isinstance(result["fullscreen_allowed"], bool)
