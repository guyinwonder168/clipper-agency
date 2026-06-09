"""Tests for repair_metrics (pure module)."""

import json
import pytest
from pathlib import Path

from clipper_agency.config.schema import RepairCycleRecord
from clipper_agency.core.repair_metrics import (
    compute_repair_cycle_record,
    extract_quality_snapshot,
    is_repair_improved,
    load_repair_history,
    persist_repair_cycle,
)


# ---------------------------------------------------------------------------
# Fixtures: representative reviewer outputs
# ---------------------------------------------------------------------------

def _full_review_output(
    score: int = 78,
    claim_support: float = 0.75,
    collision_count: int = 0,
    black_frame_ms: float = 50.0,
) -> dict:
    """Build a realistic reviewer output dict for testing."""
    return {
        "status": "pass",
        "score": score,
        "feedback": "Good quality",
        "issues": [],
        "programmatic_checks": {
            "av_sync": {"check": "av_sync", "status": "pass", "drift_sec": 0.1},
            "caption_quality": {"check": "caption_quality", "status": "pass"},
            "fact_safety": {"check": "fact_safety", "status": "pass"},
            "narrative_structure": {"check": "narrative_structure", "status": "pass", "beats": 5},
        },
        "diagnostics": {
            "text_collision": [] if collision_count == 0 else [
                {"severity": "warn", "detail": f"collision {i}"}
                for i in range(collision_count)
            ],
            "visual_coverage": {
                "status": "pass",
                "black_frame_ms": black_frame_ms,
            },
        },
        "scene_semantic_reviews": [
            {
                "beat_id": "B01",
                "passed": True,
                "person_match": 0.8,
                "event_match": 0.7,
                "claim_support": claim_support,
                "visual_quality": 0.85,
                "misleading_risk": 0.1,
            },
        ],
    }


# ---------------------------------------------------------------------------
# extract_quality_snapshot
# ---------------------------------------------------------------------------

class TestExtractQualitySnapshot:
    """Tests for extract_quality_snapshot."""

    def test_extract_quality_snapshot_from_full_review(self):
        """Full review output produces correct snapshot dict."""
        review = _full_review_output(score=78, claim_support=0.75, collision_count=0, black_frame_ms=50.0)
        snapshot = extract_quality_snapshot(review)

        assert snapshot["reviewer_score"] == 78.0
        assert snapshot["claim_support_avg"] == 0.75
        assert snapshot["collision_count"] == 0.0
        assert snapshot["black_frame_ms"] == 50.0

    def test_extract_quality_snapshot_handles_missing_fields(self):
        """Graceful defaults when fields are missing."""
        review = {"status": "pass"}  # minimal
        snapshot = extract_quality_snapshot(review)

        assert snapshot["reviewer_score"] == 0.0
        assert snapshot["claim_support_avg"] == 0.0
        assert snapshot["collision_count"] == 0.0
        assert snapshot["black_frame_ms"] == 0.0


# ---------------------------------------------------------------------------
# compute_repair_cycle_record
# ---------------------------------------------------------------------------

class TestComputeRepairCycleRecord:
    """Tests for compute_repair_cycle_record."""

    def test_compute_repair_cycle_record(self):
        """Before/after dicts produce correct RepairCycleRecord."""
        before = _full_review_output(score=30, claim_support=0.3, collision_count=2, black_frame_ms=500.0)
        after = _full_review_output(score=78, claim_support=0.75, collision_count=0, black_frame_ms=50.0)

        record = compute_repair_cycle_record(
            cycle=1,
            source_agent="reviewer",
            target_agent="visual_director",
            before_review=before,
            after_review=after,
        )

        assert isinstance(record, RepairCycleRecord)
        assert record.cycle == 1
        assert record.source_agent == "reviewer"
        assert record.target_agent == "visual_director"
        assert record.before_scores["reviewer_score"] == 30.0
        assert record.after_scores["reviewer_score"] == 78.0
        assert record.before_scores["collision_count"] == 2.0
        assert record.after_scores["collision_count"] == 0.0


# ---------------------------------------------------------------------------
# is_repair_improved
# ---------------------------------------------------------------------------

class TestIsRepairImproved:
    """Tests for is_repair_improved."""

    def test_is_repair_improved_significant_score_gain(self):
        """30 → 78 is a significant improvement (≥ 10 points)."""
        before = {"reviewer_score": 30.0, "claim_support_avg": 0.3, "collision_count": 2.0, "black_frame_ms": 500.0}
        after = {"reviewer_score": 78.0, "claim_support_avg": 0.75, "collision_count": 1.0, "black_frame_ms": 200.0}
        assert is_repair_improved(before, after) is True

    def test_is_repair_improved_marginal_score_gain(self):
        """40 → 45 is NOT significant (< 10 points), and not all critical improved."""
        before = {"reviewer_score": 40.0, "claim_support_avg": 0.5, "collision_count": 1.0, "black_frame_ms": 200.0}
        after = {"reviewer_score": 45.0, "claim_support_avg": 0.5, "collision_count": 1.0, "black_frame_ms": 200.0}
        assert is_repair_improved(before, after) is False

    def test_is_repair_improved_all_critical_metrics_improved(self):
        """Score gain < 10 but ALL critical metrics improved → True."""
        before = {"reviewer_score": 50.0, "claim_support_avg": 0.3, "collision_count": 2.0, "black_frame_ms": 500.0}
        after = {"reviewer_score": 55.0, "claim_support_avg": 0.7, "collision_count": 0.0, "black_frame_ms": 100.0}
        assert is_repair_improved(before, after) is True

    def test_is_repair_not_improved_identical_scores(self):
        """Identical scores = False."""
        scores = {"reviewer_score": 50.0, "claim_support_avg": 0.5, "collision_count": 1.0, "black_frame_ms": 200.0}
        assert is_repair_improved(scores, scores) is False


# ---------------------------------------------------------------------------
# persist_repair_cycle / load_repair_history
# ---------------------------------------------------------------------------

class TestPersistAndLoad:
    """Tests for persist_repair_cycle and load_repair_history."""

    def test_persist_repair_cycle_creates_json_file(self, tmp_path):
        """Write a record and read it back."""
        record = RepairCycleRecord(
            cycle=1,
            source_agent="reviewer",
            target_agent="visual_director",
            before_scores={"reviewer_score": 30.0, "claim_support_avg": 0.3, "collision_count": 2.0, "black_frame_ms": 500.0},
            after_scores={"reviewer_score": 78.0, "claim_support_avg": 0.75, "collision_count": 0.0, "black_frame_ms": 50.0},
        )

        path = persist_repair_cycle(str(tmp_path), job_id=42, record=record)
        assert Path(path).exists()

        data = json.loads(Path(path).read_text())
        assert data["cycle"] == 1
        assert data["after_scores"]["reviewer_score"] == 78.0

    def test_load_repair_history_returns_sorted_cycles(self, tmp_path):
        """3 cycles written out-of-order → loaded sorted by cycle number."""
        for cycle_num in [3, 1, 2]:
            record = RepairCycleRecord(
                cycle=cycle_num,
                source_agent="reviewer",
                target_agent="visual_director",
                before_scores={"reviewer_score": float(cycle_num * 10)},
                after_scores={"reviewer_score": float(cycle_num * 20)},
            )
            persist_repair_cycle(str(tmp_path), job_id=7, record=record)

        history = load_repair_history(str(tmp_path), job_id=7)
        assert len(history) == 3
        assert [r.cycle for r in history] == [1, 2, 3]

    def test_load_repair_history_empty_when_no_records(self, tmp_path):
        """No repair directory → returns empty list."""
        history = load_repair_history(str(tmp_path), job_id=99)
        assert history == []
