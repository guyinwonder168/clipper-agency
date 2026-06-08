"""Regression tests for Job #4 quality failures.

These tests encode the 5 failure modes found in logs/run-job_4.log so we
never regress on them.  Each test exercises the failure at the unit level
using the actual method signatures, not the mocked-APIs from the task spec.
"""

import pytest

from clipper_agency.agents.composer import ComposerAgent
from clipper_agency.agents.reviewer import (
    ReviewerAgent,
    _check_av_sync,
)
from clipper_agency.agents.segment_producer import SegmentProducerAgent
from clipper_agency.agents.visual_director import VisualDirectorAgent


# ---------------------------------------------------------------------------
# Failure Mode 1: Duplicate URL Dedup Repair
# ---------------------------------------------------------------------------


class TestDuplicateURLDedupRepair:
    """Visual Director resolves duplicate TikTok URLs via replacement, not deletion.

    When two beats share the same source_url, the dedup must replace the
    duplicate with an alternate candidate — never leave a ``tiktok_clip``
    action without a ``source_url``.
    """

    def test_dedup_replaces_duplicate_url_with_alternate_candidate(self):
        """Beat 2 reuses the same URL as Beat 1 — resolver picks alternate from asset_candidates."""
        director = VisualDirectorAgent()

        plan = [
            {
                "scene_number": 1,
                "beat_id": 1,
                "role": "main_claim",
                "target_duration_sec": 8.0,
                "action": {"type": "tiktok_clip", "source_url": "https://tk.com/@user/video/001"},
                "asset_candidates": [
                    {"url": "https://tk.com/@user/video/001", "type": "tiktok_clip",
                     "title": "Matching"},
                ],
            },
            {
                "scene_number": 2,
                "beat_id": 2,
                "role": "supporting_context",
                "target_duration_sec": 6.0,
                "action": {"type": "tiktok_clip", "source_url": "https://tk.com/@user/video/001"},
                "asset_candidates": [
                    {"url": "https://tk.com/@user/video/001", "type": "tiktok_clip",
                     "title": "Duplicate"},
                    {"url": "https://tk.com/@user/video/002", "type": "tiktok_clip",
                     "title": "Alternate"},
                ],
            },
        ]

        resolved = director._resolve_beat_plan_assets(plan, do_not_use=[])

        # Beat 1 keeps its URL
        assert resolved[0]["action"]["source_url"] == "https://tk.com/@user/video/001"
        # Beat 2 gets the alternate URL
        assert resolved[1]["action"]["source_url"] == "https://tk.com/@user/video/002"

    def test_dedup_never_leaves_broken_tiktok_action(self):
        """No usable candidate → action falls back to text_card, not broken tiktok_clip."""
        director = VisualDirectorAgent()

        plan = [
            {
                "scene_number": 1,
                "beat_id": 1,
                "role": "main_claim",
                "target_duration_sec": 8.0,
                "action": {"type": "tiktok_clip", "source_url": "https://tk.com/@user/video/001"},
                "asset_candidates": [
                    {"url": "https://tk.com/@user/video/001", "type": "tiktok_clip",
                     "title": "Sole candidate"},
                ],
            },
            {
                "scene_number": 2,
                "beat_id": 2,
                "role": "supporting_context",
                "target_duration_sec": 6.0,
                # Same URL as beat 1, and no alternate candidates
                "action": {"type": "tiktok_clip", "source_url": "https://tk.com/@user/video/001"},
                "asset_candidates": [
                    {"url": "https://tk.com/@user/video/001", "type": "tiktok_clip",
                     "title": "Duplicate"},
                ],
            },
        ]

        resolved = director._resolve_beat_plan_assets(plan, do_not_use=[])

        # Beat 2: since the URL was already used, and there's no alternate,
        # the action must NOT be a broken tiktok_clip
        action2 = resolved[1]["action"]
        assert action2.get("type") != "tiktok_clip" or action2.get("source_url") is not None
        # The fix should have converted it to text_card
        assert action2.get("type") == "text_card"
        assert "No usable source URL" in action2.get("reason", "")

    def test_dedup_honours_do_not_use_blocklist(self):
        """URLs listed in do_not_use must be replaced even if not yet used."""
        director = VisualDirectorAgent()

        plan = [
            {
                "scene_number": 1,
                "beat_id": 1,
                "role": "main_claim",
                "target_duration_sec": 8.0,
                "action": {"type": "tiktok_clip", "source_url": "https://tk.com/@user/video/blocked"},
                "asset_candidates": [
                    {"url": "https://tk.com/@user/video/blocked", "type": "tiktok_clip"},
                    {"url": "https://tk.com/@user/video/safe", "type": "tiktok_clip"},
                ],
            },
        ]

        resolved = director._resolve_beat_plan_assets(plan, do_not_use=["https://tk.com/@user/video/blocked"])

        assert resolved[0]["action"]["source_url"] == "https://tk.com/@user/video/safe"


# ---------------------------------------------------------------------------
# Failure Mode 2: Composer Duration Guard
# ---------------------------------------------------------------------------


class TestComposerDurationRegression:
    """Composer never returns video shorter than voiceover audio.

    The guard lives in ``_try_assemble`` (called from ``execute``) and compares
    ``_probe_output_duration`` result against ``voiceover_duration_sec``.
    We patch ``_probe_output_duration`` directly to avoid import-reference
    issues with ``probe_video``.
    """

    @staticmethod
    def _setup_common_mocks(mocker):
        """Apply all preflight/scene/ffmpeg mocks shared by duration tests."""
        mock_preflight = mocker.MagicMock()
        mock_preflight.ffmpeg_found = True
        mock_preflight.ffprobe_found = True
        mock_preflight.libx264_available = True
        mock_preflight.aac_available = True
        mock_preflight.mp3_decode_available = True
        mock_preflight.all_ok.return_value = True
        mocker.patch(
            "clipper_agency.core.ffmpeg_preflight.FFmpegPreflight.probe",
            return_value=mock_preflight,
        )
        mocker.patch("dataclasses.asdict", return_value={"ffmpeg_found": True})
        mocker.patch(
            "clipper_agency.core.scene_validator.SceneValidator.validate",
            return_value=mocker.MagicMock(valid=True, issues=[]),
        )
        mocker.patch(
            "clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
            return_value=mocker.MagicMock(success=True, error=""),
        )
        mocker.patch(
            "clipper_agency.agents.composer.run_ffmpeg_streaming", return_value=0,
        )

    def test_guard_flags_failed_when_output_probed_short(self, mocker):
        """_probe_output_duration returns 21.21s < voiceover 23.25s → guard fails."""
        self._setup_common_mocks(mocker)

        # Patch _probe_output_duration to return shorter-than-audio value
        mocker.patch.object(
            ComposerAgent, "_probe_output_duration", return_value=21.21,
        )

        agent = ComposerAgent()
        result = agent.execute(
            job_id=99,
            assets=[{"scene": 1, "path": "/tmp/scene_1.mp4"}],
            audio_files=["/tmp/voiceover.mp3"],
            output_dir="/tmp",
            voiceover_duration_sec=23.25,
        )

        # Duration guard must trigger
        assert result.get("status") == "failed", (
            f"Expected failed when output 21.21s < voiceover 23.25s, got {result.get('status')}"
        )
        assert "shorter than voiceover" in result.get("error", "").lower()

    def test_guard_passes_when_output_probed_covers_audio(self, mocker):
        """_probe_output_duration returns 30s >= voiceover 23.25s → guard passes."""
        self._setup_common_mocks(mocker)

        # Patch _probe_output_duration to return >= voiceover value
        mocker.patch.object(
            ComposerAgent, "_probe_output_duration", return_value=30.0,
        )

        agent = ComposerAgent()
        result = agent.execute(
            job_id=100,
            assets=[{"scene": 1, "path": "/tmp/scene_1.mp4"}],
            audio_files=["/tmp/voiceover.mp3"],
            output_dir="/tmp",
            voiceover_duration_sec=23.25,
        )

        assert result.get("status") == "completed"
        assert result["output_duration_sec"] >= 23.25


# ---------------------------------------------------------------------------
# Failure Mode 3: Reviewer Hard Gates
# ---------------------------------------------------------------------------


class TestReviewerHardGateRegression:
    """Reviewer programmatic hard gates catch Job #4-style metadata violations.

    These test ``_check_hard_gates`` directly — lower-level than the existing
    ``TestReviewerHardGates`` (which exercises via ``execute()`` with LLM mocks).
    """

    def test_hard_gate_fails_when_video_shorter_than_audio(self):
        """Video 21.21s < audio 23.25s → hard gate must fail."""
        reviewer = ReviewerAgent()

        # Build checks dict as ReviewerAgent.execute() does
        av_sync = _check_av_sync(audio_duration=23.25, visual_duration=21.21)
        checks = {"av_sync": av_sync}

        result = reviewer._check_hard_gates(
            checks=checks,
            audio_duration_sec=23.25,
            visual_duration_sec=21.21,
            visual_plan_actions=[{"type": "tiktok_clip", "source_url": "https://tk.com/ok"}],
        )

        assert result is not None, "Hard gate should trigger when video < audio"
        assert result["status"] == "fail"
        assert result["score"] == 0
        assert "av_duration_mismatch" in result["issues"]

    def test_hard_gate_passes_when_video_covers_audio(self):
        """Video 25s >= audio 23s → hard gate should pass (return None)."""
        reviewer = ReviewerAgent()

        av_sync = _check_av_sync(audio_duration=23.0, visual_duration=25.0)
        checks = {"av_sync": av_sync}

        result = reviewer._check_hard_gates(
            checks=checks,
            audio_duration_sec=23.0,
            visual_duration_sec=25.0,
            visual_plan_actions=[{"type": "text_card", "headline": "Story 1"}],
        )

        assert result is None, f"Hard gate should pass when video >= audio, got {result}"

    def test_hard_gate_fails_broken_tiktok_clip(self):
        """tiktok_clip action without source_url → hard gate must fail."""
        reviewer = ReviewerAgent()

        av_sync = _check_av_sync(audio_duration=23.25, visual_duration=23.25)
        checks = {"av_sync": av_sync}

        result = reviewer._check_hard_gates(
            checks=checks,
            audio_duration_sec=23.25,
            visual_duration_sec=23.25,
            visual_plan_actions=[
                {"type": "tiktok_clip"},  # broken: no source_url
                {"type": "text_card", "headline": "Story 2"},
            ],
        )

        assert result is not None, "Hard gate should trigger on broken tiktok_clip action"
        assert result["status"] == "fail"
        assert "broken_tiktok_clip_action" in result["issues"]

    def test_hard_gate_passes_when_durations_equal(self):
        """Video 23.25s == audio 23.25s → av_sync passes, hard gate passes."""
        reviewer = ReviewerAgent()

        av_sync = _check_av_sync(audio_duration=23.25, visual_duration=23.25)
        checks = {"av_sync": av_sync}

        result = reviewer._check_hard_gates(
            checks=checks,
            audio_duration_sec=23.25,
            visual_duration_sec=23.25,
            visual_plan_actions=[{"type": "tiktok_clip", "source_url": "https://tk.com/ok"}],
        )

        assert result is None, f"Hard gate should pass when durations equal, got {result}"


# ---------------------------------------------------------------------------
# Failure Mode 4: Intro Card Contract
# ---------------------------------------------------------------------------


class TestIntroCardRegression:
    """Intro card exists for roundup formats, absent for non-roundup.

    Covers both ``three_story_roundup`` and ``two_story_highlight`` formats.
    """

    def test_intro_card_present_for_three_story_roundup(self):
        """three_story_roundup must include intro card scene 0."""
        director = VisualDirectorAgent()

        plan = director._plan_intro_card(
            story_beats=[{"beat_id": 1, "role": "story_1"}],
            video_format="three_story_roundup",
            topic="Top 3 Drama Artis Hari Ini",
        )

        assert plan is not None, "Intro card should exist for three_story_roundup"
        assert plan["scene_number"] == 0
        assert plan["role"] == "intro_card"
        assert plan["action"]["type"] == "text_card"
        assert plan["action"]["headline"] == "Top 3 Drama Artis Hari Ini"

    def test_intro_card_present_for_two_story_highlight(self):
        """two_story_highlight is also a roundup format → must include intro card."""
        director = VisualDirectorAgent()

        plan = director._plan_intro_card(
            story_beats=[{"beat_id": 1, "role": "story_1"}, {"beat_id": 2, "role": "story_2"}],
            video_format="two_story_highlight",
            topic="Dua Drama Viral",
        )

        assert plan is not None, "Intro card should exist for two_story_highlight"
        assert plan["scene_number"] == 0

    def test_intro_card_absent_for_single_story_deep_dive(self):
        """single_story_deep_dive must skip intro card."""
        director = VisualDirectorAgent()

        plan = director._plan_intro_card(
            story_beats=[{"beat_id": 1, "role": "main_claim"}],
            video_format="single_story_deep_dive",
            topic="Drama Sarwendah",
        )

        assert plan is None, "Intro card should NOT exist for single_story_deep_dive"

    def test_intro_card_absent_for_unknown_format(self):
        """Non-roundup formats (including unrecognized) must NOT produce intro card."""
        director = VisualDirectorAgent()

        plan = director._plan_intro_card(
            story_beats=[{"beat_id": 1, "role": "hook"}],
            video_format="unknown_format_xyz",
            topic="Test",
        )

        assert plan is None, "Intro card should NOT exist for unrecognized format"


# ---------------------------------------------------------------------------
# Failure Mode 5: Watermark-Free URL Preference
# ---------------------------------------------------------------------------


class TestWatermarkFreeURLRegression:
    """Segment Producer prefers ``download_no_watermark_addr`` when available.

    These are direct unit tests on ``_build_asset_portfolio``, complementing
    the existing ``TestSegmentProducerAssetPortfolio`` class.
    """

    def test_no_watermark_url_chosen_in_download_url_field(self):
        """ScrapeCreators result with download_no_watermark_addr → preferred download_url."""
        agent = SegmentProducerAgent()

        portfolio = agent._build_asset_portfolio(
            scrapecreators_results=[
                {
                    "url": "https://www.tiktok.com/@user/video/123",
                    "download_url": "https://dl.example.com/watermarked.mp4",
                    "download_no_watermark_addr": "https://dl.example.com/clean.mp4",
                    "title": "Test Video",
                    "play_count": 10000,
                },
            ],
            firecrawl_results=[],
            beat_keywords=["test", "video"],
        )

        tiktok_candidates = [c for c in portfolio if c.get("source") == "scrapecreators"]
        assert len(tiktok_candidates) >= 1, "Expected at least one ScrapeCreators candidate"

        # The candidate must prefer the no-watermark URL
        candidate = tiktok_candidates[0]
        assert candidate["download_url"] == "https://dl.example.com/clean.mp4", (
            f"Expected no-watermark URL as download_url, got {candidate.get('download_url')}"
        )
        assert candidate["download_url_type"] == "no_watermark", (
            f"Expected download_url_type='no_watermark', got {candidate.get('download_url_type')}"
        )

    def test_falls_back_to_regular_download_url_when_no_watermark_missing(self):
        """ScrapeCreators result without download_no_watermark_addr → use download_url."""
        agent = SegmentProducerAgent()

        portfolio = agent._build_asset_portfolio(
            scrapecreators_results=[
                {
                    "url": "https://www.tiktok.com/@user/video/456",
                    "download_url": "https://dl.example.com/watermarked.mp4",
                    "title": "Test Video 2",
                    "play_count": 5000,
                },
            ],
            firecrawl_results=[],
            beat_keywords=["test"],
        )

        tiktok_candidates = [c for c in portfolio if c.get("source") == "scrapecreators"]
        assert len(tiktok_candidates) >= 1

        candidate = tiktok_candidates[0]
        assert candidate["download_url"] == "https://dl.example.com/watermarked.mp4"
        assert candidate["download_url_type"] == "standard"

    def test_falls_back_to_canonical_url_when_no_download_urls_at_all(self):
        """ScrapeCreators result with only a url → canonical becomes download_url."""
        agent = SegmentProducerAgent()

        portfolio = agent._build_asset_portfolio(
            scrapecreators_results=[
                {
                    "url": "https://www.tiktok.com/@user/video/789",
                    "title": "Test Video 3",
                    "play_count": 3000,
                },
            ],
            firecrawl_results=[],
            beat_keywords=["test"],
        )

        tiktok_candidates = [c for c in portfolio if c.get("source") == "scrapecreators"]
        assert len(tiktok_candidates) >= 1

        candidate = tiktok_candidates[0]
        # Fallback to canonical URL
        assert candidate["download_url"] == "https://www.tiktok.com/@user/video/789"
        assert candidate["download_url_type"] == "canonical"

