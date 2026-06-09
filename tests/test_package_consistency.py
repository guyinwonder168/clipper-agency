"""Tests for package consistency evaluator (pure module)."""

from clipper_agency.config.schema import PackageConsistencyResult
from clipper_agency.core.package_consistency import evaluate_package_consistency


class TestPackageConsistencyRoundup:
    """Package scope checks for roundup story mode."""

    def test_fails_thumbnail_single_entity_for_roundup_video(self):
        """Roundup video with single-entity thumbnail should fail."""
        result = evaluate_package_consistency(
            topic="berita artis terbaru hari ini",
            script="Kita bahas tiga kabar artis yang ramai hari ini...",
            thumbnail_text="Ruben Akhirnya Jujur",
            caption="Tiga kabar artis paling ramai hari ini",
            story_mode="roundup",
            main_entities=["Ruben", "Ayu", "Betrand"],
        )
        assert result.status == "fail"
        assert result.issue == "PACKAGE_SCOPE_MISMATCH"

    def test_pass_roundup_with_broad_thumbnail(self):
        """Roundup video with broad-scope thumbnail should pass."""
        result = evaluate_package_consistency(
            topic="berita artis terbaru hari ini",
            script="Kita bahas tiga kabar artis yang ramai hari ini...",
            thumbnail_text="3 Kabar Artis Viral Hari Ini!",
            caption="Tiga kabar artis paling ramai hari ini",
            story_mode="roundup",
            main_entities=["Ruben", "Ayu", "Betrand"],
        )
        assert result.status == "pass"

    def test_pass_roundup_with_two_entities_in_thumbnail(self):
        """Roundup video with 2+ entities in thumbnail should pass."""
        result = evaluate_package_consistency(
            topic="berita artis terbaru",
            script="Dua kabar artis hari ini...",
            thumbnail_text="Ruben dan Ayu Breaking News",
            caption="Kabar artis paling ramai",
            story_mode="roundup",
            main_entities=["Ruben", "Ayu", "Betrand"],
        )
        assert result.status == "pass"


class TestPackageConsistencySingleStory:
    """Package scope checks for single_story mode."""

    def test_pass_single_story_with_focused_thumbnail(self):
        """Single story video with matching entity thumbnail should pass."""
        result = evaluate_package_consistency(
            topic="Ruben Onsu akhirnya jujur",
            script="Ruben Onsu akhirnya bicara jujur tentang...",
            thumbnail_text="Ruben Akhirnya Jujur",
            caption="Ruben Onsu akhirnya jujur tentang semuanya",
            story_mode="single_story",
            main_entities=["Ruben"],
        )
        assert result.status == "pass"

    def test_fail_single_story_with_roundup_caption(self):
        """Single story video with multi-entity caption should fail."""
        result = evaluate_package_consistency(
            topic="Ruben Onsu akhirnya jujur",
            script="Ruben Onsu akhirnya bicara jujur tentang...",
            thumbnail_text="Ruben Akhirnya Jujur",
            caption="Tiga kabar artis paling ramai hari ini",
            story_mode="single_story",
            main_entities=["Ruben"],
        )
        assert result.status == "fail"
        assert result.issue == "PACKAGE_SCOPE_MISMATCH"


class TestPackageConsistencyEdgeCases:
    """Edge cases and backward-compatibility scenarios."""

    def test_pass_when_no_story_mode(self):
        """Missing story_mode should pass (no check possible)."""
        result = evaluate_package_consistency(
            topic="berita artis terbaru",
            script="Kabar artis hari ini...",
            thumbnail_text="Some Thumbnail",
            caption="Some caption",
            story_mode="",
            main_entities=["Ruben", "Ayu", "Betrand"],
        )
        assert result.status == "pass"

    def test_pass_when_no_main_entities(self):
        """Empty main_entities should pass (can't evaluate)."""
        result = evaluate_package_consistency(
            topic="berita artis terbaru",
            script="Kabar artis hari ini...",
            thumbnail_text="Ruben Akhirnya Jujur",
            caption="Caption here",
            story_mode="roundup",
            main_entities=[],
        )
        assert result.status == "pass"

    def test_pass_single_story_without_multi_entity_words(self):
        """Single story with clean caption should pass."""
        result = evaluate_package_consistency(
            topic="Ruben Onsu bicara",
            script="Ruben Onsu bicara tentang...",
            thumbnail_text="Ruben Bicara",
            caption="Ruben Onsu akhirnya bicara jujur #viral",
            story_mode="single_story",
            main_entities=["Ruben"],
        )
        assert result.status == "pass"

    def test_result_is_package_consistency_result(self):
        """Return type should be PackageConsistencyResult."""
        result = evaluate_package_consistency(
            topic="test",
            script="test",
            thumbnail_text="test",
            caption="test",
            story_mode="",
            main_entities=[],
        )
        assert isinstance(result, PackageConsistencyResult)
