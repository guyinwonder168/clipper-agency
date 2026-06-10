"""Candidate frame inspection pipeline — probe → plan → extract → hash → deduplicate → cap → persist."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from clipper_agency.config.schema import ExtractedFrame, FrameExtractionManifest
from clipper_agency.core import frame_hash, frame_sampler
from clipper_agency.core.frame_extractor import FfmpegRunner, extract_frames
from clipper_agency.core.inspection_paths import candidate_inspection_dir
from clipper_agency.core.media_probe import VideoInfo, probe_video
from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming

DEFAULT_MAX_FRAMES = 120
DEFAULT_DEDUP_DISTANCE = 6

HashFn = Callable[[str | Path], str]


def run_frame_inspection_pipeline(
    video_path: str | Path,
    job_id: int,
    beat_id: str,
    asset_id: str,
    cache_root: str | Path,
    allowed_base_dir: str | Path,
    *,
    scene_boundaries: list[float] | None = None,
    interval_sec: float = 0.5,
    max_frames: int = DEFAULT_MAX_FRAMES,
    dedup_max_distance: int = DEFAULT_DEDUP_DISTANCE,
    ffmpeg_runner: FfmpegRunner | None = None,
    hash_fn: HashFn | None = None,
) -> FrameExtractionManifest:
    """Run the full candidate frame inspection pipeline.

    1. Probe video duration via ffprobe
    2. Plan sample timestamps at regular intervals + scene boundaries
    3. Extract JPEG frames at each timestamp
    4. Compute perceptual hashes for each frame
    5. Deduplicate near-identical frames
    6. Cap total frames to *max_frames*
    7. Persist manifest JSON to the canonical inspection directory
    8. Return a ``FrameExtractionManifest``

    *ffmpeg_runner* and *hash_fn* are injected for testability; defaults
    use the project's real FFmpeg runner and difference-hash implementation.
    """
    info = probe_video(video_path, allowed_base_dir)
    if info is None:
        raise ValueError(f"Failed to probe video: {video_path}")

    boundaries = scene_boundaries if scene_boundaries is not None else []
    timestamps = frame_sampler.plan_frame_samples(
        duration_sec=info.duration or 0.0,
        scene_boundaries=boundaries,
        interval_sec=interval_sec,
    )

    runner = ffmpeg_runner if ffmpeg_runner is not None else run_ffmpeg_streaming
    hasher = hash_fn if hash_fn is not None else frame_hash.compute_perceptual_hash

    output_dir = candidate_inspection_dir(cache_root, job_id, beat_id, asset_id)

    frames = extract_frames(
        video_path=str(video_path),
        timestamps=timestamps,
        output_dir=output_dir,
        ffmpeg_runner=runner,
    )

    for frame in frames:
        try:
            frame.perceptual_hash = hasher(frame.path)
        except Exception:
            frame.perceptual_hash = "0000000000000000"

    frames = frame_hash.deduplicate_extracted_frames(frames, dedup_max_distance)

    if len(frames) > max_frames:
        frames = frames[:max_frames]

    manifest = FrameExtractionManifest(
        asset_id=asset_id,
        beat_id=beat_id,
        source_path=str(video_path),
        frames=frames,
    )

    manifest_path = output_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest.model_dump_json(indent=2))

    return manifest
