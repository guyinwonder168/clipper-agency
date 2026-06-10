"""Tavily web search service."""

import logging
import random
import time

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_JITTER_RANGE = 0.5
_YOUTUBE_WATCH = "youtube.com/watch"


class TavilyService:
    """Search web via Tavily API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._base_url = "https://api.tavily.com"

    @staticmethod
    def _classify_url(url: str) -> str:
        """Return 'web_video' for YouTube watch URLs, else 'article'."""
        return "web_video" if _YOUTUBE_WATCH in url else "article"

    def search(
        self,
        query: str,
        max_results: int = 5,
        include_videos: bool = True,
    ) -> list[dict]:
        """Search web via Tavily API.

        Returns list of dicts:
        {
            "source_type": "web_video" | "article",
            "url": "...",
            "title": "...",
            "content": "...",  # extracted text
            "score": 0.85,     # Tavily relevance score
        }
        """
        if not self._api_key:
            return []

        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "include_videos": include_videos,
        }

        for attempt in range(_MAX_RETRIES):
            try:
                resp = httpx.post(
                    f"{self._base_url}/search",
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception:
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, _JITTER_RANGE)
                    logger.warning("Tavily search attempt %d failed, retrying in %.1fs", attempt + 1, delay)
                    time.sleep(delay)
                else:
                    logger.exception("Tavily search failed after %d attempts", _MAX_RETRIES)
                    return []
        else:
            return []

        raw_results = data.get("results", [])
        return [
            {
                "source_type": self._classify_url(r.get("url", "")),
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0.0),
            }
            for r in raw_results
        ]
