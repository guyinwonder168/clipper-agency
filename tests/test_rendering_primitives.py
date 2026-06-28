"""Tests for render primitives — escape_drawtext, make_caption_overlays,
make_lower_third, transition_for_template."""

import pytest
from pydantic import ValidationError

from clipper_agency.rendering.contracts import CaptionOverlay, VisualOverlay
from clipper_agency.rendering.templates import (
    RenderTemplateConfig,
    TemplateTransition,
)

# ---------------------------------------------------------------------------
# escape_drawtext
# ---------------------------------------------------------------------------


def test_escape_drawtext_passthrough_plain_text():
    """Plain text with no special characters passes through unchanged."""
    from clipper_agency.rendering.primitives import escape_drawtext

    assert escape_drawtext("Hello World") == "Hello World"
    assert escape_drawtext("") == ""
    assert escape_drawtext("abc 123") == "abc 123"


def test_escape_drawtext_escapes_backslash():
    """Backslash characters are escaped."""
    from clipper_agency.rendering.primitives import escape_drawtext

    assert escape_drawtext(r"path\to\file") == r"path\\to\\file"


def test_escape_drawtext_escapes_colon():
    """Colon characters are escaped (colon separates FFmpeg filter args)."""
    from clipper_agency.rendering.primitives import escape_drawtext

    assert escape_drawtext("a:b:c") == r"a\:b\:c"


def test_escape_drawtext_escapes_percent():
    """Percent signs are escaped (prevents FFmpeg text expansion)."""
    from clipper_agency.rendering.primitives import escape_drawtext

    assert escape_drawtext("100% done") == r"100\% done"


def test_escape_drawtext_escapes_braces():
    """Curly braces are escaped (prevents FFmpeg text expansion)."""
    from clipper_agency.rendering.primitives import escape_drawtext

    assert escape_drawtext("{hello}") == r"\{hello\}"


def test_escape_drawtext_escapes_single_quote():
    """Single quote uses POSIX close-escape-reopen (``'\\''``) — a bare ``\\'``
    terminates the single-quoted filtergraph string (job_18: 'No such filter:
    14.663')."""
    from clipper_agency.rendering.primitives import escape_drawtext

    assert escape_drawtext("It's a test") == "It'\\''s a test"


def test_escape_drawtext_apostrophe_in_quotes_regression():
    """Regression (job_18): a caption with a quoted word like ``'Cong'`` must
    escape each apostrophe POSIX close-escape-reopen so the single-quoted
    ``text='...'`` value does not terminate early + leak subsequent filters."""
    from clipper_agency.rendering.primitives import escape_drawtext

    # Each ' becomes the 4-char POSIX sequence: close-quote, \, quote, reopen.
    assert escape_drawtext("'Cong'") == "'\\''Cong'\\''"
    assert escape_drawtext("sosok 'Cong' yang") == "sosok '\\''Cong'\\'' yang"


def test_escape_drawtext_escapes_all_special_chars_combined():
    """All special characters are escaped in a single string."""
    from clipper_agency.rendering.primitives import escape_drawtext

    result = escape_drawtext(r"100% {test}: it's done\now")
    expected = r"100\% \{test\}\: it'\''s done\\now"
    assert result == expected


def test_escape_drawtext_returns_same_type():
    """escape_drawtext always returns a str."""
    from clipper_agency.rendering.primitives import escape_drawtext

    assert isinstance(escape_drawtext("test"), str)
    assert isinstance(escape_drawtext(""), str)


# ---------------------------------------------------------------------------
# make_caption_overlays
# ---------------------------------------------------------------------------


def test_make_caption_overlays_empty_text_returns_empty():
    """Empty text returns an empty list."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    result = make_caption_overlays("", 10.0)
    assert result == []


def test_make_caption_overlays_whitespace_only_returns_empty():
    """Whitespace-only text returns an empty list."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    result = make_caption_overlays("   \n  \t  ", 10.0)
    assert result == []


def test_make_caption_overlays_single_word():
    """Single word produces one CaptionOverlay spanning full duration."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    result = make_caption_overlays("Hello", 10.0)
    assert len(result) == 1
    assert result[0].text == "Hello"
    assert result[0].start_seconds == 0.0
    assert result[0].end_seconds == 10.0


def test_make_caption_overlays_fewer_words_than_words_per_caption():
    """Text shorter than words_per_caption produces one overlay."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    result = make_caption_overlays("one two three", 9.0, words_per_caption=5)
    assert len(result) == 1
    assert result[0].text == "one two three"
    assert result[0].start_seconds == 0.0
    assert result[0].end_seconds == 9.0


def test_make_caption_overlays_even_split():
    """Text evenly divisible by words_per_caption splits into correct groups."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    text = "one two three four five six"
    result = make_caption_overlays(text, 6.0, words_per_caption=2)

    assert len(result) == 3
    assert result[0].text == "one two"
    assert result[1].text == "three four"
    assert result[2].text == "five six"


def test_make_caption_overlays_uneven_split():
    """Last group gets remaining words when text is not evenly divisible."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    text = "one two three four five"
    result = make_caption_overlays(text, 5.0, words_per_caption=2)

    assert len(result) == 3
    assert result[0].text == "one two"
    assert result[1].text == "three four"
    assert result[2].text == "five"


def test_make_caption_overlays_timing_evenly_distributed():
    """Each overlay is evenly distributed across the duration."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    text = "a b c d e f g h i j"
    result = make_caption_overlays(text, 10.0, words_per_caption=2)

    assert len(result) == 5
    # Each gets 2 seconds
    for i, overlay in enumerate(result):
        expected_start = i * 2.0
        expected_end = (i + 1) * 2.0
        assert overlay.start_seconds == pytest.approx(expected_start)
        assert overlay.end_seconds == pytest.approx(expected_end)


def test_make_caption_overlays_timing_precise_boundaries():
    """First overlay starts at 0, last overlay ends at duration."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    text = "a b c d e f"
    result = make_caption_overlays(text, 30.0, words_per_caption=3)

    assert result[0].start_seconds == 0.0
    assert result[-1].end_seconds == 30.0


def test_make_caption_overlays_passes_position_and_style():
    """Position and style parameters are forwarded to each CaptionOverlay."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    result = make_caption_overlays("hello world", 5.0, position="top", style="bold")
    assert len(result) == 1
    assert result[0].position == "top"
    assert result[0].style == "bold"


def test_make_caption_overlays_default_position_and_style():
    """Default position is 'bottom' and default style is 'default'."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    result = make_caption_overlays("hello", 5.0)
    assert result[0].position == "bottom"
    assert result[0].style == "default"


def test_make_caption_overlays_returns_caption_overlay_instances():
    """All returned items are CaptionOverlay instances."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    result = make_caption_overlays("a b c d", 8.0, words_per_caption=2)
    assert len(result) == 2
    for item in result:
        assert isinstance(item, CaptionOverlay)


def test_make_caption_overlays_rejects_zero_duration():
    """Zero duration with non-empty text raises ValidationError
    because end_seconds would equal start_seconds."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    with pytest.raises(ValidationError):
        make_caption_overlays("hello world", 0.0)


def test_make_caption_overlays_rejects_negative_duration():
    """Negative duration with non-empty text raises ValidationError."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    with pytest.raises(ValidationError):
        make_caption_overlays("hello world", -1.0)


def test_make_caption_overlays_words_per_caption_one():
    """Each word gets its own overlay when words_per_caption=1."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    text = "one two three"
    result = make_caption_overlays(text, 3.0, words_per_caption=1)

    assert len(result) == 3
    assert result[0].text == "one"
    assert result[1].text == "two"
    assert result[2].text == "three"
    assert result[0].start_seconds == 0.0
    assert result[0].end_seconds == 1.0
    assert result[1].start_seconds == 1.0
    assert result[1].end_seconds == 2.0
    assert result[2].start_seconds == 2.0
    assert result[2].end_seconds == 3.0


def test_make_caption_overlays_extra_whitespace_collapsed():
    """Multiple spaces between words are treated as single separators."""
    from clipper_agency.rendering.primitives import make_caption_overlays

    text = "hello    world  test"
    result = make_caption_overlays(text, 3.0, words_per_caption=1)

    assert len(result) == 3
    assert result[0].text == "hello"
    assert result[1].text == "world"
    assert result[2].text == "test"


# ---------------------------------------------------------------------------
# make_lower_third
# ---------------------------------------------------------------------------


def test_make_lower_third_creates_visual_overlay():
    """Creates a VisualOverlay with kind='lower_third'."""
    from clipper_agency.rendering.primitives import make_lower_third

    result = make_lower_third("BREAKING NEWS", 10.0)
    assert isinstance(result, VisualOverlay)
    assert result.text == "BREAKING NEWS"
    assert result.kind == "lower_third"
    assert result.start_seconds == 0.0
    assert result.end_seconds == 10.0


def test_make_lower_third_full_duration():
    """Lower third spans the entire specified duration."""
    from clipper_agency.rendering.primitives import make_lower_third

    result = make_lower_third("Artist Name", 15.5)
    assert result.start_seconds == 0.0
    assert result.end_seconds == 15.5


def test_make_lower_third_fractional_duration():
    """Fractional durations are accepted and preserved."""
    from clipper_agency.rendering.primitives import make_lower_third

    result = make_lower_third("Test", 0.5)
    assert result.end_seconds == 0.5


def test_make_lower_third_empty_text():
    """Empty text is allowed for lower third."""
    from clipper_agency.rendering.primitives import make_lower_third

    result = make_lower_third("", 5.0)
    assert result.text == ""
    assert result.kind == "lower_third"
    assert result.end_seconds == 5.0


def test_make_lower_third_rejects_zero_duration():
    """Zero duration raises ValidationError (end_seconds must be > start_seconds)."""
    from clipper_agency.rendering.primitives import make_lower_third

    with pytest.raises(ValidationError):
        make_lower_third("Test", 0.0)


def test_make_lower_third_rejects_negative_duration():
    """Negative duration raises ValidationError."""
    from clipper_agency.rendering.primitives import make_lower_third

    with pytest.raises(ValidationError):
        make_lower_third("Test", -1.0)


# ---------------------------------------------------------------------------
# transition_for_template
# ---------------------------------------------------------------------------


def test_transition_for_template_returns_type_string():
    """Returns the transition type string from the template config."""
    from clipper_agency.rendering.primitives import transition_for_template

    template = RenderTemplateConfig(
        name="test",
        type="news_card",
        transitions=TemplateTransition(type="fade", duration="0.5s"),
    )
    assert transition_for_template(template) == "fade"


def test_transition_for_template_default_is_cut():
    """Default transition type is 'cut'."""
    from clipper_agency.rendering.primitives import transition_for_template

    template = RenderTemplateConfig(
        name="test",
        type="news_card",
    )
    assert transition_for_template(template) == "cut"


def test_transition_for_template_crossfade():
    """Returns 'crossfade' when template specifies it."""
    from clipper_agency.rendering.primitives import transition_for_template

    template = RenderTemplateConfig(
        name="test",
        type="b_roll_narration",
        transitions=TemplateTransition(type="crossfade", duration="0.3s"),
    )
    assert transition_for_template(template) == "crossfade"


def test_transition_for_template_always_returns_str():
    """Return value is always a string."""
    from clipper_agency.rendering.primitives import transition_for_template

    template = RenderTemplateConfig(name="t", type="x")
    result = transition_for_template(template)
    assert isinstance(result, str)
