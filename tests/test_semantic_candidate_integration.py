"""Integration test: semantic candidate rejection through the full ranking pipeline.

Scenario:
- Candidate A: correct person, wrong event → rejected
- Candidate B: correct event and claim → selected
- Semantic metadata persisted through inspection cache

All external dependencies (LLM, filesystem) are mocked — no network, no files.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from clipper_agency.core.candidate_semantic_ranker import (
    rank_candidates,
    select_best_candidate,
)
from clipper_agency.core.inspection_cache import compute_cache_key, lookup, store
from clipper_agency.llm.multimodal_client import (
    MultimodalInspectionClient,
    parse_inspection_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_llm_response(content: str) -> dict:
    """Simulate an OpenRouter chat() response."""
    return {"content": content, "model": "test/mock-model", "usage": {"total_tokens": 100}}


def _inspection_a_wrong_event() -> dict:
    """Candidate A inspection: correct person, wrong event."""
    return {
        "person_match": 0.85,
        "event_match": 0.15,
        "claim_support": 0.20,
        "visual_quality": 0.80,
        "temporal_match": 0.70,
        "source_credibility": 0.75,
        "cleanliness_score": 0.90,
        "misleading_risk": 0.60,
        "decision": "reject",
        "reason": "Wrong event — person matches but scene is unrelated",
    }


def _inspection_b_correct_event() -> dict:
    """Candidate B inspection: correct event and claim."""
    return {
        "person_match": 0.90,
        "event_match": 0.92,
        "claim_support": 0.88,
        "visual_quality": 0.85,
        "temporal_match": 0.80,
        "source_credibility": 0.90,
        "cleanliness_score": 0.95,
        "misleading_risk": 0.05,
        "decision": "accept",
        "reason": "Strong match — shows the correct event and supports the claim",
    }


def _make_candidate_dict(
    asset_id: str,
    beat_id: str,
    inspection: dict,
    cleanliness_score: float = 0.90,
    role: str = "evidence",
    treatment: str = "picture_in_picture",
) -> dict:
    """Build a candidate dict compatible with rank_candidates()."""
    return {
        "asset_id": asset_id,
        "beat_id": beat_id,
        "role": role,
        "treatment": treatment,
        "cleanliness_score": cleanliness_score,
        "inspection": inspection,
        "visual_relevance": {
            "person_match": inspection["person_match"],
            "event_match": inspection["event_match"],
            "claim_support": inspection["claim_support"],
            "visual_quality": inspection["visual_quality"],
            "misleading_risk": inspection["misleading_risk"],
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def beat() -> dict:
    """A single story beat with a spoken claim."""
    return {
        "beat_id": "beat_awards_01",
        "spoken_point": "Raisa won the Best Female Artist award at the AMI 2024 ceremony",
        "visual_must_show": "Raisa on stage at award ceremony",
        "visual_must_not_show": "unrelated concert footage",
    }


@pytest.fixture()
def mock_llm_client() -> MagicMock:
    """Mock OpenRouterClient that returns deterministic inspection results."""
    client = MagicMock()
    # First call → candidate A (wrong event), second call → candidate B (correct)
    client.chat.side_effect = [
        _mock_llm_response(json.dumps(_inspection_a_wrong_event())),
        _mock_llm_response(json.dumps(_inspection_b_correct_event())),
    ]
    return client


@pytest.fixture()
def inspection_client(mock_llm_client: MagicMock) -> MultimodalInspectionClient:
    """MultimodalInspectionClient with mocked LLM backend."""
    return MultimodalInspectionClient(client=mock_llm_client, model="test/mock-model")


# ---------------------------------------------------------------------------
# Test: Full mocked multimodal → ranking → rejection → selection pipeline
# ---------------------------------------------------------------------------


class TestSemanticCandidateIntegration:
    """End-to-end pipeline test with mocked multimodal inspections."""

    def test_candidate_a_rejected_candidate_b_selected(
        self,
        beat: dict,
        inspection_client: MultimodalInspectionClient,
    ) -> None:
        """Candidate A (wrong event) rejected; Candidate B (correct event) selected."""
        # Step 1: Run multimodal inspections for both candidates
        result_a = inspection_client.inspect_asset(
            job_id=1,
            beat_id="beat_awards_01",
            asset_id="asset_awards_clip_wrong",
            beat=beat,
            frame_paths=["/tmp/frame_a1.jpg"],
            ocr_text="Concert Live 2023",
            source_metadata={"source": "tiktok", "url": "https://example.com/clip_a"},
        )
        result_b = inspection_client.inspect_asset(
            job_id=1,
            beat_id="beat_awards_01",
            asset_id="asset_awards_clip_correct",
            beat=beat,
            frame_paths=["/tmp/frame_b1.jpg"],
            ocr_text="AMI Awards 2024",
            source_metadata={"source": "youtube_official", "url": "https://example.com/clip_b"},
        )

        # Step 2: Build candidate dicts using inspection results
        candidate_a = _make_candidate_dict(
            asset_id="asset_awards_clip_wrong",
            beat_id="beat_awards_01",
            inspection=result_a,
            cleanliness_score=result_a.get("cleanliness_score", 0.90),
        )
        candidate_b = _make_candidate_dict(
            asset_id="asset_awards_clip_correct",
            beat_id="beat_awards_01",
            inspection=result_b,
            cleanliness_score=result_b.get("cleanliness_score", 0.95),
        )

        # Step 3: Rank candidates
        ranked = rank_candidates(beat, [candidate_a, candidate_b])

        # Step 4: Select best candidate
        best = select_best_candidate(ranked)

        # --- Assertions ---
        # Candidate A is rejected
        a_entries = [r for r in ranked if r.asset_id == "asset_awards_clip_wrong"]
        assert len(a_entries) == 1
        assert a_entries[0].decision == "reject"
        assert "HIGH_MISLEADING_RISK" in a_entries[0].rank_reason or a_entries[0].final_score < 0.60

        # Candidate B is accepted / selected
        assert best is not None
        assert best.asset_id == "asset_awards_clip_correct"
        assert best.decision == "accept"
        assert best.final_score >= 0.60

        # B scores higher than A
        b_entries = [r for r in ranked if r.asset_id == "asset_awards_clip_correct"]
        assert len(b_entries) == 1
        assert b_entries[0].final_score > a_entries[0].final_score

    def test_semantic_metadata_persisted_in_cache(
        self,
        beat: dict,
        inspection_client: MultimodalInspectionClient,
        tmp_path,
    ) -> None:
        """Inspection results are stored and retrievable from cache."""
        cache_dir = tmp_path / "inspection_cache"

        # Inspect candidate B
        result = inspection_client.inspect_asset(
            job_id=1,
            beat_id="beat_awards_01",
            asset_id="asset_awards_clip_correct",
            beat=beat,
            frame_paths=["/tmp/frame_b1.jpg"],
            source_metadata={"source": "youtube_official"},
        )

        # Compute a cache key and store
        cache_key = compute_cache_key(
            asset_path="/tmp/frame_b1.jpg",
            asset_hash="abc123",
            beat_claim=beat["spoken_point"],
            evidence_contract_hash="contract_hash_001",
            model="test/mock-model",
            prompt_version="1",
        )
        store(cache_dir, cache_key, result)

        # Lookup and verify
        cached = lookup(cache_dir, cache_key)
        assert cached is not None
        assert cached["asset_id"] == "asset_awards_clip_correct"
        assert cached["beat_id"] == "beat_awards_01"
        # First LLM call returns inspection A (wrong event)
        assert cached["person_match"] == 0.85
        assert cached["event_match"] == 0.15
        assert cached["claim_support"] == 0.20
        assert cached["misleading_risk"] == 0.60
        assert cached["decision"] == "reject"
        assert "cached_at" in cached
        assert cached["cache_key"] == cache_key

    def test_cache_miss_returns_none(
        self,
        tmp_path,
    ) -> None:
        """Cache lookup for a non-existent key returns None."""
        cache_dir = tmp_path / "inspection_cache"
        result = lookup(cache_dir, "nonexistent_key")
        assert result is None

    def test_ranked_candidate_inspection_metadata_flows_through(
        self,
        beat: dict,
        inspection_client: MultimodalInspectionClient,
    ) -> None:
        """Inspection metadata is preserved in RankedCandidate objects."""
        result = inspection_client.inspect_asset(
            job_id=1,
            beat_id="beat_awards_01",
            asset_id="asset_awards_clip_correct",
            beat=beat,
            frame_paths=["/tmp/frame_b1.jpg"],
            source_metadata={"source": "youtube_official"},
        )

        candidate = _make_candidate_dict(
            asset_id="asset_awards_clip_correct",
            beat_id="beat_awards_01",
            inspection=result,
            cleanliness_score=0.95,
        )
        ranked = rank_candidates(beat, [candidate])
        # Single candidate with misleading_risk=0.60 gets rejected + fallback appended
        assert len(ranked) == 2

        # First entry is the rejected candidate
        rejected = [r for r in ranked if r.decision == "reject"]
        assert len(rejected) == 1
        assert rejected[0].inspection["person_match"] == 0.85
        assert rejected[0].inspection["event_match"] == 0.15
        assert rejected[0].inspection["misleading_risk"] == 0.60
        assert rejected[0].cleanliness_score == 0.95

        # Second entry is the fallback
        fallback = [r for r in ranked if r.decision == "fallback_card"]
        assert len(fallback) == 1

    def test_both_candidates_inspected_in_sequence(
        self,
        beat: dict,
        mock_llm_client: MagicMock,
        inspection_client: MultimodalInspectionClient,
    ) -> None:
        """Both candidates trigger separate LLM calls with correct parameters."""
        inspection_client.inspect_asset(
            job_id=1,
            beat_id="beat_awards_01",
            asset_id="asset_a",
            beat=beat,
            frame_paths=["/tmp/frame_a.jpg"],
        )
        inspection_client.inspect_asset(
            job_id=1,
            beat_id="beat_awards_01",
            asset_id="asset_b",
            beat=beat,
            frame_paths=["/tmp/frame_b.jpg"],
        )

        # Two LLM calls made
        assert mock_llm_client.chat.call_count == 2

        # Verify correct model and temperature
        for call in mock_llm_client.chat.call_args_list:
            assert call.kwargs.get("model") == "test/mock-model"
            assert call.kwargs.get("temperature") == 0.2

    def test_all_rejected_triggers_fallback(
        self,
        beat: dict,
    ) -> None:
        """When all candidates are rejected, fallback_card is appended."""
        # Both candidates with high misleading_risk
        bad_a = _make_candidate_dict(
            asset_id="bad_a",
            beat_id="beat_awards_01",
            inspection=_inspection_a_wrong_event(),
        )
        # Override to guarantee rejection
        bad_a["inspection"]["misleading_risk"] = 0.90
        bad_a["inspection"]["claim_support"] = 0.10
        bad_a["visual_relevance"]["misleading_risk"] = 0.90
        bad_a["visual_relevance"]["claim_support"] = 0.10

        bad_b = _make_candidate_dict(
            asset_id="bad_b",
            beat_id="beat_awards_01",
            inspection=_inspection_a_wrong_event(),
        )
        bad_b["inspection"]["misleading_risk"] = 0.85
        bad_b["inspection"]["claim_support"] = 0.05
        bad_b["visual_relevance"]["misleading_risk"] = 0.85
        bad_b["visual_relevance"]["claim_support"] = 0.05

        ranked = rank_candidates(beat, [bad_a, bad_b])

        # All should be rejected
        assert all(r.decision == "reject" for r in ranked if r.asset_id != "fallback")

        # Fallback card appended
        fallback = [r for r in ranked if r.decision == "fallback_card"]
        assert len(fallback) == 1
        assert fallback[0].asset_id == "fallback"

        # select_best_candidate returns the fallback (not None, since fallback_card != "reject")
        best = select_best_candidate(ranked)
        assert best is not None
        assert best.decision == "fallback_card"
        assert best.asset_id == "fallback"

    def test_parse_inspection_json_roundtrip(self) -> None:
        """Raw LLM JSON string round-trips through parse_inspection_json."""
        raw = json.dumps(_inspection_b_correct_event())
        parsed = parse_inspection_json(raw)

        assert parsed["person_match"] == 0.90
        assert parsed["event_match"] == 0.92
        assert parsed["claim_support"] == 0.88
        assert parsed["misleading_risk"] == 0.05
        assert parsed["decision"] == "accept"

    def test_parse_inspection_json_handles_markdown_fence(self) -> None:
        """Markdown code fences are stripped during parsing."""
        raw = '```json\n{"person_match":0.9,"event_match":0.8,"claim_support":0.7,"visual_quality":0.85,"temporal_match":0.75,"source_credibility":0.8,"cleanliness_score":0.6,"misleading_risk":0.1,"decision":"accept","reason":"OK"}\n```'
        parsed = parse_inspection_json(raw)
        assert parsed["decision"] == "accept"
        assert parsed["person_match"] == 0.9

    def test_inspection_error_result_on_llm_failure(
        self,
        beat: dict,
    ) -> None:
        """LLM exception produces an error result with zero scores."""
        failing_client = MagicMock()
        failing_client.chat.side_effect = RuntimeError("API timeout")

        client = MultimodalInspectionClient(client=failing_client, model="test/mock-model")
        result = client.inspect_asset(
            job_id=1,
            beat_id="beat_awards_01",
            asset_id="asset_fail",
            beat=beat,
            frame_paths=["/tmp/frame.jpg"],
        )

        assert result["decision"] == "error"
        assert result["person_match"] == 0.0
        assert result["event_match"] == 0.0
        assert result["claim_support"] == 0.0
        assert "API timeout" in result["reason"]
