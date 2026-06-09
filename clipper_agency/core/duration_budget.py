"""Editorial duration budget allocator — deterministic section timing.

Given a story_mode, item_count, and target_duration_sec, returns a
DurationBudget with sections whose durations sum exactly to the target.

Allocation rules:
- roundup:           intro (15%), N story (equal split of remainder - cta), cta (10%, min 2s)
- single_story:      hook (10%), context (20%), evidence (30%), reveal (25%), cta (15%)
- controversy_explainer / breaking_news: same as single_story
- any other mode:    falls back to single_story
"""

from clipper_agency.config.schema import DurationBudget, DurationBudgetSection

# Roundup allocation constants
_ROUNDUP_INTRO_PCT = 0.15
_ROUNDUP_CTA_PCT = 0.10
_ROUNDUP_CTA_MIN_SEC = 2.0

# Single-story allocation constants (hook, context, evidence, reveal, cta)
_SINGLE_PCT = [0.10, 0.20, 0.30, 0.25, 0.15]
_SINGLE_TYPES = ["hook", "context", "evidence", "reveal", "cta"]

_NARRATIVE_MODES = {"single_story", "controversy_explainer", "breaking_news"}


def _allocate_narrative(target_duration_sec: int) -> list[DurationBudgetSection]:
    """hook / context / evidence / reveal / cta with fixed percentages."""
    sections: list[DurationBudgetSection] = []
    allocated = 0.0
    for i, (type_name, pct) in enumerate(zip(_SINGLE_TYPES, _SINGLE_PCT)):
        if i == len(_SINGLE_TYPES) - 1:
            # Last section absorbs rounding remainder
            dur = target_duration_sec - allocated
        else:
            dur = target_duration_sec * pct
            allocated += dur
        sections.append(
            DurationBudgetSection(type=type_name, duration_sec=dur)
        )
    return sections


def _allocate_roundup(
    item_count: int, target_duration_sec: int
) -> list[DurationBudgetSection]:
    """intro + N story sections + cta."""
    intro_dur = target_duration_sec * _ROUNDUP_INTRO_PCT
    cta_dur = max(target_duration_sec * _ROUNDUP_CTA_PCT, _ROUNDUP_CTA_MIN_SEC)
    story_total = target_duration_sec - intro_dur - cta_dur
    story_dur_each = story_total / item_count

    sections: list[DurationBudgetSection] = [
        DurationBudgetSection(type="intro", duration_sec=intro_dur),
    ]
    for _ in range(item_count):
        sections.append(
            DurationBudgetSection(type="story", duration_sec=story_dur_each)
        )
    sections.append(DurationBudgetSection(type="cta", duration_sec=cta_dur))

    # Absorb any floating-point drift into the last section (cta)
    current_sum = sum(s.duration_sec for s in sections)
    sections[-1] = sections[-1].model_copy(
        update={"duration_sec": sections[-1].duration_sec + (target_duration_sec - current_sum)}
    )
    return sections


def allocate_duration_budget(
    story_mode: str, item_count: int, target_duration_sec: int
) -> DurationBudget:
    """Return a deterministic editorial duration budget.

    Pure function — no side effects, no API calls.
    """
    if story_mode == "roundup":
        sections = _allocate_roundup(item_count, target_duration_sec)
    else:
        # single_story, controversy_explainer, breaking_news, and fallback
        sections = _allocate_narrative(target_duration_sec)

    return DurationBudget(
        target_duration_sec=target_duration_sec, sections=sections
    )
