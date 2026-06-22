"""Configuration loader — reads YAML configs + env vars into Pydantic models."""

from pathlib import Path

import yaml

from clipper_agency.config.schema import AppSettings, NicheConfig, TemplateConfig


def load_settings() -> AppSettings:
    """Load application settings from environment / .env file."""
    return AppSettings()  # type: ignore[call-arg]


def resolve_relax_gates(*sources: str) -> frozenset[str]:
    """Merge comma-separated gate-ID sources into a normalized frozenset.

    Each source is split on ``,``; tokens are stripped, uppercased; empties
    dropped; duplicates removed across all sources. Pure function — no side
    effects. Empty/whitespace-only sources contribute nothing.

    Example: ``resolve_relax_gates("g4, g5", "G10", "") -> frozenset({"G4", "G5", "G10"})``.
    """
    merged: set[str] = set()
    for source in sources:
        for token in (source or "").split(","):
            gate_id = token.strip().upper()
            if gate_id:
                merged.add(gate_id)
    return frozenset(merged)


def load_niche(niche_name: str, niches_dir: Path | None = None) -> NicheConfig:
    """Load a niche profile from YAML."""
    base = niches_dir or Path("niches")
    path = base / f"{niche_name}.yaml"
    if not path.exists():
        msg = f"Niche not found: {path}"
        raise FileNotFoundError(msg)
    with open(path) as f:
        data = yaml.safe_load(f)
    return NicheConfig(**data)


def load_template(template_name: str, templates_dir: Path | None = None) -> TemplateConfig:
    """Load a video template from YAML."""
    base = templates_dir or Path("templates")
    path = base / f"{template_name}.yaml"
    if not path.exists():
        msg = f"Template not found: {path}"
        raise FileNotFoundError(msg)
    with open(path) as f:
        data = yaml.safe_load(f)
    return TemplateConfig(**data)


def build_channel_description(niche: NicheConfig) -> str:
    """Build a human-readable channel identity string from niche config.

    Used to inject into agent prompts so they know what channel they write for,
    without hardcoding niche identity in prompt files.
    """
    language_map = {
        "id": "Indonesian",
        "en": "English",
    }
    language_name = language_map.get(niche.language, niche.language)

    # Convert content_angle like "trending_artist_update" to "trending artist update"
    angle = niche.content_angle.replace("_", " ")

    # Map tone to readable form
    tone_map = {
        "casual_tiktok": "casual TikTok",
        "professional": "professional",
        "casual": "casual",
    }
    tone_name = tone_map.get(niche.tone, niche.tone)

    return f"a {language_name} {angle} {tone_name} channel"


def get_language_name(niche: NicheConfig) -> str:
    """Return human-readable language name for a niche."""
    language_map = {"id": "Indonesian", "en": "English"}
    return language_map.get(niche.language, niche.language)


def get_tone_name(niche: NicheConfig) -> str:
    """Return human-readable tone description for a niche."""
    tone_map = {
        "casual_tiktok": "casual TikTok",
        "professional": "professional",
        "casual": "casual",
    }
    return tone_map.get(niche.tone, niche.tone)


def get_angle_name(niche: NicheConfig) -> str:
    """Return human-readable content angle for a niche."""
    return niche.content_angle.replace("_", " ")


def load_config(config_path: str | None = None) -> dict:
    """Legacy dict-based loader — delegates to structured loaders.

    Kept for backward compatibility with CLI stubs.
    """
    settings = load_settings()
    result: dict = settings.model_dump()
    if config_path:
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        result.update(user_config)
    return result


_SETTINGS_MODEL_MAP = {
    "safety": "safety_model",
    "segment_producer": "researcher_model",
    "scriptwriter": "scriptwriter_model",
    "visual_director": "visual_director_model",
    "reviewer": "reviewer_model",
}


def get_agent_config(agent_name: str) -> dict:
    """Resolve agent config: hierarchy preset → model metadata → .env overrides.

    Returns dict with keys: model, temperature, max_completion_tokens.
    """
    from clipper_agency.config.hierarchy import ConfigHierarchy
    from clipper_agency.config.model_cache import get_model_metadata

    hierarchy = ConfigHierarchy()
    model = hierarchy.get(agent_name, "model")
    temperature = hierarchy.get(agent_name, "temperature")

    # .env override for model
    settings = load_settings()
    settings_field = _SETTINGS_MODEL_MAP.get(agent_name)
    if settings_field:
        env_model = getattr(settings, settings_field, None)
        if env_model:
            model = env_model

    # Model metadata from cache
    max_completion_tokens = None
    if model:
        meta = get_model_metadata(model)
        if meta and meta.get("max_completion_tokens"):
            max_completion_tokens = meta["max_completion_tokens"]

    return {
        "model": model,
        "temperature": temperature if temperature is not None else 0.7,
        "max_completion_tokens": max_completion_tokens,
    }
