"""Candidate frame inspection pipeline.

probe -> plan -> extract -> hash -> deduplicate -> cap -> persist.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from clipper_agency.config.schema import FrameExtractionManifest
from clipper_agency.core import frame_hash, frame_sampler
from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming
from clipper_agency.core.frame_extractor import FfmpegRunner, extract_frames
from clipper_agency.core.inspection_paths import candidate_inspection_dir
from clipper_agency.core.media_probe import probe_video

DEFAULT_MAX_FRAMES = 120
DEFAULT_DEDUP_DISTANCE = 6
# RC-7: absolute safety ceiling on every extraction offset. Guards against a
# stale/huge ffprobe ``format.duration`` (observed on some yt-dlp TikTok/YouTube
# downloads reporting hundreds of seconds for a short clip) from pushing offsets
# far beyond the actually-playable media and storming the VLM inspector with
# out-of-range frame reads.
DEFAULT_MAX_EXTRACTION_OFFSET_SEC = 30.0

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

    # RC-7: bound every extraction offset to the ACTUAL source media length.
    # A stale/huge ffprobe ``format.duration`` (hundreds of seconds for a short
    # clip) must never push offsets beyond the playable media. When the probed
    # duration is missing/<=0 we fall back to the conservative safe ceiling so
    # offsets stay small instead of leaking into the hundreds of seconds.
    raw_duration = info.duration or 0.0
    safe_bound = min(
        raw_duration if raw_duration > 0 else DEFAULT_MAX_EXTRACTION_OFFSET_SEC,
        DEFAULT_MAX_EXTRACTION_OFFSET_SEC,
    )

    boundaries = scene_boundaries if scene_boundaries is not None else []
    # RC-7 / Codex P2: pass the bounded safe_bound (NOT raw_duration) as the
    # sampling window. With raw_duration a missing/<=0 probed duration (0.0)
    # made plan_frame_samples collapse to [0.0] — judging a valid clip from a
    # single frame. safe_bound (>= the 30s fallback ceiling when raw is 0/None)
    # yields the intended 0–30s window while still capping over-long probes.
    timestamps = frame_sampler.plan_frame_samples(
        duration_sec=safe_bound,
        scene_boundaries=boundaries,
        interval_sec=interval_sec,
        max_offset_sec=safe_bound,
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
