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
            # Primary: resolve relative to base_dir (documented contract).
            resolved = (base / candidate_path).resolve()
            try:
                resolved.relative_to(base)
            except ValueError:
                resolved = None

            # Fallback: when base-relative fails or doesn't exist, try
            # resolving from CWD.  This handles callers like G10 that pass
            # a full relative path (e.g. "data/outputs/job_N/video.mp4")
            # whose prefix already traces to base_dir.  CWD-resolution
            # never overrides a valid base-relative result so the Packager
            # contract (base = output_dir, candidate = "video.mp4") is
            # unaffected.
            if resolved is None or not resolved.is_file():
                from_cwd = candidate_path.resolve()
                try:
                    from_cwd.relative_to(base)
                    if from_cwd.is_file():
                        resolved = from_cwd
                except ValueError:
                    pass

            if resolved is None:
                return None

        resolved.relative_to(base)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    if not resolved.is_file():
        return None
    return resolved
