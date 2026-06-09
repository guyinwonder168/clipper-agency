"""Reconcile story_mode_decision (classifier) with legacy format_decision.

Resolves contradictions between the deterministic classifier output and
the LLM-produced legacy format into a single canonical StoryModeDecision.

Rules (priority order):
1. Explicit user mode (confidence >= 0.9) always wins.
2. >1 entity detected (item_count > 1) → roundup mode,
   unless explicitly overridden by Rule 1.
3. Legacy three_story_roundup cannot coexist with single_story — roundup wins.
4. Default fallback — use the classifier's story_mode_decision.
"""

from __future__ import annotations

from clipper_agency.config.schema import FormatDecision, StoryModeDecision

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPLICIT_CONFIDENCE_THRESHOLD: float = 0.9

_ROUNDUP_FORMATS: frozenset[str] = frozenset({
    "three_story_roundup",
    "two_story_highlight",
})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_classifier(
    raw: dict | StoryModeDecision,
) -> StoryModeDecision:
    """Accept dict or StoryModeDecision and return a validated model."""
    if isinstance(raw, StoryModeDecision):
        return raw
    return StoryModeDecision(**raw)


def _normalise_legacy(
    raw: dict | FormatDecision | None,
) -> FormatDecision | None:
    """Accept dict, FormatDecision, or None and return a validated model or None."""
    if raw is None:
        return None
    if isinstance(raw, FormatDecision):
        return raw
    return FormatDecision(**raw)


def _is_explicit_override(decision: StoryModeDecision) -> bool:
    """Rule 1: high-confidence decision is an explicit user/override signal."""
    return decision.confidence >= EXPLICIT_CONFIDENCE_THRESHOLD


def _has_multiple_entities(
    classifier: StoryModeDecision,
) -> bool:
    """Rule 2: more than one entity detected via classifier item_count."""
    return classifier.item_count > 1


def _is_roundup_contradiction(
    classifier: StoryModeDecision,
    legacy: FormatDecision | None,
) -> bool:
    """Rule 3: legacy says roundup but classifier says single_story."""
    if legacy is None:
        return False
    return (
        legacy.format in _ROUNDUP_FORMATS
        and classifier.story_mode == "single_story"
    )


def _build_reason(
    rule: int,
    classifier: StoryModeDecision,
    legacy: FormatDecision | None,
    contradiction: bool,
    original_mode: str,
) -> str:
    """Construct a diagnostic reason string."""
    parts = [f"Rule {rule} applied."]
    if contradiction:
        parts.append(
            f"Contradiction: classifier={original_mode},"
            f" legacy={legacy.format if legacy else 'none'}."
        )
    else:
        parts.append(f"Original story_mode={original_mode}.")
    if legacy:
        parts.append(f"Legacy format={legacy.format}.")
    return " ".join(parts)


def _apply_roundup(
    classifier: StoryModeDecision,
    entity_count: int,
    rule: int,
    legacy: FormatDecision | None,
    original_mode: str,
) -> StoryModeDecision:
    """Build a roundup-mode result preserving classifier fields."""
    contradiction = (
        legacy is not None
        and legacy.format in _ROUNDUP_FORMATS
        and original_mode == "single_story"
    )
    return StoryModeDecision(
        story_mode="roundup",
        confidence=classifier.confidence,
        reason=_build_reason(rule, classifier, legacy, contradiction, original_mode),
        item_count=max(entity_count, 2),
        target_duration_sec=classifier.target_duration_sec,
        requires_intro_card=True,
        thumbnail_strategy=classifier.thumbnail_strategy,
        cta_strategy=classifier.cta_strategy,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reconcile_story_decisions(
    story_mode_decision: dict | StoryModeDecision,
    legacy_format_decision: dict | FormatDecision | None,
) -> StoryModeDecision:
    """Reconcile classifier and legacy decisions into one canonical decision.

    Parameters
    ----------
    story_mode_decision:
        Output of the deterministic classifier (dict or StoryModeDecision).
    legacy_format_decision:
        Legacy FormatDecision from LLM output, or None.

    Returns
    -------
    A single canonical StoryModeDecision with diagnostic reason.
    """
    classifier = _normalise_classifier(story_mode_decision)
    legacy = _normalise_legacy(legacy_format_decision)
    original_mode = classifier.story_mode

    # Rule 1: explicit user override
    if _is_explicit_override(classifier):
        return StoryModeDecision(
            story_mode=classifier.story_mode,
            confidence=classifier.confidence,
            reason=_build_reason(1, classifier, legacy, False, original_mode),
            item_count=classifier.item_count,
            target_duration_sec=classifier.target_duration_sec,
            requires_intro_card=classifier.requires_intro_card,
            thumbnail_strategy=classifier.thumbnail_strategy,
            cta_strategy=classifier.cta_strategy,
        )

    # Rule 2: multiple entities detected
    if _has_multiple_entities(classifier):
        return _apply_roundup(classifier, classifier.item_count, 2, legacy, original_mode)

    # Rule 3: legacy roundup contradicts single_story
    if _is_roundup_contradiction(classifier, legacy):
        return _apply_roundup(classifier, 3, 3, legacy, original_mode)

    # Rule 4: default fallback — trust classifier
    return StoryModeDecision(
        story_mode=classifier.story_mode,
        confidence=classifier.confidence,
        reason=_build_reason(4, classifier, legacy, False, original_mode),
        item_count=classifier.item_count,
        target_duration_sec=classifier.target_duration_sec,
        requires_intro_card=classifier.requires_intro_card,
        thumbnail_strategy=classifier.thumbnail_strategy,
        cta_strategy=classifier.cta_strategy,
    )
