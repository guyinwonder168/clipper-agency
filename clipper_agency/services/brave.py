"""Brave Search service for video and web search."""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0


class BraveSearchService:
    """Search via Brave Search API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._base_url = "https://api.search.brave.com/res/v1"

    def _request(self, endpoint: str, query: str, count: int) -> Optional[dict]:
        """Make a GET request with retry and exponential backoff.

        Returns parsed JSON dict or None on any failure.
        """
        if not self._api_key:
            return None

        params = urllib.parse.urlencode({"q": query, "count": count})
        url = f"{self._base_url}{endpoint}?{params}"

        req = urllib.request.Request(url)
        req.add_header("X-Subscription-Token", self._api_key)
        req.add_header("Accept", "application/json")

        for attempt in range(_MAX_RETRIES):
            try:
                with urllib.request.urlopen(req) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Brave API request failed (attempt %d/%d): %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)

        return None

    def search_videos(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Search videos via Brave Search API.

        Returns list of dicts:
        {
            "source_type": "web_video",
            "url": "...",
            "title": "...",
            "description": "...",
            "thumbnail_url": "...",
        }
        """
        data = self._request("/videos/search", query, max_results)
        if data is None:
            return []

        results = data.get("results", data.get("videos", []))
        return [
            {
                "source_type": "web_video",
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "thumbnail_url": item.get("thumbnail", item.get("thumbnail_url", "")),
            }
            for item in results
        ]

    def search_web(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Search web pages via Brave Search API.

        Returns list of dicts:
        {
            "source_type": "article",
            "url": "...",
            "title": "...",
            "description": "...",
        }
        """
        data = self._request("/web/search", query, max_results)
        if data is None:
            return []

        results = data.get("results", data.get("web", {}).get("results", []))
        return [
            {
                "source_type": "article",
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
            }
            for item in results
        ]
