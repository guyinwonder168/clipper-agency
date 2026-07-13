"""Tests for yt-dlp media download service."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.services.ytdlp import DownloadResult, YtDlpService


def test_download_result_model():
    r = DownloadResult(path="/tmp/video.mp4", title="Test", duration=30.0)
    assert r.path == "/tmp/video.mp4"
    assert r.duration == 30.0


@patch("subprocess.run")
def test_download_video(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    svc = YtDlpService()
    out = tmp_path / "video.mp4"
    result = svc.download("https://example.com/video", str(out))
    assert result.path.endswith(".mp4")
    mock_run.assert_called_once()
    args = mock_run.call_args.args[0]
    assert "--" in args
    assert args[args.index("--") + 1] == "https://example.com/video"


@patch("subprocess.run")
def test_download_delimits_url_operand_from_options(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    svc = YtDlpService()

    svc.download("https://example.com/--output?name=value", str(tmp_path / "video.mp4"))

    args = mock_run.call_args.args[0]
    assert args[args.index("--") + 1] == "https://example.com/--output?name=value"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/video",
        "https://exa mple.com/video",
        "https://example.com/vi\ndeo",
        "https://example.com/vi\x00deo",
        "https://example.com/video#fragment",
    ],
)
def test_download_rejects_unsafe_urls(url, tmp_path):
    svc = YtDlpService()
    out = str(tmp_path / "video.mp4")

    with pytest.raises(ValueError):
        svc.download(url, out)


@patch("subprocess.run")
def test_download_failure(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=1)
    svc = YtDlpService()
    out = tmp_path / "out.mp4"
    result = svc.download("https://invalid-url", str(out))
    assert result is None


@patch("subprocess.run")
def test_download_file_glob_finds_extension(mock_run, tmp_path):
    """Line 57: yt-dlp adds extension; glob finds it."""
    mock_run.return_value = MagicMock(returncode=0)
    # Create a file with an extension (simulating yt-dlp's output)
    (tmp_path / "video.mp4").write_text("fake_video")
    svc = YtDlpService()
    result = svc.download("https://example.com/video", str(tmp_path / "video.mp4"))
    assert result.path == str(tmp_path / "video.mp4")
    assert isinstance(result, DownloadResult)


@patch("subprocess.run")
def test_download_timeout_returns_none(mock_run, tmp_path):
    """Line 60: subprocess.TimeoutExpired → returns None."""
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=120)
    svc = YtDlpService()
    out = tmp_path / "out.mp4"
    result = svc.download("https://slow.example.com/video", str(out))
    assert result is None


@patch("subprocess.run")
def test_download_filenotfound_returns_none(mock_run, tmp_path):
    """Line 61: FileNotFoundError (yt-dlp not installed) → returns None."""
    mock_run.side_effect = FileNotFoundError("yt-dlp not found")
    svc = YtDlpService()
    out = tmp_path / "out.mp4"
    result = svc.download("https://example.com/video", str(out))
    assert result is None
