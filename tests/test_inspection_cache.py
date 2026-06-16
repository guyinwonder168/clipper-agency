"""Tests for core/inspection_cache — multimodal asset inspection result caching."""

from __future__ import annotations

import json
from pathlib import Path

from clipper_agency.config.schema import AssetCandidate
from clipper_agency.core.inspection_cache import (
    cache_stats,
    compute_asset_content_hash,
    compute_cache_key,
    invalidate,
    lookup,
    store,
)

# ---------------------------------------------------------------------------
# compute_cache_key
# ---------------------------------------------------------------------------


class TestComputeCacheKey:
    """Tests for compute_cache_key()."""

    def test_returns_deterministic_hex_for_same_inputs(self) -> None:
        """Same inputs always produce the same SHA-256 hex string."""
        key1 = compute_cache_key(
            asset_path="/clips/a.mp4",
            asset_hash="abc123",
            beat_claim="The artist performs live",
            evidence_contract_hash="ecf001",
            model="gemini-2.0-flash",
            prompt_version="v3",
        )
        key2 = compute_cache_key(
            asset_path="/clips/a.mp4",
            asset_hash="abc123",
            beat_claim="The artist performs live",
            evidence_contract_hash="ecf001",
            model="gemini-2.0-flash",
            prompt_version="v3",
        )
        assert key1 == key2
        assert len(key1) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in key1)

    def test_returns_different_string_for_different_inputs(self) -> None:
        """Changing any input parameter produces a different cache key."""
        base = compute_cache_key(
            asset_path="/clips/a.mp4",
            asset_hash="abc123",
            beat_claim="claim",
            evidence_contract_hash="ecf",
            model="model-a",
            prompt_version="v1",
        )
        different_model = compute_cache_key(
            asset_path="/clips/a.mp4",
            asset_hash="abc123",
            beat_claim="claim",
            evidence_contract_hash="ecf",
            model="model-b",
            prompt_version="v1",
        )
        assert base != different_model

    def test_handles_empty_strings_gracefully(self) -> None:
        """Empty string inputs do not raise and return a valid hex key."""
        key = compute_cache_key(
            asset_path="",
            asset_hash="",
            beat_claim="",
            evidence_contract_hash="",
            model="",
            prompt_version="",
        )
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_different_beat_claims_produce_different_keys(self) -> None:
        """Different beat claims must not collide."""
        key_a = compute_cache_key(
            asset_path="/x.mp4",
            asset_hash="h",
            beat_claim="claim A",
            evidence_contract_hash="e",
            model="m",
            prompt_version="v",
        )
        key_b = compute_cache_key(
            asset_path="/x.mp4",
            asset_hash="h",
            beat_claim="claim B",
            evidence_contract_hash="e",
            model="m",
            prompt_version="v",
        )
        assert key_a != key_b


# ---------------------------------------------------------------------------
# compute_asset_content_hash (4f-VD: content-aware cache invalidation)
# ---------------------------------------------------------------------------


class TestComputeAssetContentHash:
    """compute_asset_content_hash() keys the inspection cache by the asset
    identity (type/url/source_type) so SP-regenerated candidates invalidate
    stale entries while identical candidates stay cached.
    """

    def test_is_deterministic_hex_for_same_candidate(self) -> None:
        cand = AssetCandidate(
            type="tiktok_clip", url="https://x/a", reason="r", source_type="youtube_official"
        )
        h = compute_asset_content_hash(cand)
        assert h == compute_asset_content_hash(cand)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_differs_by_url(self) -> None:
        a = AssetCandidate(type="tiktok_clip", url="https://x/a", reason="r", source_type="s")
        b = AssetCandidate(type="tiktok_clip", url="https://x/b", reason="r", source_type="s")
        assert compute_asset_content_hash(a) != compute_asset_content_hash(b)

    def test_differs_by_type(self) -> None:
        a = AssetCandidate(type="tiktok_clip", url="https://x/a", reason="r")
        b = AssetCandidate(type="photo", url="https://x/a", reason="r")
        assert compute_asset_content_hash(a) != compute_asset_content_hash(b)

    def test_differs_by_source_type(self) -> None:
        a = AssetCandidate(
            type="tiktok_clip", url="https://x/a", reason="r", source_type="youtube_official"
        )
        b = AssetCandidate(
            type="tiktok_clip", url="https://x/a", reason="r", source_type="web_video"
        )
        assert compute_asset_content_hash(a) != compute_asset_content_hash(b)

    def test_ignores_non_identity_metadata(self) -> None:
        """Metadata that does not change the inspected bytes must not re-key
        (avoids needless re-inspection across reruns for the same asset)."""
        a = AssetCandidate(
            type="tiktok_clip",
            url="https://x/a",
            reason="r",
            source_type="s",
            provenance="primary",
            source="yt",
            title="t1",
            relevance_score=0.9,
        )
        b = AssetCandidate(
            type="tiktok_clip",
            url="https://x/a",
            reason="r2",
            source_type="s",
            provenance="supporting",
            source="tavily",
            title="t2",
            relevance_score=0.1,
        )
        assert compute_asset_content_hash(a) == compute_asset_content_hash(b)

    def test_accepts_dict_candidate(self) -> None:
        """Dict candidates (e.g. SP raw output) hash identically to the model."""
        d = {"type": "tiktok_clip", "url": "https://x/a", "source_type": "s"}
        obj = AssetCandidate(type="tiktok_clip", url="https://x/a", reason="r", source_type="s")
        assert compute_asset_content_hash(d) == compute_asset_content_hash(obj)


class TestContentHashInvalidatesCacheKey:
    """End-to-end: a content-hash change propagates into compute_cache_key."""

    @staticmethod
    def _key(cand: AssetCandidate) -> str:
        return compute_cache_key(
            asset_path=cand.url,
            asset_hash=compute_asset_content_hash(cand),
            beat_claim="the artist performs live",
            evidence_contract_hash="",
            model="multimodal",
            prompt_version="1.0",
        )

    def test_changed_candidate_changes_cache_key(self) -> None:
        a = AssetCandidate(type="tiktok_clip", url="https://x/a", reason="r", source_type="s")
        b = AssetCandidate(type="tiktok_clip", url="https://x/b", reason="r", source_type="s")
        assert self._key(a) != self._key(b)

    def test_identical_candidate_keeps_cache_key_resume_safe(self) -> None:
        a = AssetCandidate(type="tiktok_clip", url="https://x/a", reason="r", source_type="s")
        assert self._key(a) == self._key(a)


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


class TestLookup:
    """Tests for lookup()."""

    def test_returns_none_when_no_cache_file_exists(self, tmp_path: Path) -> None:
        """Missing cache file yields None."""
        result = lookup(tmp_path / "nonexistent_dir", "deadbeef")
        assert result is None

    def test_returns_parsed_dict_when_cache_file_exists(self, tmp_path: Path) -> None:
        """An existing JSON cache file is read and returned as a dict."""
        cache_key = "abc123"
        cache_file = tmp_path / f"{cache_key}.json"
        data = {"result": "ok", "score": 0.9}
        cache_file.write_text(json.dumps(data))

        result = lookup(tmp_path, cache_key)
        assert result == data


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


class TestStore:
    """Tests for store()."""

    def test_creates_directory_if_needed(self, tmp_path: Path) -> None:
        """store() creates the cache directory when it doesn't exist."""
        cache_dir = tmp_path / "deep" / "nested" / "cache"
        cache_key = "key001"
        result = store(cache_dir, cache_key, {"verdict": "pass"})

        assert cache_dir.is_dir()
        assert result.exists()

    def test_writes_json_with_result_timestamp_and_key(self, tmp_path: Path) -> None:
        """Stored JSON contains the inspection result, cached_at, and cache_key."""
        cache_key = "key002"
        inspection_result = {"verdict": "fail", "reason": "blurry"}

        path = store(tmp_path, cache_key, inspection_result)
        stored = json.loads(path.read_text())

        assert stored["verdict"] == "fail"
        assert stored["reason"] == "blurry"
        assert "cached_at" in stored
        assert stored["cache_key"] == cache_key

    def test_returns_written_file_path(self, tmp_path: Path) -> None:
        """Return value is the Path of the written JSON file."""
        cache_key = "key003"
        path = store(tmp_path, cache_key, {"ok": True})

        assert isinstance(path, Path)
        assert path.name == f"{cache_key}.json"
        assert path.parent == tmp_path


# ---------------------------------------------------------------------------
# cache_stats
# ---------------------------------------------------------------------------


class TestCacheStats:
    """Tests for cache_stats()."""

    def test_returns_zero_entries_for_missing_directory(self, tmp_path: Path) -> None:
        """Non-existent directory reports zero entries."""
        stats = cache_stats(tmp_path / "no_such_dir")
        assert stats == {"entries": 0}

    def test_counts_entries_and_computes_sizes(self, tmp_path: Path) -> None:
        """Stats reflect actual cache files in the directory."""
        for i in range(3):
            (tmp_path / f"key{i:03d}.json").write_text(
                json.dumps({"data": f"entry-{i}", "cached_at": "2026-06-09T10:00:00"})
            )

        stats = cache_stats(tmp_path)
        assert stats["entries"] == 3
        assert stats["total_bytes"] > 0
        assert "oldest" in stats
        assert "newest" in stats


# ---------------------------------------------------------------------------
# invalidate
# ---------------------------------------------------------------------------


class TestInvalidate:
    """Tests for invalidate()."""

    def test_deletes_existing_cache_file(self, tmp_path: Path) -> None:
        """An existing cache file is removed and True is returned."""
        cache_key = "del001"
        cache_file = tmp_path / f"{cache_key}.json"
        cache_file.write_text("{}")

        result = invalidate(tmp_path, cache_key)
        assert result is True
        assert not cache_file.exists()

    def test_returns_false_for_missing_file(self, tmp_path: Path) -> None:
        """Attempting to delete a non-existent cache file returns False."""
        result = invalidate(tmp_path, "nonexistent_key")
        assert result is False


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Integration tests: store then lookup must return same data."""

    def test_store_then_lookup_returns_same_data(self, tmp_path: Path) -> None:
        """A full store → lookup cycle preserves the inspection result."""
        cache_key = compute_cache_key(
            asset_path="/video/scene1.mp4",
            asset_hash="sha256abc",
            beat_claim="Artist sings chorus",
            evidence_contract_hash="ecf999",
            model="gemini-2.0-flash",
            prompt_version="v4",
        )
        inspection_result = {
            "verdict": "pass",
            "scores": {"relevance": 0.95, "quality": 0.88},
            "notes": "Clear shot, well-lit",
        }

        store(tmp_path, cache_key, inspection_result)
        loaded = lookup(tmp_path, cache_key)

        assert loaded is not None
        # The stored payload wraps the inspection result with metadata
        assert loaded["verdict"] == inspection_result["verdict"]
        assert loaded["scores"] == inspection_result["scores"]
        assert loaded["notes"] == inspection_result["notes"]
        assert loaded["cache_key"] == cache_key
        assert "cached_at" in loaded
