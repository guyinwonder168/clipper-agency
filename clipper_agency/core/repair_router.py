"""Structured repair routing for reviewer feedback.

Pure functions that map (reason, action) pairs to pipeline agent names
and construct validated RepairPlan objects.
"""

from __future__ import annotations

from typing import Any

from clipper_agency.config.schema import RepairPatch, RepairPlan


# Deterministic gate failure reason → (patch_reason, patch_action) mapping.
# Used by build_gate_failure_repair_plan to synthesize repair patches when
# the reviewer's deterministic gates fail without an LLM-generated repair_plan.
GATE_FAILURE_REPAIR_MAP: dict[str, tuple[str, str]] = {
    "VISUAL_COVERAGE_FAILED": ("broken_source", "replace_visual"),
    "TEXT_COLLISION_FAILED": ("text_collision", "fix_text"),
    "SAFE_AREA_FAILED": ("text_collision", "fix_text"),
    "PACKAGE_CONSISTENCY_FAILED": ("wrong_event", "redo_research"),
    "TIMESTAMP_SEMANTIC_FAILED": ("semantic_mismatch", "replace_visual"),
}


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


def build_gate_failure_repair_plan(
    review_output: dict[str, Any],
) -> dict[str, Any] | None:
    """Synthesize a repair routing dict from a deterministic gate failure.

    Deterministic gates (visual_coverage, text_collision, safe_area,
    package_consistency, timestamp_semantic) hard-fail the reviewer without
    an LLM-generated ``repair_plan``, leaving the job silently blocked.
    This function bridges that gap by mapping the gate failure reason to
    a repair patch routed to the correct agent.

    Returns a routing dict (same shape as ``_handle_repair_plan``) with
    ``decision``, ``target_agent``, and ``patches``, or ``None`` if the
    review_output is not a mappable deterministic gate failure.
    """
    if review_output.get("status") != "fail":
        return None
    reason = review_output.get("reason", "")
    if reason not in GATE_FAILURE_REPAIR_MAP:
        return None

    patch_reason, action = GATE_FAILURE_REPAIR_MAP[reason]
    patch = {
        "beat_id": "global",
        "action": action,
        "reason": patch_reason,
        "rerun_from": "visual_director",
    }
    target_agent = route_repair(patch)
    patch["rerun_from"] = target_agent
    return {
        "decision": "revise",
        "target_agent": target_agent,
        "patches": [patch],
    }
