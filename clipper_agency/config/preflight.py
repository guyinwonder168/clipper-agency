"""Startup preflight — validate resolved agent models against the OpenRouter catalog.

Runs before the pipeline starts so a bad model slug (bare name, deprecated, or
removed from the catalog) fails fast with a clear error instead of surfacing as
a mid-pipeline 404 after research credits have already been spent. This was the
root cause of job_9 (bare ``mimo-v2-flash`` → 404 "No endpoints found") and
job_11 (``xiaomi/mimo-v2-flash`` removed → deprecation error).
"""

import logging

from clipper_agency.config.loader import _SETTINGS_MODEL_MAP, get_agent_config
from clipper_agency.config.model_cache import list_catalog_models, refresh_model_cache

logger = logging.getLogger(__name__)


def preflight_agent_models() -> list[tuple[str, str]]:
    """Validate every resolved agent model against the live OpenRouter catalog.

    Force-refreshes the model cache first (best-effort — ``refresh_model_cache``
    swallows network errors, so offline we degrade to whatever cache is on disk).
    Then resolves each LLM-backed agent's model and confirms it is a key in the
    catalog.

    Fail-fast policy:
    - A model missing from a *populated* catalog raises ``RuntimeError`` — better
      to abort before billing research credits than hit a mid-pipeline 404.
    - When no catalog is available (refresh failed and nothing cached) we cannot
      distinguish "not in catalog" from "no catalog", so we log a warning and
      continue rather than block every offline run.

    Returns:
        ``(agent_name, model)`` tuples for every LLM-backed agent (model set).
    """
    refresh_model_cache(force=True)
    catalog = list_catalog_models()

    validated: list[tuple[str, str]] = []
    unresolved: list[str] = []

    for agent_name in _SETTINGS_MODEL_MAP:
        model = get_agent_config(agent_name).get("model")
        if not model:
            continue  # voice_producer / composer have no LLM model
        validated.append((agent_name, model))
        if model not in catalog:
            unresolved.append(f"{agent_name}={model!r}")

    if not unresolved:
        return validated

    if catalog:
        msg = (
            "Agent model preflight failed — not in the OpenRouter catalog: "
            + ", ".join(unresolved)
            + ". Use a canonical 'vendor/model' slug in hierarchy.py or the *_MODEL env vars."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    logger.warning(
        "Agent model preflight could not reach the OpenRouter catalog and no "
        "cache is available; skipping slug validation. Could not resolve: %s",
        ", ".join(unresolved),
    )
    return validated
