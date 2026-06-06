"""Shared path conventions for cache and output directory layout."""

import os
from pathlib import Path


def job_output_dir(output_dir: str | Path, job_id: int) -> str:
    """Base output directory for a job.

    Used by all agents to construct per-job file paths.
    Falls back to ``outputs`` when *output_dir* is empty.
    """
    base = str(output_dir) or "outputs"
    return f"{base}/job_{job_id}"


def job_cache_dir(assets_cache: str | Path, job_id: int) -> str:
    """Base intermediate artifact workspace for a job."""
    base = Path(assets_cache or "data/assets/cache")
    return str(base / f"job_{job_id}")


def ensure_job_cache_dir(assets_cache: str | Path, job_id: int) -> str:
    """Create and return the base intermediate artifact workspace."""
    path = Path(job_cache_dir(assets_cache, job_id))
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def job_final_output_dir(output_dir: str | Path, job_id: int) -> str:
    """Base final customer-ready output directory for a job."""
    base = Path(output_dir or "outputs")
    return str(base / f"job_{job_id}")


def agent_dir(assets_cache: str | Path, job_id: int, agent_name: str) -> str:
    """Directory for one agent's persisted input/output artifacts."""
    return str(Path(job_cache_dir(assets_cache, job_id)) / "agents" / agent_name)


def ensure_agent_dir(assets_cache: str | Path, job_id: int, agent_name: str) -> str:
    """Create and return one agent's artifact directory."""
    path = Path(agent_dir(assets_cache, job_id, agent_name))
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def agent_input_file(assets_cache: str | Path, job_id: int, agent_name: str) -> str:
    """Path to an agent's persisted input contract."""
    return str(Path(agent_dir(assets_cache, job_id, agent_name)) / "input.json")


def agent_output_file(assets_cache: str | Path, job_id: int, agent_name: str) -> str:
    """Path to an agent's persisted output contract."""
    return str(Path(agent_dir(assets_cache, job_id, agent_name)) / "output.json")


def gate_result_file(assets_cache: str | Path, job_id: int, gate_name: str) -> str:
    """Path to a persisted gate result."""
    return str(Path(job_cache_dir(assets_cache, job_id)) / "gates" / f"{gate_name}.json")


def segment_producer_brief_file(assets_cache: str | Path, job_id: int) -> str:
    """Path to the Segment Producer human-readable Markdown brief."""
    return str(Path(agent_dir(assets_cache, job_id, "segment_producer")) / "research_brief.md")


def segment_producer_contract_file(assets_cache: str | Path, job_id: int) -> str:
    """Path to the Segment Producer normalized machine-readable contract."""
    return str(Path(agent_dir(assets_cache, job_id, "segment_producer")) / "research_contract.json")


def voice_scene_file(assets_cache: str | Path, job_id: int, scene_id: int) -> str:
    """Path to one persisted voice scene artifact."""
    return str(
        Path(agent_dir(assets_cache, job_id, "voice_producer"))
        / "voices"
        / f"scene_{scene_id}.mp3"
    )


def visual_scene_file(assets_cache: str | Path, job_id: int, scene_id: int) -> str:
    """Path to one persisted visual scene artifact."""
    return str(
        Path(agent_dir(assets_cache, job_id, "visual_director"))
        / "scenes"
        / f"scene_{scene_id}.mp4"
    )


def research_cache_dir(output_dir: str | Path, job_id: int) -> str:
    """Cache directory for Researcher API responses and LLM synthesis."""
    return f"{job_output_dir(output_dir, job_id)}/research"


def scrapecreators_cache_file(output_dir: str | Path, job_id: int) -> str:
    """Cached structured ScrapeCreators search results (JSON)."""
    return f"{research_cache_dir(output_dir, job_id)}/scrapecreators.json"


def firecrawl_cache_file(output_dir: str | Path, job_id: int) -> str:
    """Cached Firecrawl search results (JSON)."""
    return f"{research_cache_dir(output_dir, job_id)}/firecrawl.json"


def research_brief_cache_file(output_dir: str | Path, job_id: int) -> str:
    """Cached LLM-synthesized research brief (JSON)."""
    return f"{research_cache_dir(output_dir, job_id)}/research_brief.json"


def ensure_research_cache_dir(output_dir: str | Path, job_id: int) -> str:
    """Create the research cache directory if it doesn't exist.

    Returns the cache directory path.
    """
    path = research_cache_dir(output_dir, job_id)
    os.makedirs(path, exist_ok=True)
    return path
