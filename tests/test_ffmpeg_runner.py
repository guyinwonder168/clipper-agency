"""Tests for the shared FFmpeg streaming runner."""
import subprocess
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from clipper_agency.core.ffmpeg_runner import run_ffmpeg_streaming


def _make_mock_proc(
    returncode: int = 0,
    stderr_text: str = "ffmpeg output\n",
    wait_side_effect=None,
):
    """Build a mock Popen that simulates the stderr drain thread."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stderr = StringIO(stderr_text)
    proc.stdout = MagicMock()
    if wait_side_effect:
        proc.wait.side_effect = wait_side_effect
    else:
        proc.wait.return_value = returncode
    return proc


class TestRunFfmpegStreaming:
    """Unit tests for run_ffmpeg_streaming covering all branches."""

    def test_success_returns_stderr(self):
        """Successful FFmpeg run returns stderr text."""
        proc = _make_mock_proc(returncode=0, stderr_text="frame= 100 fps=30\n")
        with patch("clipper_agency.core.ffmpeg_runner.subprocess.Popen", return_value=proc):
            result = run_ffmpeg_streaming(["ffmpeg", "-version"], timeout=10, label="test")
        assert "frame= 100" in result

    def test_success_empty_stderr(self):
        """Successful run with empty stderr returns empty string."""
        proc = _make_mock_proc(returncode=0, stderr_text="")
        with patch("clipper_agency.core.ffmpeg_runner.subprocess.Popen", return_value=proc):
            result = run_ffmpeg_streaming(["ffmpeg", "-version"], timeout=10, label="test")
        assert result == ""

    def test_nonzero_returncode_raises(self):
        """Non-zero returncode raises CalledProcessError with stderr."""
        proc = _make_mock_proc(returncode=1, stderr_text="error: bad input\n")
        with patch("clipper_agency.core.ffmpeg_runner.subprocess.Popen", return_value=proc):
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                run_ffmpeg_streaming(["ffmpeg", "fail"], timeout=10, label="test")
        assert exc_info.value.returncode == 1
        assert "bad input" in exc_info.value.stderr

    def test_timeout_raises_timeout_expired(self):
        """TimeoutExpired from wait is propagated."""
        proc = _make_mock_proc(
            stderr_text="partial output\n",
            wait_side_effect=subprocess.TimeoutExpired(["ffmpeg"], 10),
        )
        with patch("clipper_agency.core.ffmpeg_runner.subprocess.Popen", return_value=proc):
            with pytest.raises(subprocess.TimeoutExpired):
                run_ffmpeg_streaming(["ffmpeg", "slow"], timeout=10, label="test")
        # Verify kill was called on timeout
        proc.kill.assert_called_once()

    def test_custom_tail_size(self):
        """tail_size parameter controls error message truncation."""
        long_stderr = "x" * 1000
        proc = _make_mock_proc(returncode=1, stderr_text=long_stderr)
        with patch("clipper_agency.core.ffmpeg_runner.subprocess.Popen", return_value=proc):
            with pytest.raises(subprocess.CalledProcessError):
                run_ffmpeg_streaming(
                    ["ffmpeg"], timeout=10, label="test", tail_size=100,
                )
