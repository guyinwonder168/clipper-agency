"""Tests for the shared FFmpeg streaming runner."""

import logging
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
                    ["ffmpeg"],
                    timeout=10,
                    label="test",
                    tail_size=100,
                )

    def test_does_not_log_raw_stderr_at_debug_by_default(self, caplog: pytest.LogCaptureFixture):
        """Regression: runner must NOT log FFmpeg's raw stderr line-by-line at DEBUG.

        Previously the drain thread emitted one DEBUG log line per stderr line
        (~600 per extraction), flooding the job log. Assert that chatty progress
        output never reaches the DEBUG log when verbose is off (the default).
        """
        chatty_stderr = (
            "frame=   10 fps= 30 q=0.0 size=       1kB time=00:00:00.33\n"
            "frame=   20 fps= 30 q=0.0 size=       2kB time=00:00:00.66\n"
            "frame=   30 fps= 30 q=0.0 size=       3kB time=00:00:01.00\n"
        )
        proc = _make_mock_proc(returncode=0, stderr_text=chatty_stderr)
        with caplog.at_level(logging.DEBUG, logger="clipper_agency.core.ffmpeg_runner"):
            with patch(
                "clipper_agency.core.ffmpeg_runner.subprocess.Popen",
                return_value=proc,
            ):
                run_ffmpeg_streaming(["ffmpeg"], timeout=10, label="extract_frames")

        debug_payloads = [
            record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG
        ]
        assert not any("frame=" in msg for msg in debug_payloads), (
            f"raw FFmpeg progress leaked to DEBUG log: {debug_payloads}"
        )
        assert not any("size=" in msg for msg in debug_payloads)

    def test_logs_single_summary_on_success(self, caplog: pytest.LogCaptureFixture):
        """On success exactly one INFO summary is logged; stderr captured but not dumped."""
        chatty_stderr = (
            "\n".join(f"frame= {i:>4} fps= 30 q=0.0 size= {i}kB" for i in range(20)) + "\n"
        )
        proc = _make_mock_proc(returncode=0, stderr_text=chatty_stderr)
        with caplog.at_level(logging.DEBUG, logger="clipper_agency.core.ffmpeg_runner"):
            with patch(
                "clipper_agency.core.ffmpeg_runner.subprocess.Popen",
                return_value=proc,
            ):
                result = run_ffmpeg_streaming(["ffmpeg"], timeout=10, label="extract_frames")

        # stderr still returned in full for diagnostics (capture preserved).
        assert "frame=" in result and result.count("\n") >= 19
        info_msgs = [
            record.getMessage() for record in caplog.records if record.levelno == logging.INFO
        ]
        assert len(info_msgs) == 1
        assert "extract_frames" in info_msgs[0]
        assert "completed" in info_msgs[0]

    def test_verbose_flag_logs_raw_stderr_at_debug(self, caplog: pytest.LogCaptureFixture):
        """verbose=True re-enables the per-line DEBUG dump (opt-in, off by default)."""
        chatty_stderr = "frame=  10 fps= 30 q=0.0\nframe=  20 fps= 30 q=0.0\n"
        proc = _make_mock_proc(returncode=0, stderr_text=chatty_stderr)
        with caplog.at_level(logging.DEBUG, logger="clipper_agency.core.ffmpeg_runner"):
            with patch(
                "clipper_agency.core.ffmpeg_runner.subprocess.Popen",
                return_value=proc,
            ):
                run_ffmpeg_streaming(["ffmpeg"], timeout=10, label="extract_frames", verbose=True)

        debug_payloads = [
            record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG
        ]
        assert sum("frame=" in msg for msg in debug_payloads) == 2

    def test_failure_logs_stderr_tail_at_error_not_per_line(self, caplog: pytest.LogCaptureFixture):
        """On failure the stderr tail is logged once at ERROR (debuggable), not line-by-line."""
        chatty_stderr = (
            "\n".join(f"frame= {i:>4} fps= 30 q=0.0" for i in range(50)) + "\nError: bad input\n"
        )
        proc = _make_mock_proc(returncode=1, stderr_text=chatty_stderr)
        with caplog.at_level(logging.DEBUG, logger="clipper_agency.core.ffmpeg_runner"):
            with patch(
                "clipper_agency.core.ffmpeg_runner.subprocess.Popen",
                return_value=proc,
            ):
                with pytest.raises(subprocess.CalledProcessError):
                    run_ffmpeg_streaming(["ffmpeg"], timeout=10, label="extract_frames")

        error_msgs = [
            record.getMessage() for record in caplog.records if record.levelno == logging.ERROR
        ]
        assert len(error_msgs) == 1
        assert "extract_frames" in error_msgs[0]
        debug_payloads = [
            record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG
        ]
        assert not any("frame=" in msg for msg in debug_payloads)
