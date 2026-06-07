"""Tests for Visual Director prompt — must contain video production knowledge."""

from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt


class TestVisualDirectorPrompt:
    """Verify the visual director prompt embeds video production expertise."""

    def _load(self) -> str:
        return load_prompt("visual_director", "", PROMPTS_DIR)

    def test_prompt_loads_without_error(self):
        text = self._load()
        assert len(text) > 200

    def test_prompt_contains_fps_rules(self):
        text = self._load()
        assert "30fps" in text
        assert "framerate" in text.lower()

    def test_prompt_contains_treatment_knowledge(self):
        text = self._load()
        assert "ken_burns" in text or "zoompan" in text
        assert "treatment" in text.lower()

    def test_prompt_contains_transition_knowledge(self):
        text = self._load()
        assert "transition" in text.lower()
        assert "crossfade" in text

    def test_prompt_contains_pacing_rules(self):
        text = self._load()
        assert "pacing" in text.lower() or "2-5" in text or "attention" in text.lower()

    def test_prompt_output_includes_treatment_field(self):
        text = self._load()
        assert '"treatment"' in text

    def test_prompt_output_includes_duration_field(self):
        text = self._load()
        assert '"target_duration"' in text

    def test_prompt_output_includes_transition_field(self):
        text = self._load()
        assert '"transition_in"' in text

    def test_prompt_contains_beat_driven_instructions(self):
        """Beat-driven mode instructions present in prompt."""
        text = self._load()
        assert "beat_driven" in text.lower()
        assert "story_beats" in text.lower()

    def test_prompt_contains_visual_hierarchy(self):
        """Visual selection hierarchy documented in prompt."""
        text = self._load()
        assert "asset_candidates" in text.lower()
        assert "visual_must_show" in text.lower()
        assert "visual_must_not_show" in text.lower()

    def test_prompt_contains_do_not_use_rule(self):
        text = self._load()
        assert "do_not_use" in text.lower()

    def test_prompt_contains_beat_role_guidance(self):
        text = self._load()
        assert "hook" in text.lower()
        assert "closing_cta" in text.lower()

    def test_prompt_contains_duration_from_timestamps_rule(self):
        text = self._load()
        assert "duration_sec" in text or "timestamps" in text.lower()
