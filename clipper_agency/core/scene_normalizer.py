"""Scene normalization — ensures all clips are 1080x1920 h264 yuv420p."""
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming

logger = logging.getLogger(__name__)

_NORMALIZE_TIMEOUT = 120  # seconds


@dataclass(frozen=True)
class NormalizeResult:
    path: str
    success: bool
    error: str = ""
    stderr: str | None = None


class SceneNormalizer:
    """Normalizes video scenes to TikTok standard: 1080x1920, h264, yuv420p, no audio."""

    TARGET_WIDTH = 1080
    TARGET_HEIGHT = 1920

    def normalize(self, input_path: str, output_path: str) -> NormalizeResult:
        """Normalize a single scene video.

        Skips if already 1080x1920. Otherwise runs ffmpeg with scale+pad filter.
        Audio is stripped (-an). Metadata is stripped (-map_metadata -1).
        """
        if not os.path.isfile(input_path):
            return NormalizeResult(
                path=input_path, success=False, error=f"Input not found: {input_path}"
            )

        # Probe current dimensions — skip ffmpeg if already correct
        try:
            from clipper_agency.core.media_probe import probe_video

            info = probe_video(input_path, Path(input_path).parent)
            sar_ok = info.sample_aspect_ratio == "1:1"
            if (
                info
                and info.width == self.TARGET_WIDTH
                and info.height == self.TARGET_HEIGHT
                and sar_ok
            ):
                return NormalizeResult(path=input_path, success=True)
        except Exception:
            pass  # Probe failed, proceed with normalization anyway

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-vf",
            (
                f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}"
                ":force_original_aspect_ratio=decrease,"
                f"pad={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1"
            ),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-map_metadata",
            "-1",
            output_path,
        ]

        try:
            logger.debug(
                "Normalizer: scene %s → %s", Path(input_path).name, Path(output_path).name,
            )
            stderr_text = run_ffmpeg_streaming(cmd, timeout=_NORMALIZE_TIMEOUT, label="normalize")
            return NormalizeResult(path=output_path, success=True, stderr=stderr_text)
        except FileNotFoundError:
            return NormalizeResult(
                path=input_path, success=False, error="FFmpeg not found"
            )
        except subprocess.TimeoutExpired:
            return NormalizeResult(
                path=input_path, success=False, error=f"FFmpeg timed out ({_NORMALIZE_TIMEOUT}s)"
            )
        except subprocess.CalledProcessError as e:
            return NormalizeResult(
                path=input_path,
                success=False,
                error=f"FFmpeg exit code {e.returncode}",
                stderr=e.stderr or "",
            )
