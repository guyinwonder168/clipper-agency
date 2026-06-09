"""Redaction helpers for persisted observability artifacts."""

from collections.abc import Mapping
from typing import Any


REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "set-cookie",
    "x-api-key",
}


def redact_trace_payload(payload: Any) -> Any:
    """Return a copy of payload with configured secret-bearing fields redacted."""

    if isinstance(payload, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(str(key)) else redact_trace_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_trace_payload(item) for item in payload]
    return payload


def _is_sensitive_key(key: str) -> bool:
    return key.lower().replace("-", "_") in {item.replace("-", "_") for item in SENSITIVE_KEYS}
