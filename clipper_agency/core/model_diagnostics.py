"""Universal model-call diagnostic writer for all LLM/TTS providers."""

import json
from datetime import datetime, timezone
from pathlib import Path


def write_model_call_diagnostic(
    output_dir: str,
    agent: str,
    purpose: str,
    provider: str,
    model: str,
    input_payload: dict,
    raw_response: str | None,
    parsed_output: dict | None,
    usage: dict,
    estimated_cost_usd: float,
    latency_ms: int,
    retry_count: int,
    status: str,
    error: str | None,
) -> str:
    """Write a single JSON diagnostic file for a model call.

    Returns the path to the written file as a string.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{agent}_{purpose}_{ts}.json"

    diagnostic = {
        "agent": agent,
        "purpose": purpose,
        "provider": provider,
        "model": model,
        "input_payload": input_payload,
        "raw_response": raw_response,
        "parsed_output": parsed_output,
        "usage": usage,
        "estimated_cost_usd": estimated_cost_usd,
        "latency_ms": latency_ms,
        "retry_count": retry_count,
        "status": status,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    filepath = Path(output_dir) / filename
    filepath.write_text(json.dumps(diagnostic, indent=2))

    return str(filepath)
