"""Safe filesystem path resolution helpers.

S6549 (path-traversal oracle) — the two ``.resolve()`` sinks in this module are
false positives, suppressed inline per the ``artifacts.py`` precedent (same
oracle, same remedy):

* ``candidate`` is always **pipeline-internal**. Every caller passes a job-owned
  path — ``media_probe.probe_video`` receives the composed video / asset-cache
  file, ``engine`` passes the voiceover output — never HTTP / end-user input.
* Containment is enforced by :func:`_within_base` (the OWASP ``relative_to``
  guard) on every resolved path before it is returned, so parent traversal is
  rejected by construction.

Sonar's taint analysis flags ``candidate`` because it flows in through a public
function parameter; it cannot model that the subsequent containment check
neutralizes traversal. See ADR 0030 + the Phase-14 path-traversal lesson.
"""

from pathlib import Path


def _within_base(base: Path, resolved: Path) -> bool:
    """True only when *resolved* is equal to or nested under *base*.

    Single OWASP path-traversal containment guard shared by the relative and
    absolute resolution branches, so the boundary check cannot drift between
    them. Returns ``False`` (never raises) so callers can treat an out-of-base
    path as a plain miss.
    """
    try:
        resolved.relative_to(base)
        return True
    except ValueError:
        return False


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
    if not _within_base(base, resolved):
        resolved = None
    if resolved is not None and resolved.is_file():
        return resolved

    # Fallback: CWD-resolution for full relative paths like
    # "data/outputs/job_N/video.mp4".
    from_cwd = (
        candidate_path.resolve()
    )  # NOSONAR — pipeline-internal path; containment checked below
    if not _within_base(base, from_cwd):
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
            resolved = (
                candidate_path.resolve()
            )  # NOSONAR — pipeline-internal path; containment checked below
        else:
            resolved = _resolve_relative_candidate(base, candidate_path)
            if resolved is None:
                return None

        if not _within_base(base, resolved):
            return None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    if not resolved.is_file():
        return None
    return resolved
