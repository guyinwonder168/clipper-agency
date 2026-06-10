"""yt-dlp media download service."""

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib import request
from urllib.parse import urlparse

try:
    import yt_dlp  # type: ignore[import-untyped]

    _HAS_YT_DLP = True
except ImportError:  # pragma: no cover
    _HAS_YT_DLP = False

logger = logging.getLogger(__name__)


UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f]")


@dataclass
class DownloadResult:
    """Result of a media download operation."""

    path: str
    title: str = ""
    duration: float = 0.0


class YtDlpService:
    """Download media using the yt-dlp CLI tool."""

    def _validated_url(self, url: str) -> str:
        """Return a normalized URL safe to pass as a yt-dlp operand."""
        if UNSAFE_URL_CHARS.search(url):
            raise ValueError(f"Invalid download URL: {url}")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.fragment:
            raise ValueError(f"Invalid download URL: {url}")

        safe_url = parsed.scheme + "://" + parsed.netloc + parsed.path
        if parsed.query:
            safe_url += "?" + parsed.query
        return safe_url

    def download(
        self,
        url: str,
        output_path: str,
    ) -> Optional[DownloadResult]:
        """Download a video from a URL.

        Returns:
            DownloadResult on success, None on failure.
        """
        safe_url = self._validated_url(url)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "-f",
                    "best[height<=1080]",
                    "-o",
                    str(out),
                    "--max-filesize",
                    "50M",
                    "--",
                    safe_url,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                return None

            # yt-dlp may add extensions to the filename
            files = list(out.parent.glob(f"{out.stem}.*"))
            if files:
                return DownloadResult(path=str(files[0]))

            return DownloadResult(path=str(out))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Search YouTube via yt-dlp ytsearchN: prefix.

        Returns list of dicts:
        {
            "source_type": "youtube_official",
            "url": "https://www.youtube.com/watch?v=...",
            "title": "...",
            "description": "...",
            "duration": 120,
            "channel": "...",
            "thumbnail_url": "https://i.ytimg.com/...",
        }
        """
        if not _HAS_YT_DLP:
            logger.warning("yt_dlp library not installed; search unavailable")
            return []

        search_url = f"ytsearch{max_results}:{query}"
        opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
        }

        for attempt in range(3):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(search_url, download=False)

                if not info or "entries" not in info:
                    return []

                results: list[dict] = []
                for entry in info["entries"]:
                    if not entry:
                        continue
                    video_id = entry.get("id") or entry.get("url", "")
                    url = (
                        f"https://www.youtube.com/watch?v={video_id}"
                        if video_id and not video_id.startswith("http")
                        else entry.get("url", "")
                    )
                    results.append({
                        "source_type": "youtube_official",
                        "url": url,
                        "title": entry.get("title", ""),
                        "description": entry.get("description", ""),
                        "duration": entry.get("duration"),
                        "channel": entry.get("channel") or entry.get("uploader", ""),
                        "thumbnail_url": entry.get("thumbnail", ""),
                    })
                return results
            except Exception:
                logger.debug("yt-dlp search attempt %d failed", attempt + 1)
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
        return []

    _YT_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})")

    def download_thumbnail(
        self,
        video_url: str,
        output_path: str,
    ) -> Optional[str]:
        """Download best-quality thumbnail for a YouTube video.

        Args:
            video_url: YouTube video URL (watch?v=... or youtu.be/...)
            output_path: Where to save the thumbnail image

        Returns:
            Path to saved thumbnail, or None on failure.
        """
        match = self._YT_VIDEO_ID_RE.search(video_url)
        if not match:
            return None

        video_id = match.group(1)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        for quality in ("maxresdefault", "hqdefault"):
            thumb_url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
            try:
                request.urlretrieve(thumb_url, str(out))
                return str(out)
            except Exception:
                logger.debug(
                    "Thumbnail download failed for %s at %s",
                    video_id, quality,
                )
        return None
