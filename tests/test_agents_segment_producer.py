"""Tests for SegmentProducerAgent."""

import json
from unittest.mock import MagicMock
import pytest

from clipper_agency.agents.segment_producer import (
    SEGMENT_PRODUCER_PROMPT,
    SegmentProducerAgent,
)


class TestSegmentProducerName:
    """Agent name property."""

    def test_segment_producer_agent_name(self):
        agent = SegmentProducerAgent()
        assert agent.agent_name == "segment_producer"


class TestSegmentProducerAggregateData:
    """Aggregating search results from multiple sources."""

    def test_aggregate_combines_sources(self):
        agent = SegmentProducerAgent()
        firecrawl_data = [
            {
                "title": "Article 1",
                "url": "https://example.com/1",
                "content": "Some content",
            },
            {
                "title": "Article 2",
                "url": "https://example.com/2",
                "content": "More content",
            },
        ]
        scrapecreators_data = [
            {
                "title": "TikTok Post 1",
                "url": "https://tiktok.com/@user/video/1",
                "play_count": 5000,
            },
        ]
        result = agent._aggregate_data(firecrawl_data, scrapecreators_data)
        assert result["firecrawl_count"] == 2
        assert result["scrapecreators_count"] == 1
        assert result["total_sources"] == 3
        assert len(result["sources"]) == 3

    def test_aggregate_handles_empty(self):
        agent = SegmentProducerAgent()
        result = agent._aggregate_data([], [])
        assert result["firecrawl_count"] == 0
        assert result["scrapecreators_count"] == 0
        assert result["total_sources"] == 0
        assert result["sources"] == []


class TestSegmentProducerSynthesize:
    """LLM-powered research synthesis."""

    @staticmethod
    def _mock_chat(content: str) -> dict:
        return {"content": content, "model": "glm-4-9b", "usage": {}}

    def test_synthesize_returns_brief_and_sources(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Research brief: Some analysis"),
        )
        agent = SegmentProducerAgent()
        aggregated = {
            "firecrawl_count": 1,
            "scrapecreators_count": 1,
            "total_sources": 2,
            "sources": [
                {"title": "Art 1", "url": "https://a.com", "content": "Data"},
                {"title": "TK 1", "url": "https://b.com", "play_count": 1000},
            ],
        }
        result = agent._synthesize_research(aggregated, "Test topic", [])
        assert result["research_brief"] == "Research brief: Some analysis"
        assert result["source_count"] == 2

    def test_synthesize_passes_topic_and_rules(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Brief content"),
        )
        agent = SegmentProducerAgent()
        aggregated = {
            "firecrawl_count": 1,
            "scrapecreators_count": 0,
            "total_sources": 1,
            "sources": [{"title": "Art 1", "url": "https://a.com", "content": "X"}],
        }
        agent._synthesize_research(
            aggregated,
            "Ariana Grande",
            ["mark_rumors_as_unconfirmed"],
        )
        messages = mock_chat.call_args.kwargs["messages"]
        system_content = messages[0]["content"]
        user_content = messages[1]["content"]
        assert "Ariana Grande" in user_content
        assert "mark_rumors_as_unconfirmed" in system_content

    def test_synthesize_model_and_temperature(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Brief"),
        )
        agent = SegmentProducerAgent()
        aggregated = {
            "firecrawl_count": 0,
            "scrapecreators_count": 0,
            "total_sources": 0,
            "sources": [],
        }
        agent._synthesize_research(aggregated, "Topic", [])
        assert mock_chat.call_args.kwargs["model"] == "mimo-v2-flash"
        assert mock_chat.call_args.kwargs["temperature"] == 0.3


class TestSegmentProducerExecute:
    """Full execute() with mocked services and LLM."""

    @staticmethod
    def _mock_chat(content: str) -> dict:
        return {"content": content, "model": "glm-4-9b", "usage": {}}

    @staticmethod
    def _mock_firecrawl_results():
        return [
            {
                "title": "Search Result 1",
                "url": "https://example.com/1",
                "content": "Content from search",
            },
            {
                "title": "Search Result 2",
                "url": "https://example.com/2",
                "content": "More content",
            },
        ]

    @staticmethod
    def _mock_scrapecreators_results():
        return [
            {
                "title": "Viral TikTok",
                "url": "https://tiktok.com/@creator/video/999",
                "play_count": 10000,
                "like_count": 500,
            },
        ]

    def test_execute_returns_research_package(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=self._mock_firecrawl_results(),
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=self._mock_scrapecreators_results(),
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Research brief: Comprehensive analysis"),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(
            job_id=2,
            topic="K-pop trends",
            output_dir=str(tmp_path),
        )
        assert result["status"] == "completed"
        assert result["research_brief"] == "Research brief: Comprehensive analysis"
        assert "sources" in result
        assert result["sources"]["firecrawl_count"] == 2
        assert result["sources"]["scrapecreators_count"] == 1

    def test_execute_handles_firecrawl_failure(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            side_effect=Exception("Firecrawl error"),
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=self._mock_scrapecreators_results(),
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Partial research brief"),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=2, topic="Test", output_dir=str(tmp_path))
        assert result["status"] == "completed"
        assert result["sources"]["firecrawl_count"] == 0
        assert result["sources"]["scrapecreators_count"] == 1

    def test_execute_handles_scrapecreators_failure(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=self._mock_firecrawl_results(),
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            side_effect=Exception("ScrapeCreators error"),
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Partial research brief"),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=2, topic="Test", output_dir=str(tmp_path))
        assert result["status"] == "completed"
        assert result["sources"]["firecrawl_count"] == 2
        assert result["sources"]["scrapecreators_count"] == 0

    def test_execute_handles_total_failure(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            side_effect=Exception("Firecrawl error"),
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            side_effect=Exception("ScrapeCreators error"),
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Minimal brief from LLM knowledge"),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=2, topic="Test", output_dir=str(tmp_path))
        assert result["status"] == "completed"
        assert result["sources"]["total_sources"] == 0

    def test_execute_uses_max_results_param(self, mocker, tmp_path):
        mock_search = mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[{
                "title": "X", "url": "https://x.com", "content": "Y",
            }],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Brief"),
        )
        agent = SegmentProducerAgent()
        agent.execute(job_id=2, topic="Test", max_results=3, output_dir=str(tmp_path))
        mock_search.assert_called_once_with("Test", 3)

    def test_execute_persists_research_contract_artifacts(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=self._mock_firecrawl_results(),
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=self._mock_scrapecreators_results(),
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("Research brief: Comprehensive analysis"),
        )
        agent = SegmentProducerAgent()

        result = agent.execute(
            job_id=125,
            topic="K-pop trends",
            output_dir=str(tmp_path / "outputs"),
            assets_cache=str(tmp_path / "assets"),
        )

        base = tmp_path / "assets" / "job_125" / "agents" / "segment_producer"
        assert (base / "input.json").exists()
        assert (base / "raw" / "scrapecreators_response.json").exists()
        assert (base / "raw" / "firecrawl_response.json").exists()
        assert (base / "research_brief.md").read_text(encoding="utf-8") == (
            "Research brief: Comprehensive analysis"
        )
        contract = json.loads((base / "research_contract.json").read_text(encoding="utf-8"))
        assert contract["topic"] == "K-pop trends"
        assert contract["topic_brief_path"] == result["research_brief_path"]
        assert contract["video_sources"] == self._mock_scrapecreators_results()
        assert contract["context_sources"] == self._mock_firecrawl_results()
        assert (base / "normalized" / "video_sources.json").exists()
        assert (base / "normalized" / "context_sources.json").exists()
        assert (base / "normalized" / "music_candidates.json").exists()
        assert (base / "normalized" / "entities.json").exists()
        assert (base / "normalized" / "risk_flags.json").exists()
        assert json.loads((base / "output.json").read_text(encoding="utf-8"))["status"] == "completed"


class TestSegmentProducerNewContract:
    """Tests for the new output contract fields."""

    @staticmethod
    def _mock_chat_with_beats() -> dict:
        beats = [
            {
                "beat_id": 1,
                "role": "hook",
                "narration_goal": "Grab attention with trending topic",
                "spoken_point": "Kamu tau nggak sih apa yang baru saja terjadi?",
                "safe_wording": "Kamu tau nggak sih apa yang baru saja terjadi?",
                "visual_must_show": "Trending TikTok clip or text card with hook text",
                "visual_must_not_show": "No unrelated content",
                "overlay_text": "GOSIP TERBARU!",
                "caption_keywords": ["gossip", "terbaru", "viral"],
                "asset_candidates": [
                    {"type": "tiktok_clip", "url": "https://tiktok.com/@user/video/1", "reason": "Viral clip"},
                ],
                "fallback": {"type": "text_card", "headline": "GOSIP TERBARU!", "image_search": ""},
                "evidence_source": "none",
                "risk_note": "",
            },
            {
                "beat_id": 2,
                "role": "main_claim",
                "narration_goal": "State the main claim",
                "spoken_point": "Kabarnya artis ini baru saja update status.",
                "safe_wording": "Ada kabar yang beredar tentang artis ini.",
                "visual_must_show": "Screenshot of social media post",
                "visual_must_not_show": "No unverified private photos",
                "overlay_text": "APA FACTNYA?",
                "caption_keywords": ["fakta", "artis", "update"],
                "asset_candidates": [],
                "fallback": {"type": "text_card", "headline": "APA FACTNYA?", "image_search": "artist portrait"},
                "evidence_source": "https://example.com/source",
                "risk_note": "Claim is unconfirmed, use safe wording",
            },
        ]
        response = json.dumps({
            "research_brief": "Two potential stories found with moderate clip availability.",
            "content_direction": {
                "recommended_format": "two_story_highlight",
                "reason": "Good clips for two stories.",
                "selected_story_count": 2,
                "selected_stories": ["story_a", "story_b"],
                "content_angle": "highlight comparison",
                "risk_notes": [],
            },
            "story_beats": beats,
            "format_decision": {
                "format": "two_story_highlight",
                "story_count": 2,
                "rationale": "Good clips for two stories",
                "video_asset_ratio": 0.75,
            },
            "asset_candidates": [
                {"type": "tiktok_clip", "url": "https://tiktok.com/@user/video/1", "reason": "Viral clip"},
            ],
            "do_not_use": ["blurry footage", "unverified photos"],
            "verified_facts": [
                {"fact": "Artist posted on Instagram", "source_url": "https://instagram.com/p/1", "confidence": "verified", "safe_wording": "Artist posted on Instagram"},
            ],
            "unverified_claims": [
                {"claim": "Artist is dating someone new", "label": "rumor", "safe_wording": "Ada kabar yang beredar"},
            ],
            "reference_style": {
                "format": "two_story_highlight",
                "target_duration_sec": 50,
                "hook_duration_sec": 2.5,
                "avg_scene_duration_sec": 6.0,
                "caption_style": "keyword",
                "transition_style": "hard_cut",
                "visual_priority": ["tiktok_clip", "screenshot", "text_card"],
            },
        })
        return {"content": response, "model": "glm-4-9b", "usage": {}}

    def test_execute_produces_story_beats(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[{"title": "X", "url": "https://x.com", "content": "Y"}],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat_with_beats(),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=1, topic="Test", output_dir=str(tmp_path))
        assert result["status"] == "completed"
        assert len(result["story_beats"]) == 2
        assert result["story_beats"][0]["role"] == "hook"
        assert result["story_beats"][1]["role"] == "main_claim"

    def test_execute_produces_format_decision(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat_with_beats(),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=1, topic="Test", output_dir=str(tmp_path))
        assert result["format_decision"]["format"] == "two_story_highlight"
        assert result["format_decision"]["story_count"] == 2
        assert 0.0 <= result["format_decision"]["video_asset_ratio"] <= 1.0

    def test_execute_produces_verified_facts(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat_with_beats(),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=1, topic="Test", output_dir=str(tmp_path))
        assert len(result["verified_facts"]) == 1
        assert result["verified_facts"][0]["confidence"] == "verified"
        assert result["verified_facts"][0]["safe_wording"] != ""

    def test_execute_produces_unverified_claims(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat_with_beats(),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=1, topic="Test", output_dir=str(tmp_path))
        assert len(result["unverified_claims"]) == 1
        assert result["unverified_claims"][0]["label"] == "rumor"
        assert result["unverified_claims"][0]["safe_wording"] != ""

    def test_execute_produces_do_not_use(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat_with_beats(),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=1, topic="Test", output_dir=str(tmp_path))
        assert "blurry footage" in result["do_not_use"]

    def test_execute_produces_reference_style(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat_with_beats(),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=1, topic="Test", output_dir=str(tmp_path))
        assert result["reference_style"]["format"] == "two_story_highlight"
        assert result["reference_style"]["caption_style"] == "keyword"
        assert result["reference_style"]["transition_style"] == "hard_cut"

    def test_execute_returns_empty_lists_when_llm_plain_text(self, mocker, tmp_path):
        """When LLM returns plain text (not JSON), all new fields default to empty."""
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={"content": "Plain text response", "model": "glm-4-9b", "usage": {}},
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=1, topic="Test", output_dir=str(tmp_path))
        assert result["status"] == "completed"
        assert result["story_beats"] == []
        assert result["format_decision"] is None
        assert result["verified_facts"] == []
        assert result["unverified_claims"] == []
        assert result["do_not_use"] == []
        assert result["asset_candidates"] == []
        assert result["reference_style"] is None

    def test_backward_compatible_research_brief(self, mocker, tmp_path):
        """Existing downstream consumers still get research_brief and sources."""
        mocker.patch(
            "clipper_agency.services.firecrawl_service.FirecrawlService.search",
            return_value=[{"title": "X", "url": "https://x.com", "content": "Y"}],
        )
        mocker.patch(
            "clipper_agency.services.scrapecreators.ScrapeCreatorsService.search_tiktok_videos",
            return_value=[],
        )
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat_with_beats(),
        )
        agent = SegmentProducerAgent()
        result = agent.execute(job_id=1, topic="Test", output_dir=str(tmp_path))
        # Old fields still present
        assert "research_brief" in result
        assert "sources" in result
        assert "risk_flags" in result
        # New fields also present
        assert "story_beats" in result
        assert "format_decision" in result


class TestSegmentProducerAssetCandidates:
    """Asset candidate extraction from raw research sources."""

    def test_builds_candidates_from_both_sources(self):
        agent = SegmentProducerAgent()

        candidates = agent._build_asset_candidates_from_sources(
            firecrawl_data=[
                {
                    "title": "Sarwendah update",
                    "url": "https://news.example/a",
                    "content": "context",
                },
            ],
            scrapecreators_data=[
                {
                    "title": "TikTok clip",
                    "url": "https://tiktok.com/@u/video/1",
                },
            ],
        )

        assert any(c["source"] == "scrapecreators" for c in candidates)
        assert any(c["source"] == "firecrawl" for c in candidates)
        assert all("url" in c for c in candidates)

    def test_handles_empty_sources(self):
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_candidates_from_sources([], [])
        assert candidates == []

    def test_handles_items_without_url(self):
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_candidates_from_sources(
            firecrawl_data=[{"title": "No URL", "content": "text"}],
            scrapecreators_data=[],
        )
        assert candidates == []

    def test_merge_deduplicates_by_url(self):
        agent = SegmentProducerAgent()
        group_a = [{"url": "https://a.com", "type": "tiktok_clip", "reason": "A"}]
        group_b = [{"url": "https://a.com", "type": "screenshot", "reason": "B duplicate"}]
        merged = agent._merge_asset_candidates(group_a, group_b)
        assert len(merged) == 1
        assert merged[0]["reason"] == "A"
