"""OpenRouter API client for chat completions."""

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OpenRouterClient:
    """LLM client for OpenRouter API with multi-model support."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENROUTER_API_KEY")

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
