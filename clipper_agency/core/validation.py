"""Artifact validation primitives — deterministic file + JSON checks."""

import glob as _glob
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from clipper_agency.core.artifacts import read_json
from clipper_agency.core.paths import (
    agent_dir,
    agent_output_file,
    segment_producer_brief_file,
    segment_producer_contract_file,
)


@dataclass(frozen=True)
class ValidationResult:
    """Immutable result of an artifact validation check."""
    passed: bool
    issues: list[str] = field(default_factory=list)


def validate_research_contract(path: Path | str) -> ValidationResult:
    """Validate research_contract.json: exists, valid JSON, required fields."""
    p = Path(path)
    if not p.exists():
        return ValidationResult(False, [f"research_contract not found: {p}"])
    try:
        data = read_json(p)
    except (ValueError, OSError) as e:
        return ValidationResult(False, [f"research_contract JSON parse error: {e}"])
    required = ["topic", "video_sources", "context_sources",
                "cache_key", "cache_freshness"]
    missing = [k for k in required if k not in data]
    if missing:
        return ValidationResult(False, [f"missing fields: {missing}"])
    return ValidationResult(True)


def validate_research_brief(path: Path | str) -> ValidationResult:
    """Validate research_brief.md: exists, non-empty."""
    p = Path(path)
    if not p.exists():
        return ValidationResult(False, [f"research_brief not found: {p}"])
    if p.stat().st_size == 0:
        return ValidationResult(False, ["research_brief is empty"])
    return ValidationResult(True)


def validate_script(path: Path | str) -> ValidationResult:
    """Validate script.json: valid JSON with non-empty scenes list."""
    p = Path(path)
    if not p.exists():
        return ValidationResult(False, [f"script not found: {p}"])
    try:
        data = read_json(p)
    except (ValueError, OSError) as e:
        return ValidationResult(False, [f"script JSON parse error: {e}"])

    if isinstance(data, list):
        scenes = data
    elif isinstance(data, dict):
        if "scenes" not in data:
            return ValidationResult(False, ["missing 'scenes' key"])
        scenes = data["scenes"]
    else:
        return ValidationResult(False, ["missing 'scenes' key"])

    if not isinstance(scenes, list) or len(scenes) == 0:
        return ValidationResult(False, ["scenes list is empty"])
    return ValidationResult(True)


def validate_voice_files(paths: list[str]) -> ValidationResult:
    """Validate voice files: all exist, non-zero size."""
    if not paths:
        return ValidationResult(False, ["no voice files provided"])
    issues: list[str] = []
    for fp in paths:
        p = Path(fp)
        if not p.exists():
            issues.append(f"voice file not found: {p}")
        elif p.stat().st_size == 0:
            issues.append(f"voice file is empty: {p}")
    return ValidationResult(len(issues) == 0, issues)


def validate_scene_files(paths: list[str]) -> ValidationResult:
    """Validate scene files: all exist, non-zero size."""
    if not paths:
        return ValidationResult(False, ["no scene files provided"])
    issues: list[str] = []
    for fp in paths:
        p = Path(fp)
        if not p.exists():
            issues.append(f"scene file not found: {p}")
        elif p.stat().st_size == 0:
            issues.append(f"scene file is empty: {p}")
    return ValidationResult(len(issues) == 0, issues)


def validate_video_file(path: str) -> ValidationResult:
    """Validate video file: exists, non-zero, minimum size."""
    p = Path(path)
    if not p.exists():
        return ValidationResult(False, [f"video file not found: {p}"])
    size = p.stat().st_size
    if size < 1024:
        return ValidationResult(False, [f"video file too small ({size} bytes)"])
    return ValidationResult(True)


def _validate_output_json(assets_cache: str, job_id: int, agent_name: str,
                          ) -> ValidationResult | None:
    """Check output.json exists and is valid JSON. Returns None on success."""
    out_path = agent_output_file(assets_cache, job_id, agent_name)
    out_p = Path(out_path)
    if not out_p.exists():
        return ValidationResult(False, [f"output.json missing for {agent_name}"])
    try:
        read_json(out_p)
    except (ValueError, OSError) as exc:
        return ValidationResult(False, [f"output.json corrupt for {agent_name}: {exc}"])
    return None


def _validate_segment_producer_artifacts(assets_cache: str, job_id: int,
                                         ) -> list[str]:
    """Validate segment_producer specific artifacts."""
    r1 = validate_research_contract(
        segment_producer_contract_file(assets_cache, job_id))
    r2 = validate_research_brief(
        segment_producer_brief_file(assets_cache, job_id))
    return r1.issues + r2.issues


def _validate_scriptwriter_artifacts(assets_cache: str, job_id: int,
                                     ) -> list[str]:
    """Validate scriptwriter specific artifacts."""
    script_path = str(
        Path(agent_dir(assets_cache, job_id, "scriptwriter")) / "script.json"
    )
    return validate_script(script_path).issues


def _validate_voice_producer_artifacts(assets_cache: str, job_id: int,
                                       ) -> list[str]:
    """Validate voice_producer specific artifacts."""
    vp_dir = Path(agent_dir(assets_cache, job_id, "voice_producer"))
    voices_dir = vp_dir / "voices"
    voice_files = (
        sorted(str(p) for p in voices_dir.glob("scene_*.mp3"))
        if voices_dir.exists() else []
    )
    # Also accept single voiceover.mp3 from audio-first path
    single_voiceover = vp_dir / "voiceover.mp3"
    if single_voiceover.exists() and single_voiceover.stat().st_size > 0:
        voice_files.append(str(single_voiceover))
    return validate_voice_files(voice_files).issues


def _validate_visual_director_artifacts(assets_cache: str, job_id: int,
                                        ) -> list[str]:
    """Validate visual_director specific artifacts."""
    scenes_dir = Path(
        agent_dir(assets_cache, job_id, "visual_director")
    ) / "scenes"
    scene_files = (
        sorted(str(p) for p in scenes_dir.glob("scene_*.mp4"))
        if scenes_dir.exists() else []
    )
    return validate_scene_files(scene_files).issues


def _validate_composer_artifacts(out_p: Path) -> list[str]:
    """Validate composer specific artifacts."""
    out_data = read_json(out_p)
    video_path = out_data.get("video_path", "")
    if not video_path:
        return []
    return validate_video_file(video_path).issues


_AGENT_ARTIFACT_VALIDATORS: dict[
    str, Callable[[str, int], list[str]]
] = {
    "segment_producer": _validate_segment_producer_artifacts,
    "scriptwriter": _validate_scriptwriter_artifacts,
    "voice_producer": _validate_voice_producer_artifacts,
    "visual_director": _validate_visual_director_artifacts,
}


def validate_agent_cache(
    assets_cache: str, job_id: int, agent_name: str,
) -> ValidationResult:
    """Validate all cached artifacts for *agent_name* before cache reuse.

    Returns a single :class:`ValidationResult` combining all per-artifact
    checks.  If any check fails the overall result is ``passed=False`` so
    the engine can fall through to re-running the agent.
    """
    # 1. output.json must exist and be valid JSON for every agent.
    err = _validate_output_json(assets_cache, job_id, agent_name)
    if err:
        return err

    # 2. Agent-specific artifact checks.
    all_issues: list[str] = []
    validator = _AGENT_ARTIFACT_VALIDATORS.get(agent_name)
    if validator:
        all_issues.extend(validator(assets_cache, job_id))
    elif agent_name == "composer":
        out_p = Path(agent_output_file(assets_cache, job_id, agent_name))
        all_issues.extend(
            _validate_composer_artifacts(out_p)
        )
    # safety, reviewer — only output.json check (already done above).

    return ValidationResult(len(all_issues) == 0, all_issues)
