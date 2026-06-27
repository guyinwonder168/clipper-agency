"""Load all persisted read-only signals for one job under AV-drift diagnosis.

The loader only READS artifacts — it never touches any agent, gate, or
pipeline state machine (ADR-0026 compliance).

Default assets_cache resolution (Codex P2#2): walk up from ``job_dir`` and
return the first ancestor that contains a ``data/assets/cache`` subdirectory
(so an absolute ``job_dir`` resolves correctly regardless of the caller's
CWD). If none is found, fall back to ``<CWD>/data/assets/cache``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from clipper_agency.diagnostics.models import JobSignals
from clipper_agency.diagnostics.planned import read_ts

_CACHE_DIR_NAME = "data/assets/cache"
_JOB_RE = re.compile(r"job_(\d+)$")


def _resolve_assets_cache(job_dir: Path, override: str | Path | None) -> Path:
    """Resolve the assets-cache root from an override or by walking up.

    Walks ``job_dir``'s ancestors and returns the first that contains
    ``data/assets/cache`` — this resolves a sibling cache for an absolute
    ``job_dir`` regardless of the caller's CWD (Codex P2#2).
    """
    if override is not None:
        return Path(override).resolve()
    cursor = job_dir.resolve()
    for parent in [cursor, *cursor.parents]:
        candidate = parent / _CACHE_DIR_NAME
        if candidate.is_dir():
            return candidate
    return (Path.cwd() / _CACHE_DIR_NAME).resolve()


def _read_json_dict(path: Path, missing_hint: str) -> dict:
    """Read + parse JSON, requiring a dict; raise FileNotFoundError on miss."""
    if not path.is_file():
        raise FileNotFoundError(f"AV-drift input missing: {missing_hint} ({path})")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(
            f"AV-drift input malformed ({missing_hint}): expected JSON object, "
            f"got {type(data).__name__}"
        )
    return data


def _read_json_list(path: Path, missing_hint: str) -> list[dict]:
    """Read + parse JSON, requiring a list of dicts; raise on miss/malformed.

    A non-dict entry raises ``ValueError`` (reject) rather than being silently
    dropped — a diagnosis tool must surface malformed beats, not hide them.
    """
    if not path.is_file():
        raise FileNotFoundError(f"AV-drift input missing: {missing_hint} ({path})")
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError(
            f"AV-drift input malformed ({missing_hint}): expected JSON array, "
            f"got {type(data).__name__}"
        )
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(
                f"AV-drift input malformed ({missing_hint}): expected JSON array "
                f"of objects, got a {type(item).__name__} entry"
            )
    return data


def _parse_job_id(job_dir: Path) -> int:
    """Parse the integer job id from a ``job_<N>`` basename."""
    match = _JOB_RE.search(job_dir.name)
    if match is None:
        raise ValueError(f"AV-drift job_dir basename is not 'job_<N>': {job_dir.name}")
    return int(match.group(1))


def load_job_signals(
    job_dir: str | Path,
    assets_cache: str | Path | None = None,
) -> JobSignals:
    """Load narrative_structure + voice timestamps + locate the muxed video.

    Raises:
        FileNotFoundError: naming the missing required input file.
        ValueError: if the job_dir basename is not ``job_<N>`` or an input
            JSON is structurally malformed.
    """
    job_dir_path = Path(job_dir).resolve()
    job_id = _parse_job_id(job_dir_path)
    cache_root = _resolve_assets_cache(job_dir_path, assets_cache)

    narrative_path = (
        cache_root / f"job_{job_id}" / "agents" / "scriptwriter" / "narrative_structure.json"
    )
    voice_path = cache_root / f"job_{job_id}" / "agents" / "voice_producer" / "output.json"
    video_path = job_dir_path / "video.mp4"

    narrative_structure = _read_json_list(
        narrative_path,
        f"job_{job_id} scriptwriter/narrative_structure.json",
    )
    voice = _read_json_dict(voice_path, f"job_{job_id} voice_producer/output.json")
    if not video_path.is_file():
        raise FileNotFoundError(f"AV-drift input missing: job_{job_id} muxed video ({video_path})")

    timestamps = list(voice.get("timestamps", []))
    provider = str(voice.get("provider", "unknown"))
    voiceover_duration = float(voice.get("voiceover_duration_sec", 0.0))

    # hook_duration = first beat's inclusive audio span.
    hook_duration = 0.0
    if narrative_structure and timestamps:
        first = narrative_structure[0]
        w0, w1 = first.get("word_range", [0, 0])
        hook_duration = read_ts(timestamps, w1, "end") - read_ts(timestamps, w0, "start")

    return JobSignals(
        job_id=job_id,
        narrative_structure=narrative_structure,
        timestamps=timestamps,
        video_path=str(video_path),
        provider=provider,
        voiceover_duration_sec=voiceover_duration,
        hook_duration_sec=hook_duration,
    )
