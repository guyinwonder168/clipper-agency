"""Tests for Visual Director beat-driven planning (audio-first architecture)."""

import json

import pytest

from clipper_agency.agents.visual_director import (
    VisualDirectorAgent,
    _is_abstract_beat,
    topic_safe_query,
)
from clipper_agency.config.schema import (
    AssetCandidate,
    BeatFallback,
    StoryBeat,
    WordTimestamp,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_beat(
    beat_id: int = 1,
    role: str = "main_claim",
    narration_goal: str = "Tell the viewer about the artist's latest release",
    spoken_point: str = "Artist X just released a new album",
    visual_must_show: str = "Artist X portrait or album cover",
    visual_must_not_show: str = "",
    overlay_text: str = "NEW ALBUM DROP",
    caption_keywords: list[str] | None = None,
    asset_candidates: list[dict] | None = None,
    fallback: dict | None = None,
    risk_note: str = "",
) -> dict:
    """Create a story beat dict matching StoryBeat schema."""
    return {
        "beat_id": beat_id,
        "role": role,
        "narration_goal": narration_goal,
        "spoken_point": spoken_point,
        "safe_wording": spoken_point,
        "visual_must_show": visual_must_show,
        "visual_must_not_show": visual_must_not_show,
        "overlay_text": overlay_text,
        "caption_keywords": caption_keywords or ["trending", "album"],
        "asset_candidates": asset_candidates or [],
        "fallback": fallback or {
            "type": "text_card",
            "headline": f"Beat {beat_id}",
            "image_search": "music artist",
        },
        "risk_note": risk_note,
    }


def _make_timestamps() -> list[dict]:
    """Create word timestamps spanning ~14 seconds."""
    return [
        {"word": "Artist", "start": 0.0, "end": 0.4},
        {"word": "X", "start": 0.4, "end": 0.6},
        {"word": "just", "start": 0.6, "end": 0.9},
        {"word": "released", "start": 0.9, "end": 1.4},
        {"word": "a", "start": 1.4, "end": 1.5},
        {"word": "new", "start": 1.5, "end": 1.8},
        {"word": "album", "start": 1.8, "end": 2.3},
        {"word": "It", "start": 2.5, "end": 2.6},
        {"word": "is", "start": 2.6, "end": 2.8},
        {"word": "amazing", "start": 2.8, "end": 3.3},
        {"word": "Everyone", "start": 3.5, "end": 4.0},
        {"word": "is", "start": 4.0, "end": 4.2},
        {"word": "talking", "start": 4.2, "end": 4.7},
        {"word": "about", "start": 4.7, "end": 5.1},
        {"word": "it", "start": 5.1, "end": 5.3},
    ]


# ---------------------------------------------------------------------------
# Beat duration calculation
# ---------------------------------------------------------------------------


class TestCalculateBeatDurations:
    """Beat duration calculation from word timestamps."""

    def test_exact_durations_from_word_matching(self):
        agent = VisualDirectorAgent()
        beats = [StoryBeat(**_make_beat(overlay_text="Artist X just released"))]
        timestamps = [WordTimestamp(**t) for t in _make_timestamps()]

        durations = agent._calculate_beat_durations(beats, timestamps)

        assert 1 in durations
        # "Artist" start=0.0 to "released" end=1.4
        assert durations[1] == 1.4

    def test_multiple_beats_get_separate_durations(self):
        agent = VisualDirectorAgent()
        beats = [
            StoryBeat(**_make_beat(beat_id=1, overlay_text="Artist X just released")),
            StoryBeat(**_make_beat(beat_id=2, overlay_text="It is amazing")),
        ]
        timestamps = [WordTimestamp(**t) for t in _make_timestamps()]

        durations = agent._calculate_beat_durations(beats, timestamps)

        assert durations[1] == 1.4  # "Artist" → "released"
        assert durations[2] == 0.8  # "It"(2.5) → "amazing"(3.3)

    def test_zero_duration_beats_get_even_distribution(self):
        agent = VisualDirectorAgent()
        beats = [
            StoryBeat(**_make_beat(beat_id=1, overlay_text="")),
            StoryBeat(**_make_beat(beat_id=2, overlay_text="")),
        ]
        timestamps = [WordTimestamp(**t) for t in _make_timestamps()]

        durations = agent._calculate_beat_durations(beats, timestamps)

        # Both should get equal share of total duration
        assert durations[1] > 0
        assert durations[2] > 0
        # Both should be roughly equal
        assert abs(durations[1] - durations[2]) < 0.01

    def test_empty_timestamps(self):
        agent = VisualDirectorAgent()
        beats = [StoryBeat(**_make_beat(overlay_text="Hello world"))]
        durations = agent._calculate_beat_durations(beats, [])

        assert durations[1] == 0.0


# ---------------------------------------------------------------------------
# Visual selection hierarchy
# ---------------------------------------------------------------------------


class TestVisualHierarchy:
    """Visual priority: source clip > screenshot > portrait > text card > stock."""

    def test_source_clip_highest_priority(self):
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            asset_candidates=[
                {"type": "tiktok_clip", "url": "https://tiktok.com/v/1", "reason": "viral clip"},
                {"type": "screenshot", "url": "https://img.com/1.jpg", "reason": "album cover"},
            ],
        ))

        action = agent._select_visual_for_beat(beat, [])
        assert action["type"] == "tiktok_clip"
        assert action["source_url"] == "https://tiktok.com/v/1"

    def test_screenshot_when_no_clip(self):
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            asset_candidates=[
                {"type": "screenshot", "url": "https://img.com/1.jpg", "reason": "album cover"},
            ],
        ))

        action = agent._select_visual_for_beat(beat, [])
        assert action["type"] == "pexels_image"
        assert "source_url" in action

    def test_portrait_search_when_no_assets(self):
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            visual_must_show="Artist X portrait",
            fallback={"type": "ken_burns_photo", "headline": "Artist X", "image_search": "Artist X singer"},
        ))

        action = agent._select_visual_for_beat(beat, [])
        assert action["type"] == "pexels_image"
        assert "search_query" in action

    def test_text_card_fallback_when_no_search(self):
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            visual_must_show="",
            spoken_point="Some abstract concept about trends",
            overlay_text="TRENDING NOW",
            fallback={"type": "text_card", "headline": "TRENDING NOW", "image_search": ""},
        ))

        action = agent._select_visual_for_beat(beat, [])
        assert action["type"] == "text_card"
        assert "headline" in action


# ---------------------------------------------------------------------------
# do_not_use enforcement
# ---------------------------------------------------------------------------


class TestDoNotUseEnforcement:
    """URLs on the do_not_use list must never be selected."""

    def test_blocked_url_skipped(self):
        agent = VisualDirectorAgent()
        blocked_url = "https://tiktok.com/v/blocked"
        beat = StoryBeat(**_make_beat(
            asset_candidates=[
                {"type": "tiktok_clip", "url": blocked_url, "reason": "blocked clip"},
                {"type": "screenshot", "url": "https://img.com/ok.jpg", "reason": "ok image"},
            ],
        ))

        action = agent._select_visual_for_beat(beat, [blocked_url])
        # Should skip the tiktok_clip and use screenshot
        assert action.get("source_url") != blocked_url
        assert action["type"] == "pexels_image"

    def test_all_urls_blocked_falls_to_search(self):
        agent = VisualDirectorAgent()
        blocked_url = "https://tiktok.com/v/blocked"
        beat = StoryBeat(**_make_beat(
            asset_candidates=[
                {"type": "tiktok_clip", "url": blocked_url, "reason": "blocked clip"},
            ],
            fallback={"type": "ken_burns_photo", "headline": "Artist", "image_search": "singer portrait"},
        ))

        action = agent._select_visual_for_beat(beat, [blocked_url])
        assert action.get("source_url") != blocked_url


# ---------------------------------------------------------------------------
# Asset candidate priority over Pexels
# ---------------------------------------------------------------------------


class TestAssetCandidatePriority:
    """Asset candidates from Segment Producer take priority over Pexels search."""

    def test_uses_segment_producer_assets_first(self):
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            asset_candidates=[
                {"type": "tiktok_clip", "url": "https://tiktok.com/v/research", "reason": "researched clip"},
            ],
        ))

        action = agent._select_visual_for_beat(beat, [])
        assert action["type"] == "tiktok_clip"
        assert action["source_url"] == "https://tiktok.com/v/research"

    def test_no_asset_candidates_uses_pexels(self):
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            asset_candidates=[],
            visual_must_show="Artist portrait",
            fallback={"type": "ken_burns_photo", "headline": "Artist", "image_search": "singer"},
        ))

        action = agent._select_visual_for_beat(beat, [])
        # Falls through to Pexels image search
        assert "search_query" in action


# ---------------------------------------------------------------------------
# Full beat-driven execution
# ---------------------------------------------------------------------------


class TestBeatDrivenExecute:
    """Full execute() with beat-driven path."""

    def test_execute_with_beats_and_timestamps(self, mocker, tmp_path):
        """Beat-driven path is selected when story_beats + timestamps are present."""
        mock_pexels = mocker.patch(
            "clipper_agency.agents.visual_director.PexelsService",
        )
        mock_pexels.return_value.search_photos.return_value = []
        mock_ytdlp = mocker.patch(
            "clipper_agency.agents.visual_director.YtDlpService",
        )
        mock_ytdlp.return_value.download.return_value = None

        mock_llm = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient",
        )
        mock_llm.return_value.chat.return_value = {
            "content": json.dumps({
                "scenes": [
                    {
                        "scene_number": 1,
                        "beat_id": 1,
                        "role": "hook",
                        "reasoning": "Use viral clip",
                        "treatment": "hook_big_caption",
                        "target_duration": 2.3,
                        "transition_in": "hard_cut",
                        "transition_out": "crossfade",
                        "action": {"type": "text_card", "headline": "NEW ALBUM", "style": "breaking_news", "image_search": "album cover"},
                        "fallback": {"type": "text_card", "headline": "ALBUM", "style": "news_card", "image_search": "music"},
                    },
                ]
            }),
            "model": "test",
            "usage": {},
        }
        mocker.patch(
            "clipper_agency.agents.prompts.load_prompt",
            return_value="You are a Visual Director for {content_angle} content.",
        )
        mocker.patch(
            "clipper_agency.config.loader.load_settings",
        )

        agent = VisualDirectorAgent()
        result = agent.execute(
            job_id=1,
            topic="Artist X",
            output_dir=str(tmp_path),
            story_beats=[_make_beat(overlay_text="Artist X just released")],
            timestamps=_make_timestamps(),
            do_not_use=["https://bad.url"],
            voiceover_duration_sec=5.3,
        )

        assert result["status"] == "completed"
        assert len(result["assets"]) == 1
        assert result["assets"][0]["scene"] == 1

    def test_execute_beat_driven_persists_artifacts(self, mocker, tmp_path):
        """Beat-driven execution writes input/output/provenance to agent dir."""
        mock_pexels = mocker.patch(
            "clipper_agency.agents.visual_director.PexelsService",
        )
        mock_pexels.return_value.search_photos.return_value = []
        mock_ytdlp = mocker.patch(
            "clipper_agency.agents.visual_director.YtDlpService",
        )

        mock_llm = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient",
        )
        mock_llm.return_value.chat.return_value = {
            "content": json.dumps({
                "scenes": [
                    {
                        "scene_number": 1,
                        "beat_id": 1,
                        "role": "hook",
                        "reasoning": "Text card hook",
                        "treatment": "hook_big_caption",
                        "target_duration": 3.0,
                        "transition_in": "hard_cut",
                        "transition_out": "crossfade",
                        "action": {"type": "text_card", "headline": "NEWS", "style": "news_card", "image_search": "test"},
                    },
                ]
            }),
            "model": "test",
            "usage": {},
        }
        mocker.patch(
            "clipper_agency.agents.prompts.load_prompt",
            return_value="You are a Visual Director for {content_angle} content.",
        )
        mocker.patch(
            "clipper_agency.config.loader.load_settings",
        )

        assets_cache = tmp_path / "assets"
        assets_cache.mkdir()

        agent = VisualDirectorAgent()
        result = agent.execute(
            job_id=50,
            topic="Test",
            output_dir=str(tmp_path),
            assets_cache=str(assets_cache),
            story_beats=[_make_beat()],
            timestamps=_make_timestamps(),
            voiceover_duration_sec=5.3,
        )

        assert result["status"] == "completed"
        input_file = (
            assets_cache / "job_50" / "agents" / "visual_director" / "input.json"
        )
        assert input_file.exists()
        data = json.loads(input_file.read_text())
        assert data["beat_driven"] is True


# ---------------------------------------------------------------------------
# Fallback deterministic plan
# ---------------------------------------------------------------------------


class TestBeatFallbackPlan:
    """Deterministic fallback when LLM fails."""

    def test_fallback_uses_hierarchy(self):
        """Fallback plan selects visuals using the hierarchy."""
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            beat_id=1,
            role="hook",
            asset_candidates=[
                {"type": "tiktok_clip", "url": "https://tiktok.com/v/1", "reason": "viral"},
            ],
        ))
        beat_durations = {1: 3.5}

        plan = agent._plan_beats_fallback([beat], beat_durations, [])

        assert len(plan) == 1
        assert plan[0]["action"]["type"] == "tiktok_clip"
        assert plan[0]["target_duration"] == 3.5

    def test_fallback_hook_gets_hook_treatment(self):
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(beat_id=1, role="hook"))
        plan = agent._plan_beats_fallback([beat], {1: 3.0}, [])

        assert plan[0]["treatment"] == "hook_big_caption"

    def test_fallback_closing_cta_gets_fade(self):
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(beat_id=3, role="closing_cta"))
        plan = agent._plan_beats_fallback([beat], {3: 4.0}, [])

        assert plan[0]["treatment"] == "fade_to_black"

    def test_fallback_text_card_includes_overlay(self):
        """Abstract beats with no assets fall to text_card with overlay text."""
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            beat_id=2,
            role="main_claim",
            narration_goal="Discuss the general trend",
            spoken_point="This is a general phenomenon",
            overlay_text="BIG ANNOUNCEMENT",
            asset_candidates=[],
        ))
        plan = agent._plan_beats_fallback([beat], {2: 5.0}, [])

        # Abstract beat with no assets → should fall to text_card
        assert plan[0]["action"]["type"] == "text_card"
        assert "ANNOUNCEMENT" in plan[0]["action"]["headline"]

    def test_fallback_respects_do_not_use(self):
        agent = VisualDirectorAgent()
        blocked = "https://tiktok.com/v/blocked"
        beat = StoryBeat(**_make_beat(
            asset_candidates=[
                {"type": "tiktok_clip", "url": blocked, "reason": "bad"},
            ],
        ))
        plan = agent._plan_beats_fallback([beat], {1: 3.0}, [blocked])

        assert plan[0]["action"].get("source_url") != blocked


# ---------------------------------------------------------------------------
# Output contract compatibility with composer
# ---------------------------------------------------------------------------


class TestComposerOutputContract:
    """Beat-driven output must be compatible with composer expectations."""

    def test_output_has_required_fields(self, mocker, tmp_path):
        """Each asset in output has scene, source, path, treatment, target_duration."""
        mock_pexels = mocker.patch(
            "clipper_agency.agents.visual_director.PexelsService",
        )
        mock_pexels.return_value.search_photos.return_value = []

        agent = VisualDirectorAgent()

        plan = [{
            "scene_number": 1,
            "beat_id": 1,
            "role": "hook",
            "reasoning": "Test",
            "treatment": "hook_big_caption",
            "target_duration": 3.5,
            "transition_in": "hard_cut",
            "transition_out": "crossfade",
            "action": {"type": "text_card", "headline": "TEST", "style": "news_card", "image_search": "test"},
            "fallback": None,
        }]

        scenes_dir = str(tmp_path / "scenes")
        assets = agent._execute_beat_plan(plan, scenes_dir)

        assert len(assets) == 1
        asset = assets[0]
        assert "scene" in asset
        assert "source" in asset
        assert "path" in asset
        assert "treatment" in asset
        assert "target_duration" in asset
        assert "transition_in" in asset
        assert "transition_out" in asset

    def test_output_beat_id_preserved(self, mocker, tmp_path):
        """beat_id passes through to output for composer timeline alignment."""
        mock_pexels = mocker.patch(
            "clipper_agency.agents.visual_director.PexelsService",
        )
        mock_pexels.return_value.search_photos.return_value = []

        agent = VisualDirectorAgent()
        plan = [{
            "scene_number": 1,
            "beat_id": 42,
            "role": "evidence",
            "reasoning": "Test",
            "treatment": "broll_standard",
            "target_duration": 5.0,
            "transition_in": "crossfade",
            "transition_out": "crossfade",
            "action": {"type": "text_card", "headline": "TEST", "style": "news_card", "image_search": "test"},
            "fallback": None,
            "start_time": 3.5,
        }]

        assets = agent._execute_beat_plan(plan, str(tmp_path / "scenes"))
        assert assets[0]["beat_id"] == 42
        assert assets[0]["start_time"] == 3.5
        assert assets[0]["role"] == "evidence"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_is_abstract_beat_true(self):
        beat = StoryBeat(**_make_beat(
            narration_goal="Explain the trending phenomenon",
            spoken_point="This trend is everywhere",
        ))
        assert _is_abstract_beat(beat) is True

    def test_is_abstract_beat_false(self):
        beat = StoryBeat(**_make_beat(
            narration_goal="Tell about Artist X's new album",
            spoken_point="Artist X released a new single",
        ))
        assert _is_abstract_beat(beat) is False

    def test_topic_safe_query_uses_visual_must_show(self):
        beat = StoryBeat(**_make_beat(
            visual_must_show="Artist X portrait",
        ))
        assert topic_safe_query(beat) == "Artist X portrait"

    def test_topic_safe_query_fallback_to_spoken_point(self):
        beat = StoryBeat(**_make_beat(
            visual_must_show="",
            spoken_point="Some interesting fact about music",
        ))
        query = topic_safe_query(beat)
        assert "music" in query

    def test_default_treatment_for_role(self):
        assert VisualDirectorAgent._default_treatment_for_role("hook") == "hook_big_caption"
        assert VisualDirectorAgent._default_treatment_for_role("closing_cta") == "fade_to_black"
        assert VisualDirectorAgent._default_treatment_for_role("main_claim") == "broll_standard"


# ---------------------------------------------------------------------------
# LLM beat-driven planning
# ---------------------------------------------------------------------------


class TestBeatDrivenLLMPlanning:
    """LLM beat-driven planning with proper prompt format."""

    def test_plan_beats_with_llm_sends_beat_payload(self, mocker):
        """LLM receives beat_driven mode with beat data."""
        agent = VisualDirectorAgent()

        mock_llm = mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient",
        )
        mock_llm.return_value.chat.return_value = {
            "content": json.dumps({
                "scenes": [
                    {
                        "scene_number": 1,
                        "beat_id": 1,
                        "role": "hook",
                        "reasoning": "Test",
                        "treatment": "hook_big_caption",
                        "target_duration": 2.3,
                        "transition_in": "hard_cut",
                        "transition_out": "crossfade",
                        "action": {"type": "text_card", "headline": "TEST", "style": "news_card", "image_search": "test"},
                    },
                ]
            }),
            "model": "test",
            "usage": {},
        }
        mocker.patch(
            "clipper_agency.agents.prompts.load_prompt",
            return_value="You are a Visual Director for {content_angle} content.",
        )
        mocker.patch(
            "clipper_agency.config.loader.load_settings",
        )

        beats = [StoryBeat(**_make_beat())]
        durations = {1: 2.3}

        plan = agent._plan_beats_with_llm(
            parsed_beats=beats,
            beat_durations=durations,
            do_not_use=["https://bad.url"],
            voiceover_duration_sec=5.3,
            topic="Test topic",
        )

        assert plan is not None
        assert len(plan) == 1

        # Verify LLM was called with beat_driven payload
        call_args = mock_llm.return_value.chat.call_args
        user_content = json.loads(call_args.kwargs["messages"][1]["content"])
        assert user_content["mode"] == "beat_driven"
        assert user_content["topic"] == "Test topic"
        assert user_content["do_not_use"] == ["https://bad.url"]
        assert user_content["voiceover_duration_sec"] == 5.3
        assert len(user_content["story_beats"]) == 1
        assert user_content["story_beats"][0]["duration_sec"] == 2.3

    def test_plan_beats_with_llm_falls_back_on_error(self, mocker):
        """If LLM fails, returns None so caller uses fallback."""
        agent = VisualDirectorAgent()

        mocker.patch(
            "clipper_agency.llm.client.OpenRouterClient",
            side_effect=Exception("API error"),
        )
        mocker.patch(
            "clipper_agency.agents.prompts.load_prompt",
            return_value="Prompt",
        )
        mocker.patch(
            "clipper_agency.config.loader.load_settings",
        )

        plan = agent._plan_beats_with_llm(
            parsed_beats=[],
            beat_durations={},
            do_not_use=[],
            voiceover_duration_sec=5.0,
            topic="Test",
        )

        assert plan is None


class TestBeatContractNormalization:
    """Visual Director must normalize LLM plan to allowed beat IDs."""

    def test_llm_plan_is_normalized_to_allowed_beat_ids(self):
        agent = VisualDirectorAgent()
        allowed = [1, 2, 9]
        plan = [
            {"scene_number": 1, "beat_id": 1},
            {"scene_number": 2, "beat_id": 2},
            {"scene_number": 8, "beat_id": 8},
            {"scene_number": 9, "beat_id": 9},
        ]

        normalized = agent._normalize_beat_plan(plan, allowed)

        assert [item["beat_id"] for item in normalized] == [1, 2, 9]

    def test_missing_beat_gets_stub_entry(self):
        agent = VisualDirectorAgent()
        plan = [
            {"scene_number": 1, "beat_id": 1},
        ]
        normalized = agent._normalize_beat_plan(plan, [1, 2])

        assert len(normalized) == 2
        assert normalized[0]["beat_id"] == 1
        assert normalized[1]["beat_id"] == 2
        assert normalized[1].get("scene_number") == 2

    def test_empty_plan_returns_stubs_for_all_beats(self):
        agent = VisualDirectorAgent()
        normalized = agent._normalize_beat_plan([], [1, 3, 5])

        assert [item["beat_id"] for item in normalized] == [1, 3, 5]


# ---------------------------------------------------------------------------
# Candidate selection and duplicate prevention
# ---------------------------------------------------------------------------


class TestCandidateSelectionAndDedup:
    """Visual Director candidate selection and duplicate prevention."""

    def test_prefers_firecrawl_screenshot_candidate(self):
        """Tier 2 screenshot candidate is used before Pexels."""
        agent = VisualDirectorAgent()
        beat = StoryBeat(**_make_beat(
            asset_candidates=[
                {
                    "type": "screenshot",
                    "url": "https://news.example/story",
                    "reason": "Relevant article image",
                    "source": "firecrawl",
                },
            ],
        ))

        action = agent._select_visual_for_beat(beat, [])

        assert action["type"] == "pexels_image"
        assert action["source_url"] == "https://news.example/story"

    def test_skips_duplicate_candidate_urls(self):
        """Previously used URL is excluded from selection."""
        agent = VisualDirectorAgent()
        duplicate_url = "https://tiktok.com/@u/video/1"
        beat = StoryBeat(**_make_beat(
            asset_candidates=[
                {"type": "tiktok_clip", "url": duplicate_url, "reason": "duplicate"},
                {"type": "screenshot", "url": "https://news.example/a", "reason": "alternate"},
            ],
        ))

        action = agent._select_visual_for_beat(beat, [duplicate_url])

        # Should skip the tiktok_clip (in do_not_use) and use screenshot
        assert action.get("source_url") != duplicate_url

    def test_fallback_accumulates_used_urls(self):
        """_plan_beats_fallback accumulates URLs across beats."""
        agent = VisualDirectorAgent()
        shared_url = "https://tiktok.com/@u/video/shared"
        beats = [
            StoryBeat(**_make_beat(
                beat_id=1,
                asset_candidates=[
                    {"type": "tiktok_clip", "url": shared_url, "reason": "shared clip"},
                ],
            )),
            StoryBeat(**_make_beat(
                beat_id=2,
                asset_candidates=[
                    {"type": "tiktok_clip", "url": shared_url, "reason": "same clip"},
                    {"type": "screenshot", "url": "https://news.example/b", "reason": "alternate"},
                ],
            )),
        ]

        plan = agent._plan_beats_fallback(beats, {1: 5.0, 2: 5.0}, [])

        # Beat 1 gets the shared URL
        assert plan[0]["action"]["source_url"] == shared_url
        # Beat 2 should NOT reuse it
        assert plan[1]["action"].get("source_url") != shared_url

    def test_deduplicate_llm_plan_urls(self):
        """_deduplicate_llm_plan_urls removes duplicate source_urls."""
        agent = VisualDirectorAgent()
        plan = [
            {"beat_id": 1, "action": {"type": "tiktok_clip", "source_url": "https://a.com/1"}},
            {"beat_id": 2, "action": {"type": "tiktok_clip", "source_url": "https://a.com/1"}},
            {"beat_id": 3, "action": {"type": "screenshot", "source_url": "https://b.com/2"}},
        ]

        result = agent._deduplicate_llm_plan_urls(plan, [])

        # Beat 1 keeps its URL
        assert result[0]["action"]["source_url"] == "https://a.com/1"
        # Beat 2's duplicate source_url is removed from action
        assert "source_url" not in result[1]["action"] or result[1]["action"].get("source_url") != "https://a.com/1"
        # Beat 3 keeps its distinct URL
        assert result[2]["action"]["source_url"] == "https://b.com/2"


# ---------------------------------------------------------------------------
# Visual Plan Resolver tests (Batch 1A — must fail)
# ---------------------------------------------------------------------------


class TestVisualPlanResolver:
    """Tests for the future _resolve_beat_plan_assets resolver.

    These tests MUST FAIL until the resolver is implemented in Batch 2A.
    """

    @pytest.fixture
    def director(self):
        return VisualDirectorAgent()

    def test_resolver_replaces_duplicate_url_with_alternate_candidate(self, director):
        """Beat 2 uses same URL as beat 1; resolver must pick alternate candidate."""
        url_primary = "https://www.tiktok.com/@user/video/111"
        url_alternate = "https://www.tiktok.com/@user/video/222"
        plan = [
            {
                "beat_id": 1,
                "scene_number": 1,
                "action": {"type": "tiktok_clip", "source_url": url_primary},
                "asset_candidates": [
                    {"type": "tiktok_clip", "url": url_primary},
                ],
            },
            {
                "beat_id": 2,
                "scene_number": 2,
                "action": {"type": "tiktok_clip", "source_url": url_primary},
                "asset_candidates": [
                    {"type": "tiktok_clip", "url": url_primary},
                    {"type": "tiktok_clip", "url": url_alternate},
                ],
            },
        ]
        resolved = director._resolve_beat_plan_assets(plan, do_not_use=[])
        beat2_action = resolved[1]["action"]
        assert beat2_action.get("source_url") == url_alternate
        assert beat2_action.get("type") == "tiktok_clip"

    def test_resolver_recovers_missing_source_url_from_candidates(self, director):
        """Action has no source_url; beat has usable candidate URL."""
        url = "https://www.tiktok.com/@user/video/333"
        plan = [
            {
                "beat_id": 1,
                "scene_number": 1,
                "action": {"type": "tiktok_clip"},
                "asset_candidates": [
                    {"type": "tiktok_clip", "url": url},
                ],
            },
        ]
        resolved = director._resolve_beat_plan_assets(plan, do_not_use=[])
        assert resolved[0]["action"].get("source_url") == url

    def test_resolver_normalizes_video_candidate_type_to_tiktok_clip(self, director):
        """Candidate type 'video' with TikTok URL resolves to tiktok_clip action."""
        url = "https://www.tiktok.com/@user/video/444"
        plan = [
            {
                "beat_id": 1,
                "scene_number": 1,
                "action": {"type": "tiktok_clip"},
                "asset_candidates": [
                    {"type": "video", "url": url},
                ],
            },
        ]
        resolved = director._resolve_beat_plan_assets(plan, do_not_use=[])
        action = resolved[0]["action"]
        assert action.get("type") == "tiktok_clip"
        assert action.get("source_url") == url

    def test_resolver_never_leaves_broken_tiktok_action(self, director):
        """No usable candidate exists — action must become text_card fallback."""
        plan = [
            {
                "beat_id": 1,
                "scene_number": 1,
                "action": {"type": "tiktok_clip"},
                "asset_candidates": [],
            },
        ]
        resolved = director._resolve_beat_plan_assets(plan, do_not_use=[])
        action = resolved[0]["action"]
        assert action.get("type") == "text_card"
        assert "reason" in action

    def test_resolver_respects_do_not_use_urls(self, director):
        """URLs in do_not_use list must not be selected even if they are candidates."""
        blocked_url = "https://www.tiktok.com/@user/video/555"
        good_url = "https://www.tiktok.com/@user/video/666"
        plan = [
            {
                "beat_id": 1,
                "scene_number": 1,
                "action": {"type": "tiktok_clip"},
                "asset_candidates": [
                    {"type": "tiktok_clip", "url": blocked_url},
                    {"type": "tiktok_clip", "url": good_url},
                ],
            },
        ]
        resolved = director._resolve_beat_plan_assets(plan, do_not_use=[blocked_url])
        assert resolved[0]["action"].get("source_url") == good_url
