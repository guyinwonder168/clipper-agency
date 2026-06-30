"""Structured repair routing for reviewer feedback.

Pure functions that map (reason, action) pairs to pipeline agent names
and construct validated RepairPlan objects.
"""

from __future__ import annotations

from typing import Any

from clipper_agency.config.schema import RepairPatch, RepairPlan

# Stable coverage-failure tokens consumed by FIX-5 routing (ADR 0030).
# Emitted by G7 (_enforce_narrative_coverage) and FIX-6
# (_enforce_timeline_contract) into GateResult.data["reason"] + the
# persisted gate artifact. Both map to the ROOT agent (Scriptwriter).
NARRATIVE_NOT_COVERED = "narrative_not_covered"
TIMELINE_NOT_COVERED = "timeline_not_covered"

# Sentinel action the engine uses to trigger the "cover ALL words" prompt
# hint + the vo-diff skip (claude-auto-tok pattern).
REGEN_NARRATIVE_ACTION = "regen_narrative"


# Deterministic gate failure reason → (patch_reason, patch_action) mapping.
# Used by build_gate_failure_repair_plan to synthesize repair patches when
# the reviewer's deterministic gates fail without an LLM-generated repair_plan.
#
# FIX-5 (ADR 0030): the two stable coverage-failure tokens route to the ROOT
# agent (Scriptwriter) so repair targets the agent that produced the defect,
# never a downstream patch of a broken structure (job_18 root cause).
GATE_FAILURE_REPAIR_MAP: dict[str, tuple[str, str]] = {
    "VISUAL_COVERAGE_FAILED": ("broken_source", "replace_visual"),
    "TEXT_COLLISION_FAILED": ("text_collision", "fix_text"),
    "SAFE_AREA_FAILED": ("text_collision", "fix_text"),
    "PACKAGE_CONSISTENCY_FAILED": ("wrong_event", "redo_research"),
    "TIMESTAMP_SEMANTIC_FAILED": ("semantic_mismatch", "replace_visual"),
    NARRATIVE_NOT_COVERED: ("narrative_coverage_gap", REGEN_NARRATIVE_ACTION),
    TIMELINE_NOT_COVERED: ("timeline_coverage_gap", REGEN_NARRATIVE_ACTION),
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
        # FIX-5: coverage gaps route to the ROOT agent (Scriptwriter) — the
        # narrative_structure producer — so the regen actually rebuilds the
        # broken contract instead of patching a downstream symptom.
        "narrative_coverage_gap": "scriptwriter",
        "timeline_coverage_gap": "scriptwriter",
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


def _build_coverage_repair_patch(patch_reason: str) -> dict[str, Any]:
    """Build the Scriptwriter-targeted regen patch for a coverage token.

    FIX-5 (ADR 0030): unlike the downstream gate patches, the coverage
    patch threads the full SP→SW→VP→VD→Composer cascade (rerun_from
    resolves to "scriptwriter" via :func:`route_repair`) so the
    narrative_structure is regenerated fresh and the broken structure is
    discarded, not patched. The ``regen_narrative`` action is the sentinel
    the engine consumes to add the "cover ALL words" prompt hint + the
    vo-diff skip.
    """
    return {
        "beat_id": "global",
        "action": REGEN_NARRATIVE_ACTION,
        "reason": patch_reason,
        "rerun_from": "scriptwriter",
    }


def build_gate_failure_repair_plan(
    review_output: dict[str, Any],
) -> dict[str, Any] | None:
    """Synthesize a repair routing dict from a deterministic gate failure.

    Deterministic gates (visual_coverage, text_collision, safe_area,
    package_consistency, timestamp_semantic) hard-fail the reviewer without
    an LLM-generated ``repair_plan``, leaving the job silently blocked.
    This function bridges that gap by mapping the gate failure reason to
    a repair patch routed to the correct agent.

    FIX-5 (ADR 0030): the two coverage tokens (``narrative_not_covered``,
    ``timeline_not_covered``) route to the ROOT agent (Scriptwriter) with
    the ``regen_narrative`` sentinel. A synthetic ``review_output`` of
    shape ``{status:"fail", reason:<token>}`` is the FIX-5 entry point
    from the G7/FIX-6 abort site (the gate fires BEFORE the Reviewer).

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
    if action == REGEN_NARRATIVE_ACTION:
        # Root-agent regen: Scriptwriter, full cascade.
        patch = _build_coverage_repair_patch(patch_reason)
        return {
            "decision": "revise",
            "target_agent": "scriptwriter",
            "patches": [patch],
        }

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
