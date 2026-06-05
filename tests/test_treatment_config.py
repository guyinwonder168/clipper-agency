"""Tests for TreatmentConfig YAML loader — frozen dataclasses for treatments and transitions."""
from pathlib import Path

import pytest

from clipper_agency.rendering.treatment_config import TreatmentConfig, TreatmentDef, TransitionDef

TEMPLATES_PATH = Path("templates/treatments.yaml")


@pytest.fixture
def config():
    """Load treatment config from the project YAML file."""
    return TreatmentConfig(TEMPLATES_PATH)


class TestTreatmentConfig:
    def test_loads_all_treatments(self, config):
        """Config loads at least 7 treatment definitions from YAML."""
        treatments = config.treatments
        assert len(treatments) >= 7

    def test_get_treatment_returns_frozen_dataclass(self, config):
        """get_treatment returns a TreatmentDef with correct field values."""
        td = config.get_treatment("ken_burns_zoom_in")
        assert td is not None
        assert isinstance(td, TreatmentDef)
        assert td.name == "ken_burns_zoom_in"
        assert td.target_fps == 30
        assert td.default_duration == 5.0
        assert td.input_type == "image"
        assert td.ffmpeg_filter is not None
        assert "zoompan" in td.ffmpeg_filter

    def test_get_treatment_null_filter(self, config):
        """broll_standard has ffmpeg_filter=None (pass-through treatment)."""
        td = config.get_treatment("broll_standard")
        assert td is not None
        assert td.ffmpeg_filter is None

    def test_get_transition_returns_definition(self, config):
        """get_transition returns a TransitionDef for crossfade."""
        tr = config.get_transition("crossfade")
        assert tr is not None
        assert isinstance(tr, TransitionDef)
        assert tr.name == "crossfade"
        assert tr.default_duration == 0.3
        assert tr.ffmpeg_filter is not None

    def test_get_transition_hard_cut_null_filter(self, config):
        """hard_cut transition has ffmpeg_filter=None (instant cut)."""
        tr = config.get_transition("hard_cut")
        assert tr is not None
        assert tr.ffmpeg_filter is None

    def test_get_treatment_unknown_returns_none(self, config):
        """get_treatment for nonexistent name returns None."""
        assert config.get_treatment("nonexistent") is None

    def test_get_transition_unknown_returns_none(self, config):
        """get_transition for nonexistent name returns None."""
        assert config.get_transition("nonexistent") is None

    def test_target_fps_from_rules(self, config):
        """target_fps property reads from fps_rules in YAML."""
        assert config.target_fps == 30

    def test_pacing_rules_accessible(self, config):
        """pacing property exposes pacing_rules dict from YAML."""
        assert "tiktok_standard" in config.pacing
