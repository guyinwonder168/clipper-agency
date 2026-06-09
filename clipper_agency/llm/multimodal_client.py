"""High-level multimodal visual inspection client wrapping OpenRouterClient.

Wraps the existing ``OpenRouterClient`` to perform semantic visual asset
inspection against story beats using a multimodal LLM (e.g. Gemini 2.5 Flash).

Pure functions for prompt construction and response parsing are exposed for
direct unit testing.  The ``MultimodalInspectionClient`` class handles the
orchestration of prompt → LLM call → parse.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCORE_KEYS: frozenset[str] = frozenset({
    "person_match", "event_match", "claim_support", "visual_quality",
    "temporal_match", "source_credibility", "cleanliness_score",
    "misleading_risk",
})

_SYSTEM_PROMPT = (
    "You are a visual evidence inspector for a short-form video production pipeline. "
    "Your job is to examine video frames against a narration beat and determine "
    "whether the visual evidence supports the spoken claim. "
    "You must respond with a structured JSON assessment."
)

_INSPECTION_FIELDS = (
    "Respond with a JSON object containing these fields:\n"
    "- person_match (0-1): Is the visible person consistent with the subject?\n"
    "- event_match (0-1): Does the scene show the described event?\n"
    "- claim_support (0-1): Does the visual directly support the claim?\n"
    "- visual_quality (0-1): Is image quality acceptable for publication?\n"
    "- temporal_match (0-1): Does timing align with narration?\n"
    "- source_credibility (0-1): Is the source text/logo credible?\n"
    "- cleanliness_score (0-1): Is the frame free of distracting overlays?\n"
    "- misleading_risk (0-1): Could the visual mislead the audience?\n"
    "- decision: one of \"accept\", \"revise\", or \"reject\"\n"
    "- reason: one-sentence justification"
)


# ---------------------------------------------------------------------------
# Pure functions — no I/O, no side effects
# ---------------------------------------------------------------------------


def build_visual_inspection_messages(
    beat: dict,
    frame_paths: list[str],
    ocr_text: str = "",
    source_metadata: dict | None = None,
    max_frames: int = 4,
) -> list[dict[str, Any]]:
    """Build multimodal messages for visual asset inspection.

    Returns a list of messages (system + user) with up to *max_frames*
    images encoded as base64 data URIs in the user message content parts.
    """
    user_parts: list[dict[str, str]] = []

    # Beat claim
    spoken = beat.get("spoken_point", "")
    if spoken:
        user_parts.append({"type": "text", "text": f"Spoken claim: {spoken}"})

    # Evidence contract — visual_must_show
    must_show = beat.get("visual_must_show", "")
    if must_show:
        user_parts.append({"type": "text", "text": f"Visual must show: {must_show}"})

    # Evidence contract — visual_must_not_show
    must_not = beat.get("visual_must_not_show", "")
    if must_not:
        user_parts.append({"type": "text", "text": f"Visual must NOT show: {must_not}"})

    # OCR text
    if ocr_text:
        user_parts.append({"type": "text", "text": f"Detected text in frame: {ocr_text}"})

    # Source description
    if source_metadata:
        src = source_metadata.get("source", "")
        url = source_metadata.get("url", "")
        if src:
            user_parts.append({"type": "text", "text": f"Asset source: {src}"})
        if url:
            user_parts.append({"type": "text", "text": f"Asset URL: {url}"})

    # Inspection instructions
    user_parts.append({"type": "text", "text": _INSPECTION_FIELDS})
    user_parts.append({
        "type": "text",
        "text": 'Example response:\n{"person_match":0.9,"event_match":0.8,'
                '"claim_support":0.7,"visual_quality":0.85,'
                '"temporal_match":0.75,"source_credibility":0.8,'
                '"cleanliness_score":0.6,"misleading_risk":0.1,'
                '"decision":"accept","reason":"Good match"}',
    })

    # Images — cap at max_frames
    capped = frame_paths[:max_frames]
    for path in capped:
        try:
            uri = _encode_image(path)
            user_parts.append({
                "type": "image_url",
                "image_url": {"url": uri},
            })
        except FileNotFoundError:
            logger.warning("Frame file not found, skipping: %s", path)

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_parts},
    ]


def _encode_image(image_path: str) -> str:
    """Read a local image file and return a base64 data URI."""
    with open(image_path, "rb") as f:
        data = f.read()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def parse_inspection_json(raw_content: str) -> dict[str, Any]:
    """Parse LLM response JSON, bound scores, and determine decision.

    Strips markdown code fences, bounds all float scores to [0.0, 1.0],
    fills missing fields with defaults, and returns a complete dict.

    On parse failure returns ``{"decision": "error", "reason": ...}``.
    """
    text = raw_content.strip()
    if not text:
        return {"decision": "error", "reason": "Empty response from LLM"}

    # Strip markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"decision": "error", "reason": f"JSON parse error: {exc}"}

    if not isinstance(parsed, dict):
        return {"decision": "error", "reason": "Response is not a JSON object"}

    # Fill defaults
    result: dict[str, Any] = {"reason": ""}
    result.update(parsed)

    # Bound float scores
    for key in _SCORE_KEYS:
        if key in result:
            result[key] = max(0.0, min(1.0, float(result[key])))
        else:
            result[key] = 0.0

    # Ensure decision is valid
    if result.get("decision") not in ("accept", "revise", "reject"):
        claim = result.get("claim_support", 0.0)
        misleading = result.get("misleading_risk", 0.0)
        if claim >= 0.70 and misleading <= 0.30:
            result["decision"] = "accept"
        elif claim < 0.40 or misleading > 0.60:
            result["decision"] = "reject"
        else:
            result["decision"] = "revise"

    return result


# ---------------------------------------------------------------------------
# Client class
# ---------------------------------------------------------------------------


class MultimodalInspectionClient:
    """High-level multimodal visual inspection client.

    Wraps an existing ``OpenRouterClient`` to perform asset inspection
    against story beats using a multimodal LLM.

    Parameters
    ----------
    client:
        An ``OpenRouterClient`` instance (or any object with a
        ``.chat(model, messages, temperature, **kwargs)`` method).
    model:
        Multimodal model identifier for OpenRouter.
    max_frames:
        Maximum number of frames to include per inspection request.
    """

    def __init__(
        self,
        client: Any,
        model: str = "google/gemini-2.5-flash",
        max_frames: int = 4,
    ) -> None:
        self._client = client
        self._model = model
        self._max_frames = max_frames

    def inspect_asset(
        self,
        job_id: int,
        beat_id: str,
        asset_id: str,
        beat: dict,
        frame_paths: list[str],
        ocr_text: str = "",
        source_metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Inspect visual frames against a narration beat.

        Returns a dict containing all ``AssetSemanticInspection`` fields.
        On failure returns a dict with ``decision="error"``.
        """
        logger.info(
            "Inspection started: job=%s beat=%s asset=%s frames=%d",
            job_id, beat_id, asset_id, len(frame_paths),
        )

        try:
            messages = build_visual_inspection_messages(
                beat=beat,
                frame_paths=frame_paths,
                ocr_text=ocr_text,
                source_metadata=source_metadata or {},
                max_frames=self._max_frames,
            )
            raw = self._client.chat(
                model=self._model,
                messages=messages,
                temperature=0.2,
            )
            parsed = parse_inspection_json(raw["content"])

            result = self._build_result(
                asset_id=asset_id,
                beat_id=beat_id,
                frame_paths=frame_paths,
                parsed=parsed,
                model=raw.get("model", self._model),
            )

            logger.info(
                "Inspection completed: job=%s beat=%s asset=%s decision=%s "
                "claim_support=%.2f misleading_risk=%.2f",
                job_id, beat_id, asset_id, result["decision"],
                result["claim_support"], result["misleading_risk"],
            )
            return result

        except Exception as exc:
            logger.error(
                "Inspection failed: job=%s beat=%s asset=%s error=%s",
                job_id, beat_id, asset_id, exc,
            )
            return self._error_result(
                asset_id=asset_id,
                beat_id=beat_id,
                frame_paths=frame_paths,
                reason=str(exc),
            )

    @staticmethod
    def _build_result(
        asset_id: str,
        beat_id: str,
        frame_paths: list[str],
        parsed: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        """Map parsed LLM output into AssetSemanticInspection-compatible dict."""
        return {
            "asset_id": asset_id,
            "beat_id": beat_id,
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
            "model": model,
        }

    def _error_result(
        self,
        asset_id: str,
        beat_id: str,
        frame_paths: list[str],
        reason: str,
    ) -> dict[str, Any]:
        """Return a standardized error dict with all required fields."""
        return {
            "asset_id": asset_id,
            "beat_id": beat_id,
            "person_match": 0.0,
            "event_match": 0.0,
            "claim_support": 0.0,
            "visual_quality": 0.0,
            "temporal_match": 0.0,
            "source_credibility": 0.0,
            "cleanliness_score": 0.0,
            "misleading_risk": 0.0,
            "decision": "error",
            "reason": reason,
            "frame_paths": frame_paths,
            "model": self._model,
        }
