"""Reviewer Agent — final content quality and safety review via LLM."""

import json
import logging
from pathlib import Path
from typing import Any, TypedDict

from clipper_agency.agents.base import BaseAgent
from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
from clipper_agency.config.loader import get_agent_config, load_settings
from clipper_agency.config.schema import SceneSemanticReview
from clipper_agency.core.candidate_semantic_ranker import (
    derive_expected_entities,
    entity_overlap,
)
from clipper_agency.core.media_probe import AUDIO_TRUNC_TOL_SEC, probe_video
from clipper_agency.core.package_consistency import evaluate_package_consistency
from clipper_agency.core.reviewer_context import (
    SceneBeatMapping,
    map_scenes_to_beats,
)
from clipper_agency.core.safe_area import detect_safe_area_issues
from clipper_agency.core.text_collision import (
    detect_source_text_density,
    detect_text_collisions,
)
from clipper_agency.llm.client import OpenRouterClient

logger = logging.getLogger(__name__)

_MAX_CAPTION_LEN = 150
_AV_DRIFT_TOLERANCE_SEC = 0.5
_MIN_SCENE_DURATION_SEC = 0.5
_MAX_BEATS_PER_SCENE = 3

_FAIL_REASON_VISUAL_COVERAGE = "VISUAL_COVERAGE_FAILED"
_FAIL_REASON_TEXT_COLLISION = "TEXT_COLLISION_FAILED"
_FAIL_REASON_SAFE_AREA = "SAFE_AREA_FAILED"
_FAIL_REASON_PACKAGE_CONSISTENCY = "PACKAGE_CONSISTENCY_FAILED"
_FAIL_REASON_TIMESTAMP_SEMANTIC = "TIMESTAMP_SEMANTIC_FAILED"
_FAIL_REASON_SEMANTIC_REVIEW = "SEMANTIC_REVIEW_FAILED"
# FIX-4 (ADR 0030): reviewer-level defense-in-depth re-probe token. Distinct
# from G10's gate-level "audio_truncated" reason so the two are distinguishable
# in logs/repair routing. Routes to Composer (redo_compose) via repair_router.
_FAIL_REASON_AUDIO_TRUNCATED = "AUDIO_TRUNCATED_REVIEWER"
# FIX-4 (ADR 0030): per-scene entity-vs-beat mismatch token. Routes to Visual
# Director (replace_visual) — the wrong-entity asset must be re-selected.
_FAIL_REASON_ENTITY_MISMATCH = "ENTITY_MISMATCH"

REVIEWER_PROMPT = """You are a content quality reviewer for a TikTok creator channel
producing short-form infotainment videos with voiceover narration.

Review the provided content for:

1. **Voiceover Quality**: Natural spoken-word style, engaging pacing, clear delivery
2. **Visual-Audio Alignment**: Visuals match what's being said (no disconnect)
3. **Caption Effectiveness**: Compelling, TikTok-optimized caption with hashtags
4. **Safety Compliance**: No illegal, defamatory, or harmful content
5. **Fact Safety**: Unverified claims use appropriate hedging language

Safety rules to enforce:
{safety_rules_text}

Programmatic checks already passed:
{programmatic_results}

Return a JSON verdict:
{{
  "verdict": "pass" or "fail",
  "score": 0-100,
  "feedback": "Detailed feedback",
  "issues": ["list", "of", "issues", "if any"]
}}
"""

_CHECK_PASS = "pass"
_CHECK_FAIL = "fail"
_CHECK_SKIP = "skip"
_CHECK_WARN = "warn"


def _check_av_sync(audio_duration: float, visual_duration: float) -> dict[str, Any]:
    """Verify audio and visual durations are within tolerance."""
    if audio_duration == 0 and visual_duration == 0:
        return {"check": "av_sync", "status": _CHECK_SKIP, "detail": "Missing duration data"}
    if audio_duration == 0 or visual_duration == 0:
        # FIX-2 (ADR 0030): one track has a known duration while the other is
        # missing/0 (typically a rendered-output probe hiccup after compose
        # completed). Surfacing as WARN keeps the gate VISIBLE — the former
        # SKIP silently defeated the job_18 truncation check whenever the
        # output-duration probe failed. Both-zero stays SKIP (legacy caller
        # that supplied no duration data at all).
        return {
            "check": "av_sync",
            "status": _CHECK_WARN,
            "detail": (f"AV sync unverifiable: audio={audio_duration}s visual={visual_duration}s"),
            "audio_sec": audio_duration,
            "visual_sec": visual_duration,
        }
    drift = abs(audio_duration - visual_duration)
    if drift > _AV_DRIFT_TOLERANCE_SEC:
        return {
            "check": "av_sync",
            "status": _CHECK_FAIL,
            "detail": f"Drift {drift:.2f}s exceeds {_AV_DRIFT_TOLERANCE_SEC}s",
            "audio_sec": audio_duration,
            "visual_sec": visual_duration,
        }
    return {"check": "av_sync", "status": _CHECK_PASS, "drift_sec": round(drift, 2)}


def _check_audio_not_truncated(
    video_path: str,
    voiceover_duration_sec: float,
) -> dict[str, Any]:
    """FIX-4 (ADR 0030): re-probe the final video's audio STREAM duration and
    assert it covers the source voiceover within tolerance.

    Defense-in-depth over G10 (GateVideoValidation): G10 runs BEFORE the
    reviewer and is relaxable via ``DEV_RELAX_GATES=G10``, so a bypassed /
    missing gate leaves the reviewer blind to a truncated voiceover (job_18:
    ``-shortest`` cut ~2.6s off the audio while container-duration parity hid
    it). This check independently re-probes the audio stream — the master —
    using the SAME ``probe_video`` + ``AUDIO_TRUNC_TOL_SEC`` G10 uses so the
    two definitions cannot diverge.

    Returns a check dict shaped like ``_check_av_sync`` output:
    - ``skip`` when ``voiceover_duration_sec`` is 0/missing (legacy caller).
    - ``warn`` when the probe fails / audio-stream duration is unavailable
      (cannot verify is NOT verified good — mirrors FIX-2 G10 None→soft_fail).
    - ``fail`` (reason ``AUDIO_TRUNCATED_REVIEWER``) when the audio stream is
      shorter than the voiceover beyond the tolerance.
    - ``pass`` otherwise.
    """
    if not voiceover_duration_sec:
        return {
            "check": "audio_not_truncated",
            "status": _CHECK_SKIP,
            "detail": "No voiceover_duration_sec supplied",
        }
    if not video_path:
        return {
            "check": "audio_not_truncated",
            "status": _CHECK_WARN,
            "detail": "No video_path supplied; cannot re-probe audio stream",
        }
    info = probe_video(video_path, Path(video_path).parent)
    if info is None or info.audio_duration is None:
        return {
            "check": "audio_not_truncated",
            "status": _CHECK_WARN,
            "detail": (
                "audio-stream duration unavailable in ffprobe metadata; cannot verify truncation"
            ),
            "voiceover_sec": voiceover_duration_sec,
        }
    if info.audio_duration < voiceover_duration_sec - AUDIO_TRUNC_TOL_SEC:
        return {
            "check": "audio_not_truncated",
            "status": _CHECK_FAIL,
            "reason": _FAIL_REASON_AUDIO_TRUNCATED,
            "detail": (
                f"AUDIO_TRUNCATED_REVIEWER: audio stream {info.audio_duration:.2f}s "
                f"< voiceover {voiceover_duration_sec:.2f}s "
                f"- {AUDIO_TRUNC_TOL_SEC}s tolerance"
            ),
            "audio_sec": info.audio_duration,
            "voiceover_sec": voiceover_duration_sec,
        }
    return {
        "check": "audio_not_truncated",
        "status": _CHECK_PASS,
        "audio_sec": info.audio_duration,
        "voiceover_sec": voiceover_duration_sec,
    }


def _check_caption_quality(caption: str) -> dict[str, Any]:
    """Verify caption follows TikTok best practices."""
    issues: list[str] = []
    if not caption.strip():
        return {"check": "caption_quality", "status": _CHECK_FAIL, "detail": "Caption is empty"}
    if len(caption) > _MAX_CAPTION_LEN:
        issues.append(f"Caption length {len(caption)} exceeds {_MAX_CAPTION_LEN}")
    if "#" not in caption:
        issues.append("No hashtag found")
    if issues:
        return {"check": "caption_quality", "status": _CHECK_WARN, "issues": issues}
    return {"check": "caption_quality", "status": _CHECK_PASS}


def _check_fact_safety(unverified_claims: list[dict]) -> dict[str, Any]:
    """Verify unverified claims use safe wording."""
    if not unverified_claims:
        return {"check": "fact_safety", "status": _CHECK_PASS, "detail": "No unverified claims"}
    missing = [f"Claim {i}" for i, c in enumerate(unverified_claims) if "safe_wording" not in c]
    if missing:
        return {
            "check": "fact_safety",
            "status": _CHECK_WARN,
            "detail": f"Missing safe_wording: {', '.join(missing)}",
        }
    return {"check": "fact_safety", "status": _CHECK_PASS}


def _check_narrative_structure(
    narrative: list[dict],
) -> dict[str, Any]:
    """Verify narrative beats have required fields."""
    if not narrative:
        return {"check": "narrative_structure", "status": _CHECK_SKIP, "detail": "No narrative"}
    required = {"beat_id", "section", "word_range"}
    for i, beat in enumerate(narrative):
        missing = required - beat.keys()
        if missing:
            return {
                "check": "narrative_structure",
                "status": _CHECK_WARN,
                "detail": f"Beat {i} missing fields: {', '.join(sorted(missing))}",
            }
    return {"check": "narrative_structure", "status": _CHECK_PASS, "beats": len(narrative)}


def _format_script_text(script: list[dict] | None) -> str:
    """Build readable script text from scene list."""
    return "\n".join(
        f"Scene {s.get('scene', i)}: {s.get('text', '')}" for i, s in enumerate(script or [])
    )


def _dump_issues(issues: list[Any]) -> list[dict]:
    """Normalize detector issue objects into plain dictionaries."""
    return [i.model_dump() if hasattr(i, "model_dump") else dict(i) for i in issues]


def _is_enabled(config: Any) -> bool:
    """Return config.enabled when present; otherwise default enabled."""
    return bool(getattr(config, "enabled", True))


def _frame_size(value: Any) -> tuple[int, int]:
    """Normalize frame size from diagnostics with a TikTok default."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    return (1080, 1920)


def _format_programmatic_results(results: list[dict[str, Any]]) -> str:
    """Format programmatic check results for prompt inclusion."""
    lines = [f"- {r['check']}: {r['status']}" for r in results]
    return "\n".join(lines)


def _format_safety_rules(rules: list[str]) -> str:
    """Format safety rules for prompt inclusion."""
    return "\n".join(f"- {r}" for r in rules) if rules else "None"


def _evaluate_scene_semantic(mapping: SceneBeatMapping) -> SceneSemanticReview:
    """Programmatically evaluate a single scene's semantic quality.

    Checks:
    - Scene has at least one matched beat.
    - Scene duration exceeds minimum threshold.
    - Scene does not span more than MAX_BEATS_PER_SCENE beats.
    """
    duration = mapping.scene_end_sec - mapping.scene_start_sec
    beat_count = len(mapping.matched_beat_ids)
    beat_id_str = ",".join(str(b) for b in mapping.matched_beat_ids) or "none"
    issues: list[str] = []
    score = 1.0

    if not mapping.matched_beat_ids:
        issues.append("Scene has no matched beat")
        score = 0.0
    if duration < _MIN_SCENE_DURATION_SEC:
        issues.append(f"Scene duration {duration:.2f}s below {_MIN_SCENE_DURATION_SEC}s")
        score = min(score, 0.3)
    if beat_count > _MAX_BEATS_PER_SCENE:
        issues.append(f"Scene spans {beat_count} beats (max {_MAX_BEATS_PER_SCENE})")
        score = min(score, 0.4)

    passed = len(issues) == 0
    return SceneSemanticReview(
        beat_id=beat_id_str,
        timestamp_start_sec=mapping.scene_start_sec,
        timestamp_end_sec=mapping.scene_end_sec,
        decision="accept" if passed else "reject",
        reason="; ".join(issues) if issues else "All programmatic checks passed",
        score=score,
    )


def _run_programmatic_scene_reviews(
    mappings: list[SceneBeatMapping],
) -> list[SceneSemanticReview]:
    """Run programmatic semantic review for all scene-beat mappings."""
    return [_evaluate_scene_semantic(m) for m in mappings]


def _entity_expected_for_beat(beat: dict) -> list[str]:
    """FIX-4 (ADR 0030): expected named entities for one beat.

    Reuses FIX-3's ``derive_expected_entities`` (DRY — single source for the
    entity-binding contract). Beat-local entities (from ``visual_must_show`` /
    ``spoken_point``) are AUTHORITATIVE and the ONLY source of expectation.

    Topic-level globals are intentionally NOT applied: widening a beat that
    names no entity itself (platform/format/hook/CTA beats whose text yields no
    entity after derive_expected_entities filters generic words like "TikTok")
    would convert genuinely non-person beats into person-expecting beats — so
    once a real subject_name flows (codex round-2 P1) a legitimate "TikTok
    logo" asset on a "TikTok viral hari ini" beat would false-positive
    ENTITY_MISMATCH (codex round-2 P2). A beat with no beat-local entity gets
    NO expectation and is skipped by the caller. Recall loss degrades safely to
    ENTITY_UNVERIFIABLE (accept-warn); the canonical topic person is still bound
    on the beats that actually name them.
    """
    return list(
        derive_expected_entities(
            spoken_point=str(beat.get("spoken_point") or ""),
            visual_must_show=str(beat.get("visual_must_show") or ""),
        )
    )


def _entity_review_for_mapping(
    m: SceneBeatMapping,
    beats_by_id: dict,
) -> SceneSemanticReview | None:
    """FIX-4 (ADR 0030): one scene's entity-vs-beat review, or None to skip.

    Extracted from ``_run_entity_binding_review`` to keep cognitive complexity
    under the gate threshold (one scene's logic in isolation).
    """
    if not m.matched_beat_ids:
        return None
    # Collect expected entities across all matched beats for this scene.
    expected: list[str] = []
    for bid in m.matched_beat_ids:
        beat = beats_by_id.get(bid)
        if beat:
            expected.extend(_entity_expected_for_beat(beat))
    if not expected:
        return None  # non-person beat → entity gate is a no-op
    beat_id_str = ",".join(str(b) for b in m.matched_beat_ids)
    if not m.subject_name:
        # WARN: cannot verify (mirror FIX-3 is_unverifiable_entity_binding).
        logger.warning(
            "FIX-4 entity gate: scene %s beat %s expects %s but subject_name "
            "is empty — cannot verify entity binding",
            m.scene_index,
            beat_id_str,
            expected,
        )
        return SceneSemanticReview(
            beat_id=beat_id_str,
            timestamp_start_sec=m.scene_start_sec,
            timestamp_end_sec=m.scene_end_sec,
            decision="accept",  # do NOT hard-fail on unverifiable
            reason=(
                f"ENTITY_UNVERIFIABLE: expected {expected} but asset "
                f"subject_name empty (cannot verify)"
            ),
            score=0.6,
        )
    if entity_overlap(m.subject_name, expected):
        return None
    return SceneSemanticReview(
        beat_id=beat_id_str,
        timestamp_start_sec=m.scene_start_sec,
        timestamp_end_sec=m.scene_end_sec,
        decision="reject",
        reason=(f"ENTITY_MISMATCH: asset depicts '{m.subject_name}' but beat expects {expected}"),
        score=0.0,
    )


def _run_entity_binding_review(
    mappings: list[SceneBeatMapping],
    story_beats: list[dict],
) -> list[SceneSemanticReview]:
    """FIX-4 (ADR 0030): per-scene entity-vs-beat binding review.

    For each scene mapped to a person/entity beat, assert the rendered asset's
    ``subject_name`` (threaded from VD inspection) overlaps the beat's expected
    entities. Reuses FIX-3's ``entity_overlap`` (the alias/fuzzy matcher) — no
    reimplementation.

    Returns only the entity-relevant reviews:
    - reject (ENTITY_MISMATCH) when subject_name is present + wrong entity.
    - accept-with-warning when the beat expects an entity but subject_name is
      empty (cannot verify != verified good — recorded, NOT a hard-fail so the
      pipeline does not death-loop on pre-FIX-4 persisted manifests).
    - Non-entity beats (no expected entities) are skipped (backward compat).
    """
    if not mappings or not story_beats:
        return []
    beats_by_id = {b.get("beat_id"): b for b in story_beats}
    reviews: list[SceneSemanticReview] = []
    for m in mappings:
        review = _entity_review_for_mapping(m, beats_by_id)
        if review is not None:
            reviews.append(review)
    return reviews


class ReviewContext(TypedDict, total=False):
    """Bundled audio-first / quality-gate parameters for ReviewerAgent.execute()."""

    audio_duration_sec: float
    visual_duration_sec: float
    narrative_structure: list[dict]
    unverified_claims: list[dict]
    visual_plan_actions: list[dict]
    story_mode_decision: dict
    thumbnail_text: str
    main_entities: list[str]
    story_beats: list[dict]
    word_timestamps: list[dict]
    rendered_scene_manifest: dict
    # FIX-4 (ADR 0030): source voiceover duration — the master the audio-stream
    # re-probe checks against. Distinct from audio_duration_sec (the rendered
    # container duration); without this the reviewer cannot detect truncation.
    voiceover_duration_sec: float


class ReviewerAgent(BaseAgent):
    """Reviews final content for quality, safety, and originality."""

    def __init__(self, trace_writer: Any | None = None) -> None:
        self._trace_writer = trace_writer

    @property
    def agent_name(self) -> str:
        return "reviewer"

    # Expose pure functions as static methods for testability
    _check_av_sync = staticmethod(_check_av_sync)
    _check_audio_not_truncated = staticmethod(_check_audio_not_truncated)
    _check_caption_quality = staticmethod(_check_caption_quality)
    _check_fact_safety = staticmethod(_check_fact_safety)
    _check_narrative_structure = staticmethod(_check_narrative_structure)
    _evaluate_scene_semantic = staticmethod(_evaluate_scene_semantic)
    _run_programmatic_scene_reviews = staticmethod(_run_programmatic_scene_reviews)
    _run_entity_binding_review = staticmethod(_run_entity_binding_review)

    def _check_hard_gates(
        self,
        checks: dict[str, Any],
        audio_duration_sec: float,
        visual_duration_sec: float,
        visual_plan_actions: list[dict] | None,
    ) -> dict[str, Any] | None:
        """Return a fail dict if any hard gate triggers, else None."""
        # Hard gate 1: AV drift (symmetric — both drift directions are real).
        # _check_av_sync fails when |drift| > tolerance; here we hard-gate that
        # fail regardless of which track is longer. A trailing clip / over-long
        # scene (video LONGER than audio) is just as much an AV desync as the
        # shorter-than case, so it must not fall through to the non-deterministic
        # LLM (RC-2).
        if checks["av_sync"]["status"] == _CHECK_FAIL:
            if visual_duration_sec < audio_duration_sec:
                return {
                    "status": "fail",
                    "score": 0,
                    "feedback": (
                        f"Hard gate: video ({visual_duration_sec}s) "
                        f"shorter than audio ({audio_duration_sec}s)"
                    ),
                    "issues": ["av_duration_mismatch"],
                }
            if (visual_duration_sec - audio_duration_sec) > _AV_DRIFT_TOLERANCE_SEC:
                return {
                    "status": "fail",
                    "score": 0,
                    "feedback": (
                        f"Hard gate: video ({visual_duration_sec}s) "
                        f"longer than audio ({audio_duration_sec}s)"
                    ),
                    "issues": ["av_duration_mismatch"],
                }

        # Hard gate 2: Broken tiktok_clip actions (missing source_url)
        if visual_plan_actions:
            for action in visual_plan_actions:
                if action.get("type") == "tiktok_clip" and not action.get("source_url"):
                    return {
                        "status": "fail",
                        "score": 0,
                        "feedback": "Hard gate: broken tiktok_clip action (missing source_url)",
                        "issues": ["broken_tiktok_clip_action"],
                    }

        return None

    def _fail_if_visual_coverage_failed(self, diagnostics: dict | None) -> dict[str, Any] | None:
        """Return fail dict if visual coverage hard-failed, else None."""
        if not diagnostics:
            return None
        vc = diagnostics.get("visual_coverage")
        if not vc or vc.get("status") != "fail":
            return None
        hard_fails = [
            i
            for i in vc.get("issues", [])
            if isinstance(i, dict) and i.get("severity") in ("hard_fail", "reject")
        ]
        if hard_fails:
            return {
                "status": "fail",
                "reason": _FAIL_REASON_VISUAL_COVERAGE,
                "score": 0,
                "feedback": (
                    f"Hard gate: visual coverage failed ({len(hard_fails)} hard-fail issues)"
                ),
                "issues": ["visual_coverage_failed"],
            }
        return None

    def _fail_if_text_collision_failed(self, diagnostics: dict | None) -> dict[str, Any] | None:
        """Return fail dict if text collision hard-failed, else None."""
        if not diagnostics:
            return None
        tc = diagnostics.get("text_collision")
        if not tc:
            return None
        hard_fails = [
            i for i in tc if isinstance(i, dict) and i.get("severity") in ("hard_fail", "reject")
        ]
        if hard_fails:
            return {
                "status": "fail",
                "reason": _FAIL_REASON_TEXT_COLLISION,
                "score": 0,
                "feedback": f"Hard gate: text collision detected ({len(hard_fails)} issues)",
                "issues": ["text_collision_failed"],
            }
        return None

    def _fail_if_safe_area_failed(self, diagnostics: dict | None) -> dict[str, Any] | None:
        """Return fail dict if safe area hard-failed, else None."""
        if not diagnostics:
            return None
        sa = diagnostics.get("safe_area")
        if not sa:
            return None
        hard_fails = [
            i for i in sa if isinstance(i, dict) and i.get("severity") in ("hard_fail", "reject")
        ]
        if hard_fails:
            return {
                "status": "fail",
                "reason": _FAIL_REASON_SAFE_AREA,
                "score": 0,
                "feedback": f"Hard gate: safe area violation ({len(hard_fails)} issues)",
                "issues": ["safe_area_failed"],
            }
        return None

    def _populate_actual_detection_diagnostics(
        self,
        diagnostics: dict | None,
    ) -> dict | None:
        """Populate text-collision and safe-area diagnostics from region data."""
        if not diagnostics:
            return diagnostics

        enriched = dict(diagnostics)
        settings = load_settings()
        quality = settings.quality
        frame_size = _frame_size(enriched.get("frame_size"))
        generated_regions = enriched.get("generated_text_regions") or []
        source_regions = enriched.get("source_text_regions") or []

        if source_regions and _is_enabled(quality.text_collision):
            try:
                thresholds = {
                    "subtitle_overlap_max": quality.text_collision.subtitle_overlap_max,
                    "headline_overlap_max": quality.text_collision.headline_overlap_max,
                }
                collisions = (
                    detect_text_collisions(
                        source_regions,
                        generated_regions,
                        thresholds,
                    )
                    if generated_regions
                    else []
                )
                density = detect_source_text_density(source_regions, frame_size)
                enriched["text_collision"] = _dump_issues(collisions + density)
            except Exception:
                logger.warning("Reviewer text collision detection failed", exc_info=True)

        if generated_regions and _is_enabled(quality.safe_area):
            try:
                safe_issues = detect_safe_area_issues(
                    generated_regions=generated_regions,
                    face_regions=enriched.get("face_regions") or [],
                    frame_size=frame_size,
                    platform=enriched.get("platform", "tiktok"),
                    face_overlap_max=quality.safe_area.face_overlap_max,
                )
                enriched["safe_area"] = _dump_issues(safe_issues)
            except Exception:
                logger.warning("Reviewer safe-area detection failed", exc_info=True)

        return enriched

    def _fail_if_package_consistency_failed(
        self,
        story_mode_decision: dict | None,
        thumbnail_text: str,
        main_entities: list[str] | None,
        caption: str,
        topic: str,
        script: list[dict] | None,
    ) -> dict[str, Any] | None:
        """Return fail dict if package consistency check fails, else None."""
        if not story_mode_decision:
            return None
        result = evaluate_package_consistency(
            topic=topic,
            script=_format_script_text(script),
            thumbnail_text=thumbnail_text or "",
            caption=caption or "",
            story_mode=story_mode_decision.get("story_mode", ""),
            main_entities=main_entities or [],
        )
        if result.status == "fail":
            return {
                "status": "fail",
                "reason": _FAIL_REASON_PACKAGE_CONSISTENCY,
                "score": 0,
                "feedback": f"Hard gate: package consistency — {result.issue}: {result.detail}",
                "issues": ["package_consistency_failed"],
            }
        return None

    def _fail_if_semantic_review_failed(self, diagnostics: dict | None) -> dict[str, Any] | None:
        """Return fail dict with repair_plan if semantic review reports revise/reject."""
        if not diagnostics:
            return None
        sr = diagnostics.get("semantic_review")
        if not sr:
            return None
        decision = sr.get("decision", "")
        if decision not in ("revise", "reject"):
            return None

        from clipper_agency.config.schema import RepairPatch, RepairPlan

        patches = sr.get("patches", [])
        repair_patches = [
            RepairPatch(
                beat_id=str(p.get("beat_id", "")),
                action=p.get("action", "replace_visual"),
                reason=p.get("reason", "semantic_mismatch"),
                rerun_from=p.get("rerun_from", "visual_director"),
                timestamp_start_sec=p.get("timestamp_start_sec", 0.0),
                timestamp_end_sec=p.get("timestamp_end_sec", 0.0),
                required_visual=p.get("required_visual", ""),
            )
            for p in patches
        ]

        plan = RepairPlan(
            decision=decision,
            max_repair_cycles=2,
            patches=repair_patches,
        )

        return {
            "status": "fail",
            "reason": _FAIL_REASON_SEMANTIC_REVIEW,
            "score": 0,
            "feedback": f"Semantic review: {decision} ({len(repair_patches)} patches)",
            "issues": ["semantic_review_failed"],
            "repair_plan": plan.model_dump(),
        }

    def _fail_if_timestamp_semantic_failed(
        self,
        scene_reviews: list[SceneSemanticReview],
    ) -> dict[str, Any] | None:
        """Return fail dict if any programmatic scene semantic check failed."""
        if not scene_reviews:
            return None
        failed = [r for r in scene_reviews if not r.passed]
        if not failed:
            return None
        issues_summary = "; ".join(f"Scene {r.beat_id}: {r.reason}" for r in failed)
        return {
            "status": "fail",
            "reason": _FAIL_REASON_TIMESTAMP_SEMANTIC,
            "score": 0,
            "feedback": (
                f"Hard gate: timestamp semantic review failed "
                f"({len(failed)}/{len(scene_reviews)} scenes): {issues_summary}"
            ),
            "issues": ["timestamp_semantic_failed"],
            "scene_semantic_reviews": [r.model_dump() for r in scene_reviews],
        }

    def _fail_if_audio_truncated(
        self,
        audio_trunc_check: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """FIX-4 (ADR 0030): hard-fail when the audio-stream re-probe detects
        truncation. The ``warn``/``skip`` outcomes do NOT hard-fail (cannot
        verify is not a proven defect); only a ``fail`` does. Routes to Composer
        via the ``AUDIO_TRUNCATED_REVIEWER`` reason token."""
        if not audio_trunc_check:
            return None
        if audio_trunc_check.get("status") != _CHECK_FAIL:
            return None
        return {
            "status": "fail",
            "reason": _FAIL_REASON_AUDIO_TRUNCATED,
            "score": 0,
            "feedback": (f"Hard gate: {audio_trunc_check.get('detail', 'audio truncated')}"),
            "issues": ["audio_truncated"],
            "audio_sec": audio_trunc_check.get("audio_sec"),
            "voiceover_sec": audio_trunc_check.get("voiceover_sec"),
        }

    def _fail_if_entity_mismatch(
        self,
        entity_reviews: list[SceneSemanticReview],
    ) -> dict[str, Any] | None:
        """FIX-4 (ADR 0030): hard-fail when a rendered scene's asset depicts the
        wrong entity for its beat (job_18: a Jennifer Coppen image in a Sarwendah
        beat). Only reject-level reviews trigger; the unverifiable (empty
        subject_name) case is accept-with-warning and does NOT hard-fail."""
        if not entity_reviews:
            return None
        failed = [r for r in entity_reviews if r.decision == "reject"]
        if not failed:
            return None
        issues_summary = "; ".join(f"Scene {r.beat_id}: {r.reason}" for r in failed)
        return {
            "status": "fail",
            "reason": _FAIL_REASON_ENTITY_MISMATCH,
            "score": 0,
            "feedback": (
                f"Hard gate: entity-vs-beat mismatch "
                f"({len(failed)}/{len(entity_reviews)} entity scenes): {issues_summary}"
            ),
            "issues": ["entity_mismatch"],
            "scene_semantic_reviews": [r.model_dump() for r in entity_reviews],
        }

    def _run_timestamp_semantic_review(
        self,
        rendered_scene_manifest: dict | None,
        story_beats: list[dict] | None,
        word_timestamps: list[dict] | None,
        audio_duration_sec: float,
        beat_timeline: list | None = None,
    ) -> list[SceneSemanticReview]:
        """Run programmatic timestamp-level semantic review using scene-beat mapping.

        Returns list of SceneSemanticReview, or empty list if data is unavailable.
        """
        if not rendered_scene_manifest or not story_beats:
            return []
        scenes = rendered_scene_manifest.get("entries", [])
        if not scenes:
            return []
        # Use canonical timeline ranges when available (ADR 0020)
        beat_time_ranges = None
        if beat_timeline:
            beat_time_ranges = [
                (e["start_sec"], e["end_sec"]) if isinstance(e, dict) else (e.start_sec, e.end_sec)
                for e in beat_timeline
            ]
        mappings = map_scenes_to_beats(
            manifest_entries=scenes,
            story_beats=story_beats,
            word_timestamps=word_timestamps or [],
            audio_duration_sec=audio_duration_sec,
            beat_time_ranges=beat_time_ranges,
        )
        return _run_programmatic_scene_reviews(mappings)

    @staticmethod
    def _compute_entity_reviews(
        ctx: dict,
        story_beats: list[dict] | None,
        audio_duration_sec: float,
        rendered_scene_manifest: dict | None,
    ) -> list[SceneSemanticReview]:
        """FIX-4 (ADR 0030): per-scene entity-vs-beat reviews via the shared
        scene→beat mapping (carrying the threaded ``subject_name``) + FIX-3's
        ``_run_entity_binding_review``. Extracted from ``execute`` to keep its
        cognitive complexity under the gate threshold.
        """
        if not rendered_scene_manifest or not story_beats:
            return []
        entries = rendered_scene_manifest.get("entries", [])
        if not entries:
            return []
        beat_time_ranges = None
        bt_ctx = ctx.get("beat_timeline")
        if bt_ctx:
            beat_time_ranges = [
                (e["start_sec"], e["end_sec"]) if isinstance(e, dict) else (e.start_sec, e.end_sec)
                for e in bt_ctx
            ]
        mappings = map_scenes_to_beats(
            manifest_entries=entries,
            story_beats=story_beats,
            word_timestamps=ctx.get("word_timestamps") or [],
            audio_duration_sec=audio_duration_sec,
            beat_time_ranges=beat_time_ranges,
        )
        return _run_entity_binding_review(mappings, story_beats)

    def execute(
        self,
        job_id: int,
        topic: str = "",
        script: list[dict] | None = None,
        caption: str = "",
        safety_rules: list[str] | None = None,
        context: ReviewContext | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Merge context dict with legacy kwargs for backward compat
        ctx: dict[str, Any] = dict(context or {})
        _legacy_keys = (
            "audio_duration_sec",
            "visual_duration_sec",
            "narrative_structure",
            "unverified_claims",
            "visual_plan_actions",
            "story_mode_decision",
            "thumbnail_text",
            "main_entities",
            "story_beats",
            "word_timestamps",
            "rendered_scene_manifest",
            "beat_timeline",
            # FIX-4 (ADR 0030): threaded on ALL reviewer entry paths (normal,
            # retry, repair, resume) so the audio-stream re-probe fires
            # everywhere — a happy-path-only wire is inert in retry/repair.
            "voiceover_duration_sec",
        )
        for key in _legacy_keys:
            if key in kwargs and key not in ctx:
                ctx[key] = kwargs.pop(key)

        audio_duration_sec: float = ctx.get("audio_duration_sec", 0.0)
        visual_duration_sec: float = ctx.get("visual_duration_sec", 0.0)
        narrative_structure: list[dict] | None = ctx.get("narrative_structure")
        unverified_claims: list[dict] | None = ctx.get("unverified_claims")
        visual_plan_actions: list[dict] | None = ctx.get("visual_plan_actions")
        story_mode_decision: dict | None = ctx.get("story_mode_decision")
        thumbnail_text: str = ctx.get("thumbnail_text", "")
        main_entities: list[str] | None = ctx.get("main_entities")
        story_beats: list[dict] | None = ctx.get("story_beats")
        word_timestamps: list[dict] | None = ctx.get("word_timestamps")
        rendered_scene_manifest: dict | None = ctx.get("rendered_scene_manifest")
        voiceover_duration_sec: float = float(ctx.get("voiceover_duration_sec", 0.0) or 0.0)

        scenes = script or []
        logger.info("Reviewer: scenes=%d", len(scenes))

        # 1. Programmatic quality checks (fast, free, deterministic)
        av_sync = _check_av_sync(audio_duration_sec, visual_duration_sec)
        caption_q = _check_caption_quality(caption)
        fact_safety = _check_fact_safety(unverified_claims or [])
        narrative_q = _check_narrative_structure(
            narrative_structure or [],
        )
        programmatic_results = [av_sync, caption_q, fact_safety, narrative_q]

        checks = {
            "av_sync": av_sync,
            "caption_quality": caption_q,
            "fact_safety": fact_safety,
            "narrative_structure": narrative_q,
        }

        # FIX-4 (ADR 0030): defense-in-depth audio-stream re-probe. Runs as a
        # programmatic check (visible in programmatic_checks) AND a hard gate
        # below. Reuse the rendered manifest's video_path so no new param is
        # required on the engine wiring beyond voiceover_duration_sec.
        video_path = ""
        if isinstance(rendered_scene_manifest, dict):
            video_path = str(rendered_scene_manifest.get("video_path") or "")
        audio_trunc = _check_audio_not_truncated(video_path, voiceover_duration_sec)
        programmatic_results.append(audio_trunc)
        checks["audio_not_truncated"] = audio_trunc

        # 2. Hard gates: force FAIL before expensive LLM call
        hard_gate_result = self._check_hard_gates(
            checks,
            audio_duration_sec,
            visual_duration_sec,
            visual_plan_actions,
        )
        if hard_gate_result is not None:
            hard_gate_result["programmatic_checks"] = checks
            return hard_gate_result

        # 2b. New deterministic quality gates (Batch 2)
        diagnostics = self._populate_actual_detection_diagnostics(
            kwargs.get("diagnostics"),
        )

        # 2c. Timestamp-level semantic review (programmatic, no LLM)
        scene_reviews = self._run_timestamp_semantic_review(
            rendered_scene_manifest,
            story_beats,
            word_timestamps,
            audio_duration_sec,
            beat_timeline=ctx.get("beat_timeline"),
        )

        # 2d. FIX-4 (ADR 0030): per-scene entity-vs-beat review (extracted to
        # _compute_entity_reviews to keep execute() cognitive complexity under
        # the gate threshold). Reuses the scene→beat mapping (with the threaded
        # subject_name) + FIX-3's derive_expected_entities / entity_overlap —
        # the job_18 wrong-entity gate the total-duration reviewer could not see.
        entity_reviews = self._compute_entity_reviews(
            ctx, story_beats, audio_duration_sec, rendered_scene_manifest
        )

        gate_result = (
            self._fail_if_visual_coverage_failed(diagnostics)
            or self._fail_if_text_collision_failed(diagnostics)
            or self._fail_if_safe_area_failed(diagnostics)
            or self._fail_if_package_consistency_failed(
                story_mode_decision,
                thumbnail_text,
                main_entities,
                caption,
                topic,
                script,
            )
            or self._fail_if_audio_truncated(audio_trunc)
            or self._fail_if_entity_mismatch(entity_reviews)
            or self._fail_if_timestamp_semantic_failed(scene_reviews)
            or self._fail_if_semantic_review_failed(diagnostics)
        )
        if gate_result is not None:
            gate_result["programmatic_checks"] = checks
            return gate_result

        # 3. Build text for LLM review
        script_text = _format_script_text(scenes)
        safety_rules_text = _format_safety_rules(safety_rules or [])
        results_text = _format_programmatic_results(programmatic_results)

        # 4. LLM review
        agent_cfg = get_agent_config("reviewer")
        llm = OpenRouterClient(trace_writer=self._trace_writer)
        prompt = load_prompt("reviewer", REVIEWER_PROMPT, PROMPTS_DIR)
        messages = [
            {
                "role": "system",
                "content": prompt.format(
                    safety_rules_text=safety_rules_text,
                    programmatic_results=results_text,
                ),
            },
            {
                "role": "user",
                "content": (f"Topic: {topic}\n\nScript:\n{script_text}\n\nCaption: {caption}"),
            },
        ]
        if self._trace_writer:
            response = llm.chat_traced(
                model=agent_cfg["model"],
                messages=messages,
                job_id=job_id,
                agent=self.agent_name,
                task="final_review",
                temperature=agent_cfg["temperature"],
                max_completion_tokens=agent_cfg.get("max_completion_tokens"),
                prompt_template_id="reviewer.md",
            )
        else:
            response = llm.chat(
                model=agent_cfg["model"],
                messages=messages,
                temperature=agent_cfg["temperature"],
                max_completion_tokens=agent_cfg.get("max_completion_tokens"),
            )
        review = self._parse_review_response(response["content"])
        logger.info(
            "Reviewer: verdict=%s score=%d issues=%d",
            review["verdict"],
            review["score"],
            len(review["issues"]),
        )

        # 5. Return combined output
        output: dict[str, Any] = {
            "status": review["verdict"],
            "score": review["score"],
            "feedback": review["feedback"],
            "issues": review["issues"],
            "programmatic_checks": checks,
        }
        if scene_reviews:
            output["scene_semantic_reviews"] = [r.model_dump() for r in scene_reviews]
        # FIX-4 (ADR 0030): surface the per-scene entity-vs-beat reviews so the
        # unverifiable (empty subject_name) warnings are visible in the output
        # even when the gate does not hard-fail.
        if entity_reviews:
            output["entity_binding_reviews"] = [r.model_dump() for r in entity_reviews]
        return output

    def _parse_review_response(self, content: str) -> dict[str, Any]:
        """Parse the JSON review response from the LLM."""
        try:
            stripped = content.strip().strip("```json").strip("```").strip()
            data = json.loads(stripped)
            return {
                "verdict": data.get("verdict", "fail"),
                "score": data.get("score", 0),
                "feedback": data.get("feedback", "No feedback"),
                "issues": data.get("issues", []),
            }
        except (json.JSONDecodeError, KeyError):
            return {
                "verdict": "fail",
                "score": 0,
                "feedback": "Failed to parse review response",
                "issues": ["parse_error"],
            }
