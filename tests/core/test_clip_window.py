"""PR 6 — clip-window selector unit tests (design slices 1, 2, 7).

``clipper_agency/core/clip_window.py`` ships the data contract + a pluggable
``WindowSelector`` Protocol + the conservative ``KeywordOverlapWindowSelector``
default. PR 6 v1 returns the FULL-CLIP window for every candidate (keyword overlap
cannot localize a spoken point to a timestamp; transcript timing is DEFERRED), so
these tests pin: deterministic scoring, the always-in-bounds contract, non-video =>
full clip, and Protocol pluggability (the seam a future transcript backend swaps in).
"""

from __future__ import annotations

from typing import Any

from clipper_agency.core.clip_window import (
    ClipWindow,
    KeywordOverlapWindowSelector,
    WindowSelector,
)


def _cand(ctype: str = "tiktok_clip", **over: Any) -> dict:
    base = {
        "type": ctype,
        "url": "https://x.com/c.mp4",
        "reason": "r",
        "title": "",
        "desc": "",
        "description": "",
    }
    base.update(over)
    return base


def _beat(**over: Any) -> dict:
    base = {
        "beat_id": 1,
        "spoken_point": "",
        "narration_goal": "",
        "visual_must_show": "",
        "caption_keywords": [],
    }
    base.update(over)
    return base


class TestClipWindowContract:
    def test_defaults_are_full_clip_from_zero(self) -> None:
        w = ClipWindow()
        assert w.source_start_sec == 0.0
        assert w.source_end_sec is None

    def test_is_frozen(self) -> None:
        w = ClipWindow(1.5, 4.0)
        assert w.source_start_sec == 1.5
        assert w.source_end_sec == 4.0


class TestKeywordOverlapRelevanceScore:
    def test_high_overlap_scores_higher_than_none(self) -> None:
        beat = _beat(spoken_point="dramatic volcano eruption")
        relevant = _cand(title="Volcano Eruption Footage", desc="dramatic")
        irrelevant = _cand(title="Cooking Pasta Recipe", desc="italian")
        sel = KeywordOverlapWindowSelector()
        assert sel.relevance_score(relevant, beat) > sel.relevance_score(irrelevant, beat)

    def test_missing_fields_score_zero(self) -> None:
        sel = KeywordOverlapWindowSelector()
        assert sel.relevance_score(_cand(), _beat()) == 0.0
        # Beat with no keywords at all.
        assert sel.relevance_score(_cand(title="anything"), _beat()) == 0.0

    def test_score_is_in_unit_interval(self) -> None:
        sel = KeywordOverlapWindowSelector()
        beat = _beat(caption_keywords=["volcano", "lava", "ash"], spoken_point="eruption")
        cand = _cand(title="volcano lava ash eruption", desc="lava")
        s = sel.relevance_score(cand, beat)
        assert 0.0 <= s <= 1.0


class TestSelectWindowAlwaysFullClipV1:
    """PR 6 v1: every candidate gets the conservative full-clip window."""

    def test_video_candidate_returns_full_clip(self) -> None:
        sel = KeywordOverlapWindowSelector()
        w = sel.select_window(_cand("tiktok_clip", title="relevant"), _beat(spoken_point="x"), 30.0)
        assert w == ClipWindow(0.0, None)

    def test_non_video_candidate_returns_full_clip(self) -> None:
        sel = KeywordOverlapWindowSelector()
        for ctype in ("screenshot", "photo", "pexels_image", "text_card"):
            w = sel.select_window(_cand(ctype), _beat(), 10.0)
            assert w == ClipWindow(0.0, None)

    def test_unknown_duration_returns_full_clip(self) -> None:
        sel = KeywordOverlapWindowSelector()
        w = sel.select_window(_cand("tiktok_clip"), _beat(), None)
        assert w == ClipWindow(0.0, None)

    def test_output_always_within_bounds(self) -> None:
        """For any input, start >= 0 and end is None or strictly after start (in-bounds)."""
        sel = KeywordOverlapWindowSelector()
        for dur in (None, 0.0, 1.0, 100.0):
            w = sel.select_window(_cand("tiktok_clip"), _beat(), dur)
            assert w.source_start_sec >= 0.0
            assert w.source_end_sec is None or w.source_end_sec > w.source_start_sec


class TestProtocolPluggability:
    def test_custom_selector_swaps_in(self) -> None:
        """A transcript-backend selector can implement the Protocol and return a real window."""

        class StubTranscriptSelector:
            def select_window(
                self, candidate: dict, beat: Any, source_duration_sec: float | None
            ) -> ClipWindow:
                # A real transcript backend would localize; here it returns a fixed window.
                end = source_duration_sec if source_duration_sec else 5.0
                return ClipWindow(2.0, min(4.0, end))

        sel: WindowSelector = StubTranscriptSelector()
        w = sel.select_window(_cand("tiktok_clip"), _beat(), 30.0)
        assert w == ClipWindow(2.0, 4.0)
