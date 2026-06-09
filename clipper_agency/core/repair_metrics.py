"""Before/after repair quality metrics.

Pure functions that extract quality snapshots from reviewer output,
compare across repair cycles, and persist RepairCycleRecord objects.
"""

from __future__ import annotations

import json
from pathlib import Path

from clipper_agency.config.schema import RepairCycleRecord

# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

_SCORE_THRESHOLD = 10.0


def extract_quality_snapshot(review_output: dict) -> dict[str, float]:
    """Extract a flat quality metric dict from reviewer output.

    Returns scores for: reviewer_score, claim_support_avg,
    collision_count, black_frame_ms.
    """
    # reviewer_score: top-level "score" field (0-100)
    reviewer_score = float(review_output.get("score", 0))

    # claim_support_avg: average across scene_semantic_reviews
    scene_reviews = review_output.get("scene_semantic_reviews", [])
    if scene_reviews:
        claim_values = [
            r.get("claim_support", 0.0) for r in scene_reviews
        ]
        claim_support_avg = sum(claim_values) / len(claim_values)
    else:
        claim_support_avg = 0.0

    # collision_count: count of text_collision diagnostic entries
    diagnostics = review_output.get("diagnostics", {})
    text_collision = diagnostics.get("text_collision", [])
    if isinstance(text_collision, list):
        collision_count = float(len(text_collision))
    else:
        collision_count = 0.0

    # black_frame_ms: from visual_coverage diagnostics
    visual_coverage = diagnostics.get("visual_coverage", {})
    if isinstance(visual_coverage, dict):
        black_frame_ms = float(visual_coverage.get("black_frame_ms", 0.0))
    else:
        black_frame_ms = 0.0

    return {
        "reviewer_score": reviewer_score,
        "claim_support_avg": claim_support_avg,
        "collision_count": collision_count,
        "black_frame_ms": black_frame_ms,
    }


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------

def compute_repair_cycle_record(
    cycle: int,
    source_agent: str,
    target_agent: str,
    before_review: dict,
    after_review: dict,
) -> RepairCycleRecord:
    """Build a RepairCycleRecord from before/after reviewer outputs."""
    return RepairCycleRecord(
        cycle=cycle,
        source_agent=source_agent,
        target_agent=target_agent,
        before_scores=extract_quality_snapshot(before_review),
        after_scores=extract_quality_snapshot(after_review),
    )


# ---------------------------------------------------------------------------
# Improvement detection
# ---------------------------------------------------------------------------

_CRITICAL_KEYS = ("claim_support_avg", "collision_count", "black_frame_ms")


def is_repair_improved(before: dict[str, float], after: dict[str, float]) -> bool:
    """Return True if after scores are meaningfully better than before.

    Meaningful improvement = reviewer_score improved by >= 10 points
    OR all critical metrics (claim_support_avg, collision_count,
    black_frame_ms) improved.
    """
    # Check 1: significant reviewer_score improvement
    score_gain = after.get("reviewer_score", 0.0) - before.get("reviewer_score", 0.0)
    if score_gain >= _SCORE_THRESHOLD:
        return True

    # Check 2: all critical metrics improved
    # For collision_count and black_frame_ms, "improved" means *decreased*
    # For claim_support_avg, "improved" means *increased*
    claim_improved = (
        after.get("claim_support_avg", 0.0) > before.get("claim_support_avg", 0.0)
    )
    collision_improved = (
        after.get("collision_count", 0.0) < before.get("collision_count", 0.0)
    )
    black_frame_improved = (
        after.get("black_frame_ms", 0.0) < before.get("black_frame_ms", 0.0)
    )

    if claim_improved and collision_improved and black_frame_improved:
        return True

    return False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def persist_repair_cycle(
    cache_root: str,
    job_id: int,
    record: RepairCycleRecord,
) -> str:
    """Persist a RepairCycleRecord to the repair directory.

    Path: {cache_root}/job_{job_id}/repair/cycle_{n}.json
    Returns the path written.
    """
    repair_dir = Path(cache_root) / f"job_{job_id}" / "repair"
    repair_dir.mkdir(parents=True, exist_ok=True)
    file_path = repair_dir / f"cycle_{record.cycle}.json"
    file_path.write_text(record.model_dump_json(indent=2))
    return str(file_path)


def load_repair_history(
    cache_root: str,
    job_id: int,
) -> list[RepairCycleRecord]:
    """Load all repair cycle records for a job, sorted by cycle number."""
    repair_dir = Path(cache_root) / f"job_{job_id}" / "repair"
    if not repair_dir.is_dir():
        return []

    records: list[RepairCycleRecord] = []
    for json_file in repair_dir.glob("cycle_*.json"):
        data = json.loads(json_file.read_text())
        records.append(RepairCycleRecord(**data))

    records.sort(key=lambda r: r.cycle)
    return records
