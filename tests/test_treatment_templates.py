"""Tests for treatment template definitions."""
import pytest
import yaml
from pathlib import Path

TEMPLATES_PATH = Path("templates/treatments.yaml")


class TestTreatmentTemplates:
    def test_treatments_file_exists(self):
        assert TEMPLATES_PATH.is_file(), "templates/treatments.yaml must exist"

    def test_treatments_is_valid_yaml(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        assert isinstance(data, dict)
        assert "treatments" in data

    def test_required_treatments_defined(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        treatments = data["treatments"]
        required = [
            "ken_burns_zoom_in",
            "ken_burns_pan_left",
            "lower_third_slide",
            "text_card_reveal",
            "cinematic_crop",
            "fade_to_black",
            "hook_big_caption",
        ]
        for name in required:
            assert name in treatments, f"Missing treatment: {name}"

    def test_each_treatment_has_required_fields(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        for name, treatment in data["treatments"].items():
            assert "description" in treatment, f"{name} missing description"
            assert "target_fps" in treatment, f"{name} missing target_fps"
            assert "default_duration" in treatment, f"{name} missing default_duration"
            assert "input_type" in treatment, f"{name} missing input_type"
            assert treatment["input_type"] in ("image", "video", "text", "any")
            assert treatment["target_fps"] == 30, f"{name} target_fps must be 30"

    def test_transitions_defined(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        assert "transitions" in data
        transitions = data["transitions"]
        required = ["crossfade", "hard_cut", "wipe_left"]
        for name in required:
            assert name in transitions, f"Missing transition: {name}"

    def test_fps_rules_defined(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        assert "fps_rules" in data
        assert data["fps_rules"]["target_fps"] == 30

    def test_pacing_rules_defined(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        assert "pacing_rules" in data
        assert "tiktok_standard" in data["pacing_rules"]

    def test_xfade_transitions_have_duration_and_offset_vars(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        for name, transition in data["transitions"].items():
            filt = transition.get("ffmpeg_filter")
            if filt is None:
                continue
            assert "{duration}" in filt, (
                f"Transition '{name}' filter missing {{duration}} var"
            )
            assert "{offset}" in filt, (
                f"Transition '{name}' filter missing {{offset}} var"
            )

    def test_image_treatments_use_zoompan(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        for name, treatment in data["treatments"].items():
            if treatment.get("input_type") != "image":
                continue
            filt = treatment.get("ffmpeg_filter")
            assert filt is not None, f"Image treatment '{name}' missing ffmpeg_filter"
            assert "zoompan" in filt, f"Image treatment '{name}' must use zoompan"

    def test_fps_rules_has_target_fps(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        fps = data["fps_rules"]
        assert fps["target_fps"] == 30
        assert isinstance(fps["rules"], list)
        assert len(fps["rules"]) >= 3, "fps_rules.rules must have at least 3 items"

    def test_pacing_rules_have_hook_window(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        profiles = data["pacing_rules"]
        has_hook = False
        for _name, profile in profiles.items():
            if "hook_window_seconds" in profile:
                val = profile["hook_window_seconds"]
                assert val > 0, "hook_window_seconds must be positive"
                has_hook = True
        assert has_hook, "At least one pacing profile must define hook_window_seconds"
