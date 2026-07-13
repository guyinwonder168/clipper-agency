"""Tests for rendering template loader."""

from pathlib import Path

import pytest

from clipper_agency.rendering.templates import (
    RenderTemplateConfig,
    TemplateLayout,
    TemplateLoadError,
    TemplateTransition,
    load_render_template,
)


def test_load_render_template_reads_news_card():
    """Happy path: loads the news_card template with correct fields."""
    template = load_render_template("news_card", Path("templates"))

    assert template.name == "news_card"
    assert template.type == "news_card"
    assert template.style == "headline_image_facts"
    assert template.layout.resolution == "1080x1920"
    assert template.layout.background_color == "#1a1a2e"
    assert template.layout.title_font_size == 56
    assert template.layout.subtitle_font_size == 32
    assert template.layout.caption_position == "bottom"
    assert template.transitions.type == "fade"
    assert template.transitions.duration == "0.5s"


def test_load_render_template_reads_b_roll_narration():
    """Happy path: loads the b_roll_narration template."""
    template = load_render_template("b_roll_narration", Path("templates"))

    assert template.name == "b_roll_narration"
    assert template.type == "b_roll_narration"
    assert template.style == "voiceover_clips_captions"
    assert template.layout.resolution == "1080x1920"
    assert template.layout.clip_duration == "3-5s"
    assert template.layout.caption_style == "dynamic"
    assert template.transitions.type == "crossfade"
    assert template.transitions.duration == "0.3s"


def test_load_render_template_reads_rapid_update():
    """Happy path: loads the rapid_update template."""
    template = load_render_template("rapid_update", Path("templates"))

    assert template.name == "rapid_update"
    assert template.type == "rapid_update"
    assert template.style == "fast_cuts_punchy"
    assert template.layout.resolution == "1080x1920"
    assert template.layout.clip_duration == "1.5-3s"
    assert template.layout.caption_style == "punchy_centered"
    assert template.transitions.type == "cut"
    assert template.transitions.duration == "0s"


def test_load_render_template_returns_correct_types():
    """Verify returned config contains correct Pydantic model types."""
    template = load_render_template("news_card", Path("templates"))

    assert isinstance(template, RenderTemplateConfig)
    assert isinstance(template.layout, TemplateLayout)
    assert isinstance(template.transitions, TemplateTransition)


def test_load_render_template_default_layout_and_transitions():
    """When YAML omits optional fields, defaults are used."""
    template = load_render_template("rapid_update", Path("templates"))

    # Fields not in rapid_update.yaml should use defaults
    assert template.layout.background_color is None
    assert template.layout.title_font_size is None
    assert template.layout.subtitle_font_size is None


def test_load_render_template_unknown_name_raises():
    """Unknown template name raises TemplateLoadError."""
    templates = Path("templates")
    with pytest.raises(TemplateLoadError, match="Template not found"):
        load_render_template("nonexistent_template", templates)


def test_load_render_template_rejects_path_like_name_with_slash():
    """Path-like names with '/' are rejected."""
    templates = Path("templates")
    with pytest.raises(TemplateLoadError, match="Invalid template name"):
        load_render_template("../news_card", templates)


def test_load_render_template_rejects_path_like_name_with_dotdot():
    """Path-like names with '..' are rejected."""
    templates = Path("templates")
    with pytest.raises(TemplateLoadError, match="Invalid template name"):
        load_render_template("..\\news_card", templates)


def test_load_render_template_rejects_path_like_name_traversal():
    """Path traversal attempts via path-like names are rejected."""
    templates = Path("templates")
    with pytest.raises(TemplateLoadError, match="Invalid template name"):
        load_render_template("news_card/../../etc/passwd", templates)


def test_load_render_template_rejects_invalid_name_pattern():
    """Names not matching [a-z][a-z0-9_]* are rejected."""
    invalid_names = ["News_Card", "123news", "_news", "news card", "news-card", ""]
    templates = Path("templates")
    for name in invalid_names:
        with pytest.raises(TemplateLoadError, match="Invalid template name"):
            load_render_template(name, templates)


def test_load_render_template_missing_file_raises():
    """Missing template file raises TemplateLoadError with actionable message."""
    templates = Path("templates")
    with pytest.raises(TemplateLoadError, match="Template not found"):
        load_render_template("valid_name_but_no_file", templates)


def test_load_render_template_defaults_templates_dir():
    """Calling without templates_dir defaults to Path("templates")."""
    template = load_render_template("news_card")

    assert template.name == "news_card"


def test_load_render_template_accepts_string_dir():
    """templates_dir can be a string path."""
    template = load_render_template("news_card", "templates")

    assert template.name == "news_card"


def test_load_render_template_invalid_yaml_schema_raises(tmp_path):
    """Missing required fields (name, type) raises TemplateLoadError."""
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text("style: missing_fields\nlayout:\n  resolution: 1080x1920\n")

    with pytest.raises(TemplateLoadError, match="Invalid template bad"):
        load_render_template("bad", tmp_path)


def test_load_render_template_invalid_yaml_syntax_raises(tmp_path):
    """Malformed YAML raises TemplateLoadError."""
    yaml_file = tmp_path / "broken.yaml"
    yaml_file.write_text("name: broken\n\tindentation: bad\n")

    with pytest.raises(TemplateLoadError, match="Invalid template broken"):
        load_render_template("broken", tmp_path)


def test_load_render_template_rejects_invalid_transition_type(tmp_path):
    """Unsupported transition type raises TemplateLoadError."""
    yaml_file = tmp_path / "bad_transition.yaml"
    yaml_file.write_text("name: bad_transition\ntype: test\ntransitions:\n  type: fdae\n")

    with pytest.raises(TemplateLoadError, match="Invalid template bad_transition"):
        load_render_template("bad_transition", tmp_path)
