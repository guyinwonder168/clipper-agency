"""Tests for SafetyAgent."""

import pytest

from clipper_agency.agents.safety import SafetyAgent


class TestSafetyAgentName:
    """Agent name property."""

    def test_safety_agent_name(self):
        agent = SafetyAgent()
        assert agent.agent_name == "safety"


class TestSafetyParseResponse:
    """JSON response parsing."""

    def test_parse_pass_verdict(self):
        agent = SafetyAgent()
        result = agent._parse_response(
            '{"verdict": "pass", "reason": "Topic appears safe"}'
        )
        assert result["status"] == "pass"
        assert result["reason"] == "Topic appears safe"

    def test_parse_hard_block_verdict(self):
        agent = SafetyAgent()
        result = agent._parse_response(
            '{"verdict": "hard_block", "reason": "Illegal content"}'
        )
        assert result["status"] == "hard_fail"
        assert result["reason"] == "Illegal content"

    def test_parse_soft_warning_verdict(self):
        agent = SafetyAgent()
        result = agent._parse_response(
            '{"verdict": "soft_warning", "reason": "Unverified claims"}'
        )
        assert result["status"] == "soft_warning"
        assert result["reason"] == "Unverified claims"
        assert result["requires_cautious_wording"] is True

    def test_parse_malformed_json_returns_hard_fail(self):
        agent = SafetyAgent()
        result = agent._parse_response("not valid json")
        assert result["status"] == "hard_fail"
        assert "parse" in result["reason"].lower()

    def test_parse_empty_verdict_defaults_to_hard_block(self):
        agent = SafetyAgent()
        result = agent._parse_response('{"reason": "no verdict key"}')
        assert result["status"] == "hard_fail"

    def test_parse_json_with_code_fence_wrappers(self):
        agent = SafetyAgent()
        result = agent._parse_response(
            '```json\n{"verdict": "pass", "reason": "Safe"}\n```'
        )
        assert result["status"] == "pass"
        assert result["reason"] == "Safe"


class TestSafetyExecute:
    """execute() method integration with mocked LLM."""

    @staticmethod
    def _mock_chat(content: str) -> dict:
        return {"content": content, "model": "glm-4-9b", "usage": {}}

    def test_execute_pass(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(
                '{"verdict": "pass", "reason": "Entertainment topic"}'
            ),
        )
        agent = SafetyAgent()
        result = agent.execute(
            job_id=1,
            topic="Ariana Grande concert in Jakarta",
            safety_rules=["no_defamation"],
        )
        assert result["status"] == "pass"
        assert result["reason"] == "Entertainment topic"

    def test_execute_uses_traced_chat_when_writer_configured(self, mocker):
        writer = object()
        mock_traced = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat_traced",
            return_value=self._mock_chat(
                '{"verdict": "pass", "reason": "Traced"}'
            ),
        )

        agent = SafetyAgent(trace_writer=writer)
        result = agent.execute(job_id=7, topic="Trace topic")

        assert result["status"] == "pass"
        mock_traced.assert_called_once()
        assert mock_traced.call_args.kwargs["job_id"] == 7
        assert mock_traced.call_args.kwargs["agent"] == "safety"
        assert mock_traced.call_args.kwargs["task"] == "safety_check"

    def test_execute_uses_plain_chat_when_writer_is_none(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(
                '{"verdict": "pass", "reason": "Untraced"}'
            ),
        )
        mock_traced = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat_traced",
        )

        result = SafetyAgent(trace_writer=None).execute(job_id=8, topic="No trace")

        assert result["status"] == "pass"
        mock_chat.assert_called_once()
        mock_traced.assert_not_called()

    def test_execute_hard_block(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(
                '{"verdict": "hard_block", "reason": "Hate speech detected"}'
            ),
        )
        agent = SafetyAgent()
        result = agent.execute(
            job_id=1, topic="Hate speech content", safety_rules=[]
        )
        assert result["status"] == "hard_fail"
        assert result["reason"] == "Hate speech detected"

    def test_execute_soft_warning(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(
                '{"verdict": "soft_warning", "reason": "Unverified rumor"}'
            ),
        )
        agent = SafetyAgent()
        result = agent.execute(
            job_id=1,
            topic="Unverified celebrity rumor",
            safety_rules=["mark_rumors_as_unconfirmed"],
        )
        assert result["status"] == "soft_warning"
        assert result["requires_cautious_wording"] is True

    def test_execute_passes_safety_rules_to_llm(self, mocker):
        mocker.patch(
            "clipper_agency.agents.safety.get_agent_config",
            return_value={"model": "glm-4.7-flash", "temperature": 0.1, "max_completion_tokens": None},
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(
                '{"verdict": "pass", "reason": "OK"}'
            ),
        )
        agent = SafetyAgent()
        agent.execute(
            job_id=1,
            topic="Test topic",
            safety_rules=["no_defamation", "mark_rumors_as_unconfirmed"],
        )
        call_args = mock_chat.call_args
        messages = call_args.kwargs["messages"]
        user_content = messages[1]["content"]
        assert "no_defamation" in user_content
        assert call_args.kwargs["temperature"] == 0.1
        assert call_args.kwargs["max_completion_tokens"] is None
        assert call_args.kwargs["model"] == "glm-4.7-flash"

    def test_execute_defaults_empty_safety_rules(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(
                '{"verdict": "pass", "reason": "OK"}'
            ),
        )
        agent = SafetyAgent()
        result = agent.execute(job_id=1, topic="Test topic")
        assert result["status"] == "pass"
        # Should not crash when safety_rules is omitted
        mock_chat.assert_called_once()

    def test_execute_calls_llm_with_correct_model(self, mocker):
        mocker.patch(
            "clipper_agency.agents.safety.get_agent_config",
            return_value={"model": "glm-4.7-flash", "temperature": 0.1, "max_completion_tokens": None},
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(
                '{"verdict": "pass", "reason": "OK"}'
            ),
        )
        agent = SafetyAgent()
        agent.execute(job_id=1, topic="Test")
        assert mock_chat.call_args.kwargs["model"] == "glm-4.7-flash"

    def test_execute_uses_prompt_file_when_available(self, mocker, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "safety.md").write_text("File safety prompt", encoding="utf-8")
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(
                '{"verdict": "pass", "reason": "OK"}'
            ),
        )
        mocker.patch("clipper_agency.agents.safety.PROMPTS_DIR", prompts_dir)

        SafetyAgent().execute(job_id=1, topic="Test")

        system_content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert system_content == "File safety prompt"
