"""Package consistency evaluator — pure heuristic checks.

Deterministic rules comparing thumbnail text, caption, and video scope.
No LLM calls. All functions are pure.
"""

import re

from clipper_agency.config.schema import PackageConsistencyResult

_MULTI_ENTITY_WORDS = frozenset({"tiga", "beberapa", "banyak", "semua", "empat", "lima", "berbagai"})

_MIN_ENTITY_LEN = 2


def _count_matching_entities(text: str, entities: list[str]) -> int:
    """Count how many entities appear in text (case-insensitive word match).

    Entities shorter than 2 characters are skipped to avoid false
    substring matches (e.g. ``"a"`` matching inside ``"akhirnya"``).
    """
    lower = text.lower()
    count = 0
    for entity in entities:
        if len(entity) < _MIN_ENTITY_LEN:
            continue
        if re.search(r"\b" + re.escape(entity.lower()) + r"\b", lower):
            count += 1
    return count


def _caption_mentions_multiple(caption: str) -> bool:
    """Check if caption uses multi-entity indicator words."""
    words = set(caption.lower().split())
    return bool(words & _MULTI_ENTITY_WORDS)


def evaluate_package_consistency(
    topic: str,
    script: str,
    thumbnail_text: str,
    caption: str,
    story_mode: str,
    main_entities: list[str],
) -> PackageConsistencyResult:
    """Evaluate whether the output package (thumbnail + caption) matches video scope.

    Args:
        topic: Video topic string.
        script: Full script text.
        thumbnail_text: Text shown on thumbnail.
        caption: TikTok caption text.
        story_mode: "roundup" or "single_story" (empty = skip).
        main_entities: Named entities from the story.

    Returns:
        PackageConsistencyResult with pass/fail status.
    """
    if not story_mode or not main_entities:
        return PackageConsistencyResult(status="pass")

    if story_mode == "roundup":
        return _check_roundup(thumbnail_text, caption, main_entities)

    if story_mode == "single_story":
        return _check_single_story(thumbnail_text, caption, main_entities)

    return PackageConsistencyResult(status="pass")


def _check_roundup(
    thumbnail_text: str,
    _caption: str,
    main_entities: list[str],
) -> PackageConsistencyResult:
    """Roundup video: thumbnail should cover multiple entities, not just one."""
    if len(main_entities) < 3:
        return PackageConsistencyResult(status="pass")

    matching = _count_matching_entities(thumbnail_text, main_entities)
    if matching == 1:
        matched = next(
            e for e in main_entities if e.lower() in thumbnail_text.lower()
        )
        return PackageConsistencyResult(
            status="fail",
            issue="PACKAGE_SCOPE_MISMATCH",
            detail=(
                f"Roundup video has single-entity thumbnail "
                f"(only '{matched}' found, {len(main_entities)} entities total)"
            ),
        )

    return PackageConsistencyResult(status="pass")


def _check_single_story(
    _thumbnail_text: str,
    caption: str,
    _main_entities: list[str],
) -> PackageConsistencyResult:
    """Single story video: caption should not imply multiple stories."""
    if _caption_mentions_multiple(caption):
        return PackageConsistencyResult(
            status="fail",
            issue="PACKAGE_SCOPE_MISMATCH",
            detail=(
                "Single-story video has multi-entity caption "
                f"(mentions multiple: '{caption[:80]}')"
            ),
        )

    return PackageConsistencyResult(status="pass")
