"""File-based cache for multimodal asset inspection results.

Keys are deterministic SHA-256 hashes over the asset identity, beat context,
model, and prompt version.  Each cache entry is a JSON file containing the
inspection result plus a ``cached_at`` timestamp and the ``cache_key``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    raw = _SEP.join(
        [
            asset_path,
            asset_hash,
            beat_claim,
            evidence_contract_hash,
            model,
            prompt_version,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Candidate cache-key convention — single source of truth (PR-5 parity).
#
# Visual Director's ``_score_one_candidate`` and asset_qualification's
# ``_score_candidate`` MUST derive byte-identical cache keys for the same
# ``(candidate, beat)`` so the pre-VD pass and VD share one cache namespace and
# VLM is never spent twice on the same candidate. Both call sites route through
# ``compute_candidate_cache_key`` (below), which feeds these constants into
# ``compute_cache_key``. Bump ``CANDIDATE_CACHE_PROMPT_VERSION`` on any prompt or
# evidence-contract change — the resulting key shift invalidates every prior
# cache entry (structural invalidation, defense-in-depth alongside the
# subject_name runtime guard).
# ---------------------------------------------------------------------------
CANDIDATE_CACHE_MODEL = "multimodal"
# FIX-3 added ``subject_name`` + ``visual_must_show``/``visual_must_not_show`` to
# the multimodal inspection prompt, so caches produced under the old "1.0" prompt
# are stale — "1.1" invalidates them via the key hash.
CANDIDATE_CACHE_PROMPT_VERSION = "1.1"


def compute_evidence_contract_hash(
    visual_must_show: str,
    visual_must_not_show: str,
) -> str:
    """SHA-256 over the evidence-contract fields that change the VLM prompt body.

    FIX-3 added ``visual_must_show`` / ``visual_must_not_show`` to the multimodal
    inspection prompt body, so two beats that inspect the same asset under
    different evidence contracts must NOT share a cache entry. This hash feeds
    ``compute_cache_key``'s ``evidence_contract_hash`` slot (previously the empty
    literal ``""``).
    """
    raw = _SEP.join([visual_must_show or "", visual_must_not_show or ""])
    return hashlib.sha256(raw.encode()).hexdigest()


def _candidate_field(candidate: Any, name: str) -> str:
    """Read a string field from a dict or attribute-based candidate object."""
    if isinstance(candidate, dict):
        value = candidate.get(name)
    else:
        value = getattr(candidate, name, None)
    return str(value) if value is not None else ""


def compute_asset_content_hash(candidate: Any) -> str:
    """Return a SHA-256 hash over the asset-identity fields that determine
    *what media gets inspected*: ``type``, ``url``, ``source_type``.

    Metadata that does not change the downloaded bytes (``source``,
    ``provenance``, scores, ``title``) is intentionally excluded, so
    re-inspection is forced only when the inspected asset actually changes.

    Used as ``asset_hash`` in :func:`compute_cache_key` so Segment-Producer-
    regenerated candidates invalidate stale inspection-cache entries, while an
    identical candidate (e.g. a resumed run) keeps hitting the cache. Accepts
    either an :class:`AssetCandidate` model or a raw dict.
    """
    identity = {
        "type": _candidate_field(candidate, "type"),
        "url": _candidate_field(candidate, "url"),
        "source_type": _candidate_field(candidate, "source_type"),
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_candidate_cache_key(
    candidate: Any,
    spoken_point: str,
    visual_must_show: str,
    visual_must_not_show: str,
) -> str:
    """Deterministic inspection-cache key shared by VD and AQ (PR-5 parity).

    Single source of truth for the inspection-cache key: Visual Director's
    ``_score_one_candidate`` and asset_qualification's ``_score_candidate`` both
    call this, so a pre-qualified candidate is a cache hit in VD (no double-VLM
    spend). The evidence-contract hash covers ``visual_must_show`` /
    ``visual_must_not_show`` (added to the VLM prompt body by FIX-3), so two beats
    that inspect the same asset under different evidence contracts no longer
    collide on one cache entry.

    Accepts either an :class:`AssetCandidate` model or a raw dict (url is read via
    :func:`_candidate_field`).
    """
    return compute_cache_key(
        asset_path=_candidate_field(candidate, "url"),
        asset_hash=compute_asset_content_hash(candidate),
        beat_claim=spoken_point,
        evidence_contract_hash=compute_evidence_contract_hash(
            visual_must_show, visual_must_not_show
        ),
        model=CANDIDATE_CACHE_MODEL,
        prompt_version=CANDIDATE_CACHE_PROMPT_VERSION,
    )


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
        "cached_at": datetime.now(UTC).isoformat(),
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
