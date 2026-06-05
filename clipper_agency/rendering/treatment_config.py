"""YAML loader for treatment and transition definitions.

Exposes frozen dataclasses for immutable access to treatment/transition
configuration from templates/treatments.yaml.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

TEMPLATES_PATH = Path("templates/treatments.yaml")


@dataclass(frozen=True)
class TreatmentDef:
    """Immutable treatment definition."""

    name: str
    description: str
    target_fps: int
    default_duration: Optional[float]
    input_type: str
    ffmpeg_filter: Optional[str]


@dataclass(frozen=True)
class TransitionDef:
    """Immutable transition definition."""

    name: str
    description: str
    default_duration: float
    ffmpeg_filter: Optional[str]


class TreatmentConfig:
    """Load and validate treatment/transition definitions from YAML."""

    def __init__(self, path: Path = TEMPLATES_PATH) -> None:
        raw = yaml.safe_load(path.read_text())
        self._treatments = {
            name: TreatmentDef(
                name=name,
                description=td["description"],
                target_fps=td["target_fps"],
                default_duration=td.get("default_duration"),
                input_type=td["input_type"],
                ffmpeg_filter=td.get("ffmpeg_filter"),
            )
            for name, td in raw["treatments"].items()
        }
        self._transitions = {
            name: TransitionDef(
                name=name,
                description=td["description"],
                default_duration=td["default_duration"],
                ffmpeg_filter=td.get("ffmpeg_filter"),
            )
            for name, td in raw["transitions"].items()
        }
        self._fps_rules = raw.get("fps_rules", {})
        self._pacing_rules = raw.get("pacing_rules", {})

    def get_treatment(self, name: str) -> Optional[TreatmentDef]:
        """Return treatment definition by name, or None if not found."""
        return self._treatments.get(name)

    def get_transition(self, name: str) -> Optional[TransitionDef]:
        """Return transition definition by name, or None if not found."""
        return self._transitions.get(name)

    @property
    def target_fps(self) -> int:
        """Target FPS from fps_rules, defaults to 30."""
        return self._fps_rules.get("target_fps", 30)

    @property
    def pacing(self) -> dict:
        """Pacing rules dict (e.g. tiktok_standard profile)."""
        return self._pacing_rules

    @property
    def treatments(self) -> dict[str, TreatmentDef]:
        """All treatment definitions (copy for immutability)."""
        return dict(self._treatments)

    @property
    def transitions(self) -> dict[str, TransitionDef]:
        """All transition definitions (copy for immutability)."""
        return dict(self._transitions)
