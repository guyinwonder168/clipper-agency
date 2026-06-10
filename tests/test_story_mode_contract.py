"""Tests for story-mode contract derivation.

Contract rules map a canonical StoryModeDecision to production-level
strategies (thumbnail, CTA, duration structure).
"""

import pytest

from clipper_agency.config.schema import StoryModeDecision
from clipper_agency.core.story_mode_contract import derive_story_mode_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decision(**overrides) -> StoryModeDecision:
    """Build a StoryModeDecision with sensible defaults + overrides."""
    defaults = dict(
        story_mode="single_story",
        confidence=0.8,
        reason="test",
        item_count=1,
        target_duration_sec=30,
    )
    defaults.update(overrides)
    return StoryModeDecision(**defaults)


# ---------------------------------------------------------------------------
# 1. Roundup mode
# ---------------------------------------------------------------------------

def test_roundup_mode_returns_correct_contract():
    result = derive_story_mode_contract(_decision(story_mode="roundup", item_count=3))
    assert result["requires_intro_card"] is True
    assert result["thumbnail_strategy"] == "multi_entity_roundup"
    assert result["cta_strategy"] == "compare_items"
    assert result["duration_structure"] == "intro_story_items_cta"


# ---------------------------------------------------------------------------
# 2. Single story mode
# ---------------------------------------------------------------------------

def test_single_story_mode_returns_correct_contract():
    result = derive_story_mode_contract(_decision(story_mode="single_story"))
    assert result["requires_intro_card"] is False
    assert result["thumbnail_strategy"] == "single_claim"
    assert result["cta_strategy"] == "opinion_or_followup"
    assert result["duration_structure"] == "hook_context_evidence_reveal_cta"


# ---------------------------------------------------------------------------
# 3. Controversy explainer mode
# ---------------------------------------------------------------------------

def test_controversy_explainer_returns_correct_contract():
    result = derive_story_mode_contract(_decision(story_mode="controversy_explainer"))
    assert result["requires_intro_card"] is False
    assert result["thumbnail_strategy"] == "controversy_split"
    assert result["cta_strategy"] == "opinion_or_followup"
    assert result["duration_structure"] == "hook_context_evidence_reveal_cta"


# ---------------------------------------------------------------------------
# 4. Breaking news mode
# ---------------------------------------------------------------------------

def test_breaking_news_returns_correct_contract():
    result = derive_story_mode_contract(_decision(story_mode="breaking_news"))
    assert result["requires_intro_card"] is True
    assert result["thumbnail_strategy"] == "breaking_visual"
    assert result["cta_strategy"] == "breaking_followup"
    assert result["duration_structure"] == "hook_context_evidence_reveal_cta"


# ---------------------------------------------------------------------------
# 5. Unknown mode falls back
# ---------------------------------------------------------------------------

def test_unknown_mode_falls_back_to_single_story_contract():
    result = derive_story_mode_contract(_decision(story_mode="unknown"))
    assert result["requires_intro_card"] is False
    assert result["thumbnail_strategy"] == "single_claim"
    assert result["cta_strategy"] == "opinion_or_followup"
    assert result["duration_structure"] == "hook_context_evidence_reveal_cta"


# ---------------------------------------------------------------------------
# 6. Dict input works same as StoryModeDecision
# ---------------------------------------------------------------------------

def test_dict_input_works_same_as_model():
    model_result = derive_story_mode_contract(_decision(story_mode="roundup"))
    dict_result = derive_story_mode_contract(
        {"story_mode": "roundup", "confidence": 0.8, "reason": "test",
         "item_count": 1, "target_duration_sec": 30}
    )
    assert model_result["thumbnail_strategy"] == dict_result["thumbnail_strategy"]
    assert model_result["cta_strategy"] == dict_result["cta_strategy"]
    assert model_result["duration_structure"] == dict_result["duration_structure"]


# ---------------------------------------------------------------------------
# 7. duration_structure always present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [
    "roundup", "single_story", "controversy_explainer", "breaking_news", "unknown",
])
def test_duration_structure_always_present(mode):
    result = derive_story_mode_contract(_decision(story_mode=mode))
    assert "duration_structure" in result
    assert isinstance(result["duration_structure"], str)
    assert len(result["duration_structure"]) > 0


# ---------------------------------------------------------------------------
# 8. All strategy fields populated
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [
    "roundup", "single_story", "controversy_explainer", "breaking_news", "unknown",
])
def test_strategy_fields_populated(mode):
    result = derive_story_mode_contract(_decision(story_mode=mode))
    assert result["thumbnail_strategy"] != "default"
    assert result["cta_strategy"] != "default"


# ---------------------------------------------------------------------------
# 9. item_count and target_duration_sec preserved from input
# ---------------------------------------------------------------------------

def test_item_count_and_duration_preserved():
    result = derive_story_mode_contract(
        _decision(story_mode="roundup", item_count=5, target_duration_sec=45)
    )
    assert result["item_count"] == 5
    assert result["target_duration_sec"] == 45
