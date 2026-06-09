"""Unit tests for clipper_agency.core.safe_area — safe-area and face overlap geometry checks."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helper: import target inside each test so the RED phase fails cleanly
# when the module does not exist yet.
# ---------------------------------------------------------------------------


class TestTiktokUnsafeZones:
    """Tests for tiktok_unsafe_zones() helper."""

    def test_returns_top_and_bottom_zones(self):
        from clipper_agency.core.safe_area import tiktok_unsafe_zones

        zones = tiktok_unsafe_zones((1080, 1920))
        labels = {z["label"] for z in zones}
        assert "top_interaction" in labels
        assert "bottom_caption" in labels

    def test_top_zone_is_upper_portion(self):
        from clipper_agency.core.safe_area import tiktok_unsafe_zones

        zones = tiktok_unsafe_zones((1080, 1920))
        top = next(z for z in zones if z["label"] == "top_interaction")
        bbox = top["bbox"]
        # Must start at y=0 and cover roughly top 8% (<= 154px for 1920)
        assert bbox[1] == 0
        assert bbox[3] <= 200  # reasonable upper bound

    def test_bottom_zone_is_lower_portion(self):
        from clipper_agency.core.safe_area import tiktok_unsafe_zones

        zones = tiktok_unsafe_zones((1080, 1920))
        bottom = next(z for z in zones if z["label"] == "bottom_caption")
        bbox = bottom["bbox"]
        # Must end at frame height and start roughly bottom 21% (<= 404px from bottom)
        assert bbox[3] == 1920
        assert bbox[1] >= 1500  # starts in lower portion


class TestDetectSafeAreaIssues:
    """Tests for detect_safe_area_issues()."""

    # -- Happy path: no issues ------------------------------------------

    def test_no_issues_when_caption_in_safe_area_no_face_overlap(self):
        from clipper_agency.core.safe_area import detect_safe_area_issues

        issues = detect_safe_area_issues(
            generated_regions=[{"bbox": [100, 500, 980, 600], "layer": "subtitle"}],
            face_regions=[],
            frame_size=(1080, 1920),
            platform="tiktok",
            face_overlap_max=0.15,
        )
        assert issues == []

    # -- Platform unsafe zone checks -------------------------------------

    def test_caption_inside_tiktok_bottom_unsafe_zone_is_rejected(self):
        """Caption in bottom 400px should trigger PLATFORM_UNSAFE_ZONE."""
        from clipper_agency.core.safe_area import detect_safe_area_issues

        issues = detect_safe_area_issues(
            generated_regions=[{"bbox": [760, 1500, 1080, 1900], "layer": "subtitle"}],
            face_regions=[],
            frame_size=(1080, 1920),
            platform="tiktok",
            face_overlap_max=0.15,
        )

        assert len(issues) >= 1
        assert issues[0].type == "PLATFORM_UNSAFE_ZONE"

    def test_caption_inside_tiktok_top_unsafe_zone_is_rejected(self):
        """Caption in top 150px should trigger PLATFORM_UNSAFE_ZONE."""
        from clipper_agency.core.safe_area import detect_safe_area_issues

        issues = detect_safe_area_issues(
            generated_regions=[{"bbox": [100, 10, 500, 100], "layer": "headline"}],
            face_regions=[],
            frame_size=(1080, 1920),
            platform="tiktok",
            face_overlap_max=0.15,
        )

        assert len(issues) >= 1
        assert issues[0].type == "PLATFORM_UNSAFE_ZONE"

    def test_non_tiktok_platform_skips_unsafe_zone_check(self):
        """Non-TikTok platforms should not trigger unsafe zone issues."""
        from clipper_agency.core.safe_area import detect_safe_area_issues

        issues = detect_safe_area_issues(
            generated_regions=[{"bbox": [760, 1500, 1080, 1900], "layer": "subtitle"}],
            face_regions=[],
            frame_size=(1080, 1920),
            platform="youtube",
            face_overlap_max=0.15,
        )
        # Same caption position that would fail on TikTok — should pass on YouTube
        assert issues == []

    # -- Face overlap checks ---------------------------------------------

    def test_caption_overlapping_face_above_threshold_is_rejected(self):
        """Large overlap between caption and face → FACE_TEXT_OVERLAP."""
        from clipper_agency.core.safe_area import detect_safe_area_issues

        issues = detect_safe_area_issues(
            generated_regions=[{"bbox": [400, 300, 700, 650], "layer": "headline"}],
            face_regions=[{"bbox": [420, 320, 680, 640], "confidence": 0.9}],
            frame_size=(1080, 1920),
            platform="tiktok",
            face_overlap_max=0.15,
        )

        assert len(issues) >= 1
        face_issues = [i for i in issues if i.type == "FACE_TEXT_OVERLAP"]
        assert len(face_issues) >= 1

    def test_face_region_with_no_overlap_no_issue(self):
        """Face far from caption → no FACE_TEXT_OVERLAP issue."""
        from clipper_agency.core.safe_area import detect_safe_area_issues

        issues = detect_safe_area_issues(
            generated_regions=[{"bbox": [100, 500, 980, 600], "layer": "subtitle"}],
            face_regions=[{"bbox": [400, 200, 600, 400], "confidence": 0.95}],
            frame_size=(1080, 1920),
            platform="tiktok",
            face_overlap_max=0.15,
        )
        face_issues = [i for i in issues if i.type == "FACE_TEXT_OVERLAP"]
        assert face_issues == []

    def test_slight_face_overlap_below_threshold_no_issue(self):
        """Overlap ratio below face_overlap_max → no issue."""
        from clipper_agency.core.safe_area import detect_safe_area_issues

        # Caption and face barely touch at edge — overlap ratio should be tiny
        issues = detect_safe_area_issues(
            generated_regions=[{"bbox": [100, 500, 400, 600], "layer": "subtitle"}],
            face_regions=[{"bbox": [390, 500, 700, 700], "confidence": 0.9}],
            frame_size=(1080, 1920),
            platform="tiktok",
            face_overlap_max=0.15,
        )
        face_issues = [i for i in issues if i.type == "FACE_TEXT_OVERLAP"]
        assert face_issues == []

    # -- Edge cases -------------------------------------------------------

    def test_empty_generated_regions_returns_empty(self):
        from clipper_agency.core.safe_area import detect_safe_area_issues

        issues = detect_safe_area_issues(
            generated_regions=[],
            face_regions=[{"bbox": [400, 300, 700, 650], "confidence": 0.9}],
            frame_size=(1080, 1920),
            platform="tiktok",
            face_overlap_max=0.15,
        )
        assert issues == []

    def test_no_face_regions_no_face_overlap_issues(self):
        from clipper_agency.core.safe_area import detect_safe_area_issues

        issues = detect_safe_area_issues(
            generated_regions=[{"bbox": [100, 500, 980, 600], "layer": "subtitle"}],
            face_regions=[],
            frame_size=(1080, 1920),
            platform="tiktok",
            face_overlap_max=0.15,
        )
        face_issues = [i for i in issues if i.type == "FACE_TEXT_OVERLAP"]
        assert face_issues == []
