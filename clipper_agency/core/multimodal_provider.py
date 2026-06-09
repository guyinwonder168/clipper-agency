"""Provider-independent multimodal inspection protocol and OpenRouter implementation.

Defines a ``MultimodalProvider`` protocol and a concrete
``OpenRouterMultimodalProvider`` that wraps the existing ``OpenRouterClient``
to perform semantic asset inspection via a multimodal LLM.

Pure helper functions are exposed for direct unit testing.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MultimodalProvider(Protocol):
    """Provider-independent interface for multimodal asset inspection."""

    def inspect_asset(
        self,
        beat: dict,
        frame_paths: list[str],
        ocr_regions: list[dict],
        source_metadata: dict,
    ) -> dict:
        """Inspect visual frames against a beat and return structured scores."""
        ...


# ---------------------------------------------------------------------------
# Pure helpers (no I/O, no side effects — fully testable)
# ---------------------------------------------------------------------------

_INSPECTION_QUESTIONS = """\
Answer these 6 questions with float scores (0.0–1.0) and a decision:

1. person_match: Is the visible person consistent with the subject of the claim?
2. event_match: Does the scene appear to show the same event described?
3. claim_support: Does the visual directly support the spoken claim?
4. misleading_risk: Could the visual mislead the audience? (higher = more risky)
5. source_credibility: Is the source text or logo dominant/credible?
6. visual_quality: Is the image quality acceptable for publication?
7. role_check: Is this evidence, context, or decoration?

Also provide:
- cleanliness_score (0–1): Is the frame free of distracting overlays?
- temporal_match (0–1): Does timing align with the narration?
- decision: "accept", "revise", or "reject"
- reason: One-sentence justification
"""


def build_inspection_prompt(
    beat: dict,
    ocr_text: str,
    source_metadata: dict,
) -> str:
    """Build the text prompt for multimodal asset inspection.

    Parameters
    ----------
    beat:
        Story beat dict with at least ``spoken_point`` and ``beat_id``.
    ocr_text:
        Concatenated OCR text detected in the frames.
    source_metadata:
        Metadata about the asset source (platform, url, etc.).
    """
    parts: list[str] = ["Inspect this visual asset against the narration beat."]

    spoken = beat.get("spoken_point", "")
    if spoken:
        parts.append(f"Spoken claim: {spoken}")

    beat_id = beat.get("beat_id", "")
    if beat_id:
        parts.append(f"Beat ID: {beat_id}")

    if ocr_text:
        parts.append(f"Detected text in frame: {ocr_text}")

    if source_metadata:
        src = source_metadata.get("source", "")
        url = source_metadata.get("url", "")
        if src:
            parts.append(f"Asset source platform: {src}")
        if url:
            parts.append(f"Asset URL: {url}")

    parts.append(_INSPECTION_QUESTIONS)
    parts.append(
        'Respond ONLY with a JSON object. Example:\n'
        '{"person_match":0.9,"event_match":0.8,"claim_support":0.7,'
        '"visual_quality":0.85,"temporal_match":0.75,'
        '"source_credibility":0.8,"cleanliness_score":0.6,'
        '"misleading_risk":0.1,"decision":"accept","reason":"Good match"}'
    )
    return "\n\n".join(parts)


def encode_image_as_data_uri(image_path: str) -> str:
    """Read a local image file and return a base64 data URI.

    Raises ``FileNotFoundError`` if the file does not exist.
    """
    with open(image_path, "rb") as f:
        data = f.read()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def parse_inspection_response(raw_content: str) -> dict:
    """Extract JSON from an LLM response (possibly markdown-wrapped).

    Returns a dict with float scores bounded to 0-1.
    On malformed input returns ``{"decision": "error", "reason": ...}``.
    """
    text = raw_content.strip()
    if not text:
        return {"decision": "error", "reason": "Empty response from LLM"}

    # Try to extract JSON from markdown code fences first
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"decision": "error", "reason": f"JSON parse error: {exc}"}

    if not isinstance(parsed, dict):
        return {"decision": "error", "reason": "Response is not a JSON object"}

    # Bound float scores to [0.0, 1.0]
    _SCORE_KEYS = {
        "person_match", "event_match", "claim_support", "visual_quality",
        "temporal_match", "source_credibility", "cleanliness_score",
        "misleading_risk",
    }
    for key in _SCORE_KEYS:
        if key in parsed:
            parsed[key] = max(0.0, min(1.0, float(parsed[key])))

    return parsed


# ---------------------------------------------------------------------------
# Concrete implementation
# ---------------------------------------------------------------------------


class OpenRouterMultimodalProvider:
    """Multimodal asset inspection via OpenRouter LLM.

    Parameters
    ----------
    client:
        An object with a ``.chat(model, messages, **kwargs)`` method
        returning ``{"content": str, "model": str, "usage": dict}``.
    model:
        Multimodal model identifier for OpenRouter.
    max_retries:
        Number of retry attempts on transient failures.
    timeout_sec:
        Total budget (seconds) for the inspect call including retries.
    """

    def __init__(
        self,
        client: Any,
        model: str = "google/gemini-2.5-flash",
        max_retries: int = 2,
        timeout_sec: float = 30.0,
    ) -> None:
        self._client = client
        self._model = model
        self._max_retries = max_retries
        self._timeout_sec = timeout_sec

    def inspect_asset(
        self,
        beat: dict,
        frame_paths: list[str],
        ocr_regions: list[dict],
        source_metadata: dict,
    ) -> dict:
        """Inspect frames against a beat using the multimodal LLM.

        Returns a dict compatible with ``AssetSemanticInspection`` fields,
        or ``{"decision": "error", "reason": ...}`` on failure.
        """
        messages = self._build_messages(beat, frame_paths, ocr_regions, source_metadata)
        raw_response = self._call_with_retries(messages)

        if raw_response is None:
            return self._error_result(beat, frame_paths, "All retry attempts failed")

        parsed = parse_inspection_response(raw_response["content"])
        return self._success_result(beat, frame_paths, source_metadata, parsed, raw_response)

    @staticmethod
    def _build_messages(
        beat: dict,
        frame_paths: list[str],
        ocr_regions: list[dict],
        source_metadata: dict,
    ) -> list[dict]:
        """Build the multimodal user message with text + image parts."""
        ocr_text = " | ".join(
            r.get("text", "") for r in ocr_regions if r.get("text")
        )
        prompt_text = build_inspection_prompt(beat, ocr_text, source_metadata)

        content_parts: list[dict[str, Any]] = [
            {"type": "text", "text": prompt_text},
        ]
        for path in frame_paths:
            try:
                uri = encode_image_as_data_uri(path)
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": uri},
                })
            except FileNotFoundError:
                logger.warning("Frame file not found, skipping: %s", path)

        return [{"role": "user", "content": content_parts}]

    def _error_result(
        self,
        beat: dict,
        frame_paths: list[str],
        reason: str,
    ) -> dict:
        """Return a standardized error dict."""
        return {
            "asset_id": "",
            "beat_id": str(beat.get("beat_id", "")),
            "decision": "error",
            "reason": reason,
            "frame_paths": frame_paths,
            "model": self._model,
            "person_match": 0.0,
            "event_match": 0.0,
            "claim_support": 0.0,
            "visual_quality": 0.0,
            "temporal_match": 0.0,
            "source_credibility": 0.0,
            "cleanliness_score": 0.0,
            "misleading_risk": 0.0,
        }

    @staticmethod
    def _success_result(
        beat: dict,
        frame_paths: list[str],
        source_metadata: dict,
        parsed: dict,
        raw_response: dict,
    ) -> dict:
        """Map parsed LLM output into AssetSemanticInspection-compatible dict."""
        return {
            "asset_id": source_metadata.get("asset_id", ""),
            "beat_id": str(beat.get("beat_id", "")),
            "person_match": parsed.get("person_match", 0.0),
            "event_match": parsed.get("event_match", 0.0),
            "claim_support": parsed.get("claim_support", 0.0),
            "visual_quality": parsed.get("visual_quality", 0.0),
            "temporal_match": parsed.get("temporal_match", 0.0),
            "source_credibility": parsed.get("source_credibility", 0.0),
            "cleanliness_score": parsed.get("cleanliness_score", 0.0),
            "misleading_risk": parsed.get("misleading_risk", 0.0),
            "decision": parsed.get("decision", "error"),
            "reason": parsed.get("reason", ""),
            "frame_paths": frame_paths,
            "model": raw_response.get("model", ""),
        }

    def _call_with_retries(
        self,
        messages: list[dict],
    ) -> dict[str, Any] | None:
        """Call the LLM client with exponential backoff retries."""
        deadline = time.monotonic() + self._timeout_sec
        last_exc: Exception | None = None

        for attempt in range(1 + self._max_retries):
            if time.monotonic() > deadline:
                logger.warning("Timeout budget exceeded before attempt %d", attempt + 1)
                break
            try:
                return self._client.chat(
                    model=self._model,
                    messages=messages,
                    temperature=0.2,
                )
            except Exception as exc:
                last_exc = exc
                logger.debug("LLM call failed (attempt %d): %s", attempt + 1, exc)
                if attempt < self._max_retries:
                    backoff = 0.5 * (2 ** attempt)
                    time.sleep(min(backoff, 5.0))

        if last_exc is not None:
            logger.error("All retries exhausted: %s", last_exc)
        return None
