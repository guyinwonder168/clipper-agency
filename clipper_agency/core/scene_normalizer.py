"""Scene normalization — ensures all clips are 1080x1920 h264 yuv420p."""
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming

logger = logging.getLogger(__name__)

_NORMALIZE_TIMEOUT = 120  # seconds
_IMAGE_NORMALIZE_TIMEOUT = 300  # seconds — zoompan is CPU-intensive
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_IMAGE_DURATION = 5  # seconds per image scene
_KEN_BURNS_FRAMES = 150  # 5s * 30fps


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

    @staticmethod
    def _is_image(path: str) -> bool:
        """Return True if the file extension indicates a still image."""
        return Path(path).suffix.lower() in _IMAGE_EXTENSIONS

    def normalize(self, input_path: str, output_path: str) -> NormalizeResult:
        """Normalize a single scene video.

        Skips if already 1080x1920. Otherwise runs ffmpeg with scale+pad filter.
        Audio is stripped (-an). Metadata is stripped (-map_metadata -1).
        """
        if not os.path.isfile(input_path):
            return NormalizeResult(
                path=input_path, success=False, error=f"Input not found: {input_path}"
            )

        # Image path — always process with zoompan
        if self._is_image(input_path):
            return self._normalize_image(input_path, output_path)

        # Probe current dimensions — skip ffmpeg if already correct
        try:
            from clipper_agency.core.media_probe import probe_video

            info = probe_video(input_path, Path(input_path).parent)
            sar_ok = info.sample_aspect_ratio == "1:1"
            fps_ok = abs(getattr(info, "fps", 30.0) - 30.0) < 0.01
            if (
                info
                and info.width == self.TARGET_WIDTH
                and info.height == self.TARGET_HEIGHT
                and sar_ok
                and fps_ok
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
            "-r", "30",
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

    def _normalize_image(self, input_path: str, output_path: str) -> NormalizeResult:
        """Convert still image to 5s 30fps 1080x1920 video with Ken Burns zoompan."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-vf",
            (
                f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}"
                ":force_original_aspect_ratio=decrease,"
                f"pad={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                f"zoompan=z='min(zoom+0.001,1.2)':x='iw/2-(iw/zoom/2)'"
                f":y='ih/2-(ih/zoom/2)'"
                f":d={_KEN_BURNS_FRAMES}:s={self.TARGET_WIDTH}x{self.TARGET_HEIGHT}:fps=30,"
                "setsar=1"
            ),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-t", str(_IMAGE_DURATION),
            "-an",
            "-map_metadata", "-1",
            output_path,
        ]

        try:
            logger.debug(
                "Normalizer: image→video %s (ken burns, %ds)",
                Path(input_path).name, _IMAGE_DURATION,
            )
            stderr_text = run_ffmpeg_streaming(
                cmd, timeout=_IMAGE_NORMALIZE_TIMEOUT, label="image-normalize",
            )
            return NormalizeResult(path=output_path, success=True, stderr=stderr_text)
        except FileNotFoundError:
            return NormalizeResult(
                path=input_path, success=False, error="FFmpeg not found",
            )
        except subprocess.TimeoutExpired:
            return NormalizeResult(
                path=input_path,
                success=False,
                error=f"FFmpeg timed out ({_IMAGE_NORMALIZE_TIMEOUT}s)",
            )
        except subprocess.CalledProcessError as e:
            return NormalizeResult(
                path=input_path,
                success=False,
                error=f"FFmpeg exit code {e.returncode}",
                stderr=e.stderr or "",
            )
