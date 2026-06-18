"""PR 6 — Visual Director clip-window threading (design slice 4).

Two unit-tested pieces (hermetic — no downloads/FFmpeg):
* ``_attach_candidate_windows`` re-attaches ``source_start_sec``/``source_end_sec`` from
  each beat's matching candidate (by ``source_url``) onto the planned action — works for
  both the LLM plan and the fallback plan (the LLM rebuilds actions and drops candidate
  metadata, so this post-pass restores the window the qualification boundary attached).
* ``_exec_tiktok_clip`` carries the window from the action into the Composer asset dict.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from clipper_agency.agents.visual_director import VisualDirectorAgent
from clipper_agency.config.schema import AssetCandidate, BeatFallback, StoryBeat


def _beat(beat_id: int, candidates: list[AssetCandidate]) -> StoryBeat:
    return StoryBeat(
        beat_id=beat_id,
        role="evidence",
        narration_goal="g",
        spoken_point="p",
        safe_wording="s",
        visual_must_show="v",
        visual_must_not_show="",
        overlay_text="o",
        caption_keywords=[],
        asset_candidates=candidates,
        fallback=BeatFallback(type="text_card", headline="h", image_search=""),
        risk_note="",
    )


class TestAttachCandidateWindows:
    def test_copies_window_by_url(self) -> None:
        cand = AssetCandidate(
            type="tiktok_clip",
            url="https://x.com/a.mp4",
            reason="r",
            source_start_sec=3.0,
            source_end_sec=7.0,
        )
        beat = _beat(1, [cand])
        plan = [
            {"beat_id": 1, "action": {"type": "tiktok_clip", "source_url": "https://x.com/a.mp4"}}
        ]
        result = VisualDirectorAgent()._attach_candidate_windows(plan, [beat])
        assert result[0]["action"]["source_start_sec"] == 3.0
        assert result[0]["action"]["source_end_sec"] == 7.0

    def test_no_match_leaves_action_unchanged(self) -> None:
        beat = _beat(1, [AssetCandidate(type="tiktok_clip", url="https://x.com/a.mp4", reason="r")])
        plan = [
            {
                "beat_id": 1,
                "action": {"type": "tiktok_clip", "source_url": "https://other.com/b.mp4"},
            }
        ]
        result = VisualDirectorAgent()._attach_candidate_windows(plan, [beat])
        assert "source_start_sec" not in result[0]["action"]

    def test_action_without_url_skipped(self) -> None:
        beat = _beat(1, [])
        plan = [{"beat_id": 1, "action": {"type": "text_card", "headline": "h"}}]
        original = [dict(item) for item in plan]
        result = VisualDirectorAgent()._attach_candidate_windows(plan, [beat])
        assert result[0]["action"] == original[0]["action"]


class TestExecTiktokClipCarriesWindow:
    def _ytdlp(self, path: Path) -> Any:
        return SimpleNamespace(download=lambda url, out: SimpleNamespace(path=str(path)))

    def test_window_flows_to_asset(self, tmp_path: Path) -> None:
        action = {
            "type": "tiktok_clip",
            "source_url": "https://x.com/a.mp4",
            "source_start_sec": 2.5,
            "source_end_sec": 5.0,
        }
        asset = VisualDirectorAgent()._exec_tiktok_clip(
            action, 1, str(tmp_path), None, self._ytdlp(tmp_path / "scene_1.mp4")
        )
        assert asset is not None
        assert asset["source_start_sec"] == 2.5
        assert asset["source_end_sec"] == 5.0
        assert "path" in asset

    def test_no_window_still_returns_asset(self, tmp_path: Path) -> None:
        action = {"type": "tiktok_clip", "source_url": "https://x.com/a.mp4"}
        asset = VisualDirectorAgent()._exec_tiktok_clip(
            action, 1, str(tmp_path), None, self._ytdlp(tmp_path / "scene_1.mp4")
        )
        assert asset is not None
        assert asset["source"] == "tiktok_clip"
        assert "source_start_sec" not in asset
