"""Duration Gate — estimates script duration and enforces time budgets."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DurationBudget:
    """Immutable duration constraints."""

    target: int
    hard: int


def estimate_script_duration_sec(
    scenes: list[dict],
    words_per_sec: float = 2.0,
    pause_buffer: float = 0.5,
) -> float:
    """Estimate total narration duration from scene word counts.

    Falls back to splitting scene.text when word_count is absent.
    """
    total_words = 0
    for s in scenes:
        wc = s.get("word_count")
        if not wc:
            text = s.get("text", "")
            wc = len(text.split()) if text else 0
        total_words += wc
    return (total_words / words_per_sec) + (pause_buffer * len(scenes))


def check_script_duration_budget(
    estimated_sec: float,
    budget: DurationBudget,
) -> dict:
    """Check whether estimated duration fits within budget.

    Returns a dict with 'pass' (bool) and 'reason' (str).
    """
    if estimated_sec <= budget.target:
        return {"pass": True, "reason": "within_target"}
    if estimated_sec <= budget.hard:
        return {"pass": True, "reason": "exceeds_target"}
    return {"pass": False, "reason": "exceeds_hard_limit"}
