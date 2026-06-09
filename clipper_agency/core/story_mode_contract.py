"""Story-mode production contract derivation.

Derives thumbnail strategy, CTA strategy, and duration structure from a
canonical StoryModeDecision.  Pure lookup — no side effects.
"""

from __future__ import annotations

from clipper_agency.config.schema import StoryModeDecision

# ---------------------------------------------------------------------------
# Contract lookup table
# ---------------------------------------------------------------------------

_STORY_MODE_CONTRACTS: dict[str, dict] = {
    "roundup": {
        "requires_intro_card": True,
        "thumbnail_strategy": "multi_entity_roundup",
        "cta_strategy": "compare_items",
        "duration_structure": "intro_story_items_cta",
    },
    "single_story": {
        "requires_intro_card": False,
        "thumbnail_strategy": "single_claim",
        "cta_strategy": "opinion_or_followup",
        "duration_structure": "hook_context_evidence_reveal_cta",
    },
    "controversy_explainer": {
        "requires_intro_card": False,
        "thumbnail_strategy": "controversy_split",
        "cta_strategy": "opinion_or_followup",
        "duration_structure": "hook_context_evidence_reveal_cta",
    },
    "breaking_news": {
        "requires_intro_card": True,
        "thumbnail_strategy": "breaking_visual",
        "cta_strategy": "breaking_followup",
        "duration_structure": "hook_context_evidence_reveal_cta",
    },
}

_FALLBACK_CONTRACT = _STORY_MODE_CONTRACTS["single_story"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_story_mode_contract(
    story_mode_decision: dict | StoryModeDecision,
) -> dict:
    """Derive production contract from a story-mode decision.

    Accepts both a ``StoryModeDecision`` model and a plain ``dict``.
    Returns the input fields merged with contract overrides.
    """
    if isinstance(story_mode_decision, StoryModeDecision):
        base = story_mode_decision.model_dump()
    else:
        base = dict(story_mode_decision)

    mode = base.get("story_mode", "")
    contract = _STORY_MODE_CONTRACTS.get(mode, _FALLBACK_CONTRACT)
    base.update(contract)
    return base
