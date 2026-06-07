import json
from unittest.mock import patch

from clipper_agency.agents.segment_producer import (
    SEGMENT_PRODUCER_PROMPT,
    SegmentProducerAgent,
)
from clipper_agency.config.schema import AppSettings, ContentPlanningConfig


class TestSegmentProducerContentDirection:
    def test_parse_content_direction_from_llm_response(self):
        agent = SegmentProducerAgent()
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
        agent = SegmentProducerAgent()
        raw = json.dumps({"research_brief": "Just a brief. No direction."})
        result = agent._parse_synthesis_response(raw)
        assert result["research_brief"] == "Just a brief. No direction."
        assert result.get("content_direction") is None

    def test_malformed_json_returns_raw_brief(self):
        agent = SegmentProducerAgent()
        raw = "This is not JSON at all."
        result = agent._parse_synthesis_response(raw)
        assert result["research_brief"] == "This is not JSON at all."
        assert result.get("content_direction") is None

    def test_dict_brief_converted_to_string(self):
        """Regression: LLM may return research_brief as dict, not string."""
        agent = SegmentProducerAgent()
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

    def test_parse_story_beats_from_llm_response(self):
        agent = SegmentProducerAgent()
        raw = json.dumps({
            "research_brief": "Brief.",
            "story_beats": [
                {"beat_id": 1, "role": "hook", "narration_goal": "Grab attention",
                 "spoken_point": "Kamu tau nggak?", "safe_wording": "Kamu tau nggak?",
                 "visual_must_show": "TikTok clip", "visual_must_not_show": "Nothing unrelated",
                 "overlay_text": "VIRAL!", "caption_keywords": ["viral"],
                 "asset_candidates": [], "fallback": {"type": "text_card", "headline": "VIRAL!"},
                 "evidence_source": "none", "risk_note": ""},
            ],
        })
        result = agent._parse_synthesis_response(raw)
        assert len(result["story_beats"]) == 1
        assert result["story_beats"][0]["role"] == "hook"

    def test_parse_format_decision_from_llm_response(self):
        agent = SegmentProducerAgent()
        raw = json.dumps({
            "research_brief": "Brief.",
            "format_decision": {
                "format": "single_story_deep_dive",
                "story_count": 1,
                "rationale": "Strong clips for one story",
                "video_asset_ratio": 0.9,
            },
        })
        result = agent._parse_synthesis_response(raw)
        assert result["format_decision"]["format"] == "single_story_deep_dive"
        assert result["format_decision"]["story_count"] == 1

    def test_parse_verified_facts_from_llm_response(self):
        agent = SegmentProducerAgent()
        raw = json.dumps({
            "research_brief": "Brief.",
            "verified_facts": [
                {"fact": "Artist posted", "source_url": "https://ig.com/p/1",
                 "confidence": "verified", "safe_wording": "Artist posted"},
            ],
        })
        result = agent._parse_synthesis_response(raw)
        assert len(result["verified_facts"]) == 1
        assert result["verified_facts"][0]["confidence"] == "verified"

    def test_parse_unverified_claims_from_llm_response(self):
        agent = SegmentProducerAgent()
        raw = json.dumps({
            "research_brief": "Brief.",
            "unverified_claims": [
                {"claim": "Artist dating", "label": "rumor", "safe_wording": "Ada kabar beredar"},
            ],
        })
        result = agent._parse_synthesis_response(raw)
        assert len(result["unverified_claims"]) == 1
        assert result["unverified_claims"][0]["label"] == "rumor"

    def test_missing_structured_fields_default_to_empty(self):
        agent = SegmentProducerAgent()
        raw = json.dumps({"research_brief": "Just a brief."})
        result = agent._parse_synthesis_response(raw)
        assert result["story_beats"] == []
        assert result["format_decision"] is None
        assert result["asset_candidates"] == []
        assert result["do_not_use"] == []
        assert result["verified_facts"] == []
        assert result["unverified_claims"] == []
        assert result["reference_style"] is None


class TestSegmentProducerPromptBudgetParams:
    """Verify SEGMENT_PRODUCER_PROMPT includes timeline budget parameters."""

    def test_prompt_contains_budget_template_vars(self):
        assert "{target_duration_sec}" in SEGMENT_PRODUCER_PROMPT
        assert "{hard_limit_sec}" in SEGMENT_PRODUCER_PROMPT
        assert "{estimated_words_per_second}" in SEGMENT_PRODUCER_PROMPT
        assert "{max_stories_per_video}" in SEGMENT_PRODUCER_PROMPT

    def test_prompt_uses_max_stories_in_selected_story_count(self):
        assert "1-{max_stories_per_video}" in SEGMENT_PRODUCER_PROMPT

    def test_synthesize_research_formats_budget_from_config(self):
        agent = SegmentProducerAgent()
        cp = ContentPlanningConfig(
            target_duration_sec=45,
            hard_limit_sec=55,
            estimated_words_per_second=2.5,
            max_stories_per_video=2,
        )
        settings = AppSettings(content_planning=cp)

        with (
            patch("clipper_agency.agents.segment_producer.load_settings", return_value=settings),
            patch.object(
                agent, "_parse_synthesis_response",
                return_value={"research_brief": "brief", "content_direction": None,
                              "story_beats": [], "format_decision": None,
                              "asset_candidates": [], "do_not_use": [],
                              "verified_facts": [], "unverified_claims": [],
                              "reference_style": None},
            ),
        ):
            mock_llm_response = {"content": json.dumps({"research_brief": "brief"})}
            with patch(
                "clipper_agency.agents.segment_producer.OpenRouterClient"
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
