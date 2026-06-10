"""Tests for TavilyService — web search via Tavily API."""

from unittest.mock import patch, MagicMock

import httpx
import pytest

from clipper_agency.services.tavily import TavilyService


class TestTavilySearch:
    """Test suite for TavilyService.search."""

    def _mock_response(self, status_code: int = 200, json_data: dict | None = None):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.raise_for_status.return_value = None
        if status_code >= 400:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=resp,
            )
        return resp

    @patch("httpx.post")
    def test_search_returns_structured_results(self, mock_post):
        """Search returns dicts with required fields."""
        mock_post.return_value = self._mock_response(json_data={
            "results": [
                {
                    "url": "https://example.com/article",
                    "title": "Test Article",
                    "content": "Some content",
                    "score": 0.92,
                }
            ]
        })
        svc = TavilyService(api_key="key123")
        results = svc.search("test query")

        assert len(results) == 1
        r = results[0]
        assert r["source_type"] == "article"
        assert r["url"] == "https://example.com/article"
        assert r["title"] == "Test Article"
        assert r["content"] == "Some content"
        assert r["score"] == 0.92

    @patch("httpx.post")
    def test_youtube_urls_get_web_video_type(self, mock_post):
        """YouTube URLs classified as web_video."""
        mock_post.return_value = self._mock_response(json_data={
            "results": [
                {
                    "url": "https://www.youtube.com/watch?v=abc123",
                    "title": "Video",
                    "content": "desc",
                    "score": 0.8,
                }
            ]
        })
        svc = TavilyService(api_key="key123")
        results = svc.search("music video")

        assert results[0]["source_type"] == "web_video"

    @patch("httpx.post")
    def test_non_video_urls_get_article_type(self, mock_post):
        """Non-video URLs classified as article."""
        mock_post.return_value = self._mock_response(json_data={
            "results": [
                {
                    "url": "https://example.com/blog/post",
                    "title": "Blog",
                    "content": "text",
                    "score": 0.75,
                }
            ]
        })
        svc = TavilyService(api_key="key123")
        results = svc.search("blog post")

        assert results[0]["source_type"] == "article"

    def test_empty_api_key_returns_empty(self):
        """Empty API key skips API call and returns []."""
        svc = TavilyService(api_key="")
        assert svc.search("test") == []

    @patch("httpx.post")
    def test_network_error_returns_empty(self, mock_post):
        """Network errors return empty list, not exception."""
        mock_post.side_effect = httpx.ConnectError("connection refused")
        svc = TavilyService(api_key="key123")
        # Patch time.sleep to avoid delays in test
        with patch("time.sleep"):
            results = svc.search("test")

        assert results == []

    @patch("httpx.post")
    def test_api_payload_construction(self, mock_post):
        """Verify correct API payload is sent."""
        mock_post.return_value = self._mock_response(json_data={"results": []})
        svc = TavilyService(api_key="test-key")
        svc.search("indonesian music", max_results=10, include_videos=False)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "https://api.tavily.com/search"
        body = call_kwargs[1]["json"]
        assert body["query"] == "indonesian music"
        assert body["max_results"] == 10
        assert body["include_videos"] is False
        assert body["api_key"] == "test-key"

    @patch("httpx.post")
    def test_multiple_results_classified(self, mock_post):
        """Mixed URLs get correct source_type classification."""
        mock_post.return_value = self._mock_response(json_data={
            "results": [
                {"url": "https://www.youtube.com/watch?v=xyz", "title": "Vid", "content": "c", "score": 0.9},
                {"url": "https://news.site.com/story", "title": "News", "content": "c", "score": 0.7},
                {"url": "https://m.youtube.com/watch?v=abc", "title": "Mobile", "content": "c", "score": 0.6},
            ]
        })
        svc = TavilyService(api_key="key123")
        results = svc.search("mixed")

        assert results[0]["source_type"] == "web_video"
        assert results[1]["source_type"] == "article"
        assert results[2]["source_type"] == "web_video"

    @patch("httpx.post")
    def test_empty_results_from_api(self, mock_post):
        """API returning empty results list yields empty list."""
        mock_post.return_value = self._mock_response(json_data={"results": []})
        svc = TavilyService(api_key="key123")
        assert svc.search("nothing") == []

    def test_classify_url_static(self):
        """Static helper classifies correctly."""
        assert TavilyService._classify_url("https://www.youtube.com/watch?v=abc") == "web_video"
        assert TavilyService._classify_url("https://example.com/page") == "article"
