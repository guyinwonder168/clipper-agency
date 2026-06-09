from pathlib import Path

from clipper_agency.core.inspection_paths import (
    candidate_inspection_dir,
    final_inspection_dir,
    repair_cycle_path,
)


def test_candidate_inspection_dir_uses_canonical_layout():
    path = candidate_inspection_dir(Path("data/assets/cache"), 5, "B02", "asset_7")

    assert path == Path(
        "data/assets/cache/job_5/inspections/candidates/beat_B02/asset_asset_7"
    )


def test_final_inspection_dir_uses_canonical_layout():
    path = final_inspection_dir(Path("data/assets/cache"), 5)

    assert path == Path("data/assets/cache/job_5/inspections/final")


def test_repair_cycle_path_uses_canonical_layout():
    path = repair_cycle_path(Path("data/assets/cache"), 5, 2)

    assert path == Path("data/assets/cache/job_5/repair/cycle_2.json")
