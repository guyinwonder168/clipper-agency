"""Tests for perceptual frame hashing and near-duplicate deduplication."""

from pathlib import Path

from PIL import Image, ImageDraw

from clipper_agency.config.schema import ExtractedFrame
from clipper_agency.core.frame_hash import (
    compute_perceptual_hash,
    deduplicate_extracted_frames,
    hash_distance,
)


def _save_gradient(path: Path, offset: int = 0) -> None:
    img = Image.new("RGB", (32, 32))
    draw = ImageDraw.Draw(img)
    for x in range(32):
        shade = min(255, x * 8 + offset)
        draw.line((x, 0, x, 31), fill=(shade, shade, shade))
    img.save(path)


def _frame(timestamp_sec: float, perceptual_hash: str) -> ExtractedFrame:
    return ExtractedFrame(
        timestamp_sec=timestamp_sec,
        path=f"/tmp/frame_{timestamp_sec}.jpg",
        perceptual_hash=perceptual_hash,
        width=32,
        height=32,
    )


class TestComputePerceptualHash:
    """Tests for compute_perceptual_hash()."""

    def test_returns_stable_hex_hash_for_same_image(self, tmp_path):
        """Hashing the same image twice produces the same 64-bit hex string."""
        image_path = tmp_path / "gradient.jpg"
        _save_gradient(image_path)

        first_hash = compute_perceptual_hash(image_path)
        second_hash = compute_perceptual_hash(image_path)

        assert first_hash == second_hash
        assert len(first_hash) == 16
        assert int(first_hash, 16) >= 0

    def test_visually_similar_images_have_small_hash_distance(self, tmp_path):
        """A tiny visual change should remain near the original hash."""
        original_path = tmp_path / "original.jpg"
        similar_path = tmp_path / "similar.jpg"
        _save_gradient(original_path)
        _save_gradient(similar_path, offset=1)

        distance = hash_distance(
            compute_perceptual_hash(original_path),
            compute_perceptual_hash(similar_path),
        )

        assert distance <= 6


class TestHashDistance:
    """Tests for hash_distance()."""

    def test_counts_bit_differences_between_hex_hashes(self):
        """Hex hashes are compared by Hamming distance of their bits."""
        assert hash_distance("0000000000000000", "000000000000000f") == 4

    def test_rejects_hashes_with_different_lengths(self):
        """A distance is only meaningful for same-width hashes."""
        try:
            hash_distance("0", "00")
        except ValueError as exc:
            assert "same length" in str(exc)
        else:
            raise AssertionError("Expected ValueError for mismatched hash lengths")


class TestDeduplicateExtractedFrames:
    """Tests for deduplicate_extracted_frames()."""

    def test_removes_near_duplicate_frames_and_preserves_first_timestamp(self):
        """Near-identical hashes collapse to the first frame, not the later one."""
        frames = [
            _frame(0.0, "0000000000000000"),
            _frame(0.5, "0000000000000003"),
            _frame(1.0, "ffffffffffffffff"),
        ]

        deduplicated = deduplicate_extracted_frames(frames, max_distance=2)

        assert [frame.timestamp_sec for frame in deduplicated] == [0.0, 1.0]

    def test_keeps_frames_when_distance_exceeds_threshold(self):
        """A frame is retained when its hash distance is above max_distance."""
        frames = [
            _frame(0.0, "0000000000000000"),
            _frame(0.5, "0000000000000007"),
        ]

        deduplicated = deduplicate_extracted_frames(frames, max_distance=2)

        assert [frame.timestamp_sec for frame in deduplicated] == [0.0, 0.5]

    def test_empty_list_returns_empty(self):
        """No extracted frames means no deduplicated frames."""
        assert deduplicate_extracted_frames([], max_distance=6) == []
