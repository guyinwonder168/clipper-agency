"""Canonical paths for runtime inspection and repair artifacts."""

from pathlib import Path


def _job_cache_dir(cache_root: str | Path, job_id: int) -> Path:
    return Path(cache_root) / f"job_{job_id}"


def candidate_inspection_dir(cache_root: str | Path, job_id: int, beat_id: str, asset_id: str) -> Path:
    """Return the canonical candidate inspection directory for one beat asset."""

    return (
        _job_cache_dir(cache_root, job_id)
        / "inspections"
        / "candidates"
        / f"beat_{beat_id}"
        / f"asset_{asset_id}"
    )


def final_inspection_dir(cache_root: str | Path, job_id: int) -> Path:
    """Return the canonical final rendered output inspection directory."""

    return _job_cache_dir(cache_root, job_id) / "inspections" / "final"


def repair_cycle_path(cache_root: str | Path, job_id: int, cycle: int) -> Path:
    """Return the canonical repair cycle diagnostics path."""

    return _job_cache_dir(cache_root, job_id) / "repair" / f"cycle_{cycle}.json"
