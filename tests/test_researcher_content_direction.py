import json
from unittest.mock import patch

from clipper_agency.agents.researcher import RESEARCH_PROMPT, ResearcherAgent
from clipper_agency.config.schema import AppSettings, ContentPlanningConfig


class TestResearcherContentDirection:
    def test_parse_content_direction_from_llm_response(self):
        agent = ResearcherAgent()
        raw = json.dumps({
            "research_brief": "Three safe stories found.",
            "content_direction": {
                "recommended_format": "three_story_roundup",
                "reason": "Three distinct stories with similar viral potential.",
                "selected_story_count": 3,
                "selected_stories": ["story_a", "story_b", "story_c"],
                "content_angle": "fast gossip roundup",
                "risk_notes": ["Use cautious wording for unverified claims."],
            },
        })
        result = agent._parse_synthesis_response(raw)
        assert result["research_brief"] == "Three safe stories found."
        assert result["content_direction"]["recommended_format"] == "three_story_roundup"
        assert result["content_direction"]["selected_story_count"] == 3
        assert len(result["content_direction"]["selected_stories"]) == 3
        assert "risk_notes" in result["content_direction"]

    def test_missing_content_direction_returns_none(self):
        agent = ResearcherAgent()
        raw = json.dumps({"research_brief": "Just a brief. No direction."})
        result = agent._parse_synthesis_response(raw)
        assert result["research_brief"] == "Just a brief. No direction."
        assert result.get("content_direction") is None

    def test_malformed_json_returns_raw_brief(self):
        agent = ResearcherAgent()
        raw = "This is not JSON at all."
        result = agent._parse_synthesis_response(raw)
        assert result["research_brief"] == "This is not JSON at all."
        assert result.get("content_direction") is None

    def test_dict_brief_converted_to_string(self):
        """Regression: LLM may return research_brief as dict, not string."""
        agent = ResearcherAgent()
        raw = json.dumps({
            "research_brief": {"summary": "Three stories", "sources": 5},
            "content_direction": {
                "recommended_format": "three_story_roundup",
                "selected_story_count": 3,
            },
        })
        result = agent._parse_synthesis_response(raw)
        assert isinstance(result["research_brief"], str)
        assert "summary" in result["research_brief"]
        assert result["content_direction"]["selected_story_count"] == 3


class TestResearcherPromptBudgetParams:
    """Verify RESEARCH_PROMPT includes timeline budget parameters."""

    def test_prompt_contains_budget_template_vars(self):
        assert "{target_duration_sec}" in RESEARCH_PROMPT
        assert "{hard_limit_sec}" in RESEARCH_PROMPT
        assert "{estimated_words_per_second}" in RESEARCH_PROMPT
        assert "{max_stories_per_video}" in RESEARCH_PROMPT

    def test_prompt_uses_max_stories_in_selected_story_count(self):
        assert "1-{max_stories_per_video}" in RESEARCH_PROMPT

    def test_synthesize_research_formats_budget_from_config(self):
        agent = ResearcherAgent()
        cp = ContentPlanningConfig(
            target_duration_sec=45,
            hard_limit_sec=55,
            estimated_words_per_second=2.5,
            max_stories_per_video=2,
        )
        settings = AppSettings(content_planning=cp)

        with (
            patch("clipper_agency.agents.researcher.load_settings", return_value=settings),
            patch.object(
                agent, "_parse_synthesis_response",
                return_value={"research_brief": "brief", "content_direction": None},
            ),
        ):
            mock_llm_response = {"content": json.dumps({"research_brief": "brief"})}
            with patch(
                "clipper_agency.agents.researcher.OpenRouterClient"
            ) as MockLLM:
                MockLLM.return_value.chat.return_value = mock_llm_response
                agent._synthesize_research(
                    aggregated={"sources": [{"text": "source data"}]},
                    topic="test topic",
                    safety_rules=[],
                )
                call_args = MockLLM.return_value.chat.call_args
                system_msg = call_args.kwargs["messages"][0]["content"]
                assert "Target duration: 45 seconds" in system_msg
                assert "Hard limit: 55 seconds" in system_msg
                assert "2.5 words/second" in system_msg
                assert "Max stories allowed: 2" in system_msg
                assert "1-2" in system_msg
