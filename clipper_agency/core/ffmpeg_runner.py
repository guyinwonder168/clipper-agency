"""Shared FFmpeg subprocess runner with streaming stderr and timeout."""
import logging
import subprocess
import threading

logger = logging.getLogger(__name__)

# Default stderr tail size for error messages.
STDERR_TAIL_SIZE = 500


def run_ffmpeg_streaming(
    cmd: list[str],
    timeout: int,
    label: str,
    tail_size: int = STDERR_TAIL_SIZE,
) -> str:
    """Run an FFmpeg command with real-time progress logging and timeout.

    Streams stderr (where FFmpeg writes progress) line-by-line to DEBUG log.
    Returns the full stderr text for diagnostics.
    Raises subprocess.TimeoutExpired on timeout, subprocess.CalledProcessError on failure.
    """
    logger.debug("FFmpeg %s command: %s", label, " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr_lines: list[str] = []

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            stripped = line.rstrip()
            if stripped:
                logger.debug("FFmpeg %s: %s", label, stripped)

    drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
    drain_thread.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        drain_thread.join(timeout=5)
        stderr_text = "".join(stderr_lines)
        logger.error(
            "FFmpeg %s timed out after %ds — stderr tail: %s",
            label, timeout, stderr_text[-tail_size:] if stderr_text else "(empty)",
        )
        raise
    drain_thread.join(timeout=5)

    stderr_text = "".join(stderr_lines)
    if proc.returncode != 0:
        logger.error(
            "FFmpeg %s failed (rc=%d) — stderr tail: %s",
            label, proc.returncode, stderr_text[-tail_size:] if stderr_text else "(empty)",
        )
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr_text)

    return stderr_text
