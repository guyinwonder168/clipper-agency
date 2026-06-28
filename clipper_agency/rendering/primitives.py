"""Pure, deterministic render primitives for FFmpeg-driven video composition.

All functions are side-effect-free: same input always produces same output,
no mutation, no I/O.
"""

from __future__ import annotations

from clipper_agency.rendering.contracts import CaptionOverlay, VisualOverlay
from clipper_agency.rendering.templates import RenderTemplateConfig

# --- FFmpeg drawtext special characters (order matters: \ must be first) ---
# Single quote is NOT here — it needs POSIX close-escape-reopen (see below),
# not a bare backslash escape.

_ESCAPE_CHARS = ("\\", ":", "%", "{", "}")


def escape_drawtext(text: str) -> str:
    """Escape FFmpeg drawtext special characters for use inside ``text='...'``.

    Backslash, colon, percent, and braces are backslash-escaped. A literal
    single quote uses the POSIX ``'\\''`` close-escape-reopen sequence — a bare
    ``\\'`` does NOT survive ffmpeg's single-quoted filtergraph parser (it
    terminates the string, leaking subsequent content as filter names; job_18
    failed with "No such filter: '14.663'" from a caption containing
    ``'Cong'``).
    """
    result = text
    for char in _ESCAPE_CHARS:
        result = result.replace(char, "\\" + char)
    # Single quote: POSIX close-quote, escaped-quote, reopen-quote. A bare \'
    # terminates the single-quoted filtergraph string.
    result = result.replace("'", "'\\''")
    return result


# --- Caption / overlay helpers -------------------------------------------------


def make_caption_overlays(
    text: str,
    duration_seconds: float,
    words_per_caption: int = 5,
    position: str = "bottom",
    style: str = "default",
) -> list[CaptionOverlay]:
    """Split *text* into word groups and return evenly-timed overlays.

    Args:
        text: Plain-text caption content.
        duration_seconds: Total duration to distribute overlays across.
        words_per_caption: Maximum words per overlay group (>= 1).
        position: Screen placement forwarded to each ``CaptionOverlay``.
        style: Named style key forwarded to each ``CaptionOverlay``.

    Returns:
        Ordered list of ``CaptionOverlay`` instances, or an empty list
        when *text* is empty / whitespace-only.
    """
    words = text.split()
    if not words:
        return []

    # Group words into chunks of words_per_caption
    groups: list[str] = []
    for i in range(0, len(words), words_per_caption):
        groups.append(" ".join(words[i : i + words_per_caption]))

    n = len(groups)
    chunk = duration_seconds / n

    return [
        CaptionOverlay(
            text=group,
            start_seconds=i * chunk,
            end_seconds=(i + 1) * chunk,
            position=position,
            style=style,
        )
        for i, group in enumerate(groups)
    ]


def make_lower_third(text: str, duration_seconds: float) -> VisualOverlay:
    """Create a single lower-third ``VisualOverlay`` spanning the full duration.

    Args:
        text: Display text for the lower-third.
        duration_seconds: How long the overlay is visible (must be > 0).

    Returns:
        ``VisualOverlay`` with ``kind="lower_third"``, ``start_seconds=0.0``,
        and ``end_seconds=duration_seconds``.
    """
    return VisualOverlay(
        text=text,
        kind="lower_third",
        start_seconds=0.0,
        end_seconds=duration_seconds,
    )


# --- Transition helper ---------------------------------------------------------


def transition_for_template(template: RenderTemplateConfig) -> str:
    """Return the FFmpeg transition name from *template* configuration.

    Args:
        template: A validated ``RenderTemplateConfig``.

    Returns:
        Transition type string (e.g. ``"fade"``, ``"crossfade"``, ``"cut"``).
    """
    return template.transitions.type


def transition_duration_for_template(template: RenderTemplateConfig) -> float:
    """Return transition duration in seconds from *template* configuration.

    Handles duration strings like ``"0.5s"``, ``"0.3s"``, ``"0s"``.

    Args:
        template: A validated ``RenderTemplateConfig``.

    Returns:
        Duration as a ``float`` in seconds (always >= 0).
    """
    dur_str = template.transitions.duration
    if isinstance(dur_str, (int, float)):
        return float(dur_str)
    if dur_str.endswith("s"):
        return float(dur_str[:-1])
    return float(dur_str)
