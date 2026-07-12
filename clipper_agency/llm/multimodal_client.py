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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clipper_agency.observability.llm_trace import LLMTraceWriter, TraceHandle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCORE_KEYS: frozenset[str] = frozenset(
    {
        "person_match",
        "event_match",
        "claim_support",
        "visual_quality",
        "temporal_match",
        "source_credibility",
        "cleanliness_score",
        "misleading_risk",
    }
)

_SYSTEM_PROMPT = (
    "You are a visual evidence inspector for a short-form video production pipeline. "
    "Your job is to examine video frames against a narration beat and determine "
    "whether the visual evidence supports the spoken claim. "
    "You must respond with a structured JSON assessment."
)

_INSPECTION_FIELDS = (
    "Respond with a JSON object containing these fields:\n"
    "- person_match (0-1): Is the visible person consistent with the subject?\n"
    "- subject_name (string): the name of the main person/entity clearly "
    'depicted, or "" if non-person or unknown — used to verify the image '
    "shows the BEAT's subject, not a different person\n"
    "- event_match (0-1): Does the scene show the described event?\n"
    "- claim_support (0-1): Does the visual directly support the claim?\n"
    "- visual_quality (0-1): Is image quality acceptable for publication?\n"
    "- temporal_match (0-1): Does timing align with narration?\n"
    "- source_credibility (0-1): Is the source text/logo credible?\n"
    "- cleanliness_score (0-1): Is the frame free of distracting overlays?\n"
    "- misleading_risk (0-1): Could the visual mislead the audience?\n"
    '- decision: one of "accept", "revise", or "reject"\n'
    "- reason: one-sentence justification"
)


# ---------------------------------------------------------------------------
# Pure functions — no I/O, no side effects
# ---------------------------------------------------------------------------


def _add_text_part(parts: list[dict[str, Any]], label: str, value: str) -> None:
    """Append a labelled text part only when value is non-empty.

    DRY helper for the conditional user-message builders — collapses the
    repeated ``if x: parts.append({...})`` blocks so
    ``build_visual_inspection_messages`` stays under Sonar's cognitive
    complexity limit (python:S3776).
    """
    if value:
        parts.append({"type": "text", "text": f"{label}: {value}"})


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
    user_parts: list[dict[str, Any]] = []
    _add_text_part(user_parts, "Spoken claim", beat.get("spoken_point", ""))
    _add_text_part(user_parts, "Visual must show", beat.get("visual_must_show", ""))
    _add_text_part(user_parts, "Visual must NOT show", beat.get("visual_must_not_show", ""))
    _add_text_part(user_parts, "Detected text in frame", ocr_text)
    if source_metadata:
        _add_text_part(user_parts, "Asset source", source_metadata.get("source", ""))
        _add_text_part(user_parts, "Asset URL", source_metadata.get("url", ""))

    # Inspection instructions
    user_parts.append({"type": "text", "text": _INSPECTION_FIELDS})
    user_parts.append(
        {
            "type": "text",
            "text": 'Example response:\n{"person_match":0.9,"subject_name":"Sarwendah",'
            '"event_match":0.8,'
            '"claim_support":0.7,"visual_quality":0.85,'
            '"temporal_match":0.75,"source_credibility":0.8,'
            '"cleanliness_score":0.6,"misleading_risk":0.1,'
            '"decision":"accept","reason":"Good match"}',
        }
    )

    # Images — cap at max_frames
    capped = frame_paths[:max_frames]
    for path in capped:
        try:
            uri = _encode_image(path)
            user_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": uri},
                }
            )
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


def _bound_scores(result: dict[str, Any]) -> None:
    """Bound all ``_SCORE_KEYS`` float fields to [0.0, 1.0], defaulting missing to 0.0.

    Extracted from ``parse_inspection_json`` to keep its cognitive complexity
    under Sonar's python:S3776 limit.
    """
    for key in _SCORE_KEYS:
        if key in result:
            result[key] = max(0.0, min(1.0, float(result[key])))
        else:
            result[key] = 0.0


def _infer_decision(result: dict[str, Any]) -> str:
    """Derive a valid decision from scores when the LLM omitted/garbled it.

    Extracted from ``parse_inspection_json`` (the ``and``/``or`` branches were
    the bulk of its cognitive complexity — python:S3776).
    """
    claim = result.get("claim_support", 0.0)
    misleading = result.get("misleading_risk", 0.0)
    if claim >= 0.70 and misleading <= 0.30:
        return "accept"
    if claim < 0.40 or misleading > 0.60:
        return "reject"
    return "revise"


def parse_inspection_json(raw_content: str) -> dict[str, Any]:
    """Parse LLM response JSON, bound scores, and determine decision.

    Strips markdown code fences, bounds all float scores to [0.0, 1.0],
    fills missing fields with defaults, and returns a complete dict.

    ``subject_name`` is coerced to a string (default ``""``); it is NOT a
    bounded score, so it is intentionally outside ``_SCORE_KEYS``.

    On parse failure returns ``{"decision": "error", "reason": ...}``.
    """
    text = raw_content.strip()
    if not text:
        return {"decision": "error", "reason": "Empty response from LLM"}

    # Strip markdown code fences
    fence_match = re.search(r"```(?:json)?[^\S\r\n]*\n([\s\S]*?)```", text)
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
    _bound_scores(result)

    # subject_name — string identity field (FIX-3 entity-binding), not a score.
    result["subject_name"] = str(result.get("subject_name", "") or "")

    # Ensure decision is valid
    if result.get("decision") not in ("accept", "revise", "reject"):
        result["decision"] = _infer_decision(result)

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
        trace_writer: LLMTraceWriter | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._max_frames = max_frames
        self._trace_writer = trace_writer

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
            job_id,
            beat_id,
            asset_id,
            len(frame_paths),
        )

        handle: TraceHandle | None = None
        if self._trace_writer is not None:
            handle = self._start_trace(job_id)

        try:
            messages = build_visual_inspection_messages(
                beat=beat,
                frame_paths=frame_paths,
                ocr_text=ocr_text,
                source_metadata=source_metadata or {},
                max_frames=self._max_frames,
            )
            self._trace_request(handle, messages)

            raw = self._client.chat(
                model=self._model,
                messages=messages,
                temperature=0.2,
            )
            parsed = parse_inspection_json(raw["content"])

            self._trace_response(handle, raw, parsed)

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
                job_id,
                beat_id,
                asset_id,
                result["decision"],
                result["claim_support"],
                result["misleading_risk"],
            )
            return result

        except Exception as exc:
            logger.exception(
                "Inspection failed: job=%s beat=%s asset=%s error=%s",
                job_id,
                beat_id,
                asset_id,
                exc,
            )
            return self._error_result(
                asset_id=asset_id,
                beat_id=beat_id,
                frame_paths=frame_paths,
                reason=str(exc),
            )

    # ------------------------------------------------------------------
    # Trace helpers — no-op when trace_writer is None
    # ------------------------------------------------------------------

    def _start_trace(self, job_id: int) -> TraceHandle | None:
        try:
            return self._trace_writer.start_call(  # type: ignore[union-attr]
                job_id=job_id,
                agent="visual_director",
                task="candidate_inspection",
                provider="openrouter",
                model=self._model,
                prompt_template_id="visual_inspection",
                prompt_version="1",
            )
        except Exception:
            logger.warning("Trace start_call failed for job %s", job_id)
            return None

    def _trace_request(self, handle: TraceHandle | None, messages: list[dict]) -> None:
        if handle is None:
            return
        try:
            self._trace_writer.persist_request(  # type: ignore[union-attr]
                handle,
                messages=messages,
                parameters={"temperature": 0.2},
            )
        except Exception:
            logger.warning("Trace request persist failed for call %s", handle.call_id)

    def _trace_response(
        self,
        handle: TraceHandle | None,
        raw: dict[str, Any],
        parsed: dict[str, Any],
    ) -> None:
        if handle is None:
            return
        try:
            self._trace_writer.persist_response(  # type: ignore[union-attr]
                handle,
                raw_response={"content": raw.get("content", "")},
                usage=raw.get("usage", {}),
                provider_metadata={"model": raw.get("model", self._model)},
            )
            self._trace_writer.persist_parsed_response(handle, parsed)  # type: ignore[union-attr]
            logger.info("Inspection trace persisted: %s", handle.trace_dir)
        except Exception:
            logger.warning("Trace response persist failed for call %s", handle.call_id)

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
            "subject_name": parsed.get("subject_name", ""),
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
            "subject_name": "",
            "decision": "error",
            "reason": reason,
            "frame_paths": frame_paths,
            "model": self._model,
        }
