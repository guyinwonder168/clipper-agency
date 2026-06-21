"""Shared FFmpeg subprocess runner with captured stderr and timeout."""

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
    verbose: bool = False,
) -> str:
    """Run an FFmpeg command with captured stderr and timeout.

    stderr (where FFmpeg writes progress) is captured silently so it is still
    available for error detection (non-zero exit) and diagnostics, but it is
    NOT logged line-by-line. A single one-line summary is logged on success,
    and the stderr tail is logged at ERROR level on failure for debuggability.

    Set ``verbose=True`` to emit FFmpeg's raw stderr line-by-line at DEBUG.
    This is off by default to avoid log flooding (a single frame extraction can
    emit hundreds of progress lines).

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
            # Raw stderr is captured regardless of verbosity so non-zero exits
            # can still be diagnosed. Only forward it to the logger when the
            # caller explicitly opted into verbose output.
            if verbose:
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
            label,
            timeout,
            stderr_text[-tail_size:] if stderr_text else "(empty)",
        )
        raise
    drain_thread.join(timeout=5)

    stderr_text = "".join(stderr_lines)
    if proc.returncode != 0:
        logger.error(
            "FFmpeg %s failed (rc=%d) — stderr tail: %s",
            label,
            proc.returncode,
            stderr_text[-tail_size:] if stderr_text else "(empty)",
        )
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr_text)

    # Single one-line success summary — no per-line stderr dump.
    logger.info("ffmpeg %s completed (rc=0)", label)
    return stderr_text
