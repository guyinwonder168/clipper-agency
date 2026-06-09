"""Tests for deterministic story-mode classifier.

Rules (no LLM, pure keyword/pattern matching):
1. target_duration_sec < 20 → single_story
2. Controversy keywords → controversy_explainer
3. Breaking-news keywords → breaking_news
4. Roundup indicators → roundup
5. Default → single_story
"""

import pytest

from clipper_agency.config.schema import StoryModeDecision
from clipper_agency.core.story_mode import classify_story_mode


# ---------------------------------------------------------------------------
# 1. Broad entertainment topics → roundup
# ---------------------------------------------------------------------------

def test_broad_entertainment_topic_classifies_as_roundup():
    decision = classify_story_mode("berita artis terbaru hari ini", target_duration_sec=30)
    assert decision.story_mode == "roundup"
    assert decision.requires_intro_card is True
    assert decision.item_count >= 2


# ---------------------------------------------------------------------------
# 2. Specific clarification topics → single_story or controversy/breaking
# ---------------------------------------------------------------------------

def test_specific_clarification_topic_classifies_as_single_story():
    decision = classify_story_mode(
        "Ruben akhirnya memberikan klarifikasi soal nafkah", target_duration_sec=30
    )
    assert decision.story_mode in {"single_story", "controversy_explainer", "breaking_news"}
    assert decision.item_count == 1


# ---------------------------------------------------------------------------
# 3. Short duration forces single_story (can't fit multiple stories)
# ---------------------------------------------------------------------------

def test_short_duration_forces_single_story():
    decision = classify_story_mode("berita artis terbaru hari ini", target_duration_sec=15)
    assert decision.story_mode == "single_story"
    assert decision.item_count == 1
    assert "duration" in decision.reason.lower() or "short" in decision.reason.lower()


# ---------------------------------------------------------------------------
# 4. Breaking-news keywords
# ---------------------------------------------------------------------------

def test_breaking_news_keyword_triggers_breaking_news():
    for keyword in ("breaking", "terbaru banget", "barusan", "just now"):
        decision = classify_story_mode(f"{keyword} berita hari ini", target_duration_sec=30)
        assert decision.story_mode == "breaking_news", f"keyword '{keyword}' should trigger breaking_news"


# ---------------------------------------------------------------------------
# 5. Controversy keywords
# ---------------------------------------------------------------------------

def test_controversy_keyword_triggers_controversy_explainer():
    for keyword in ("kontroversi", "heboh", "viral", "skandal", "drama"):
        decision = classify_story_mode(f"artis {keyword} di media sosial", target_duration_sec=30)
        assert decision.story_mode == "controversy_explainer", (
            f"keyword '{keyword}' should trigger controversy_explainer"
        )


# ---------------------------------------------------------------------------
# 6. Roundup with comma-separated entity names
# ---------------------------------------------------------------------------

def test_roundup_with_multiple_entities():
    decision = classify_story_mode("Ruben, Ayu, dan Dewi persidangan hari ini", target_duration_sec=30)
    assert decision.story_mode == "roundup"
    assert decision.item_count >= 2


# ---------------------------------------------------------------------------
# 7. Default falls to single_story with lower confidence
# ---------------------------------------------------------------------------

def test_default_falls_to_single_story():
    decision = classify_story_mode("kucing lucu bermain di taman", target_duration_sec=30)
    assert decision.story_mode == "single_story"
    assert decision.confidence < 0.8


# ---------------------------------------------------------------------------
# 8. Return type is StoryModeDecision
# ---------------------------------------------------------------------------

def test_return_type_is_story_mode_decision():
    decision = classify_story_mode("anything", target_duration_sec=30)
    assert isinstance(decision, StoryModeDecision)


# ---------------------------------------------------------------------------
# 9. Breaking news takes precedence over roundup for short duration
# ---------------------------------------------------------------------------

def test_short_duration_with_breaking_keyword_still_single_story():
    """Duration < 20 overrides all keyword matches."""
    decision = classify_story_mode("breaking news hari ini", target_duration_sec=15)
    assert decision.story_mode == "single_story"
