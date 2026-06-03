"""Safe filesystem path resolution helpers."""

from pathlib import Path


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
            # Resolve relative candidate from CWD first (handles cases where
            # caller passes a path like "data/outputs/job_N/video.mp4" that
            # already contains the base_dir prefix).  Fall back to resolving
            # from base_dir when the CWD-resolution does not sit inside base.
            resolved = candidate_path.resolve()
            try:
                resolved.relative_to(base)
            except ValueError:
                resolved = (base / candidate_path).resolve()

        resolved.relative_to(base)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    if not resolved.is_file():
        return None
    return resolved
