"""Tests for ReviewerAgent."""

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

    def test_warn_when_audio_zero(self):
        """FIX-2 (ADR 0030): one duration known + the other 0 (compose ran
        but probe hiccupped) → WARN (visible), not SKIP. The former SKIP
        silently defeated the job_18 truncation check."""
        result = _check_av_sync(0.0, 10.0)
        assert result["status"] == "warn"

    def test_warn_when_visual_zero(self):
        """FIX-2: visual 0 + audio known → WARN (visible), not SKIP."""
        result = _check_av_sync(10.0, 0.0)
        assert result["status"] == "warn"

    def test_skip_only_when_both_zero(self):
        """Both durations 0 (legacy no-data caller) → still SKIP."""
        result = _check_av_sync(0.0, 0.0)
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
        result = _check_narrative_structure(narrative)
        assert result["status"] == "pass"
        assert result["beats"] == 2

    def test_pass_empty_structure_skips(self):
        result = _check_narrative_structure([])
        assert result["status"] == "skip"

    def test_warn_missing_beat_fields(self):
        narrative = [
            {"beat_id": "hook", "section": "intro"},
        ]
        result = _check_narrative_structure(narrative)
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

    def test_execute_uses_traced_chat_when_writer_configured(self, mocker):
        writer = object()
        mock_traced = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat_traced",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )

        result = ReviewerAgent(trace_writer=writer).execute(
            job_id=13,
            topic="Trace topic",
            script=[{"scene": 1, "text": "Hey!", "duration": 3}],
            caption="Caption",
            safety_rules=[],
        )

        assert result["status"] == "pass"
        mock_traced.assert_called_once()
        assert mock_traced.call_args.kwargs["job_id"] == 13
        assert mock_traced.call_args.kwargs["agent"] == "reviewer"
        assert mock_traced.call_args.kwargs["task"] == "final_review"

    def test_execute_uses_plain_chat_when_writer_is_none(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value=self._mock_chat(MOCK_REVIEW_PASS),
        )
        mock_traced = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat_traced",
        )

        result = ReviewerAgent(trace_writer=None).execute(
            job_id=14,
            topic="No trace",
            script=[{"scene": 1, "text": "Hey!", "duration": 3}],
            caption="Caption",
            safety_rules=[],
        )

        assert result["status"] == "pass"
        mock_chat.assert_called_once()
        mock_traced.assert_not_called()

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
        mocker.patch(
            "clipper_agency.agents.reviewer.get_agent_config",
            return_value={
                "model": "gemini-2.5-flash",
                "temperature": 0.2,
                "max_completion_tokens": None,
            },
        )
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
        assert mock_chat.call_args.kwargs["model"] == "gemini-2.5-flash"
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
        expected_prompt = (
            "File reviewer prompt: - no_defamation | - av_sync: skip\n"
            "- caption_quality: pass\n- fact_safety: pass\n"
            "- narrative_structure: skip\n- audio_not_truncated: skip"
        )
        assert system_content == expected_prompt

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
            context={
                "audio_duration_sec": 30.0,
                "visual_duration_sec": 30.1,
                "narrative_structure": [
                    {"beat_id": "hook", "section": "intro", "word_range": [0, 50]},
                ],
                "unverified_claims": [
                    {"claim": "dating rumor", "safe_wording": "Reportedly dating"},
                ],
            },
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
            context={
                "audio_duration_sec": 10.0,
                "visual_duration_sec": 12.0,
            },
        )
        assert "programmatic_checks" in result
        checks = result["programmatic_checks"]
        assert set(checks.keys()) == {
            "av_sync",
            "caption_quality",
            "fact_safety",
            "narrative_structure",
            # FIX-4 (ADR 0030): audio-stream re-probe (skip here — no
            # voiceover_duration_sec supplied).
            "audio_not_truncated",
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
            context={
                "audio_duration_sec": 10.0,
                "visual_duration_sec": 10.0,
            },
        )
        system_content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert "av_sync: pass" in system_content
        assert "programmatic checks already passed" in system_content.lower()


# ---------------------------------------------------------------------------
# Reviewer hard-gate tests (Batch 1A — must fail)
# ---------------------------------------------------------------------------


class TestReviewerHardGates:
    """Tests for programmatic hard gates that force FAIL before LLM review.

    These tests MUST FAIL until hard gates are implemented in Batch 2A.
    """

    def test_reviewer_fails_when_video_shorter_than_audio(self, mocker):
        """Hard gate: video shorter than audio must FAIL regardless of LLM score."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 90, "feedback": "Great!", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        mocker.patch(
            "clipper_agency.agents.reviewer.get_agent_config",
            return_value={"model": "test-model", "temperature": 0.3, "max_completion_tokens": 500},
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Great video #test",
            context={
                "audio_duration_sec": 23.25,
                "visual_duration_sec": 21.21,
            },
        )
        # The LLM returned pass/90 but the hard gate should override to fail
        assert result["status"] == "fail", (
            "Reviewer should fail when video (21.21s) is shorter than audio (23.25s), "
            f"got status={result['status']} score={result.get('score')}"
        )
        # Hard gate means LLM should NOT even be called
        # (or if called for soft checks, its verdict is overridden)

    def test_reviewer_fails_broken_tiktok_clip_action(self, mocker):
        """Hard gate: broken tiktok_clip action (no source_url) must FAIL."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "Looks fine", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        mocker.patch(
            "clipper_agency.agents.reviewer.get_agent_config",
            return_value={"model": "test-model", "temperature": 0.3, "max_completion_tokens": 500},
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Nice #viral",
            context={
                "visual_plan_actions": [
                    {"type": "tiktok_clip"},  # broken: no source_url
                    {"type": "text_card", "headline": "Story 2"},
                ],
            },
        )
        assert result["status"] == "fail", (
            "Reviewer should fail when visual plan has broken tiktok_clip action, "
            f"got status={result['status']}"
        )


# ---------------------------------------------------------------------------
# Reviewer deterministic quality gates (Batch 2 — visual coverage,
# text collision, safe area)
# ---------------------------------------------------------------------------


class TestReviewerVisualCoverageGate:
    """Visual coverage hard gate blocks LLM when coverage fails."""

    def test_blocks_llm_on_visual_coverage_failure(self, mocker):
        """When visual coverage fails, Reviewer must fail WITHOUT calling LLM."""
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 90, "feedback": "Great!", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Nice #test",
            context={
                "audio_duration_sec": 21.0,
                "visual_duration_sec": 21.0,
            },
            diagnostics={
                "visual_coverage": {
                    "status": "fail",
                    "output_duration_sec": 21.0,
                    "voiceover_duration_sec": 21.0,
                    "coverage_ratio": 0.6,
                    "issues": [{"type": "BLACK_FRAME", "severity": "hard_fail", "detail": "test"}],
                },
            },
        )
        assert result["status"] == "fail"
        assert (
            "visual_coverage" in result.get("reason", "").lower()
            or "VISUAL_COVERAGE" in result.get("reason", "")
            or "visual coverage" in result.get("feedback", "").lower()
        )
        mock_chat.assert_not_called()

    def test_allows_llm_when_visual_coverage_passes(self, mocker):
        """When visual coverage passes, Reviewer proceeds to LLM."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "Good", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Nice #test",
            context={
                "audio_duration_sec": 21.0,
                "visual_duration_sec": 21.0,
            },
            diagnostics={
                "visual_coverage": {
                    "status": "pass",
                    "output_duration_sec": 21.0,
                    "voiceover_duration_sec": 21.0,
                    "coverage_ratio": 1.0,
                    "issues": [],
                },
            },
        )
        assert result["status"] == "pass"


class TestReviewerProgrammaticChecksPersistedOnGateFail:
    """4f-Reviewer: the 4 programmatic checks must be persisted even when a
    deterministic gate hard-fails before the LLM review runs.

    Regression for the bug where early-return gate-fail paths discarded the
    already-computed checks by returning ``programmatic_checks: {}``.
    """

    _EXPECTED_CHECK_KEYS = ("av_sync", "caption_quality", "fact_safety", "narrative_structure")

    @staticmethod
    def _patch_llm(mocker):
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 90, "feedback": "Great!", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        mocker.patch(
            "clipper_agency.agents.reviewer.get_agent_config",
            return_value={"model": "test-model", "temperature": 0.3, "max_completion_tokens": 500},
        )

    def _assert_all_four_checks(self, checks: dict) -> None:
        """All 4 programmatic checks are present and non-empty (have a status)."""
        assert isinstance(checks, dict), f"checks must be a dict, got {type(checks)}"
        assert checks, "programmatic_checks must be non-empty (was {})"
        for key in self._EXPECTED_CHECK_KEYS:
            assert key in checks, f"missing check: {key}"
            value = checks[key]
            assert isinstance(value, dict) and "status" in value, (
                f"check '{key}' must be a non-empty dict with a status, got {value!r}"
            )

    def test_checks_persisted_on_visual_coverage_gate_fail(self, mocker):
        """visual_coverage hard-fail (gate_result path) must persist checks."""
        self._patch_llm(mocker)
        mock_chat = mocker.patch("clipper_agency.llm.client.OpenRouterClient.chat")
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Nice #test",
            context={
                "audio_duration_sec": 21.0,
                "visual_duration_sec": 21.0,
            },
            diagnostics={
                "visual_coverage": {
                    "status": "fail",
                    "output_duration_sec": 21.0,
                    "voiceover_duration_sec": 21.0,
                    "coverage_ratio": 0.6,
                    "issues": [{"type": "BLACK_FRAME", "severity": "hard_fail", "detail": "test"}],
                },
            },
        )
        assert result["status"] == "fail"
        mock_chat.assert_not_called()
        self._assert_all_four_checks(result["programmatic_checks"])

    def test_checks_persisted_on_av_drift_hard_gate_fail(self, mocker):
        """AV-drift hard gate (_check_hard_gates path) must persist checks."""
        self._patch_llm(mocker)
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Great video #test",
            context={
                "audio_duration_sec": 23.25,
                "visual_duration_sec": 21.21,
            },
        )
        assert result["status"] == "fail"
        self._assert_all_four_checks(result["programmatic_checks"])


class TestReviewerTextCollisionGate:
    """Text collision hard gate blocks LLM when collisions detected."""

    def test_runs_actual_text_collision_detection(self, mocker):
        """Reviewer should call collision detectors from diagnostic regions."""
        mock_collision = mocker.patch(
            "clipper_agency.agents.reviewer.detect_text_collisions",
            create=True,
            return_value=[
                {"type": "SUBTITLE_SOURCE_TEXT_OVERLAP", "severity": "reject"},
            ],
        )
        mock_density = mocker.patch(
            "clipper_agency.agents.reviewer.detect_source_text_density",
            create=True,
            return_value=[],
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "Good", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )

        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test",
            script=[{"scene": 1, "text": "Hi"}],
            caption="Ok #tag",
            diagnostics={
                "visual_coverage": {"status": "pass", "issues": []},
                "source_text_regions": [
                    {"bbox": [120, 1480, 960, 1740], "text": "burned text"},
                ],
                "generated_text_regions": [
                    {"layer": "subtitle", "bbox": [120, 500, 960, 700]},
                ],
                "frame_size": (1080, 1920),
            },
        )

        mock_collision.assert_called_once()
        mock_density.assert_called_once()
        assert result["status"] == "fail"
        assert result["reason"] == "TEXT_COLLISION_FAILED"
        mock_chat.assert_not_called()

    def test_text_collision_detection_allows_clean_video(self, mocker):
        """Clean detector results should allow Reviewer to continue to LLM."""
        mock_collision = mocker.patch(
            "clipper_agency.agents.reviewer.detect_text_collisions",
            create=True,
            return_value=[],
        )
        mock_density = mocker.patch(
            "clipper_agency.agents.reviewer.detect_source_text_density",
            create=True,
            return_value=[],
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "Good", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )

        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test",
            script=[{"scene": 1, "text": "Hi"}],
            caption="Ok #tag",
            diagnostics={
                "visual_coverage": {"status": "pass", "issues": []},
                "source_text_regions": [
                    {"bbox": [10, 10, 200, 100], "text": "source text"},
                ],
                "generated_text_regions": [
                    {"layer": "subtitle", "bbox": [120, 500, 960, 700]},
                ],
                "frame_size": (1080, 1920),
            },
        )

        mock_collision.assert_called_once()
        mock_density.assert_called_once()
        assert result["status"] == "pass"
        mock_chat.assert_called_once()

    def test_blocks_llm_on_text_collision(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test",
            script=[{"scene": 1, "text": "Hi"}],
            caption="Ok #tag",
            diagnostics={
                "visual_coverage": {"status": "pass", "issues": []},
                "text_collision": [
                    {"type": "SUBTITLE_OVERLAP", "severity": "hard_fail", "detail": "test"},
                ],
            },
        )
        assert result["status"] == "fail"
        mock_chat.assert_not_called()


class TestReviewerSafeAreaGate:
    """Safe area hard gate blocks LLM when issues detected."""

    def test_runs_actual_safe_area_detection(self, mocker):
        """Reviewer should call safe-area detection from generated/face regions."""
        mock_safe = mocker.patch(
            "clipper_agency.agents.reviewer.detect_safe_area_issues",
            create=True,
            return_value=[
                {"type": "FACE_TEXT_OVERLAP", "severity": "reject"},
            ],
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "Good", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )

        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test",
            script=[{"scene": 1, "text": "Hi"}],
            caption="Ok #tag",
            diagnostics={
                "visual_coverage": {"status": "pass", "issues": []},
                "generated_text_regions": [
                    {"layer": "headline", "bbox": [100, 100, 400, 400]},
                ],
                "face_regions": [
                    {"bbox": [100, 100, 400, 500], "confidence": 0.9},
                ],
                "frame_size": (1080, 1920),
            },
        )

        mock_safe.assert_called_once()
        assert result["status"] == "fail"
        assert result["reason"] == "SAFE_AREA_FAILED"
        mock_chat.assert_not_called()

    def test_safe_area_detection_skips_without_generated_regions(self, mocker):
        """Safe-area detection should gracefully skip when inputs are absent."""
        mock_safe = mocker.patch(
            "clipper_agency.agents.reviewer.detect_safe_area_issues",
            create=True,
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "Good", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )

        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test",
            script=[{"scene": 1, "text": "Hi"}],
            caption="Ok #tag",
            diagnostics={"visual_coverage": {"status": "pass", "issues": []}},
        )

        mock_safe.assert_not_called()
        assert result["status"] == "pass"
        mock_chat.assert_called_once()

    def test_blocks_llm_on_safe_area_issue(self, mocker):
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=4,
            topic="Test",
            script=[{"scene": 1, "text": "Hi"}],
            caption="Ok #tag",
            diagnostics={
                "visual_coverage": {"status": "pass", "issues": []},
                "safe_area": [
                    {"type": "FACE_TEXT_OVERLAP", "severity": "hard_fail", "detail": "test"},
                ],
            },
        )
        assert result["status"] == "fail"
        mock_chat.assert_not_called()


# ---------------------------------------------------------------------------
# Reviewer package consistency gate (Batch 3)
# ---------------------------------------------------------------------------


class TestReviewerPackageConsistencyGate:
    """Package consistency hard gate blocks LLM when scope mismatches."""

    def test_blocks_llm_on_package_consistency_failure(self, mocker):
        """Package consistency failure should skip LLM review."""
        from clipper_agency.config.schema import PackageConsistencyResult

        mocker.patch(
            "clipper_agency.agents.reviewer.evaluate_package_consistency",
            return_value=PackageConsistencyResult(
                status="fail",
                issue="PACKAGE_SCOPE_MISMATCH",
                detail="Roundup video has single-entity thumbnail",
            ),
        )
        llm_mock = mocker.patch("clipper_agency.llm.client.OpenRouterClient.chat")

        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="berita artis terbaru",
            caption="test caption #viral",
            context={
                "audio_duration_sec": 30.0,
                "visual_duration_sec": 30.0,
                "story_mode_decision": {"story_mode": "roundup", "item_count": 3},
                "thumbnail_text": "Ruben Akhirnya Jujur",
                "main_entities": ["Ruben", "A", "B"],
            },
        )

        assert result["status"] == "fail"
        assert (
            "PACKAGE" in result.get("reason", "") or "package" in result.get("feedback", "").lower()
        )
        llm_mock.assert_not_called()

    def test_allows_llm_when_package_consistency_passes(self, mocker):
        """When package consistency passes, Reviewer proceeds to LLM."""
        from clipper_agency.config.schema import PackageConsistencyResult

        mocker.patch(
            "clipper_agency.agents.reviewer.evaluate_package_consistency",
            return_value=PackageConsistencyResult(status="pass"),
        )
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "Good", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )

        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="berita artis terbaru",
            caption="test caption #viral",
            context={
                "audio_duration_sec": 30.0,
                "visual_duration_sec": 30.0,
                "story_mode_decision": {"story_mode": "roundup", "item_count": 3},
                "thumbnail_text": "3 Kabar Artis Viral!",
                "main_entities": ["Ruben", "A", "B"],
            },
        )

        assert result["status"] == "pass"
        mock_chat.assert_called_once()

    def test_skips_gate_when_no_story_mode_decision(self, mocker):
        """No story_mode_decision should skip the check and proceed to LLM."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 90, "feedback": "Great", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )

        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="berita artis terbaru",
            caption="test caption #viral",
            context={
                "audio_duration_sec": 30.0,
                "visual_duration_sec": 30.0,
            },
        )

        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Reviewer semantic review gate (Batch 4 — Worker O)
# ---------------------------------------------------------------------------


class TestReviewerSemanticReviewGate:
    """Semantic review repair plan output gate."""

    def test_reviewer_returns_repair_plan_for_semantic_revise(self, mocker):
        """Reviewer should return repair_plan when semantic review says revise."""
        mock_chat = mocker.patch("clipper_agency.llm.client.OpenRouterClient.chat")
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
            },
            diagnostics={
                "semantic_review": {
                    "decision": "revise",
                    "patches": [
                        {
                            "beat_id": "B04",
                            "action": "replace_visual",
                            "reason": "wrong_event",
                            "rerun_from": "visual_director",
                            "timestamp_start_sec": 12.4,
                            "timestamp_end_sec": 17.8,
                            "required_visual": "same-event interview",
                        }
                    ],
                }
            },
        )

        assert result["status"] == "fail"
        assert result["reason"] == "SEMANTIC_REVIEW_FAILED"
        assert "repair_plan" in result
        assert result["repair_plan"]["decision"] == "revise"
        assert len(result["repair_plan"]["patches"]) == 1
        assert result["repair_plan"]["patches"][0]["beat_id"] == "B04"
        mock_chat.assert_not_called()

    def test_reviewer_returns_repair_plan_for_semantic_reject(self, mocker):
        """Reviewer should return repair_plan with reject decision."""
        mock_chat = mocker.patch("clipper_agency.llm.client.OpenRouterClient.chat")
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
            },
            diagnostics={
                "semantic_review": {
                    "decision": "reject",
                    "patches": [],
                }
            },
        )

        assert result["status"] == "fail"
        assert result["reason"] == "SEMANTIC_REVIEW_FAILED"
        assert result["repair_plan"]["decision"] == "reject"
        mock_chat.assert_not_called()

    def test_reviewer_allows_llm_when_semantic_accept(self, mocker):
        """Reviewer should proceed to LLM when semantic review accepts."""
        mock_chat = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 90, "feedback": "OK", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
            },
            diagnostics={
                "semantic_review": {
                    "decision": "accept",
                    "patches": [],
                }
            },
        )

        assert result["status"] == "pass"
        mock_chat.assert_called_once()

    def test_reviewer_skips_semantic_gate_when_no_diagnostics(self, mocker):
        """Reviewer should skip semantic gate when no diagnostics provided."""
        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient.chat",
            return_value={
                "content": '{"verdict": "pass", "score": 85, "feedback": "OK", "issues": []}',
                "model": "test",
                "usage": {},
            },
        )
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=1,
            topic="test topic",
            context={
                "audio_duration_sec": 20.0,
                "visual_duration_sec": 20.0,
            },
        )

        assert result["status"] == "pass"
