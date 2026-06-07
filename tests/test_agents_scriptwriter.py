"""Tests for ScriptwriterAgent — continuous voiceover contract."""

import json
from unittest.mock import MagicMock

import pytest

from clipper_agency.agents.scriptwriter import ScriptwriterAgent


MOCK_VOICEOVER_RESPONSE = json.dumps({
    "voiceover_text": (
        "Halo guys, hari ini ada kabar besar dari dunia seleb Indonesia! "
        "Anji ternyata sudah resmi menikah lagi dengan Wina Natalia, "
        "dan ini bikin heboh banget karena nggak ada yang nyangka. "
        "Terus ada juga gossip tentang Raffi Ahmad yang katanya lagi punya "
        "project baru bareng Nagita Slavina, tapi ini belum bisa dipastikan. "
        "Dan yang paling bikin penasaran, ternyata ada artis lain yang juga "
        "lagi proses pernikahan rahasia nih, tapi namanya masih dirahasiakan. "
        "Jadi tunggu aja kelanjutannya ya, jangan lupa follow buat update "
        "gossip terbaru setiap hari!"
    ),
    "narrative_structure": [
        {
            "beat_id": 1,
            "section": "hook",
            "description": "Attention-grabbing opening",
            "word_range": [0, 15],
            "overlay_text": "KABAR BESAR SELEB",
            "caption_keywords": ["gossip", "seleb"],
        },
        {
            "beat_id": 2,
            "section": "story_1",
            "description": "Main story",
            "word_range": [15, 50],
            "overlay_text": "STORY ONE",
            "caption_keywords": ["story"],
        },
        {
            "beat_id": 3,
            "section": "closing_cta",
            "description": "Call to action",
            "word_range": [50, 75],
            "overlay_text": "FOLLOW",
            "caption_keywords": ["follow"],
        },
    ],
    "hook_text_onscreen": "KABAR BESAR!",
    "caption": "Check this out! #viral",
    "hashtags": ["#viral", "#trending"],
    "quality_score": 8,
    "quality_notes": "Good flow",
})


class TestScriptwriterName:
    """Agent name property."""

    def test_scriptwriter_agent_name(self):
        agent = ScriptwriterAgent()
        assert agent.agent_name == "scriptwriter"


class TestScriptwriterParse:
    """JSON response parsing from LLM."""

    def test_parse_voiceover_json(self):
        agent = ScriptwriterAgent()
        result = agent._parse_script_response(MOCK_VOICEOVER_RESPONSE)
        assert result["voiceover_text"] != ""
        assert len(result["narrative_structure"]) == 3
        assert result["caption"] == "Check this out! #viral"
        assert result["hashtags"] == ["#viral", "#trending"]
        assert result["hook_text_onscreen"] == "KABAR BESAR!"

    def test_parse_with_code_fence(self):
        agent = ScriptwriterAgent()
        raw = f"```json\n{MOCK_VOICEOVER_RESPONSE}\n```"
        result = agent._parse_script_response(raw)
        assert result["voiceover_text"] != ""

    def test_parse_malformed_json_returns_empty(self):
        agent = ScriptwriterAgent()
        result = agent._parse_script_response("not valid json")
        assert result["voiceover_text"] == ""
        assert result["narrative_structure"] == []
        assert result["caption"] == ""


class TestScriptwriterExecute:
    """Full execute() with mocked LLM."""

    @staticmethod
    def _mock_chat(content: str) -> dict:
        return {"content": content, "model": "glm-4-9b", "usage": {}}

    def test_execute_generates_voiceover(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        agent = ScriptwriterAgent()
        result = agent.execute(
            job_id=3,
            topic="Ariana Grande new album",
            research_brief="She is releasing a new album next month",
        )
        assert result["status"] == "completed"
        assert result["voiceover_text"] != ""
        assert isinstance(result["narrative_structure"], list)
        assert result["caption"] == "Check this out! #viral"
        assert result["hashtags"] == ["#viral", "#trending"]

    def test_execute_includes_research_brief_in_prompt(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        agent = ScriptwriterAgent()
        agent.execute(
            job_id=3,
            topic="Topic X",
            research_brief="Research about Topic X",
        )
        messages = mock_chat.call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        assert "Research about Topic X" in user_content

    def test_execute_passes_safety_rules(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        agent = ScriptwriterAgent()
        agent.execute(
            job_id=3,
            topic="Topic",
            research_brief="Brief",
            safety_rules=["mark_rumors_as_unconfirmed"],
        )
        messages = mock_chat.call_args.kwargs["messages"]
        system_content = messages[0]["content"]
        assert "mark_rumors_as_unconfirmed" in system_content

    def test_execute_model_and_temperature(self, mocker):
        mocker.patch(
            "clipper_agency.agents.scriptwriter.get_agent_config",
            return_value={"model": "qwen3-32b", "temperature": 0.7, "max_completion_tokens": None},
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        agent = ScriptwriterAgent()
        agent.execute(job_id=3, topic="Topic", research_brief="Brief")
        assert mock_chat.call_args.kwargs["model"] == "qwen3-32b"
        assert mock_chat.call_args.kwargs["temperature"] == 0.7

    def test_execute_handles_llm_failure(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat("NOT VALID JSON AT ALL"),
        )
        agent = ScriptwriterAgent()
        result = agent.execute(
            job_id=3,
            topic="Topic",
            research_brief="Brief",
        )
        assert result["status"] == "completed"
        assert result["voiceover_text"] == ""
        assert result["caption"] == ""

    def test_execute_returns_narrative_structure(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        agent = ScriptwriterAgent()
        result = agent.execute(job_id=3, topic="Topic", research_brief="B")
        assert isinstance(result["narrative_structure"], list)
        assert len(result["narrative_structure"]) == 3
        for beat in result["narrative_structure"]:
            assert "beat_id" in beat
            assert "section" in beat
            assert "word_range" in beat

    def test_execute_includes_estimated_duration(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        agent = ScriptwriterAgent()
        result = agent.execute(job_id=3, topic="Topic", research_brief="B")
        assert "estimated_duration_sec" in result
        assert isinstance(result["estimated_duration_sec"], float)
        assert result["estimated_duration_sec"] > 0

    def test_execute_uses_prompt_file_when_available(self, mocker, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "scriptwriter.md").write_text(
            "File scriptwriter prompt: {safety_rules_text} {topic}",
            encoding="utf-8",
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        mocker.patch("clipper_agency.agents.scriptwriter.PROMPTS_DIR", prompts_dir)

        ScriptwriterAgent().execute(
            job_id=3,
            topic="TestTopic",
            research_brief="Brief",
            safety_rules=["no_defamation"],
        )

        system_content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert "File scriptwriter prompt:" in system_content
        assert "no_defamation" in system_content
        assert "TestTopic" in system_content

    def test_execute_persists_voiceover_artifacts(self, mocker, tmp_path):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        agent = ScriptwriterAgent()

        result = agent.execute(
            job_id=125,
            topic="Ariana Grande new album",
            research_brief="She is releasing a new album next month",
            safety_rules=["no_defamation"],
            assets_cache=str(tmp_path),
        )

        base = tmp_path / "job_125" / "agents" / "scriptwriter"
        input_data = json.loads((base / "input.json").read_text(encoding="utf-8"))
        assert input_data["topic"] == "Ariana Grande new album"

        voiceover = (base / "voiceover.txt").read_text(encoding="utf-8")
        assert voiceover == result["voiceover_text"]

        narrative = json.loads((base / "narrative_structure.json").read_text(encoding="utf-8"))
        assert narrative == result["narrative_structure"]

        caption = (base / "caption.txt").read_text(encoding="utf-8")
        assert caption == result["caption"]

        hashtags = json.loads((base / "hashtags.json").read_text(encoding="utf-8"))
        assert hashtags == result["hashtags"]

        output = json.loads((base / "output.json").read_text(encoding="utf-8"))
        assert output["status"] == "completed"

    def test_execute_receives_blueprint_data(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_VOICEOVER_RESPONSE),
        )
        agent = ScriptwriterAgent()
        agent.execute(
            job_id=7,
            topic="Topic",
            research_brief="Brief",
            story_beats=[{"beat_id": 1, "role": "hook", "narration_goal": "Grab attention"}],
            verified_facts=[{"fact": "Test fact", "safe_wording": "Reportedly test"}],
            unverified_claims=[{"claim": "Test claim", "safe_wording": "Rumor has it"}],
            format_decision={"format": "single_story_deep_dive", "story_count": 1},
        )
        system_content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert "hook" in system_content
        assert "Test fact" in system_content
        assert "single_story_deep_dive" in system_content
