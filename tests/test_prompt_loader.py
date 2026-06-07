"""Tests for agent prompt file loading."""

from clipper_agency.agents.prompts import load_prompt


def test_load_prompt_returns_file_content_from_prompt_dir(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "safety.md").write_text("Prompt from file\n", encoding="utf-8")

    result = load_prompt("safety", fallback="Fallback prompt", prompts_dir=prompts_dir)

    assert result == "Prompt from file"


def test_load_prompt_returns_fallback_when_file_missing(tmp_path):
    result = load_prompt("safety", fallback="Fallback prompt", prompts_dir=tmp_path)

    assert result == "Fallback prompt"


def test_load_prompt_returns_fallback_when_file_empty(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "safety.md").write_text("\n", encoding="utf-8")

    result = load_prompt("safety", fallback="Fallback prompt", prompts_dir=prompts_dir)

    assert result == "Fallback prompt"


def test_segment_producer_prompt_has_channel_description_placeholder():
    """segment_producer.md must contain {channel_description} placeholder."""
    from clipper_agency.agents.prompts import PROMPTS_DIR
    content = (PROMPTS_DIR / "segment_producer.md").read_text()
    assert "{channel_description}" in content


def test_scriptwriter_prompt_has_channel_description_placeholder():
    """scriptwriter.md must contain {channel_description} placeholder."""
    from clipper_agency.agents.prompts import PROMPTS_DIR
    content = (PROMPTS_DIR / "scriptwriter.md").read_text()
    assert "{channel_description}" in content


def test_no_hardcoded_niche_in_prompt_files():
    """No prompt file should contain 'Indonesian artist infotainment'."""
    from clipper_agency.agents.prompts import PROMPTS_DIR
    for md_file in PROMPTS_DIR.glob("*.md"):
        content = md_file.read_text()
        assert "Indonesian artist infotainment" not in content, (
            f"{md_file.name} still contains hardcoded niche text"
        )
