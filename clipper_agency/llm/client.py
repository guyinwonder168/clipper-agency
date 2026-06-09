"""OpenRouter API client for chat completions."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from clipper_agency.observability.llm_trace import LLMTraceWriter

logger = logging.getLogger(__name__)


class OpenRouterClient:
    """LLM client for OpenRouter API with multi-model support."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, trace_writer: LLMTraceWriter | None = None) -> None:
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.trace_writer = trace_writer

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_completion_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Returns:
            dict with keys: content, model, usage.
        """
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")

        total_input_chars = sum(
            len(m.get("content", "")) for m in messages
        )
        logger.debug(
            "LLM request: model=%s messages=%d input_chars=%d",
            model, len(messages), total_input_chars,
        )

        start = time.monotonic()
        with httpx.Client(base_url=self.BASE_URL, timeout=60) as client:
            resp = client.post(
                "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "reasoning_effort": "none",
                    **({"max_completion_tokens": max_completion_tokens} if max_completion_tokens is not None else {}),
                    **kwargs,
                },
            )
            elapsed = time.monotonic() - start

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                detail = resp.text[:1000]
                logger.error(
                    "LLM error: HTTP %d model=%s in %.1fs — %s",
                    resp.status_code, model, elapsed, detail,
                )
                raise httpx.HTTPStatusError(
                    f"{resp.status_code} - {detail[:500]}",
                    request=resp.request,
                    response=resp,
                )

            data = resp.json()
            usage = data.get("usage", {})
            logger.info(
                "LLM response: model=%s status=%d tokens_in=%s tokens_out=%s cost=$%.5f latency=%.1fs",
                model,
                resp.status_code,
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
                usage.get("total_tokens", 0) * 0.000001,  # approximate cost
                elapsed,
            )
            return {
                "content": data["choices"][0]["message"]["content"],
                "model": model,
                "usage": usage,
            }

    def chat_traced(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        job_id: int,
        agent: str,
        task: str,
        temperature: float = 0.7,
        max_completion_tokens: int | None = None,
        prompt_template_id: str = "",
        prompt_version: str = "",
        repair_cycle: int = 0,
    ) -> dict[str, Any]:
        """Send a traced chat completion request.

        Falls back to :meth:`chat` without tracing when no trace writer
        is configured.  Trace failures are caught and logged — they never
        prevent the LLM call from completing.
        """
        if self.trace_writer is None:
            return self.chat(
                model=model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )

        handle = self.trace_writer.start_call(
            job_id=job_id,
            agent=agent,
            task=task,
            provider="openrouter",
            model=model,
            prompt_template_id=prompt_template_id,
            prompt_version=prompt_version,
            retry_count=repair_cycle,
        )
        try:
            self.trace_writer.persist_request(
                handle,
                messages=messages,
                parameters={
                    "temperature": temperature,
                    "max_completion_tokens": max_completion_tokens,
                },
            )
        except Exception:
            logger.warning("Trace request persist failed for call %s", handle.call_id)

        result = self.chat(
            model=model,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
        )

        try:
            self.trace_writer.persist_response(
                handle,
                raw_response={"content": result["content"]},
                usage=result.get("usage", {}),
                provider_metadata={"model": result.get("model", model)},
            )
            logger.info("LLM trace persisted: %s", handle.trace_dir)
        except Exception:
            logger.warning("Trace response persist failed for call %s", handle.call_id)

        return result
