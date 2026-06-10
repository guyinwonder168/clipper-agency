"""Tests for BraveSearchService — video and web search via Brave API."""

import json
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.services.brave import BraveSearchService


def _mock_response(body: dict, status: int = 200) -> MagicMock:
    """Build a MagicMock that behaves like an http.client.HTTPResponse."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(body).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = status
    return resp


# ---------------------------------------------------------------------------
# Video search
# ---------------------------------------------------------------------------


class TestBraveVideoSearch:
    def test_search_videos_returns_structured_results(self):
        """Video search returns dicts with required fields."""
        api_body = {
            "results": [
                {
                    "url": "https://example.com/video1",
                    "title": "Test Video",
                    "description": "A test video",
                    "thumbnail": "https://img.example.com/thumb.jpg",
                }
            ]
        }
        with patch("clipper_agency.services.brave.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _mock_response(api_body)
            svc = BraveSearchService(api_key="test-key")
            results = svc.search_videos("cats")

        assert len(results) == 1
        r = results[0]
        assert r["source_type"] == "web_video"
        assert r["url"] == "https://example.com/video1"
        assert r["title"] == "Test Video"
        assert r["description"] == "A test video"
        assert r["thumbnail_url"] == "https://img.example.com/thumb.jpg"

    def test_search_videos_uses_correct_endpoint(self):
        """Verifies GET to /videos/search."""
        with patch("clipper_agency.services.brave.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _mock_response({"results": []})
            svc = BraveSearchService(api_key="test-key")
            svc.search_videos("dogs")

        req = mock_urlopen.call_args[0][0]
        assert "/videos/search" in req.full_url
        assert "q=dogs" in req.full_url

    def test_search_videos_empty_api_key(self):
        """Empty API key returns []."""
        svc = BraveSearchService(api_key="")
        assert svc.search_videos("test") == []


# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------


class TestBraveWebSearch:
    def test_search_web_returns_structured_results(self):
        """Web search returns dicts with required fields."""
        api_body = {
            "web": {
                "results": [
                    {
                        "url": "https://example.com/article1",
                        "title": "Test Article",
                        "description": "A test article",
                    }
                ]
            }
        }
        with patch("clipper_agency.services.brave.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _mock_response(api_body)
            svc = BraveSearchService(api_key="test-key")
            results = svc.search_web("python tutorials")

        assert len(results) == 1
        r = results[0]
        assert r["source_type"] == "article"
        assert r["url"] == "https://example.com/article1"
        assert r["title"] == "Test Article"
        assert r["description"] == "A test article"

    def test_search_web_uses_correct_endpoint(self):
        """Verifies GET to /web/search."""
        with patch("clipper_agency.services.brave.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _mock_response({"web": {"results": []}})
            svc = BraveSearchService(api_key="test-key")
            svc.search_web("python tutorials")

        req = mock_urlopen.call_args[0][0]
        assert "/web/search" in req.full_url
        assert "q=python+tutorials" in req.full_url

    def test_network_error_returns_empty(self):
        """Network errors return empty list."""
        from urllib.error import URLError

        with patch("clipper_agency.services.brave.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("connection refused")
            # Patch time.sleep to speed up retries
            with patch("clipper_agency.services.brave.time.sleep"):
                svc = BraveSearchService(api_key="test-key")
                results = svc.search_web("anything")

        assert results == []


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


class TestBraveHeaders:
    def test_api_key_in_header(self):
        """X-Subscription-Token header includes API key."""
        with patch("clipper_agency.services.brave.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _mock_response({"results": []})
            svc = BraveSearchService(api_key="my-secret-key")
            svc.search_videos("test")

        req = mock_urlopen.call_args[0][0]
        # Check header dicts directly (case may vary across Python versions)
        all_headers = {**req.headers, **req.unredirected_hdrs}
        values = list(all_headers.values())
        assert "my-secret-key" in values
        assert "application/json" in values
