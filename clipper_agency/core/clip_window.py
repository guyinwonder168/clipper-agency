"""Clip-window selection for qualified source videos (PR 6).

A pluggable ``WindowSelector`` chooses the coherent sub-window of a source video to
trim for a beat. PR 6 ships only the conservative ``KeywordOverlapWindowSelector`` —
it establishes the data-flow contract + bounds discipline WITHOUT localizing a spoken
point to a timestamp (that needs transcript timing, DEFERRED to a post-v2.4.0 backend;
see ``docs/plans/pr6-clip-window-design.md`` §1). The selector runs at the
qualification boundary (the PR 5 seam); Composer re-clamps the window to source bounds
at render time (defense-in-depth).
"""

from __future__ import annotations

import logging
import string
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from clipper_agency.config.schema import StoryBeat

logger = logging.getLogger(__name__)

# Candidate types that represent a trimmable video window (vs. a static image/card).
_VIDEO_TYPES = frozenset({"tiktok_clip", "video", "pexels_video", "youtube"})


@dataclass(frozen=True)
class ClipWindow:
    """A source-video trim window in seconds (local-file frame).

    ``source_end_sec`` is ``None`` => "to end of source". Always within source bounds;
    Composer re-validates and clamps at render time.
    """

    source_start_sec: float = 0.0
    source_end_sec: float | None = None


class WindowSelector(Protocol):
    """Selects a source-video trim window for a candidate against a beat."""

    def select_window(
        self,
        candidate: dict,
        beat: StoryBeat | dict,
        source_duration_sec: float | None,
    ) -> ClipWindow:
        """Return the trim window. Must be within ``[0, source_duration_sec]``."""
        ...


def _candidate_text(candidate: dict) -> str:
    return " ".join(
        str(candidate.get(k, ""))
        for k in ("title", "desc", "description", "reason")
        if candidate.get(k)
    ).lower()


def _beat_keywords(beat: Any) -> list[str]:
    """Lowercased keyword tokens from a beat (caption_keywords + narration fields)."""
    tokens: list[str] = []

    def _get(key: str, default: Any) -> Any:
        if isinstance(beat, dict):
            return beat.get(key, default)
        return getattr(beat, key, default)

    caption_kw = _get("caption_keywords", None)
    if isinstance(caption_kw, list):
        tokens.extend(str(k) for k in caption_kw)
    for field in ("spoken_point", "narration_goal", "visual_must_show"):
        val = _get(field, "")
        if val:
            tokens.extend(str(val).split())
    # Lowercase + strip edge punctuation so "volcano," matches "volcano".
    return [t.lower().strip(string.punctuation) for t in tokens if t]


class KeywordOverlapWindowSelector:
    """Conservative keyword-overlap window selector (PR 6 v1 default).

    Scores normalized keyword overlap between the beat and the candidate's text
    metadata, but returns the FULL-CLIP window (``ClipWindow(0.0, None)``) for every
    candidate: keyword overlap cannot localize a spoken point to a timestamp, and a
    wrong sub-segment is worse than the full clip. The score is computed for
    observability and as the seam a future transcript backend (DEFERRED) replaces.

    Non-video candidates (images/cards) always get the full-clip window by
    construction. Output is always within source bounds (start=0.0, end=None).
    """

    def relevance_score(self, candidate: dict, beat: Any) -> float:
        """Normalized keyword-overlap score in ``[0.0, 1.0]``. Pure, deterministic."""
        text = _candidate_text(candidate)
        keywords = _beat_keywords(beat)
        if not keywords or not text:
            return 0.0
        matched = sum(1 for kw in keywords if kw and kw in text)
        return matched / len(keywords)

    def select_window(
        self,
        candidate: dict,
        beat: Any,
        source_duration_sec: float | None,
    ) -> ClipWindow:
        # Non-video candidates (images/cards) have no notion of a trim window.
        if candidate.get("type", "") not in _VIDEO_TYPES:
            return ClipWindow(0.0, None)
        # Video candidates: keyword overlap cannot localize a spoken point to a
        # timestamp (transcript timing is DEFERRED), so return the full-clip window.
        # The relevance score + duration are logged for observability only.
        logger.debug(
            "clip_window: keyword_overlap=%.2f source_duration=%s -> full-clip window (v1)",
            self.relevance_score(candidate, beat),
            source_duration_sec,
        )
        return ClipWindow(0.0, None)
