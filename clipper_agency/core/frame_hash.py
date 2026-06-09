"""Perceptual hashing helpers for extracted runtime-inspection frames."""

from __future__ import annotations

from os import PathLike

from PIL import Image

from clipper_agency.config.schema import ExtractedFrame


HASH_SIZE = 8


def compute_perceptual_hash(image_path: str | PathLike[str]) -> str:
    """Compute a 64-bit difference hash for an image as fixed-width hex."""
    with Image.open(image_path) as image:
        grayscale = image.convert("L").resize((HASH_SIZE + 1, HASH_SIZE))
        pixels = list(grayscale.tobytes())

    bit_string = "".join(
        "1" if row[col] > row[col + 1] else "0"
        for row in _hash_rows(pixels)
        for col in range(HASH_SIZE)
    )
    return f"{int(bit_string, 2):016x}"


def hash_distance(hash_a: str, hash_b: str) -> int:
    """Return the bit-level Hamming distance between same-width hex hashes."""
    if len(hash_a) != len(hash_b):
        raise ValueError("Perceptual hashes must have the same length")

    return (int(hash_a, 16) ^ int(hash_b, 16)).bit_count()


def deduplicate_extracted_frames(
    frames: list[ExtractedFrame],
    max_distance: int,
) -> list[ExtractedFrame]:
    """Remove perceptually near-identical frames while keeping first occurrences."""
    deduplicated: list[ExtractedFrame] = []
    for frame in frames:
        if not _is_near_duplicate(frame, deduplicated, max_distance):
            deduplicated.append(frame)
    return deduplicated


def _hash_rows(pixels: list[int]) -> list[list[int]]:
    """Split flattened grayscale pixels into dHash rows."""
    row_width = HASH_SIZE + 1
    return [pixels[start : start + row_width] for start in range(0, len(pixels), row_width)]


def _is_near_duplicate(
    frame: ExtractedFrame,
    previous_frames: list[ExtractedFrame],
    max_distance: int,
) -> bool:
    """Check if a frame matches any previously retained perceptual hash."""
    return any(
        hash_distance(frame.perceptual_hash, previous.perceptual_hash) <= max_distance
        for previous in previous_frames
    )
