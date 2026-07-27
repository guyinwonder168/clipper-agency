"""Scriptwriter Agent — Continuous voiceover narration generator via LLM."""

import json
import logging
import re
from typing import Any

from clipper_agency.agents.base import BaseAgent
from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
from clipper_agency.config.loader import get_agent_config
from clipper_agency.core.artifacts import write_json, write_text
from clipper_agency.core.beat_anchor import count_words, derive_word_ranges, tokenize
from clipper_agency.core.paths import agent_dir, agent_input_file, agent_output_file
from clipper_agency.core.repair_router import NARRATIVE_NOT_COVERED
from clipper_agency.llm.client import OpenRouterClient

logger = logging.getLogger(__name__)

# Fallback prompt if prompts/scriptwriter.md is missing or empty
_FALLBACK_PROMPT = """You are a voiceover scriptwriter for {{channel_description}}.

Write in {{language}} with a {{tone}} style. Content focus: {{content_angle}}.

Write a SINGLE CONTINUOUS voiceover narration ({{min_words}}-{{max_words}} words, no emojis, spoken-word style).
Target duration: {{target_duration_sec}} seconds. Target words: ~{{target_words}}.

For each beat, emit a `start_cue`: the 3-5 FIRST WORDS of that beat, copied
VERBATIM from the voiceover_text. Code will derive word indices from each cue.

Output JSON:
{{
  "voiceover_text": "...",
  "narrative_structure": [
    {{"beat_id":1, "section":"hook",
      "start_cue":"<3-5 first words of beat>",
      "overlay_text":"...", "caption_keywords":[...]}}
  ],
  "hook_text_onscreen": "...", "caption": "...",
  "hashtags": [...], "quality_score": 8, "quality_notes": "..."
}}

Safety rules:
{{safety_rules_text}}
"""

# Default word count bounds (overridden by ContentPlanningConfig when available)
_DEFAULT_TARGET_SEC = 55
_DEFAULT_HARD_LIMIT_SEC = 60
_DEFAULT_WORDS_PER_SEC = 2.0

# Unicode emoji detection pattern
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002600-\U000026ff"  # misc symbols
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"  # zero-width joiner
    "]+",
    re.UNICODE,
)

# FIX-8 (codex round-5 P1): validation errors that are FATAL on a fresh LLM
# run (a non-compliant response must not reach Voice Producer). Substring
# markers keep it decoupled from the exact error wording in _validate_output.
_CONTRACT_ERROR_MARKERS = (
    "standalone punctuation",
    "start_cue",
    "missing required",
)


def _contains_emoji(text: str) -> bool:
    """Return True if text contains any emoji characters."""
    return bool(_EMOJI_RE.search(text))


def _word_count(text: str) -> int:
    """Canonical word count via beat_anchor.tokenize (FIX-8 ruler parity)."""
    return count_words(text)


def _extract_blueprint(blueprint: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Extract blueprint data from dict param or legacy kwargs."""
    bp = blueprint or {}
    return {
        "story_beats": bp.get("story_beats") or kwargs.get("story_beats"),
        "verified_facts": bp.get("verified_facts") or kwargs.get("verified_facts"),
        "unverified_claims": bp.get("unverified_claims") or kwargs.get("unverified_claims"),
        "format_decision": bp.get("format_decision") or kwargs.get("format_decision"),
        "target_duration_sec": bp.get("target_duration_sec"),
        "hard_limit_sec": bp.get("hard_limit_sec"),
        "estimated_words_per_second": bp.get("estimated_words_per_second"),
    }


def _write_input_artifacts(
    assets_cache: str,
    job_id: int,
    agent_name: str,
    data: dict[str, Any],
) -> None:
    """Persist input artifacts if assets_cache is set."""
    if not assets_cache:
        return
    write_json(agent_input_file(assets_cache, job_id, agent_name), data)


def _format_system_prompt(
    channel_description: str,
    language: str,
    tone: str,
    content_angle: str,
    rules: list[str],
    bp_data: dict[str, Any],
    topic: str,
) -> str:
    """Serialize blueprint data and build the formatted system prompt."""
    safety_rules_text = "\n".join(f"- {r}" for r in rules) if rules else "None"
    beats_json = json.dumps(bp_data.get("story_beats") or [], ensure_ascii=False, indent=2)
    facts_json = json.dumps(bp_data.get("verified_facts") or [], ensure_ascii=False, indent=2)
    claims_json = json.dumps(bp_data.get("unverified_claims") or [], ensure_ascii=False, indent=2)
    decision_json = json.dumps(bp_data.get("format_decision") or {}, ensure_ascii=False, indent=2)

    # Duration-driven word budget (fallback to ContentPlanningConfig defaults)
    target_sec = bp_data.get("target_duration_sec") or 55
    hard_limit = bp_data.get("hard_limit_sec") or 60
    words_per_sec = bp_data.get("estimated_words_per_second") or 2.0
    target_words = int(target_sec * words_per_sec)
    min_words = int(target_words * 0.85)
    max_words = int(hard_limit * words_per_sec)

    prompt_template = load_prompt("scriptwriter", _FALLBACK_PROMPT, PROMPTS_DIR)
    return prompt_template.format(
        channel_description=channel_description or "a content creator",
        language=language or "English",
        tone=tone or "casual",
        content_angle=content_angle or "trending topics",
        safety_rules_text=safety_rules_text,
        story_beats_json=beats_json,
        verified_facts_json=facts_json,
        unverified_claims_json=claims_json,
        format_decision_json=decision_json,
        topic=topic,
        target_duration_sec=target_sec,
        hard_limit_sec=hard_limit,
        min_words=min_words,
        max_words=max_words,
        target_words=target_words,
    )


def _write_output_artifacts(
    assets_cache: str,
    job_id: int,
    agent_name: str,
    result: dict[str, Any],
) -> None:
    """Persist output artifacts if assets_cache is set."""
    if not assets_cache:
        return
    base_dir = agent_dir(assets_cache, job_id, agent_name)
    write_json(f"{base_dir}/narrative_structure.json", result["narrative_structure"])
    write_json(f"{base_dir}/script.json", {"scenes": result["narrative_structure"]})
    write_text(f"{base_dir}/voiceover.txt", result["voiceover_text"])
    write_text(f"{base_dir}/caption.txt", result["caption"])
    write_json(f"{base_dir}/hashtags.json", result["hashtags"])
    write_json(agent_output_file(assets_cache, job_id, agent_name), result)


class ScriptwriterAgent(BaseAgent):
    """Generates continuous voiceover narration from an edit blueprint."""

    def __init__(self, trace_writer: Any | None = None) -> None:
        self._trace_writer = trace_writer

    @property
    def agent_name(self) -> str:
        return "scriptwriter"

    def execute(
        self,
        job_id: int,
        topic: str = "",
        research_brief: str = "",
        safety_rules: list[str] | None = None,
        channel_description: str = "",
        language: str = "",
        tone: str = "",
        content_angle: str = "",
        assets_cache: str = "",
        blueprint: dict[str, Any] | None = None,
        coverage_directive: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        bp_data = _extract_blueprint(blueprint, kwargs)
        rules = safety_rules or []
        logger.info("Scriptwriter: job_id=%s, beats=%d", job_id, len(bp_data["story_beats"] or []))

        _write_input_artifacts(
            assets_cache,
            job_id,
            self.agent_name,
            {
                "job_id": job_id,
                "topic": topic,
                **bp_data,
                "safety_rules": rules,
            },
        )

        system_prompt = _format_system_prompt(
            channel_description,
            language,
            tone,
            content_angle,
            rules,
            bp_data,
            topic,
        )
        # FIX-5 (ADR 0030, Codex P2): on a coverage-regen attempt the engine
        # passes a directive instructing the model to make narrative_structure
        # word_ranges fully cover [0, word_count-1]. Append it to the system
        # prompt so the regen actually differs from the first-run prompt.
        if coverage_directive:
            system_prompt = f"{system_prompt}\n\n{coverage_directive}"
            logger.info("Scriptwriter: coverage-regen directive applied (job %d)", job_id)
        user_content = f"Topic: {topic}\n\nResearch Brief: {research_brief}"

        agent_cfg = get_agent_config("scriptwriter")
        llm = OpenRouterClient(trace_writer=self._trace_writer)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        if self._trace_writer:
            response = llm.chat_traced(
                model=agent_cfg["model"],
                messages=messages,
                job_id=job_id,
                agent=self.agent_name,
                task="write_script",
                temperature=agent_cfg["temperature"],
                max_completion_tokens=agent_cfg.get("max_completion_tokens"),
                prompt_template_id="scriptwriter.md",
            )
        else:
            response = llm.chat(
                model=agent_cfg["model"],
                messages=messages,
                temperature=agent_cfg["temperature"],
                max_completion_tokens=agent_cfg.get("max_completion_tokens"),
            )

        parsed = self._parse_script_response(response["content"])
        # Dynamic word bounds from ContentPlanningConfig
        target_sec = bp_data.get("target_duration_sec") or _DEFAULT_TARGET_SEC
        hard_limit = bp_data.get("hard_limit_sec") or _DEFAULT_HARD_LIMIT_SEC
        words_per_sec = bp_data.get("estimated_words_per_second") or _DEFAULT_WORDS_PER_SEC
        min_words = int(target_sec * words_per_sec * 0.85)
        max_words = int(hard_limit * words_per_sec)
        validation_errors = _validate_output(parsed, min_words=min_words, max_words=max_words)
        if validation_errors:
            logger.warning("Scriptwriter validation issues: %s", validation_errors)
        # FIX-8 (codex round-5 P1): contract errors (missing/malformed start_cue,
        # standalone punctuation in voiceover) are FATAL on a fresh LLM run — a
        # non-compliant response must not reach Voice Producer (where the G7
        # legacy word_range fallback would otherwise let unreliable LLM indices
        # slip through). Soft warnings (word count) stay non-fatal. Persisted
        # legacy artifacts reloaded on resume bypass this (run() not re-called).
        contract_errors = [
            e for e in validation_errors if any(m in e for m in _CONTRACT_ERROR_MARKERS)
        ]
        if contract_errors:
            # FIX-8 (codex P2): set BOTH ``error`` (consumed by _fail_agent) and
            # ``reason`` so the actual cue/voiceover violation propagates to the
            # persisted job + agent error fields (not a generic default_reason).
            diagnostic = "scriptwriter_contract_violation: " + "; ".join(contract_errors)
            return {
                "status": "failed",
                "error": diagnostic,
                "reason": diagnostic,
                # FIX-8 (codex round-8 P2): stamp the stable coverage token so
                # the caller routes this through the bounded Scriptwriter regen
                # loop (same path G7 cue failures take), not terminal-fail.
                "gate_reason": NARRATIVE_NOT_COVERED,
            }

        voiceover_text = parsed["voiceover_text"]
        word_count = _word_count(voiceover_text)
        estimated_duration = word_count / 2.5

        logger.info(
            "Scriptwriter: %d words, %.1fs estimated, %d narrative beats",
            word_count,
            estimated_duration,
            len(parsed["narrative_structure"]),
        )

        result = {
            "status": "completed",
            "voiceover_text": voiceover_text,
            "narrative_structure": parsed["narrative_structure"],
            "hook_text_onscreen": parsed["hook_text_onscreen"],
            "caption": parsed["caption"],
            "hashtags": parsed["hashtags"],
            "estimated_duration_sec": round(estimated_duration, 1),
        }

        _write_output_artifacts(assets_cache, job_id, self.agent_name, result)
        return result

    def _parse_script_response(
        self,
        content: str,
        *_args: Any,
    ) -> dict[str, Any]:
        """Parse the JSON voiceover response from the LLM."""
        try:
            stripped = content.strip().strip("```json").strip("```").strip()
            data = json.loads(stripped)
        except (json.JSONDecodeError, KeyError):
            return _empty_output()

        voiceover_text = data.get("voiceover_text", "")
        if not isinstance(voiceover_text, str):
            voiceover_text = str(voiceover_text)

        narrative_structure = _normalize_narrative_structure(
            data.get("narrative_structure", []),
            voiceover_text,
        )

        return {
            "voiceover_text": voiceover_text,
            "narrative_structure": narrative_structure,
            "hook_text_onscreen": data.get("hook_text_onscreen", ""),
            "caption": data.get("caption", ""),
            "hashtags": data.get("hashtags", []),
            "quality_score": data.get("quality_score", 0),
            "quality_notes": data.get("quality_notes", ""),
        }


def _validate_output(
    parsed: dict[str, Any],
    min_words: int = 0,
    max_words: int = 9999,
) -> list[str]:
    """Validate parsed output and return list of error strings (empty = valid).

    Per FIX-8 (ADR 0030): the LLM no longer emits ``word_range`` — it emits
    ``start_cue`` (3-5 first words of each beat, verbatim from voiceover_text).
    The cue contract is enforced here; word indices are derived in
    :func:`_normalize_narrative_structure`.
    """
    errors: list[str] = []
    voiceover_text = parsed.get("voiceover_text", "")

    wc = _word_count(voiceover_text)
    if wc < min_words:
        errors.append(f"voiceover_text too short: {wc} words (min {min_words})")
    if wc > max_words:
        errors.append(f"voiceover_text too long: {wc} words (max {max_words})")
    if _contains_emoji(voiceover_text):
        errors.append("voiceover_text contains emojis")

    # FIX-8 (codex round-3 P1): voiceover_text must be clean spoken prose with
    # NO standalone punctuation tokens (``...`` / ``—`` as whitespace-separated
    # tokens). Reason: beat_anchor._tokenize strips attached punctuation, but
    # the Voice Producer timestamp builder (chars_to_words / _approximate) uses
    # whitespace split — they produce the SAME word count iff no standalone
    # punctuation, so derived word_range indices align 1:1 with timestamps. A
    # divergence offsets build_canonical_timeline's beat→audio mapping.
    if voiceover_text and len(voiceover_text.split()) != count_words(voiceover_text):
        errors.append(
            "voiceover_text contains standalone punctuation tokens (e.g. '...' "
            "or em-dash as separate words) — forbidden; write clean spoken prose"
        )

    # start_cue contract: each beat MUST carry a non-empty 3-5 token cue. The
    # G7 gate fuzzy-matches each cue against the voiceover; a missing/short
    # cue fails the contract before the LLM wastes a TTS call.
    for beat in parsed.get("narrative_structure", []):
        cue = beat.get("start_cue", "")
        if not isinstance(cue, str) or not cue.strip():
            errors.append(f"beat {beat.get('beat_id', '?')} missing required start_cue")
            continue
        cue_tokens = tokenize(cue)
        if not (3 <= len(cue_tokens) <= 5):
            errors.append(
                f"beat {beat.get('beat_id', '?')} start_cue must be 3-5 words "
                f"(got {len(cue_tokens)})"
            )

    return errors


_BEAT_DEFAULTS = {
    "description": "",
    "start_cue": "",
    "overlay_text": "",
    "caption_keywords": list,  # factory
    "word_range": lambda: [0, 0],  # legacy default; overwritten on cue derivation
}


def _backfill_beat_defaults(beat: dict[str, Any], i: int) -> dict[str, Any]:
    """Return a copy of ``beat`` with required fields backfilled (beat_id, section, defaults)."""
    b = dict(beat)
    b.setdefault("beat_id", i + 1)
    b.setdefault("section", f"section_{i + 1}")
    for field, default in _BEAT_DEFAULTS.items():
        if field not in b:
            b[field] = default() if callable(default) else default
    return b


def _normalize_narrative_structure(
    raw_beats: list[dict[str, Any]],
    voiceover_text: Any = None,
    *_args: Any,
) -> list[dict[str, Any]]:
    """Normalize narrative_structure entries, ensuring required fields exist.

    FIX-8 (ADR 0030): ``word_range`` is now DERIVED from ``start_cue`` (via
    :func:`clipper_agency.core.beat_anchor.derive_word_ranges`) so downstream
    consumers (``build_canonical_timeline``, Visual Director, Composer,
    Reviewer) keep reading the field unchanged. On derivation failure the
    legacy ``[0, 0]`` sentinel is left in place and the G7 gate catches it —
    failure routing emits a cue-specific reason (``cue_not_found`` /
    ``cue_out_of_order``) for the FIX-5 reason-based repair router.
    """
    normalized = [_backfill_beat_defaults(beat, i) for i, beat in enumerate(raw_beats)]

    # FIX-8: derive word_range from start_cue so downstream sees a contract-
    # correct field without any LLM-emitted indices. Only attempt when a
    # voiceover is available (legacy callers / parse-fallback pass None).
    cues = [b.get("start_cue", "") for b in normalized]
    if voiceover_text and any(isinstance(c, str) and c.strip() for c in cues):
        derived = derive_word_ranges(str(voiceover_text), cues)
        if derived.ok:
            for b, rng in zip(normalized, derived.word_ranges, strict=True):
                b["word_range"] = list(rng)
        else:
            # Cue contract failure — surface LOUDLY. The [0,0] sentinel stays
            # (downstream reads word_range), but G7 re-derives independently
            # and routes repair via the cue-specific reason. Silent swallow
            # here would hide the job_18 mega-beat seed (review round-1).
            logger.warning(
                "Scriptwriter normalize: cue derivation failed "
                "(reason=%s, details=%s) — leaving [0,0] sentinel; G7 will "
                "catch and route to Scriptwriter repair.",
                derived.reason,
                derived.details,
            )
    return normalized


def _empty_output() -> dict[str, Any]:
    """Return a valid empty output when parsing fails."""
    return {
        "voiceover_text": "",
        "narrative_structure": [],
        "hook_text_onscreen": "",
        "caption": "",
        "hashtags": [],
        "quality_score": 0,
        "quality_notes": "",
    }
