"""Universal model-call diagnostic writer for all LLM/TTS providers."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ModelCallDiagnostic:
    """Diagnostic data for a single LLM/TTS model call."""

    provider: str
    model: str
    input_payload: dict
    raw_response: str | None
    parsed_output: dict | None
    usage: dict
    estimated_cost_usd: float
    latency_ms: int
    retry_count: int
    status: str
    error: str | None


def write_model_call_diagnostic(
    output_dir: str,
    agent: str,
    purpose: str,
    diagnostic: ModelCallDiagnostic,
) -> str:
    """Write a single JSON diagnostic file for a model call.

    Returns the path to the written file as a string.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{agent}_{purpose}_{ts}.json"

    record = {
        "agent": agent,
        "purpose": purpose,
        **asdict(diagnostic),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    filepath = Path(output_dir) / filename
    filepath.write_text(json.dumps(record, indent=2))

    return str(filepath)
