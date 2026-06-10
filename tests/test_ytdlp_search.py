"""Tests for YtDlpService.search() — YouTube search via yt-dlp."""

import pytest
from unittest.mock import patch, MagicMock

from clipper_agency.services.ytdlp import YtDlpService

# Patch target: the module-level name in the production module.
_YTDLP_MOD = "clipper_agency.services.ytdlp"
_HAS_YTDLP = f"{_YTDLP_MOD}._HAS_YT_DLP"
_YT_DLP = f"{_YTDLP_MOD}.yt_dlp"


def _fake_entry(
    video_id="abc123",
    title="Test Video",
    description="A test video",
    duration=120,
    channel="TestChannel",
    thumbnail="https://i.ytimg.com/vi/abc123/hqdefault.jpg",
):
    return {
        "id": video_id,
        "title": title,
        "description": description,
        "duration": duration,
        "channel": channel,
        "thumbnail": thumbnail,
    }


def _make_mock_ydl(extract_info_return=None, extract_info_side_effect=None):
    """Create a mock YoutubeDL context manager."""
    mock_ydl = MagicMock()
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    if extract_info_return is not None:
        mock_ydl.extract_info.return_value = extract_info_return
    if extract_info_side_effect is not None:
        mock_ydl.extract_info.side_effect = extract_info_side_effect
    return mock_ydl


class TestYtDlpSearch:
    """Verify YouTube search via yt-dlp."""

    def test_search_returns_structured_results(self):
        """Search returns dicts with required fields."""
        mock_ydl = _make_mock_ydl(extract_info_return={"entries": [_fake_entry()]})

        with patch(_HAS_YTDLP, True), patch(_YT_DLP, create=True) as mock_mod:
            mock_mod.YoutubeDL.return_value = mock_ydl
            svc = YtDlpService()
            results = svc.search("Sarwendah drama", max_results=5)

        assert len(results) == 1
        r = results[0]
        assert r["source_type"] == "youtube_official"
        assert "youtube.com/watch" in r["url"]
        assert r["title"] == "Test Video"
        assert r["thumbnail_url"] == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"

    def test_search_constructs_ytsearch_prefix(self):
        """Verifies ytsearch{N}:{query} URL format."""
        mock_ydl = _make_mock_ydl(extract_info_return={"entries": []})

        with patch(_HAS_YTDLP, True), patch(_YT_DLP, create=True) as mock_mod:
            mock_mod.YoutubeDL.return_value = mock_ydl
            svc = YtDlpService()
            svc.search("Sarwendah drama", max_results=5)

        call_args = mock_ydl.extract_info.call_args
        assert call_args[0][0] == "ytsearch5:Sarwendah drama"

    def test_search_handles_empty_results(self):
        """Network/API errors return empty list, not exception."""
        mock_ydl = _make_mock_ydl(
            extract_info_side_effect=Exception("network error"),
        )

        with patch(_HAS_YTDLP, True), \
             patch(_YT_DLP, create=True) as mock_mod, \
             patch(f"{_YTDLP_MOD}.time.sleep"):
            mock_mod.YoutubeDL.return_value = mock_ydl
            svc = YtDlpService()
            results = svc.search("anything")

        assert results == []

    def test_search_max_results_param(self):
        """max_results controls ytsearch prefix number."""
        mock_ydl = _make_mock_ydl(extract_info_return={"entries": []})

        with patch(_HAS_YTDLP, True), patch(_YT_DLP, create=True) as mock_mod:
            mock_mod.YoutubeDL.return_value = mock_ydl
            svc = YtDlpService()
            svc.search("test query", max_results=3)

        call_args = mock_ydl.extract_info.call_args
        assert call_args[0][0] == "ytsearch3:test query"

    def test_search_retry_on_failure(self):
        """Retries up to 2 times on failure, returns results on success."""
        mock_ydl = _make_mock_ydl(
            extract_info_side_effect=[
                Exception("fail 1"),
                {"entries": [_fake_entry(video_id="retry_ok")]},
            ],
        )

        with patch(_HAS_YTDLP, True), \
             patch(_YT_DLP, create=True) as mock_mod, \
             patch(f"{_YTDLP_MOD}.time.sleep"):
            mock_mod.YoutubeDL.return_value = mock_ydl
            svc = YtDlpService()
            results = svc.search("retry test")

        assert len(results) == 1
        assert results[0]["url"].endswith("retry_ok")

    def test_search_handles_none_entries(self):
        """None entries in results list are skipped."""
        mock_ydl = _make_mock_ydl(
            extract_info_return={"entries": [None, _fake_entry(), None]},
        )

        with patch(_HAS_YTDLP, True), patch(_YT_DLP, create=True) as mock_mod:
            mock_mod.YoutubeDL.return_value = mock_ydl
            svc = YtDlpService()
            results = svc.search("test")

        assert len(results) == 1

    def test_search_url_from_url_field(self):
        """When entry has 'url' but no 'id', builds URL from url field."""
        entry = {
            "url": "https://www.youtube.com/watch?v=xyz789",
            "title": "URL Field Video",
            "description": "",
            "duration": 60,
            "channel": "Ch",
            "thumbnail": "https://i.ytimg.com/thumb.jpg",
        }
        mock_ydl = _make_mock_ydl(extract_info_return={"entries": [entry]})

        with patch(_HAS_YTDLP, True), patch(_YT_DLP, create=True) as mock_mod:
            mock_mod.YoutubeDL.return_value = mock_ydl
            svc = YtDlpService()
            results = svc.search("test")

        assert results[0]["url"] == "https://www.youtube.com/watch?v=xyz789"

    def test_search_returns_empty_when_no_ytdlp(self):
        """Returns empty list when yt_dlp library is not installed."""
        with patch(_HAS_YTDLP, False):
            svc = YtDlpService()
            results = svc.search("anything")

        assert results == []
