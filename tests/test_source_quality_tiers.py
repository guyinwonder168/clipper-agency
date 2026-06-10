"""Tests for source quality tiers and refactored asset candidate building."""

import pytest

from clipper_agency.agents.segment_producer import (
    DEFAULT_SOURCE_QUALITY,
    SOURCE_QUALITY_TIERS,
    SegmentProducerAgent,
)


# ---------------------------------------------------------------------------
# Tier lookups
# ---------------------------------------------------------------------------


class TestTierLookup:
    """Verify SOURCE_QUALITY_TIERS maps each known type to the right score."""

    @pytest.mark.parametrize(
        ("source_type", "expected"),
        [
            ("youtube_official", 0.95),
            ("web_video", 0.85),
            ("tiktok_clip", 0.50),
            ("image", 0.70),
            ("article", 0.40),
            ("firecrawl", 0.30),
        ],
    )
    def test_tier_lookup_known_types(self, source_type: str, expected: float) -> None:
        assert SOURCE_QUALITY_TIERS[source_type] == expected

    def test_tier_lookup_unknown_defaults(self) -> None:
        assert SOURCE_QUALITY_TIERS.get("nonexistent", DEFAULT_SOURCE_QUALITY) == 0.40


class TestTierDowngrades:
    """Verify specific scoring changes."""

    def test_scrapecreators_downgrade(self) -> None:
        """TikTok clips score 0.50 (was 0.9) due to watermarks/hardcoded subs."""
        assert SOURCE_QUALITY_TIERS["tiktok_clip"] == 0.50

    def test_firecrawl_score(self) -> None:
        """Firecrawl is the lowest quality tier."""
        assert SOURCE_QUALITY_TIERS["firecrawl"] == 0.30


# ---------------------------------------------------------------------------
# _normalize_sources
# ---------------------------------------------------------------------------


class TestNormalizeSources:
    """Verify _normalize_sources tags legacy sources with source_type."""

    def test_normalize_sources_assigns_source_type(self) -> None:
        agent = SegmentProducerAgent()
        firecrawl = [{"url": "https://news.example/a", "title": "Article"}]
        scrapecreators = [{"url": "https://tiktok.com/@u/video/1", "title": "Clip"}]

        result = agent._normalize_sources(firecrawl, scrapecreators)

        assert len(result) == 2
        # scrapecreators first, then firecrawl
        assert result[0]["source_type"] == "tiktok_clip"
        assert result[0]["url"] == "https://tiktok.com/@u/video/1"
        assert result[1]["source_type"] == "firecrawl"
        assert result[1]["url"] == "https://news.example/a"

    def test_normalize_sources_empty(self) -> None:
        agent = SegmentProducerAgent()
        result = agent._normalize_sources([], [])
        assert result == []


# ---------------------------------------------------------------------------
# _build_asset_candidates_from_sources (refactored)
# ---------------------------------------------------------------------------


class TestBuildCandidatesTiers:
    """Verify refactored method uses tiers for relevance_score."""

    def test_build_candidates_uses_tiers(self) -> None:
        agent = SegmentProducerAgent()
        sources = [
            {"url": "https://youtube.com/watch?v=abc", "source_type": "youtube_official", "title": "Official"},
            {"url": "https://tiktok.com/@u/1", "source_type": "tiktok_clip", "title": "Clip"},
            {"url": "https://news.example/a", "source_type": "firecrawl", "title": "Article"},
            {"url": "https://images.example/pic.jpg", "source_type": "image", "title": "Photo"},
        ]

        candidates = agent._build_asset_candidates_from_sources(sources)

        by_type = {c["source_type"]: c for c in candidates}
        assert by_type["youtube_official"]["relevance_score"] == 0.95
        assert by_type["tiktok_clip"]["relevance_score"] == 0.50
        assert by_type["firecrawl"]["relevance_score"] == 0.30
        assert by_type["image"]["relevance_score"] == 0.70

    def test_build_candidates_unknown_type_gets_default(self) -> None:
        agent = SegmentProducerAgent()
        sources = [
            {"url": "https://example.com/unknown", "source_type": "mystery_source", "title": "Unknown"},
        ]

        candidates = agent._build_asset_candidates_from_sources(sources)

        assert len(candidates) == 1
        assert candidates[0]["relevance_score"] == DEFAULT_SOURCE_QUALITY

    def test_build_candidates_includes_source_type(self) -> None:
        agent = SegmentProducerAgent()
        sources = [
            {"url": "https://tiktok.com/@u/1", "source_type": "tiktok_clip", "title": "Clip"},
        ]

        candidates = agent._build_asset_candidates_from_sources(sources)

        assert candidates[0]["source_type"] == "tiktok_clip"


# ---------------------------------------------------------------------------
# Backward compatibility — legacy calling convention
# ---------------------------------------------------------------------------


class TestBuildCandidatesBackwardCompat:
    """Verify existing callers (keyword args) still get same structure."""

    def test_legacy_keyword_args(self) -> None:
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_candidates_from_sources(
            firecrawl_data=[
                {"title": "Article", "url": "https://news.example/a", "content": "text"},
            ],
            scrapecreators_data=[
                {"title": "Clip", "url": "https://tiktok.com/@u/video/1"},
            ],
        )

        by_source = {c["source"]: c for c in candidates}
        assert "scrapecreators" in by_source or any(
            c.get("source_type") == "tiktok_clip" for c in candidates
        )
        assert "firecrawl" in by_source or any(
            c.get("source_type") == "firecrawl" for c in candidates
        )
        assert all("url" in c for c in candidates)
        assert all("source_type" in c for c in candidates)

    def test_legacy_keyword_args_scores(self) -> None:
        """Legacy callers should see tier-based scores, not old hardcoded ones."""
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_candidates_from_sources(
            firecrawl_data=[
                {"title": "Article", "url": "https://news.example/a"},
            ],
            scrapecreators_data=[
                {"title": "Clip", "url": "https://tiktok.com/@u/video/1"},
            ],
        )

        tiktok = [c for c in candidates if c["source_type"] == "tiktok_clip"][0]
        firecrawl = [c for c in candidates if c["source_type"] == "firecrawl"][0]

        # tiktok_clip downgraded from 0.9 → 0.50
        assert tiktok["relevance_score"] == 0.50
        # firecrawl now 0.30 (was 0.7)
        assert firecrawl["relevance_score"] == 0.30

    def test_legacy_empty_sources(self) -> None:
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_candidates_from_sources(
            firecrawl_data=[], scrapecreators_data=[],
        )
        assert candidates == []

    def test_legacy_positional_empty(self) -> None:
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_candidates_from_sources([], [])
        assert candidates == []
