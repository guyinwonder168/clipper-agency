"""Config hierarchy: Agent → Niche → Account → Job override resolution."""

from typing import Any


class AgentDefaults:
    """Default LLM/model settings per agent."""

    PRESETS = {
        # Canonical OpenRouter slugs: vendor/model. Bare slugs (e.g. "mimo-v2-flash")
        # 404 with "No endpoints found"; removed models (e.g. "xiaomi/mimo-v2-flash")
        # return deprecation errors mid-pipeline. Startup preflight validates these
        # against the live catalog (see config/preflight.py).
        "budget_east": {
            "safety": {"model": "z-ai/glm-4.7-flash", "temperature": 0.1},
            "segment_producer": {"model": "xiaomi/mimo-v2.5", "temperature": 0.3},
            "scriptwriter": {"model": "qwen/qwen3-32b", "temperature": 0.7},
            "voice_producer": {"model": None},
            "visual_director": {"model": "xiaomi/mimo-v2.5", "temperature": 0.5},
            "composer": {"model": None},
            "reviewer": {"model": "google/gemini-2.5-flash", "temperature": 0.2},
        }
    }

    def __init__(self, preset: str = "budget_east") -> None:
        self.agents = dict(self.PRESETS[preset])


class ConfigHierarchy:
    """Agent → Niche → Account → Job config overrides."""

    def __init__(self, preset: str = "budget_east") -> None:
        self._defaults = AgentDefaults(preset).agents
        self._niche_overrides: dict[str, dict[str, Any]] = {}
        self._account_overrides: dict[str, dict[str, Any]] = {}
        self._job_overrides: dict[str, dict[str, Any]] = {}

    def set_niche_override(self, agent: str, key: str, value: Any) -> None:
        self._niche_overrides.setdefault(agent, {})[key] = value

    def set_account_override(self, agent: str, key: str, value: Any) -> None:
        self._account_overrides.setdefault(agent, {})[key] = value

    def set_job_override(self, agent: str, key: str, value: Any) -> None:
        self._job_overrides.setdefault(agent, {})[key] = value

    def get(self, agent: str, key: str) -> Any:
        """Resolve config value through hierarchy: job > account > niche > default."""
        if agent in self._job_overrides and key in self._job_overrides[agent]:
            return self._job_overrides[agent][key]
        if agent in self._account_overrides and key in self._account_overrides[agent]:
            return self._account_overrides[agent][key]
        if agent in self._niche_overrides and key in self._niche_overrides[agent]:
            return self._niche_overrides[agent][key]
        return self._defaults.get(agent, {}).get(key)
