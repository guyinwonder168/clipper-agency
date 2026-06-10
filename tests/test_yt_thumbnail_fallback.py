"""Tests for YouTube thumbnail extraction fallback."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestDownloadThumbnail:
    """Tests for YtDlpService.download_thumbnail()."""

    def test_extracts_video_id_from_watch_url(self, tmp_path):
        """Should extract video ID from youtube.com/watch?v=... URL."""
        from clipper_agency.services.ytdlp import YtDlpService
        svc = YtDlpService()
        # Mock urllib.request.urlretrieve
        with patch("clipper_agency.services.ytdlp.request.urlretrieve") as mock_dl:
            mock_dl.return_value = (None, None)
            svc.download_thumbnail(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                str(tmp_path / "thumb.jpg"),
            )
            # Verify it tried to download from maxresdefault
            call_url = mock_dl.call_args[0][0]
            assert "dQw4w9WgXcQ" in call_url
            assert "maxresdefault" in call_url

    def test_extracts_video_id_from_short_url(self, tmp_path):
        """Should extract video ID from youtu.be/... URL."""
        from clipper_agency.services.ytdlp import YtDlpService
        svc = YtDlpService()
        with patch("clipper_agency.services.ytdlp.request.urlretrieve") as mock_dl:
            mock_dl.return_value = (None, None)
            svc.download_thumbnail(
                "https://youtu.be/dQw4w9WgXcQ",
                str(tmp_path / "thumb.jpg"),
            )
            call_url = mock_dl.call_args[0][0]
            assert "dQw4w9WgXcQ" in call_url

    def test_returns_none_on_invalid_url(self, tmp_path):
        """Should return None for non-YouTube URLs."""
        from clipper_agency.services.ytdlp import YtDlpService
        svc = YtDlpService()
        result = svc.download_thumbnail("https://example.com/video", str(tmp_path / "thumb.jpg"))
        assert result is None

    def test_returns_none_on_download_failure(self, tmp_path):
        """Should return None when download fails."""
        from clipper_agency.services.ytdlp import YtDlpService
        svc = YtDlpService()
        with patch("clipper_agency.services.ytdlp.request.urlretrieve", side_effect=Exception("network error")):
            result = svc.download_thumbnail(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                str(tmp_path / "thumb.jpg"),
            )
            assert result is None

    def test_fallback_to_hqdefault(self, tmp_path):
        """Should try hqdefault.jpg when maxresdefault fails."""
        from clipper_agency.services.ytdlp import YtDlpService
        svc = YtDlpService()
        call_count = [0]
        def side_effect(url, path):
            call_count[0] += 1
            if "maxresdefault" in url:
                raise Exception("not available")
            return (None, None)

        with patch("clipper_agency.services.ytdlp.request.urlretrieve", side_effect=side_effect):
            result = svc.download_thumbnail(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                str(tmp_path / "thumb.jpg"),
            )
            assert call_count[0] == 2  # Tried both resolutions


class TestThumbnailFallbackCandidates:
    """Tests for SP._get_thumbnail_fallback_candidates()."""

    def test_extracts_thumbnails_from_youtube_sources(self):
        """Should create image candidates from YouTube search results."""
        from clipper_agency.agents.segment_producer import SegmentProducerAgent
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        sources = [{
            "source_type": "youtube_official",
            "url": "https://www.youtube.com/watch?v=abc123",
            "title": "Test Video",
            "thumbnail_url": "https://i.ytimg.com/vi/abc123/hqdefault.jpg",
        }]

        candidates = sp._get_thumbnail_fallback_candidates(sources, "/tmp", 1)
        assert len(candidates) == 1
        assert candidates[0]["type"] == "photo"
        assert candidates[0]["source_type"] == "image"
        assert candidates[0]["relevance_score"] == 0.70

    def test_skips_non_youtube_sources(self):
        """Should skip sources that aren't youtube_official."""
        from clipper_agency.agents.segment_producer import SegmentProducerAgent
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        sources = [
            {"source_type": "web_video", "url": "https://example.com/video"},
            {"source_type": "tiktok_clip", "url": "https://tiktok.com/@user/video/123"},
        ]
        candidates = sp._get_thumbnail_fallback_candidates(sources, "/tmp", 1)
        assert len(candidates) == 0

    def test_skips_sources_without_thumbnail(self):
        """Should skip YouTube sources that have no thumbnail_url."""
        from clipper_agency.agents.segment_producer import SegmentProducerAgent
        sp = SegmentProducerAgent.__new__(SegmentProducerAgent)

        sources = [{
            "source_type": "youtube_official",
            "url": "https://www.youtube.com/watch?v=abc123",
            "title": "No Thumbnail",
        }]
        candidates = sp._get_thumbnail_fallback_candidates(sources, "/tmp", 1)
        assert len(candidates) == 0
