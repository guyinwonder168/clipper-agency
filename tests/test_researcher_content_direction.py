import json

from clipper_agency.agents.researcher import ResearcherAgent


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
