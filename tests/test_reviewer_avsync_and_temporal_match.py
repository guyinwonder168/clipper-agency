"""RC-2 + RC-4: symmetrize AV-sync hard gate and wire temporal_match at default weight 0.0.

PR 16 (RC-2): The AV-drift hard gate was asymmetric — it only hard-failed when
``visual_duration_sec < audio_duration_sec``. The opposite drift direction
(video LONGER than audio — e.g. a trailing clip / over-long scene) fell through
to the non-deterministic LLM. This test asserts the SYMMETRIC branch hard-fails
with the same ``av_duration_mismatch`` issue type.

PR 14.B (RC-4): ``score_visual_relevance`` previously discarded the
``temporal_match`` signal the VLM returns. It now reads ``temporal_match`` into
the weighted sum with a new weight that DEFAULTS to 0.0 — so at the default the
accept/revise/reject behavior is byte-identical whether temporal_match is 0.0 or
1.0. This guards the no-behavior-change invariant.
"""

import pytest

from clipper_agency.agents.reviewer import ReviewerAgent
from clipper_agency.core.semantic_visual_review import score_visual_relevance


def _patch_reviewer_llm(mocker, verdict: str = "pass", score: int = 90):
    """Patch the OpenRouter client + agent config so the LLM is bypassed/canned."""
    mocker.patch(
        "clipper_agency.llm.client.OpenRouterClient.chat",
        return_value={
            "content": (
                f'{{"verdict": "{verdict}", "score": {score}, "feedback": "canned", "issues": []}}'
            ),
            "model": "test",
            "usage": {},
        },
    )
    mocker.patch(
        "clipper_agency.agents.reviewer.get_agent_config",
        return_value={
            "model": "test-model",
            "temperature": 0.3,
            "max_completion_tokens": 500,
        },
    )


# ---------------------------------------------------------------------------
# RC-2: symmetric AV-drift hard gate (PR 16)
# ---------------------------------------------------------------------------


class TestAVSyncSymmetricHardGate:
    """The AV-drift hard gate must fire in BOTH drift directions."""

    def test_video_longer_than_audio_hard_fails(self, mocker):
        """RC-2: visual - audio > tolerance must hard-fail with av_duration_mismatch.

        Mirror of the existing shorter-than test. A trailing clip / over-long
        scene is a real drift direction and must not fall through to the LLM.
        """
        _patch_reviewer_llm(mocker, verdict="pass", score=90)
        agent = ReviewerAgent()
        # audio=21.21s, visual=23.25s -> drift=2.04s > 0.5s tolerance,
        # and visual is LONGER than audio (the previously-unguarded direction).
        result = agent.execute(
            job_id=5,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Great video #test",
            context={
                "audio_duration_sec": 21.21,
                "visual_duration_sec": 23.25,
            },
        )
        assert result["status"] == "fail", (
            "Reviewer should hard-fail when video (23.25s) is longer than audio "
            f"(21.21s) by more than the drift tolerance, got status="
            f"{result['status']} score={result.get('score')}"
        )
        assert "av_duration_mismatch" in result["issues"], (
            f"Expected 'av_duration_mismatch' in issues, got {result.get('issues')}"
        )

    def test_video_shorter_than_audio_still_hard_fails(self, mocker):
        """RC-2 regression guard: the pre-existing shorter-than branch is unchanged."""
        _patch_reviewer_llm(mocker, verdict="pass", score=90)
        agent = ReviewerAgent()
        result = agent.execute(
            job_id=6,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Great video #test",
            context={
                "audio_duration_sec": 23.25,
                "visual_duration_sec": 21.21,
            },
        )
        assert result["status"] == "fail"
        assert "av_duration_mismatch" in result["issues"]

    def test_within_tolerance_does_not_hard_fail(self, mocker):
        """RC-2: drift within tolerance must NOT trip the hard gate (no over-firing)."""
        _patch_reviewer_llm(mocker, verdict="pass", score=90)
        agent = ReviewerAgent()
        # audio=22.0s, visual=22.3s -> drift=0.3s < 0.5s tolerance (video longer,
        # but within tolerance) -> must NOT hard-fail on the symmetric branch.
        result = agent.execute(
            job_id=7,
            topic="Test topic",
            script=[{"scene": 1, "text": "Hello"}],
            caption="Great video #test",
            context={
                "audio_duration_sec": 22.0,
                "visual_duration_sec": 22.3,
            },
        )
        assert "av_duration_mismatch" not in result.get("issues", []), (
            "Symmetric branch must respect the same tolerance — within-tolerance "
            f"video-longer drift should not hard-fail. issues={result.get('issues')}"
        )


# ---------------------------------------------------------------------------
# RC-4: temporal_match wired at default weight 0.0 (PR 14.B)
# ---------------------------------------------------------------------------


class TestTemporalMatchDefaultWeightZero:
    """At the default temporal_match weight (0.0), scoring is byte-identical."""

    @pytest.mark.parametrize(
        "inspection",
        [
            # accept-region
            {
                "person_match": 0.95,
                "event_match": 0.90,
                "claim_support": 0.85,
                "visual_quality": 0.80,
            },
            # revise-region
            {
                "person_match": 0.60,
                "event_match": 0.50,
                "claim_support": 0.55,
                "visual_quality": 0.70,
            },
            # reject-region (low score)
            {
                "person_match": 0.20,
                "event_match": 0.25,
                "claim_support": 0.30,
                "visual_quality": 0.35,
            },
            # misleading-risk reject
            {
                "person_match": 0.96,
                "event_match": 0.30,
                "claim_support": 0.20,
                "visual_quality": 0.82,
            },
        ],
    )
    def test_score_unchanged_regardless_of_temporal_match_at_default_weight(self, inspection):
        """A 0.0-weighted temporal_match term cannot move the score.

        At the default weight, score_visual_relevance must be byte-identical
        whether temporal_match is 0.0 or 1.0. This guards the
        no-behavior-change invariant for PR 14.B; raising the weight and
        asserting a lowering effect is a separate follow-up.
        """
        beat = {"beat_id": "B01", "claim": {"subject": "S", "action": "a"}}

        # Baseline: temporal_match absent (legacy callers).
        score_baseline = score_visual_relevance(beat=beat, asset_inspection=dict(inspection))
        # temporal_match = 0.0
        score_zero = score_visual_relevance(
            beat=beat,
            asset_inspection={**inspection, "temporal_match": 0.0},
        )
        # temporal_match = 1.0
        score_one = score_visual_relevance(
            beat=beat,
            asset_inspection={**inspection, "temporal_match": 1.0},
        )

        # Byte-identical: decision, every numeric field, and detail string.
        assert score_zero.decision == score_baseline.decision == score_one.decision
        assert score_zero.misleading_risk == score_baseline.misleading_risk
        assert score_one.misleading_risk == score_baseline.misleading_risk
        assert score_zero.person_match == score_one.person_match
        assert score_zero.event_match == score_one.event_match
        assert score_zero.claim_support == score_one.claim_support
        assert score_zero.visual_quality == score_one.visual_quality
        # The detail string embeds the combined score; equality proves byte-identity.
        assert score_zero.detail == score_one.detail == score_baseline.detail
