"""Structured repair routing for reviewer feedback.

Pure functions that map (reason, action) pairs to pipeline agent names
and construct validated RepairPlan objects.
"""

from __future__ import annotations

from clipper_agency.config.schema import RepairPatch, RepairPlan


def route_repair(patch: dict) -> str:
    """Return the agent name a repair patch should be routed to.

    Uses a lookup table keyed by (reason, action).  Falls back to
    ``visual_director`` for any unmatched combination.
    """
    reason = patch.get("reason", "")
    action = patch.get("action", "")

    # Exact (reason, action) overrides
    _exact: dict[tuple[str, str], str] = {
        ("wrong_event", "redo_research"): "segment_producer",
        ("package_mismatch", "narrow_topic"): "segment_producer",
    }
    key = (reason, action)
    if key in _exact:
        return _exact[key]

    # Reason-only routing (action-agnostic)
    _by_reason: dict[str, str] = {
        "broken_source": "visual_director",
        "wrong_event": "visual_director",
        "text_collision": "visual_director",
        "black_frame": "composer",
        "freeze_frame": "composer",
        "duration_mismatch": "composer",
        "script_scope_mismatch": "segment_producer_and_scriptwriter",
        "unsafe_factual_claim": "segment_producer_and_scriptwriter",
    }
    if reason in _by_reason:
        return _by_reason[reason]

    # Safe default
    return "visual_director"


def build_repair_plan(
    decision: str,
    patches: list[dict],
    max_cycles: int = 2,
) -> RepairPlan:
    """Validate and construct a :class:`RepairPlan`.

    Parameters
    ----------
    decision:
        One of ``"revise"``, ``"reject"``, ``"accept"``.
    patches:
        Raw patch dicts — each must contain at least ``beat_id``,
        ``action``, ``reason``, and ``rerun_from``.
    max_cycles:
        Maximum number of repair iterations allowed.
    """
    validated_patches = [
        RepairPatch(
            beat_id=p["beat_id"],
            action=p["action"],
            reason=p["reason"],
            rerun_from=p["rerun_from"],
        )
        for p in patches
    ]

    return RepairPlan(
        decision=decision,
        max_repair_cycles=max_cycles,
        patches=validated_patches,
    )
