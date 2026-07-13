"""Safe filesystem path resolution helpers."""

from pathlib import Path


def _resolve_relative_candidate(base: Path, candidate_path: Path) -> Path | None:
    """Resolve a relative *candidate_path* under *base*, with CWD fallback.

    Primary strategy: resolve relative to ``base_dir`` (documented contract).
    Fallback strategy: resolve from CWD — handles callers (e.g. G10) that
    pass a full relative path whose prefix traces to ``base_dir``.
    The fallback never overrides a valid base-relative result, so the
    Packager contract (``base = output_dir``, ``candidate = "video.mp4"``)
    is unaffected.
    """
    # Primary: resolve relative to base_dir.
    resolved = (base / candidate_path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        resolved = None

    # Fast path: base-relative resolution exists and is a file.
    if resolved is not None and resolved.is_file():
        return resolved

    # Fallback: CWD-resolution for full relative paths like
    # "data/outputs/job_N/video.mp4".
    from_cwd = candidate_path.resolve()
    try:
        from_cwd.relative_to(base)
    except ValueError:
        return None

    return from_cwd if from_cwd.is_file() else resolved


def resolve_existing_file_under(
    base_dir: str | Path,
    candidate: str | Path,
) -> Path | None:
    """Return a resolved existing file only when it is inside ``base_dir``.

    Relative candidates are resolved from ``base_dir``. Absolute candidates are
    accepted only if their canonical path is still contained by ``base_dir``.
    This prevents parent traversal and string-prefix boundary mistakes.
    """
    if not base_dir or not candidate:
        return None

    try:
        base = Path(base_dir).resolve()
        candidate_path = Path(candidate)
        if candidate_path.is_absolute():
            resolved = candidate_path.resolve()
        else:
            resolved = _resolve_relative_candidate(base, candidate_path)
            if resolved is None:
                return None

        resolved.relative_to(base)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    if not resolved.is_file():
        return None
    return resolved
