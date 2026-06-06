"""Tests for ReviewerAgent."""

import pytest

from clipper_agency.agents.reviewer import (
    ReviewerAgent,
    _check_av_sync,
    _check_caption_quality,
    _check_fact_safety,
    _check_narrative_structure,
)


MOCK_REVIEW_PASS = """{
  "verdict": "pass",
  "score": 85,
  "feedback": "Good script with engaging content",
  "issues": []
}"""

MOCK_REVIEW_FAIL = """{
  "verdict": "fail",
  "score": 40,
  "feedback": "Script contains unverified claims",
  "issues": ["unverified_claims", "misleading"]
}"""


# --- Programmatic checks (pure function tests) ---


class TestAVSync:
    """Audio-visual sync validation."""

    def test_pass_when_durations_match(self):
        result = _check_av_sync(10.0, 10.2)
        assert result["status"] == "pass"
        assert result["drift_sec"] == 0.2

    def test_fail_when_drift_exceeds_500ms(self):
        result = _check_av_sync(10.0, 11.0)
        assert result["status"] == "fail"
        assert result["audio_sec"] == 10.0
        assert result["visual_sec"] == 11.0

    def test_skip_when_audio_zero(self):
        result = _check_av_sync(0.0, 10.0)
        assert result["status"] == "skip"

    def test_skip_when_visual_zero(self):
        result = _check_av_sync(10.0, 0.0)
        assert result["status"] == "skip"


class TestCaptionQuality:
    """Caption quality checks."""

    def test_pass_good_caption(self):
        result = _check_caption_quality("Amazing story! #kpop #viral")
        assert result["status"] == "pass"

    def test_fail_empty_caption(self):
        result = _check_caption_quality("")
        assert result["status"] == "fail"

    def test_warn_long_caption(self):
        long_caption = "x" * 151 + " #tag"
        result = _check_caption_quality(long_caption)
        assert result["status"] == "warn"
        assert any("exceeds" in issue.lower() for issue in result["issues"])

    def test_warn_no_hashtag(self):
        result = _check_caption_quality("Nice video without tags")
        assert result["status"] == "warn"
        assert any("hashtag" in issue.lower() for issue in result["issues"])


class TestFactSafety:
    """Fact safety checks for unverified claims."""

    def test_pass_all_safe_wording(self):
        claims = [
            {"claim": "X dating Y", "safe_wording": "Reportedly dating"},
            {"claim": "Z fired", "safe_wording": "Rumored to be fired"},
        ]
        result = _check_fact_safety(claims)
        assert result["status"] == "pass"

    def test_warn_missing_safe_wording(self):
        claims = [
            {"claim": "X dating Y", "safe_wording": "Reportedly dating"},
            {"claim": "Z fired"},
        ]
        result = _check_fact_safety(claims)
        assert result["status"] == "warn"
        assert "Claim 1" in result["detail"]

    def test_pass_no_claims(self):
        result = _check_fact_safety([])
        assert result["status"] == "pass"


class TestNarrativeStructure:
    """Narrative structure completeness checks."""

    def test_pass_complete_structure(self):
        narrative = [
            {"beat_id": "hook", "section": "intro", "word_range": [0, 50]},
            {"beat_id": "body", "section": "main", "word_range": [50, 200]},
        ]
        result = _check_narrative_structure(narrative, 30.0)
        assert result["status"] == "pass"
        assert result["beats"] == 2

    def test_pass_empty_structure_skips(self):
        result = _check_narrative_structure([], 30.0)
        assert result["status"] == "skip"

    def test_warn_missing_beat_fields(self):
        narrative = [
            {"beat_id": "hook", "section": "intro"},
        ]
        result = _check_narrative_structure(narrative, 30.0)
        assert result["status"] == "warn"
        assert "word_range" in result["detail"]


# --- Existing tests (preserved) ---


class TestReviewerName:
    """Agent name property."""

    def test_reviewer_agent_name(self):
        agent = ReviewerAgent()
        assert agent.agent_name == "reviewer"


class TestReviewerParse:
    """JSON response parsing."""

    def test_parse_pass_verdict(self):
        agent = ReviewerAgent()
        result = agent._parse_review_response(MOCK_REVIEW_PASS)
        assert result["verdict"] == "pass"
        assert result["score"] == 85
        assert result["issues"] == []

    def test_parse_fail_verdict(self):
        agent = ReviewerAgent()
        result = agent._parse_review_response(MOCK_REVIEW_FAIL)
        assert result["verdict"] == "fail"
        assert result["score"] == 40
        assert len(result["issues"]) == 2

    def test_parse_with_code_fence(self):
        agent = ReviewerAgent()
        result = agent._parse_review_response(f"```json\n{MOCK_REVIEW_PASS}\n```")
        assert result["verdict"] == "pass"

    def test_parse_malformed_json(self):
        agent = ReviewerAgent()
        result = agent._parse_review_response("not json")
        assert result["verdict"] == "fail"
        assert "parse" in result["feedback"].lower()


class TestReviewerExecute:
    """Full execute() with mocked LLM."""

    @staticmethod
    def _mock_chat(content: str) -> dict:
        return {"content": content, "model": "glm-4-9b", "usage": {}}

    def test_execute_returns_pass(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=6,
            topic="Ariana Grande",
            script=[{"scene": 1, "text": "Hey!", "duration": 3}],
            caption="Check this out!",
            safety_rules=[],
        )
        assert result["status"] == "pass"
        assert result["score"] == 85

    def test_execute_returns_fail(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_FAIL),
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=6,
            topic="Topic",
            script=[{"scene": 1, "text": "Test", "duration": 3}],
            caption="Caption",
            safety_rules=[],
        )
        assert result["status"] == "fail"
        assert result["score"] == 40
        assert len(result["issues"]) == 2

    def test_execute_passes_safety_rules(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        agent = ReviewerAgent()
        agent.execute(
            job_id=6,
            topic="Topic",
            script=[{"scene": 1, "text": "Test", "duration": 3}],
            caption="Caption",
            safety_rules=["mark_rumors_as_unconfirmed"],
        )
        system_content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert "mark_rumors_as_unconfirmed" in system_content

    def test_execute_includes_script_and_caption(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        agent = ReviewerAgent()
        agent.execute(
            job_id=6,
            topic="K-pop",
            script=[{"scene": 1, "text": "Script text here", "duration": 5}],
            caption="Best caption ever",
            safety_rules=[],
        )
        user_content = mock_chat.call_args.kwargs["messages"][1]["content"]
        assert "Script text here" in user_content
        assert "Best caption ever" in user_content

    def test_execute_llm_config(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        agent = ReviewerAgent()
        agent.execute(
            job_id=6,
            topic="Topic",
            script=[{"scene": 1, "text": "Test", "duration": 3}],
            caption="Caption",
        )
        assert mock_chat.call_args.kwargs["model"] == "mimo-v2-flash"
        assert mock_chat.call_args.kwargs["temperature"] == 0.2

    def test_execute_uses_prompt_file_when_available(self, mocker, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "reviewer.md").write_text(
            "File reviewer prompt: {safety_rules_text} | {programmatic_results}",
            encoding="utf-8",
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        mocker.patch("clipper_agency.agents.reviewer.PROMPTS_DIR", prompts_dir)

        ReviewerAgent().execute(
            job_id=6,
            topic="Topic",
            script=[{"scene": 1, "text": "Test", "duration": 3}],
            caption="Caption #tag",
            safety_rules=["no_defamation"],
        )

        system_content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert system_content == "File reviewer prompt: - no_defamation | - av_sync: skip\n- caption_quality: pass\n- fact_safety: pass\n- narrative_structure: skip"

    # --- New audio-first execute tests ---

    def test_execute_with_audio_first_data(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=6,
            topic="BTS",
            script=[{"scene": 1, "text": "Voiceover text", "duration": 5}],
            caption="Hot news! #kpop",
            safety_rules=[],
            audio_duration_sec=30.0,
            visual_duration_sec=30.1,
            narrative_structure=[
                {"beat_id": "hook", "section": "intro", "word_range": [0, 50]},
            ],
            unverified_claims=[
                {"claim": "dating rumor", "safe_wording": "Reportedly dating"},
            ],
        )
        assert result["status"] == "pass"
        checks = result["programmatic_checks"]
        assert checks["av_sync"]["status"] == "pass"
        assert checks["caption_quality"]["status"] == "pass"
        assert checks["fact_safety"]["status"] == "pass"
        assert checks["narrative_structure"]["status"] == "pass"

    def test_execute_backward_compat_no_audio_data(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=6,
            topic="Topic",
            script=[{"scene": 1, "text": "Test", "duration": 3}],
            caption="Caption #tag",
            safety_rules=[],
        )
        assert result["status"] == "pass"
        checks = result["programmatic_checks"]
        # No audio data → skip
        assert checks["av_sync"]["status"] == "skip"
        # Empty narrative → skip
        assert checks["narrative_structure"]["status"] == "skip"

    def test_execute_returns_programmatic_checks(self, mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=6,
            topic="Topic",
            script=[{"scene": 1, "text": "Test", "duration": 3}],
            caption="Short #ok",
            safety_rules=[],
            audio_duration_sec=10.0,
            visual_duration_sec=12.0,
        )
        assert "programmatic_checks" in result
        checks = result["programmatic_checks"]
        assert set(checks.keys()) == {
            "av_sync", "caption_quality", "fact_safety", "narrative_structure",
        }
        # AV drift > 0.5s → fail
        assert checks["av_sync"]["status"] == "fail"

    def test_execute_includes_programmatic_results_in_prompt(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        agent = ReviewerAgent()
        agent.execute(
            job_id=6,
            topic="Topic",
            script=[{"scene": 1, "text": "Test", "duration": 3}],
            caption="Caption #tag",
            safety_rules=[],
            audio_duration_sec=10.0,
            visual_duration_sec=10.0,
        )
        system_content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert "av_sync: pass" in system_content
        assert "programmatic checks already passed" in system_content.lower()
