"""Tests for story decision reconciliation module.

Reconciles story_mode_decision (classifier) with legacy format_decision (LLM)
into a single canonical StoryModeDecision.

Rules (priority order):
1. Explicit user mode (confidence >= 0.9) always wins
2. >1 entity detected → roundup mode, unless overridden by Rule 1
3. Legacy three_story_roundup cannot coexist with single_story — roundup wins
4. Default fallback — use classifier's story_mode_decision
"""

from clipper_agency.config.schema import FormatDecision, StoryModeDecision
from clipper_agency.core.story_decision_reconciliation import (
    EXPLICIT_CONFIDENCE_THRESHOLD,
    reconcile_story_decisions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classifier(mode: str = "single_story", confidence: float = 0.6,
                item_count: int = 1, **kwargs) -> dict:
    """Build a minimal classifier story_mode_decision dict."""
    return {
        "story_mode": mode,
        "confidence": confidence,
        "reason": f"classifier chose {mode}",
        "item_count": item_count,
        "target_duration_sec": kwargs.get("target_duration_sec", 30),
        "requires_intro_card": kwargs.get("requires_intro_card", False),
        "thumbnail_strategy": kwargs.get("thumbnail_strategy", "default"),
        "cta_strategy": kwargs.get("cta_strategy", "default"),
    }


def _legacy(fmt: str = "three_story_roundup", story_count: int = 3,
            **kwargs) -> dict:
    """Build a minimal legacy FormatDecision dict."""
    return {
        "format": fmt,
        "story_count": story_count,
        "rationale": kwargs.get("rationale", "auto"),
        "video_asset_ratio": kwargs.get("video_asset_ratio", 0.8),
    }


# ---------------------------------------------------------------------------
# 1. Explicit user mode (high confidence) wins over everything
# ---------------------------------------------------------------------------

class TestExplicitUserModeWins:
    """Rule 1: confidence >= 0.9 is an explicit/override and always wins."""

    def test_high_confidence_single_story_overrides_legacy_roundup(self):
        classifier = _classifier("single_story", confidence=0.95)
        legacy = _legacy("three_story_roundup", story_count=3)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "single_story"
        assert "Rule 1" in result.reason

    def test_high_confidence_breaking_news_overrides_legacy(self):
        classifier = _classifier("breaking_news", confidence=0.92)
        legacy = _legacy("three_story_roundup")
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "breaking_news"

    def test_high_confidence_roundup_preserved(self):
        classifier = _classifier("roundup", confidence=0.93, item_count=4)
        legacy = _legacy("single_story_deep_dive", story_count=1)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "roundup"
        assert result.item_count == 4

    def test_confidence_at_threshold_is_explicit(self):
        """Confidence exactly at threshold counts as explicit."""
        classifier = _classifier("controversy_explainer", confidence=EXPLICIT_CONFIDENCE_THRESHOLD)
        legacy = _legacy("three_story_roundup")
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "controversy_explainer"


# ---------------------------------------------------------------------------
# 2. Multiple entities → roundup mode
# ---------------------------------------------------------------------------

class TestMultipleEntitiesForceRoundup:
    """Rule 2: item_count > 1 → roundup."""

    def test_multiple_beats_do_not_override_item_count_1(self):
        """Beat count is no longer a proxy for entity count.

        Only classifier.item_count > 1 triggers Rule 2. A single story
        with 3 narrative beats but item_count=1 stays single_story.
        """
        classifier = _classifier("single_story", confidence=0.7, item_count=1)
        legacy = _legacy("single_story_deep_dive", story_count=1)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "single_story"

    def test_item_count_gt_1_forces_roundup(self):
        classifier = _classifier("single_story", confidence=0.7, item_count=3)
        legacy = _legacy("single_story_deep_dive", story_count=1)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "roundup"
        assert "Rule 2" in result.reason

    def test_single_entity_does_not_trigger_rule2(self):
        classifier = _classifier("single_story", confidence=0.5, item_count=1)
        legacy = _legacy("single_story_deep_dive", story_count=1)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "single_story"

    def test_rule2_not_applied_when_rule1_overrides(self):
        """Even with item_count > 1, explicit mode wins."""
        classifier = _classifier("single_story", confidence=0.95, item_count=3)
        legacy = _legacy("three_story_roundup", story_count=3)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "single_story"


# ---------------------------------------------------------------------------
# 3. Legacy three_story_roundup overrides single_story classifier
# ---------------------------------------------------------------------------

class TestLegacyRoundupContradiction:
    """Rule 3: three_story_roundup format cannot coexist with single_story."""

    def test_legacy_roundup_overrides_single_story_classifier(self):
        classifier = _classifier("single_story", confidence=0.7)
        legacy = _legacy("three_story_roundup", story_count=3)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "roundup"
        assert "Rule 3" in result.reason

    def test_legacy_roundup_with_two_story_highlight(self):
        classifier = _classifier("single_story", confidence=0.6)
        legacy = _legacy("two_story_highlight", story_count=2)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "roundup"

    def test_no_contradiction_when_classifier_already_roundup(self):
        classifier = _classifier("roundup", confidence=0.7, item_count=3)
        legacy = _legacy("three_story_roundup", story_count=3)
        result = reconcile_story_decisions(classifier, legacy)
        # No contradiction — classifier already says roundup, Rule 4 applies
        assert result.story_mode == "roundup"

    def test_rule3_not_applied_when_rule1_overrides(self):
        classifier = _classifier("single_story", confidence=0.95)
        legacy = _legacy("three_story_roundup", story_count=3)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "single_story"


# ---------------------------------------------------------------------------
# 4. Default fallback — use classifier's decision
# ---------------------------------------------------------------------------

class TestDefaultFallback:
    """Rule 4: no clear signal → trust the classifier."""

    def test_default_uses_classifier_decision(self):
        classifier = _classifier("controversy_explainer", confidence=0.7)
        legacy = _legacy("single_story_deep_dive", story_count=1)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "controversy_explainer"
        assert "Rule 4" in result.reason

    def test_default_with_no_legacy(self):
        classifier = _classifier("single_story", confidence=0.6)
        result = reconcile_story_decisions(classifier, None)
        assert result.story_mode == "single_story"

    def test_default_preserves_classifier_fields(self):
        classifier = _classifier(
            "single_story", confidence=0.6,
            target_duration_sec=45,
            requires_intro_card=True,
            thumbnail_strategy="custom",
            cta_strategy="share",
        )
        result = reconcile_story_decisions(classifier, None)
        assert result.target_duration_sec == 45
        assert result.requires_intro_card is True
        assert result.thumbnail_strategy == "custom"
        assert result.cta_strategy == "share"


# ---------------------------------------------------------------------------
# 5. Contradiction detection and diagnostic reason
# ---------------------------------------------------------------------------

class TestContradictionDetection:
    """The reason field must contain diagnostic info about contradictions."""

    def test_contradiction_detected_in_reason(self):
        classifier = _classifier("single_story", confidence=0.7)
        legacy = _legacy("three_story_roundup", story_count=3)
        result = reconcile_story_decisions(classifier, legacy)
        assert "contradiction" in result.reason.lower()

    def test_no_contradiction_when_aligned(self):
        classifier = _classifier("roundup", confidence=0.7, item_count=3)
        legacy = _legacy("three_story_roundup", story_count=3)
        result = reconcile_story_decisions(classifier, legacy)
        assert "contradiction" not in result.reason.lower()

    def test_reason_contains_original_values(self):
        classifier = _classifier("single_story", confidence=0.7)
        legacy = _legacy("three_story_roundup", story_count=3)
        result = reconcile_story_decisions(classifier, legacy)
        # Should mention what the original values were
        assert "single_story" in result.reason
        assert "three_story_roundup" in result.reason

    def test_reason_contains_applied_rule(self):
        classifier = _classifier("single_story", confidence=0.95)
        result = reconcile_story_decisions(classifier, None)
        assert "Rule 1" in result.reason


# ---------------------------------------------------------------------------
# 6. None / missing legacy_format_decision handled gracefully
# ---------------------------------------------------------------------------

class TestNoneLegacyHandling:
    """legacy_format_decision can be None or missing."""

    def test_none_legacy_uses_classifier(self):
        classifier = _classifier("roundup", confidence=0.7, item_count=3)
        result = reconcile_story_decisions(classifier, None)
        assert result.story_mode == "roundup"

    def test_none_legacy_with_single_story(self):
        classifier = _classifier("single_story", confidence=0.6)
        result = reconcile_story_decisions(classifier, None)
        assert result.story_mode == "single_story"

    def test_none_legacy_with_high_confidence(self):
        classifier = _classifier("breaking_news", confidence=0.95)
        result = reconcile_story_decisions(classifier, None)
        assert result.story_mode == "breaking_news"
        assert "Rule 1" in result.reason


# ---------------------------------------------------------------------------
# 7. Return type is always StoryModeDecision
# ---------------------------------------------------------------------------

class TestReturnType:
    """reconcile_story_decisions always returns a StoryModeDecision."""

    def test_returns_story_mode_decision_with_legacy(self):
        result = reconcile_story_decisions(
            _classifier("single_story", confidence=0.6),
            _legacy("single_story_deep_dive", story_count=1),
        )
        assert isinstance(result, StoryModeDecision)

    def test_returns_story_mode_decision_without_legacy(self):
        result = reconcile_story_decisions(
            _classifier("roundup", confidence=0.7, item_count=3),
            None,
        )
        assert isinstance(result, StoryModeDecision)

    def test_accepts_pydantic_model_inputs(self):
        classifier_model = StoryModeDecision(
            story_mode="single_story", confidence=0.6, reason="test",
            item_count=1, target_duration_sec=30,
        )
        legacy_model = FormatDecision(
            format="three_story_roundup", story_count=3,
            rationale="test", video_asset_ratio=0.8,
        )
        result = reconcile_story_decisions(classifier_model, legacy_model)
        assert isinstance(result, StoryModeDecision)
        assert result.story_mode == "roundup"

    def test_accepts_dict_inputs(self):
        result = reconcile_story_decisions(
            _classifier("single_story", confidence=0.6),
            _legacy("single_story_deep_dive", story_count=1),
        )
        assert isinstance(result, StoryModeDecision)


# ---------------------------------------------------------------------------
# 8. item_count from story_mode_decision respected
# ---------------------------------------------------------------------------

class TestItemCountRespected:
    """item_count from the classifier decision carries through."""

    def test_item_count_carried_through_on_rule1(self):
        classifier = _classifier("roundup", confidence=0.95, item_count=5)
        result = reconcile_story_decisions(classifier, None)
        assert result.item_count == 5

    def test_item_count_updated_on_rule2(self):
        classifier = _classifier("single_story", confidence=0.7, item_count=3)
        result = reconcile_story_decisions(classifier, None)
        assert result.story_mode == "roundup"
        assert result.item_count == 3

    def test_beats_do_not_override_item_count_1(self):
        """Beat count is no longer a proxy — only item_count matters."""
        classifier = _classifier("single_story", confidence=0.7, item_count=1)
        legacy = _legacy("single_story_deep_dive", story_count=1)
        result = reconcile_story_decisions(classifier, legacy)
        assert result.story_mode == "single_story"
        assert result.item_count == 1
