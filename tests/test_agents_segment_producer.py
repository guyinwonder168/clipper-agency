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


class TestSegmentProducerStoryModeAndBudget:
    """Story mode classification and duration budget integration."""

    @staticmethod
    def _mock_chat_minimal() -> dict:
        return {"content": "Brief", "model": "glm-4-9b", "usage": {}}

    def _setup_base_mocks(self, mocker, tmp_path):
        """Common mocks for services and LLM — no story_mode/budget mocking."""
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
            return_value=self._mock_chat_minimal(),
        )

    def test_segment_producer_output_includes_story_mode_decision(self, mocker, tmp_path):
        """Segment Producer should classify story mode and include it in output."""
        from clipper_agency.config.schema import StoryModeDecision

        self._setup_base_mocks(mocker, tmp_path)

        mock_decision = StoryModeDecision(
            story_mode="roundup",
            confidence=0.85,
            reason="Broad entertainment topic with multiple entities",
            item_count=3,
            target_duration_sec=55,
            requires_intro_card=True,
        )
        mocker.patch(
            "clipper_agency.agents.segment_producer.classify_story_mode",
            return_value=mock_decision,
        )
        mocker.patch(
            "clipper_agency.agents.segment_producer.allocate_duration_budget",
            return_value=mocker.MagicMock(model_dump=lambda: {"target_duration_sec": 55, "sections": []}),
        )

        agent = SegmentProducerAgent()
        result = agent.execute(
            job_id=1,
            topic="berita artis terbaru hari ini",
            output_dir=str(tmp_path),
        )

        assert "story_mode_decision" in result
        assert result["story_mode_decision"]["story_mode"] == "roundup"
        assert result["story_mode_decision"]["requires_intro_card"] is True
        assert result["story_mode_decision"]["item_count"] == 3

    def test_segment_producer_output_includes_duration_budget(self, mocker, tmp_path):
        """Segment Producer should allocate duration budget and include it in output."""
        from clipper_agency.config.schema import DurationBudget, DurationBudgetSection

        self._setup_base_mocks(mocker, tmp_path)

        mocker.patch(
            "clipper_agency.agents.segment_producer.classify_story_mode",
            return_value=mocker.MagicMock(
                story_mode="single_story",
                item_count=1,
                model_dump=lambda: {},
            ),
        )

        mock_budget = DurationBudget(
            target_duration_sec=55,
            sections=[
                DurationBudgetSection(type="hook", duration_sec=3.0, label="Hook"),
                DurationBudgetSection(type="story", duration_sec=40.0, label="Main Story"),
                DurationBudgetSection(type="cta", duration_sec=5.0, label="CTA"),
            ],
        )
        mocker.patch(
            "clipper_agency.agents.segment_producer.allocate_duration_budget",
            return_value=mock_budget,
        )

        agent = SegmentProducerAgent()
        result = agent.execute(
            job_id=1,
            topic="berita artis terbaru hari ini",
            output_dir=str(tmp_path),
        )

        assert "duration_budget" in result
        assert result["duration_budget"]["target_duration_sec"] == 55
        assert len(result["duration_budget"]["sections"]) == 3
        section_types = [s["type"] for s in result["duration_budget"]["sections"]]
        assert "hook" in section_types
        assert "story" in section_types

    def test_story_mode_uses_target_duration_from_settings(self, mocker, tmp_path):
        """Story mode classification should receive target_duration from settings."""
        from clipper_agency.config.schema import StoryModeDecision

        self._setup_base_mocks(mocker, tmp_path)

        mock_classify = mocker.patch(
            "clipper_agency.agents.segment_producer.classify_story_mode",
            return_value=StoryModeDecision(
                story_mode="single_story",
                confidence=0.9,
                reason="Single entity topic",
                item_count=1,
                target_duration_sec=55,
            ),
        )
        mocker.patch(
            "clipper_agency.agents.segment_producer.allocate_duration_budget",
            return_value=mocker.MagicMock(model_dump=lambda: {"target_duration_sec": 55, "sections": []}),
        )

        agent = SegmentProducerAgent()
        agent.execute(
            job_id=1,
            topic="single artist gossip",
            output_dir=str(tmp_path),
        )

        mock_classify.assert_called_once()
        call_kwargs = mock_classify.call_args
        # The topic should be passed as first positional arg
        assert call_kwargs[0][0] == "single artist gossip"
        # target_duration_sec should come from settings (default 55)
        assert call_kwargs[1]["target_duration_sec"] == 55

    def test_duration_budget_receives_story_mode_output(self, mocker, tmp_path):
        """Duration budget allocation should receive story_mode and item_count from story mode decision."""
        from clipper_agency.config.schema import StoryModeDecision

        self._setup_base_mocks(mocker, tmp_path)

        mock_decision = StoryModeDecision(
            story_mode="controversy_explainer",
            confidence=0.8,
            reason="Hot topic with opposing views",
            item_count=2,
            target_duration_sec=55,
        )
        mocker.patch(
            "clipper_agency.agents.segment_producer.classify_story_mode",
            return_value=mock_decision,
        )
        mock_budget = mocker.patch(
            "clipper_agency.agents.segment_producer.allocate_duration_budget",
            return_value=mocker.MagicMock(model_dump=lambda: {"target_duration_sec": 55, "sections": []}),
        )

        agent = SegmentProducerAgent()
        agent.execute(
            job_id=1,
            topic="kontroversi artis",
            output_dir=str(tmp_path),
        )

        mock_budget.assert_called_once()
        call_kwargs = mock_budget.call_args
        assert call_kwargs[1]["story_mode"] == "controversy_explainer"
        assert call_kwargs[1]["item_count"] == 2
        assert call_kwargs[1]["target_duration_sec"] == 55


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


# ---------------------------------------------------------------------------
# Segment Producer richer asset portfolio tests (Batch 1A — must fail)
# ---------------------------------------------------------------------------


class TestSegmentProducerAssetPortfolio:
    """Tests for richer asset portfolio with ranking and no-watermark URLs.

    These tests MUST FAIL until the enhanced portfolio is implemented in Batch 2A.
    """

    def test_asset_candidates_are_ranked_with_relevance_metadata(self):
        """Asset candidates should include relevance_score and provenance metadata."""
        agent = SegmentProducerAgent()
        # This method will be added in Batch 2A
        candidates = agent._build_asset_portfolio(
            scrapecreators_results=[
                {
                    "title": "Ruben Onsu Sarwendah drama",
                    "url": "https://www.tiktok.com/@user/video/111",
                    "play_count": 500000,
                    "download_no_watermark_addr": "https://cdn.example.com/nw/111.mp4",
                },
                {
                    "title": "Unrelated cooking video",
                    "url": "https://www.tiktok.com/@chef/video/222",
                    "play_count": 1000,
                },
            ],
            firecrawl_results=[
                {
                    "title": "Sarwendah apologizes publicly",
                    "url": "https://news.example.com/sarwendah",
                    "content": "Sarwendah made a public apology...",
                },
            ],
            beat_keywords=["Sarwendah", "apology", "drama"],
        )
        assert len(candidates) >= 1
        # Each candidate should have relevance metadata
        for c in candidates:
            assert "relevance_score" in c
            assert isinstance(c["relevance_score"], (int, float))
            assert "provenance" in c
            assert "source" in c

    def test_scrapecreators_no_watermark_url_becomes_download_url(self):
        """When download_no_watermark_addr exists, it becomes download_url."""
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_portfolio(
            scrapecreators_results=[
                {
                    "title": "TikTok video",
                    "url": "https://www.tiktok.com/@user/video/111",
                    "download_no_watermark_addr": "https://cdn.example.com/nw/111.mp4",
                },
            ],
            firecrawl_results=[],
            beat_keywords=["test"],
        )
        tiktok_candidates = [c for c in candidates if c.get("source") == "scrapecreators"]
        assert len(tiktok_candidates) >= 1
        c = tiktok_candidates[0]
        # Canonical URL is preserved
        assert "tiktok.com" in c.get("url", "")
        # download_url points to no-watermark version
        assert c.get("download_url") == "https://cdn.example.com/nw/111.mp4"
        assert c.get("download_url_type") == "no_watermark"

    def test_scrapecreators_missing_no_watermark_uses_existing_download_url_fallback(self):
        """When download_no_watermark_addr is absent, use existing download URL logic."""
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_portfolio(
            scrapecreators_results=[
                {
                    "title": "TikTok video",
                    "url": "https://www.tiktok.com/@user/video/222",
                    # No download_no_watermark_addr field
                    "download_url": "https://cdn.example.com/wm/222.mp4",
                },
            ],
            firecrawl_results=[],
            beat_keywords=["test"],
        )
        tiktok_candidates = [c for c in candidates if c.get("source") == "scrapecreators"]
        if tiktok_candidates:
            c = tiktok_candidates[0]
            # Should use the existing download_url, not crash
            assert c.get("download_url") is not None
            # download_url_type should NOT be "no_watermark"
            assert c.get("download_url_type") != "no_watermark"

    def test_important_beat_gets_video_image_and_text_fallback_candidates(self):
        """Important beat should have at least 2 video + 1 image + 1 fallback candidate."""
        agent = SegmentProducerAgent()
        candidates = agent._build_asset_portfolio(
            scrapecreators_results=[
                {
                    "title": "Ruben Onsu video 1",
                    "url": "https://www.tiktok.com/@user/video/301",
                    "play_count": 500000,
                },
                {
                    "title": "Ruben Onsu video 2",
                    "url": "https://www.tiktok.com/@user/video/302",
                    "play_count": 300000,
                },
            ],
            firecrawl_results=[
                {
                    "title": "Ruben Onsu news article with image",
                    "url": "https://news.example.com/ruben",
                    "content": "Article about Ruben...",
                    "image": "https://img.example.com/ruben.jpg",
                },
            ],
            beat_keywords=["Ruben Onsu", "drama"],
            is_important_beat=True,
        )
        video_candidates = [c for c in candidates if c.get("type") in ("tiktok_clip", "video")]
        image_candidates = [c for c in candidates if c.get("type") in ("photo", "screenshot", "image")]
        fallback_candidates = [c for c in candidates if c.get("type") in ("text_card",)]

        assert len(video_candidates) >= 2, f"Expected >= 2 video candidates, got {len(video_candidates)}"
        assert len(image_candidates) >= 1 or len(fallback_candidates) >= 1, (
            "Expected at least 1 image or fallback candidate"
        )


class TestStoryBeatEvidenceContract:
    """Test evidence_contract field on StoryBeat and Segment Producer output."""

    def test_story_beat_model_accepts_evidence_contract(self):
        """StoryBeat model should accept optional evidence_contract."""
        from clipper_agency.config.schema import StoryBeat, EvidenceContract, BeatFallback

        ec = EvidenceContract(
            preferred=["same-event interview"],
            acceptable=["press conference footage"],
            forbidden=["unrelated event"],
        )
        beat = StoryBeat(
            beat_id=1,
            role="evidence",
            narration_goal="Show the interview",
            spoken_point="Ruben gave an interview",
            safe_wording="Reportedly",
            visual_must_show="Ruben interview footage",
            visual_must_not_show="unrelated person",
            overlay_text="",
            caption_keywords=["ruben"],
            asset_candidates=[],
            fallback=BeatFallback(type="text_card", headline="Test"),
            evidence_contract=ec,
        )
        assert beat.evidence_contract is not None
        assert beat.evidence_contract.preferred == ["same-event interview"]
        assert beat.evidence_contract.forbidden == ["unrelated event"]

    def test_story_beat_without_evidence_contract_defaults_to_none(self):
        """StoryBeat without evidence_contract should default to None."""
        from clipper_agency.config.schema import StoryBeat, BeatFallback

        beat = StoryBeat(
            beat_id=1,
            role="hook",
            narration_goal="Hook",
            spoken_point="test",
            safe_wording="test",
            visual_must_show="test",
            visual_must_not_show="test",
            overlay_text="",
            caption_keywords=[],
            asset_candidates=[],
            fallback=BeatFallback(type="text_card", headline="Test"),
        )
        assert beat.evidence_contract is None

    def test_segment_producer_populates_evidence_contracts(self):
        """Segment Producer should populate evidence_contract from visual_must_show/not_show."""
        from clipper_agency.agents.segment_producer import SegmentProducerAgent

        beats = [
            {
                "beat_id": 1,
                "role": "evidence",
                "visual_must_show": "Ruben interview footage, behind the scenes",
                "visual_must_not_show": "unrelated person, stock footage",
            },
            {
                "beat_id": 2,
                "role": "hook",
                "visual_must_show": "dramatic reaction clip",
                "visual_must_not_show": "",
            },
        ]

        result = SegmentProducerAgent._enrich_beats_with_evidence_contracts(beats)

        assert len(result) == 2

        # Beat 1 has both visual_must_show and visual_must_not_show
        beat1 = result[0]
        assert beat1["evidence_contract"] is not None
        assert "Ruben interview footage" in beat1["evidence_contract"]["preferred"]
        assert "behind the scenes" in beat1["evidence_contract"]["preferred"]
        assert "unrelated person" in beat1["evidence_contract"]["forbidden"]
        assert "stock footage" in beat1["evidence_contract"]["forbidden"]

        # Beat 2 has visual_must_show but empty visual_must_not_show
        beat2 = result[1]
        assert beat2["evidence_contract"] is not None
        assert len(beat2["evidence_contract"]["preferred"]) == 1
        assert beat2["evidence_contract"]["preferred"][0] == "dramatic reaction clip"
        assert len(beat2["evidence_contract"]["forbidden"]) == 0
