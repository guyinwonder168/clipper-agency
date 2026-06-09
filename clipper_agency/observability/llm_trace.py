"""Structured LLM trace artifact contracts and writer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from clipper_agency.observability.redaction import redact_trace_payload


class LLMTraceMetadata(BaseModel):
    """Operational metadata for a single LLM or multimodal model call."""

    call_id: str
    job_id: int
    agent: str
    task: str
    provider: str
    model: str
    prompt_template_id: str
    prompt_version: str
    request_timestamp: str
    response_timestamp: str | None
    provider_request_id: str | None
    retry_count: int
    latency_sec: float | None
    tokens_in: int | None
    tokens_out: int | None
    cost: float | None
    finish_reason: str | None
    parse_status: str
    schema_validation_status: str


@dataclass(frozen=True)
class TraceHandle:
    """Filesystem handle for a single trace call directory."""

    call_id: str
    trace_dir: Path
    metadata: LLMTraceMetadata


class LLMTraceWriter:
    """Persist structured LLM trace artifacts under the job cache directory."""

    def __init__(self, cache_root: str | Path, redact_secrets: bool = True) -> None:
        self.cache_root = Path(cache_root)
        self.redact_secrets = redact_secrets

    def start_call(
        self,
        *,
        job_id: int,
        agent: str,
        task: str,
        provider: str,
        model: str,
        prompt_template_id: str,
        prompt_version: str,
        retry_count: int = 0,
        call_id: str | None = None,
    ) -> TraceHandle:
        resolved_call_id = call_id or uuid4().hex
        trace_dir = self.cache_root / f"job_{job_id}" / "llm_traces" / agent / resolved_call_id
        metadata = LLMTraceMetadata(
            call_id=resolved_call_id,
            job_id=job_id,
            agent=agent,
            task=task,
            provider=provider,
            model=model,
            prompt_template_id=prompt_template_id,
            prompt_version=prompt_version,
            request_timestamp=_utc_timestamp(),
            response_timestamp=None,
            provider_request_id=None,
            retry_count=retry_count,
            latency_sec=None,
            tokens_in=None,
            tokens_out=None,
            cost=None,
            finish_reason=None,
            parse_status="pending",
            schema_validation_status="pending",
        )
        handle = TraceHandle(call_id=resolved_call_id, trace_dir=trace_dir, metadata=metadata)
        self._write_json(handle, "metadata.json", metadata.model_dump())
        return handle

    def persist_request(
        self,
        handle: TraceHandle,
        messages: list[dict],
        parameters: dict,
        image_manifest: dict | None = None,
    ) -> Path:
        payload = {
            "agent": handle.metadata.agent,
            "task": handle.metadata.task,
            "model": handle.metadata.model,
            "provider": handle.metadata.provider,
            "prompt_template_id": handle.metadata.prompt_template_id,
            "prompt_version": handle.metadata.prompt_version,
            "messages": messages,
            "parameters": parameters,
            "image_manifest": image_manifest,
            "request_timestamp": handle.metadata.request_timestamp,
            "call_id": handle.call_id,
            "job_id": handle.metadata.job_id,
        }
        return self._write_json(handle, "request.json", payload)

    def persist_response(
        self,
        handle: TraceHandle,
        raw_response: dict,
        usage: dict,
        provider_metadata: dict,
    ) -> Path:
        payload = {
            "raw_response": raw_response,
            "usage": usage,
            "provider_metadata": provider_metadata,
            "response_timestamp": _utc_timestamp(),
        }
        return self._write_json(handle, "response.json", payload)

    def persist_parsed_response(self, handle: TraceHandle, parsed_result: dict) -> Path:
        return self._write_json(handle, "parsed_response.json", {"parsed_result": parsed_result})

    def persist_validation(self, handle: TraceHandle, validation_result: dict) -> Path:
        return self._write_json(handle, "validation.json", {"validation_result": validation_result})

    def _write_json(self, handle: TraceHandle, filename: str, payload: dict) -> Path:
        handle.trace_dir.mkdir(parents=True, exist_ok=True)
        path = handle.trace_dir / filename
        persisted_payload = redact_trace_payload(payload) if self.redact_secrets else payload
        path.write_text(json.dumps(persisted_payload, indent=2, sort_keys=True), encoding="utf-8")
        return path


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()
