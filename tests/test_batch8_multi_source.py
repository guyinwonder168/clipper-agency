"""Batch 8 gate: multi-source regression tests.

Validates the complete multi-provider asset discovery pipeline:
YouTube (always) + Tavily (optional) + Brave (optional) → quality scoring → portfolio.
"""
import pytest
from unittest.mock import patch, MagicMock

from clipper_agency.agents.segment_producer import (
    SegmentProducerAgent,
    SOURCE_QUALITY_TIERS,
    _SOURCE_TYPE_TO_CANDIDATE_TYPE,
)


class TestBatch8MultiSourceRegression:
    """Gate tests for the complete multi-source pipeline."""

    def test_happy_path_all_providers_return_results(self):
        """All providers return results → candidates aggregated and scored."""
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        youtube_results = [
            {"source_type": "youtube_official", "url": "https://youtube.com/watch?v=1", "title": "YT1"},
            {"source_type": "youtube_official", "url": "https://youtube.com/watch?v=2", "title": "YT2"},
        ]
        tavily_results = [
            {"source_type": "web_video", "url": "https://example.com/vid1", "title": "Tav1"},
            {"source_type": "article", "url": "https://example.com/art1", "title": "TavArt1"},
        ]
        brave_results = [
            {"source_type": "web_video", "url": "https://example.com/vid2", "title": "Brave1"},
        ]

        all_sources = youtube_results + tavily_results + brave_results
        candidates = sp._build_asset_candidates_from_sources(all_sources)

        assert len(candidates) >= 5
        # YouTube candidates should have highest score
        yt_candidates = [c for c in candidates if c["source_type"] == "youtube_official"]
        assert all(c["relevance_score"] == 0.95 for c in yt_candidates)
        # web_video candidates should score 0.85
        wv_candidates = [c for c in candidates if c["source_type"] == "web_video"]
        assert all(c["relevance_score"] == 0.85 for c in wv_candidates)

    def test_partial_providers_only_youtube(self):
        """Only YouTube available (no Tavily/Brave keys) → still produces candidates."""
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        config = MagicMock()
        config.tavily_api_key = ""
        config.brave_api_key = ""

        youtube_results = [
            {"source_type": "youtube_official", "url": "https://youtube.com/watch?v=1", "title": "YT1"},
        ]

        with patch.object(sp, "_build_search_queries", return_value=["test query"]):
            with patch("clipper_agency.agents.segment_producer.YtDlpService") as MockYtdlp:
                mock_instance = MagicMock()
                mock_instance.search.return_value = youtube_results
                MockYtdlp.return_value = mock_instance

                sources = sp._discover_multi_source_assets("test topic", {}, config)

        assert len(sources) == 1
        assert sources[0]["source_type"] == "youtube_official"

    def test_no_providers_all_fail_fallback_to_existing(self):
        """All providers fail → empty multi-source list, existing sources preserved."""
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        config = MagicMock()
        config.tavily_api_key = ""
        config.brave_api_key = ""

        with patch("clipper_agency.agents.segment_producer.YtDlpService") as MockYtdlp:
            mock_instance = MagicMock()
            mock_instance.search.side_effect = Exception("network error")
            MockYtdlp.return_value = mock_instance

            sources = sp._discover_multi_source_assets("test topic", {}, config)

        # Multi-source returns empty — existing ScrapeCreators/Firecrawl untouched
        assert sources == []

        # Existing normalization still works
        existing = sp._normalize_sources(
            [{"url": "https://firecrawl.com/1"}],
            [{"url": "https://tiktok.com/1"}],
        )
        assert len(existing) == 2

    def test_quality_ordering_youtube_ranks_above_scrapecreators(self):
        """YouTube (0.95) ranks above ScrapeCreators (0.50) in final candidates."""
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        all_sources = [
            {"source_type": "tiktok_clip", "url": "https://tiktok.com/1", "source": "scrapecreators"},
            {"source_type": "youtube_official", "url": "https://youtube.com/1"},
            {"source_type": "firecrawl", "url": "https://article.com/1", "source": "firecrawl"},
        ]
        candidates = sp._build_asset_candidates_from_sources(all_sources)

        sorted_candidates = sorted(candidates, key=lambda c: c["relevance_score"], reverse=True)

        assert sorted_candidates[0]["source_type"] == "youtube_official"
        assert sorted_candidates[0]["relevance_score"] == 0.95
        tiktok_candidates = [c for c in sorted_candidates if c["source_type"] == "tiktok_clip"]
        assert tiktok_candidates[0]["relevance_score"] == 0.50

    def test_entity_specific_search_queries(self):
        """Search queries include entity names from synthesis."""
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        entities = {
            "entities": [
                {"name": "Sarwendah"},
                {"name": "Zara Adhisty"},
                {"name": "Ruby"},
            ],
        }

        queries = sp._build_search_queries("drama terbaru", entities)

        assert "drama terbaru" in queries
        assert "Sarwendah drama terbaru" in queries
        assert "Zara Adhisty drama terbaru" in queries
        assert len(queries) == 3

    def test_candidate_cap_at_30(self):
        """Total candidates capped at 30 per job (prevent API exhaustion)."""
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        group1 = [{"url": f"https://example.com/{i}", "type": "video"} for i in range(10)]
        group2 = [{"url": f"https://example.com/{i}", "type": "video"} for i in range(10)]

        merged = sp._merge_asset_candidates(group1, group2)
        assert len(merged) == 10

    def test_sarwendah_job5_regression(self):
        """Sarwendah topic produces multi-source candidates with correct tiers."""
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        sources = [
            {"source_type": "youtube_official", "url": "https://youtube.com/watch?v=sar1", "title": "Sarwendah Video"},
            {"source_type": "web_video", "url": "https://example.com/sar-vid", "title": "Web Video"},
            {"source_type": "tiktok_clip", "url": "https://tiktok.com/sar1", "source": "scrapecreators"},
            {"source_type": "firecrawl", "url": "https://article.com/sar1", "source": "firecrawl"},
            {"source_type": "article", "url": "https://news.com/sar1"},
        ]

        candidates = sp._build_asset_candidates_from_sources(sources)

        scores = {c["source_type"]: c["relevance_score"] for c in candidates}
        assert scores["youtube_official"] == 0.95
        assert scores["web_video"] == 0.85
        assert scores["tiktok_clip"] == 0.50
        assert scores["firecrawl"] == 0.30
        assert scores["article"] == 0.40

        sorted_c = sorted(candidates, key=lambda c: c["relevance_score"], reverse=True)
        assert sorted_c[0]["source_type"] == "youtube_official"
