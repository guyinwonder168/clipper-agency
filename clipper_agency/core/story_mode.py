"""Deterministic story-mode classifier.

Pure keyword/pattern matching — no LLM calls.  Every decision is
reproducible from the same inputs.

Priority (highest → lowest):
1. target_duration_sec < 20  → single_story  (hard constraint)
2. Controversy keywords      → controversy_explainer
3. Breaking-news keywords    → breaking_news
4. Roundup indicators        → roundup
5. Default fallback          → single_story
"""

from __future__ import annotations

import re

from clipper_agency.config.schema import StoryModeDecision

# ---------------------------------------------------------------------------
# Keyword sets (lowercased, stripped)
# ---------------------------------------------------------------------------

_CONTROVERSY_KEYWORDS = frozenset({
    "kontroversi", "heboh", "viral", "skandal", "drama",
})

_BREAKING_KEYWORDS = frozenset({
    "breaking", "terbaru banget", "barusan", "just now",
})

_ROUNDUP_BROAD_WORDS = frozenset({
    "berbagai", "beberapa", "kumpulan",
})

# Pattern: at least 2 comma-separated tokens (entity names)
_COMMA_ENTITIES_RE = re.compile(r",\s*|\s+dan\s+", flags=re.IGNORECASE)

# ---------------------------------------------------------------------------
# Helpers (pure functions)
# ---------------------------------------------------------------------------


def _topic_lower(topic: str) -> str:
    """Normalise topic to lowercase for keyword matching."""
    return topic.lower().strip()


def _has_keyword(topic_lower: str, keywords: frozenset[str]) -> bool:
    """Return True if *any* keyword appears as a substring in the topic."""
    return any(kw in topic_lower for kw in keywords)


def _count_comma_entities(topic: str) -> int:
    """Estimate entity count from comma / 'dan' separated names."""
    parts = _COMMA_ENTITIES_RE.split(topic)
    # Keep parts that look like names (alphabetic, length > 1)
    return sum(1 for p in parts if p.strip() and re.search(r"[A-Za-z]{2,}", p.strip()))


def _is_roundup_topic(topic_lower: str, entity_count: int) -> bool:
    """Heuristic: topic looks like a roundup / list of multiple items."""
    if entity_count >= 2:
        return True
    # "berita terbaru hari ini" pattern — broad entertainment scope
    if "terbaru hari ini" in topic_lower:
        return True
    if "berita terbaru" in topic_lower and topic_lower.endswith("hari ini"):
        return True
    if any(w in topic_lower for w in _ROUNDUP_BROAD_WORDS):
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_MIN_ROUNDUP_DURATION = 20


def classify_story_mode(
    topic: str,
    target_duration_sec: int = 30,
) -> StoryModeDecision:
    """Classify a topic into a story mode using deterministic rules.

    Parameters
    ----------
    topic:
        The research topic string (e.g. "berita artis terbaru hari ini").
    target_duration_sec:
        Desired video duration in seconds.

    Returns
    -------
    StoryModeDecision with all fields populated.
    """
    topic_lower = _topic_lower(topic)

    # --- Rule 1: hard duration constraint (overrides everything) ---
    if target_duration_sec < _MIN_ROUNDUP_DURATION:
        return StoryModeDecision(
            story_mode="single_story",
            confidence=0.95,
            reason="Duration too short for multi-item formats; forced single_story.",
            item_count=1,
            target_duration_sec=target_duration_sec,
            requires_intro_card=False,
            thumbnail_strategy="default",
            cta_strategy="default",
        )

    # --- Rule 2: controversy keywords ---
    if _has_keyword(topic_lower, _CONTROVERSY_KEYWORDS):
        return StoryModeDecision(
            story_mode="controversy_explainer",
            confidence=0.9,
            reason="Controversy keyword detected; deep-dive explainer mode selected.",
            item_count=1,
            target_duration_sec=target_duration_sec,
            requires_intro_card=False,
            thumbnail_strategy="controversy",
            cta_strategy="opinion_ask",
        )

    # --- Rule 3: breaking-news keywords ---
    if _has_keyword(topic_lower, _BREAKING_KEYWORDS):
        return StoryModeDecision(
            story_mode="breaking_news",
            confidence=0.9,
            reason="Breaking-news keyword detected; urgent delivery mode selected.",
            item_count=1,
            target_duration_sec=target_duration_sec,
            requires_intro_card=False,
            thumbnail_strategy="breaking",
            cta_strategy="share_cta",
        )

    # --- Rule 4: roundup indicators ---
    entity_count = _count_comma_entities(topic)
    if _is_roundup_topic(topic_lower, entity_count):
        items = max(entity_count, 3) if entity_count >= 2 else 3
        return StoryModeDecision(
            story_mode="roundup",
            confidence=0.85,
            reason="Multiple entities or broad-scope topic detected; roundup mode selected.",
            item_count=items,
            target_duration_sec=target_duration_sec,
            requires_intro_card=True,
            thumbnail_strategy="collage",
            cta_strategy="comment_ask",
        )

    # --- Rule 5: default fallback ---
    return StoryModeDecision(
        story_mode="single_story",
        confidence=0.6,
        reason="No specific mode indicators found; defaulting to single_story.",
        item_count=1,
        target_duration_sec=target_duration_sec,
        requires_intro_card=False,
        thumbnail_strategy="default",
        cta_strategy="default",
    )
