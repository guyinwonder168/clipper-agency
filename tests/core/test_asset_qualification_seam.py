"""SLICE 7 — the engine seam: ``Orchestrator._apply_asset_qualification``.

The pre-VD qualification boundary is wired into ``_run_visual_director_phase`` via this
helper (design §6). These tests pin the seam's load-bearing contracts that the module
unit tests (tests/core/test_asset_qualification.py) cannot, because they are properties
of the engine rewrite, not of ``_qualify_beat`` in isolation:

* rejected candidates never reach VD's live per-beat ``beat.asset_candidates`` surface;
* the rewrite is IMMUTABLE (the caller's ``research_output`` is untouched);
* the flat pool is defense-in-depth-filtered by the union of reject_reasons;
* ``qualification_report.json`` is written with the documented shape.

The helper is driven via a lightweight stub ``self`` (``_trace_writer=None``) so the full
``Orchestrator`` (DB, gates, …) is not constructed. Cache hits are forced by pre-storing
inspections, so the injected VD inspector is never invoked (no real VLM/FFmpeg). The SP
discovery triggered by recovery is mocked to return nothing (the failing beat stays
``exhausted_text_card``).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from clipper_agency.agents.segment_producer import SegmentProducerAgent
from clipper_agency.config.schema import AssetCandidate, BeatFallback, StoryBeat
from clipper_agency.core import inspection_cache
from clipper_agency.core.clip_window import ClipWindow
from clipper_agency.core.inspection_cache import compute_cache_key
from clipper_agency.core.paths import ensure_agent_dir, job_cache_dir
from clipper_agency.orchestrator.engine import Orchestrator

# ---------------------------------------------------------------------------
# Fixtures (mirror tests/core/test_asset_qualification.py)
# ---------------------------------------------------------------------------


def _candidate(url: str, ctype: str = "tiktok_clip") -> dict:
    return {"type": ctype, "url": url, "reason": f"candidate {url}"}


def _fallback() -> BeatFallback:
    return BeatFallback(type="text_card", headline="Card", image_search="")


def _beat_dict(beat_id: int, candidates: list[dict], **overrides: Any) -> dict:
    base = StoryBeat(
        beat_id=beat_id,
        role="evidence",
        narration_goal=f"Beat {beat_id}",
        spoken_point=f"Point {beat_id}",
        safe_wording=f"Safe {beat_id}",
        visual_must_show=f"Visual {beat_id}",
        visual_must_not_show="",
        overlay_text=f"Overlay {beat_id}",
        caption_keywords=[],
        asset_candidates=[AssetCandidate(**c) for c in candidates],
        fallback=_fallback(),
        risk_note="",
    ).model_dump()
    base.update(overrides)
    return base


def _high() -> dict:
    return {
        "decision": "accept",
        "subject_name": "Point 1",
        "person_match": 0.9,
        "event_match": 0.85,
        "claim_support": 0.9,
        "visual_quality": 0.8,
        "misleading_risk": 0.1,
        "source_credibility": 0.8,
    }


def _low() -> dict:
    return {
        "decision": "reject",
        "subject_name": "Point 1",
        "person_match": 0.1,
        "event_match": 0.1,
        "claim_support": 0.2,
        "visual_quality": 0.2,
        "misleading_risk": 0.8,
        "source_credibility": 0.1,
    }


def _store(cache_dir: str, cand: dict, beat_claim: str, insp: dict) -> None:
    """Pre-store an inspection so ``_score_candidate`` hits cache (no inspector call)."""
    from clipper_agency.core.inspection_cache import store as cache_store

    ac = AssetCandidate(**cand)
    cache_store(
        cache_dir,
        compute_cache_key(
            asset_path=ac.url,
            asset_hash=inspection_cache.compute_asset_content_hash(ac),
            beat_claim=beat_claim,
            evidence_contract_hash="",
            model="multimodal",
            prompt_version="1.0",
        ),
        insp,
    )


class TestApplyAssetQualificationSeam:
    """SLICE 7 — the engine seam qualifies before VD + rewrites immutably."""

    def test_rejects_removed_input_untouched_report_written(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        assets_cache = str(tmp_path)
        job_id = 7
        vd_dir = ensure_agent_dir(assets_cache, job_id, "visual_director")
        cache_dir = f"{vd_dir}/inspection_cache"

        accept = _candidate("https://a.com/good.mp4")
        reject_b1 = _candidate("https://b.com/bad1.mp4")
        reject_b2 = _candidate("https://c.com/bad2.mp4")

        beat1 = _beat_dict(1, [accept, reject_b1])  # accept + reject → qualified
        beat2 = _beat_dict(2, [reject_b2])  # all reject → exhausted_text_card

        # Force cache hits (no real inspector). beat_claim is each beat's spoken_point.
        _store(cache_dir, accept, "Point 1", _high())
        _store(cache_dir, reject_b1, "Point 1", _low())
        _store(cache_dir, reject_b2, "Point 2", _low())

        research_output = {
            "story_beats": [beat1, beat2],
            "asset_candidates": [accept, reject_b1, reject_b2],
            "entities": [],
            "do_not_use": [],
        }
        research_output_before = _deep_copy(research_output)

        # Recovery in beat2 would call real SP discovery → mock it to return nothing.
        monkeypatch.setattr(
            SegmentProducerAgent,
            "_discover_multi_source_assets",
            lambda self, topic, entities, config, beats=None: ([], []),
        )

        stub = SimpleNamespace(_trace_writer=None)
        qualified_beats, qualified_flat = Orchestrator._apply_asset_qualification(
            stub, research_output, job_id, "TOPIC", assets_cache
        )

        # (SLICE 9) beat1 keeps ONLY the accept candidate; the reject is gone.
        assert len(qualified_beats) == 2
        b1_urls = {c["url"] for c in qualified_beats[0]["asset_candidates"]}
        assert b1_urls == {"https://a.com/good.mp4"}

        # (SLICE 13) beat2 — all rejected — has no candidates reaching VD, and carries
        # the qualification text-card decision as audit metadata.
        assert qualified_beats[1]["asset_candidates"] == []
        assert qualified_beats[1]["qualification_text_card"]["type"] == "text_card"

        # (SLICE 9 immutability) the caller's research_output is UNTOUCHED.
        assert research_output == research_output_before

        # Flat-pool defense-in-depth: rejects dropped from the flat surface too.
        flat_urls = {c["url"] for c in qualified_flat}
        assert flat_urls == {"https://a.com/good.mp4"}

        # (SLICE 11) qualification_report.json written with the documented shape.
        report_path = Path(job_cache_dir(assets_cache, job_id)) / "qualification_report.json"
        assert report_path.exists()
        import json

        report = json.loads(report_path.read_text())
        assert report["job_id"] == job_id
        assert report["summary"] == {
            "total_beats": 2,
            "qualified_beats": 1,
            "recovered_beats": 0,
            "text_card_last_resort_beats": 1,
            "providers_attempted_added": 0,
        }

    def test_passthrough_when_no_story_beats(self, tmp_path: Path) -> None:
        """Empty story_beats → no beats rewritten, empty flat filter, report still written."""
        stub = SimpleNamespace(_trace_writer=None)
        qualified_beats, qualified_flat = Orchestrator._apply_asset_qualification(
            stub, {"story_beats": [], "asset_candidates": []}, 1, "T", str(tmp_path)
        )
        assert qualified_beats == []
        assert qualified_flat == []
        assert (Path(job_cache_dir(str(tmp_path), 1)) / "qualification_report.json").exists()

    def test_clip_window_attached_to_kept_video_candidate(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """PR 6 — the window selector's window is attached to each kept video candidate."""
        assets_cache = str(tmp_path)
        job_id = 9
        vd_dir = ensure_agent_dir(assets_cache, job_id, "visual_director")
        cache_dir = f"{vd_dir}/inspection_cache"
        accept = _candidate("https://a.com/win.mp4", ctype="tiktok_clip")
        beat = _beat_dict(1, [accept])
        _store(cache_dir, accept, "Point 1", _high())
        monkeypatch.setattr(
            SegmentProducerAgent,
            "_discover_multi_source_assets",
            lambda self, t, e, c, beats=None: ([], []),
        )
        stub_selector = _StubSelector(ClipWindow(2.0, 5.0))
        research = {"story_beats": [beat], "asset_candidates": [accept], "entities": []}
        before = _deep_copy(research)

        qualified_beats, _qualified_flat = Orchestrator._apply_asset_qualification(
            SimpleNamespace(_trace_writer=None),
            research,
            job_id,
            "TOPIC",
            assets_cache,
            window_selector=stub_selector,
        )

        kept = qualified_beats[0]["asset_candidates"]
        assert len(kept) == 1
        # The selector's window rides the qualified candidate through to VD.
        assert kept[0]["source_start_sec"] == 2.0
        assert kept[0]["source_end_sec"] == 5.0
        # Immutability: the original candidate dicts are untouched (new dicts per kept).
        assert research == before

    def test_default_selector_attaches_full_clip_window(self, tmp_path: Path) -> None:
        """PR 6 — without an injected selector, the default attaches the safe full-clip window."""
        assets_cache = str(tmp_path)
        job_id = 10
        vd_dir = ensure_agent_dir(assets_cache, job_id, "visual_director")
        cache_dir = f"{vd_dir}/inspection_cache"
        accept = _candidate("https://a.com/default.mp4", ctype="tiktok_clip")
        beat = _beat_dict(1, [accept])
        _store(cache_dir, accept, "Point 1", _high())

        qualified_beats, _ = Orchestrator._apply_asset_qualification(
            SimpleNamespace(_trace_writer=None),
            {"story_beats": [beat], "asset_candidates": [accept], "entities": []},
            job_id,
            "TOPIC",
            assets_cache,
        )
        kept = qualified_beats[0]["asset_candidates"]
        assert kept[0]["source_start_sec"] == 0.0
        assert kept[0]["source_end_sec"] is None


class _StubSelector:
    """Test double WindowSelector returning a fixed window."""

    def __init__(self, window: ClipWindow) -> None:
        self._window = window

    def select_window(
        self, candidate: dict, beat: Any, source_duration_sec: float | None
    ) -> ClipWindow:
        return self._window


def _deep_copy(obj: Any) -> Any:
    import copy

    return copy.deepcopy(obj)
