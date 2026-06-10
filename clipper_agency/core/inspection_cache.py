"""File-based cache for multimodal asset inspection results.

Keys are deterministic SHA-256 hashes over the asset identity, beat context,
model, and prompt version.  Each cache entry is a JSON file containing the
inspection result plus a ``cached_at`` timestamp and the ``cache_key``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_SEP = "::"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def compute_cache_key(
    asset_path: str,
    asset_hash: str,
    beat_claim: str,
    evidence_contract_hash: str,
    model: str,
    prompt_version: str,
) -> str:
    """Return a deterministic SHA-256 hex digest for the given cache inputs."""
    raw = _SEP.join([
        asset_path,
        asset_hash,
        beat_claim,
        evidence_contract_hash,
        model,
        prompt_version,
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def lookup(
    cache_dir: str | Path,
    cache_key: str,
) -> dict | None:
    """Read a cached inspection result or return *None* if absent."""
    path = Path(cache_dir) / f"{cache_key}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def store(
    cache_dir: str | Path,
    cache_key: str,
    inspection_result: dict,
) -> Path:
    """Persist an inspection result and return the written file path."""
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)

    payload = {
        **inspection_result,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "cache_key": cache_key,
    }
    path = directory / f"{cache_key}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def cache_stats(cache_dir: str | Path) -> dict:
    """Return entry count, total bytes, and oldest/newest timestamps."""
    directory = Path(cache_dir)
    if not directory.is_dir():
        return {"entries": 0}

    files = sorted(directory.glob("*.json"))
    if not files:
        return {"entries": 0}

    total_bytes = 0
    timestamps: list[str] = []
    for fp in files:
        total_bytes += fp.stat().st_size
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            ts = data.get("cached_at")
            if ts:
                timestamps.append(ts)
        except (json.JSONDecodeError, OSError):
            pass

    oldest = min(timestamps) if timestamps else None
    newest = max(timestamps) if timestamps else None

    return {
        "entries": len(files),
        "total_bytes": total_bytes,
        "oldest": oldest,
        "newest": newest,
    }


def invalidate(cache_dir: str | Path, cache_key: str) -> bool:
    """Delete a cached entry.  Returns *True* if the file was removed."""
    path = Path(cache_dir) / f"{cache_key}.json"
    if path.is_file():
        path.unlink()
        return True
    return False
