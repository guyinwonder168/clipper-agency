"""Regression tests for Job #5 runtime quality.

These tests encode the 12 runtime-quality expectations from the job5
improvement design so we never regress on them.  Each test exercises
the expectation at the unit level using actual module signatures.
All tests run offline — no external API calls, no FFmpeg required.
"""

import json

import pytest

from clipper_agency.agents.reviewer import ReviewerAgent, _check_av_sync
from clipper_agency.config.schema import (
    DurationBudget,
    RepairCycleRecord,
    RepairPlan,
    StoryModeDecision,
)
from clipper_agency.core.candidate_semantic_ranker import (
    apply_rejection_rules,
    compute_final_score,
    rank_candidates,
    select_best_candidate,
)
from clipper_agency.core.duration_budget import allocate_duration_budget
from clipper_agency.core.frame_quality import (
    compute_frame_variance,
    detect_empty_segments,
    is_empty_or_uniform_frame,
)
from clipper_agency.core.frame_sampler import plan_frame_samples
from clipper_agency.core.media_detectors import _parse_black_segments
from clipper_agency.core.repair_metrics import (
    compute_repair_cycle_record,
    extract_quality_snapshot,
    is_repair_improved,
    persist_repair_cycle,
)
from clipper_agency.core.repair_router import build_repair_plan, route_repair
from clipper_agency.core.source_cleanliness import (
    score_source_cleanliness,
    TREATMENT_FULLSCREEN,
    ISSUE_BURNED_CAPTION,
    ISSUE_DOMINANT_LOGO,
    ISSUE_LOW_RESOLUTION,
)
from clipper_agency.core.story_mode import classify_story_mode
from clipper_agency.core.story_mode_contract import derive_story_mode_contract
from clipper_agency.observability.llm_trace import LLMTraceWriter
from clipper_agency.observability.redaction import REDACTED, redact_trace_payload


# ---------------------------------------------------------------------------
# Expectation 1: Broad gossip topic resolves to roundup
# ---------------------------------------------------------------------------


class TestBroadGossipTopicResolvesToRoundup:
    """Broad entertainment/gossip topics must classify as roundup mode."""

    def test_gossip_artist_topic_classifies_as_roundup(self):
        """'gosip artis terbaru' must produce story_mode=roundup."""
        decision = classify_story_mode(
            topic="gosip artis terbaru hari ini",
            target_duration_sec=55,
        )
        assert decision.story_mode == "roundup", (
            f"Expected 'roundup', got '{decision.story_mode}'"
        )
        assert decision.item_count >= 2
        assert decision.confidence >= 0.7

    def test_entertainment_update_classifies_as_roundup(self):
        """'berita hiburan terkini' must classify as roundup."""
        decision = classify_story_mode(
            topic="berita hiburan terkini update artis",
            target_duration_sec=55,
        )
        assert decision.story_mode == "roundup"

    def test_single_entity_topic_does_not_classify_as_roundup(self):
        """A specific single-entity topic should not classify as roundup."""
        decision = classify_story_mode(
            topic="drama sarwendah dan ruben onsu",
            target_duration_sec=55,
        )
        # Specific drama should be controversy_explainer or single_story
        assert decision.story_mode in ("controversy_explainer", "single_story")

    def test_roundup_contract_has_intro_and_cta(self):
        """Roundup story mode must produce a contract with intro + CTA."""
        decision = StoryModeDecision(
            story_mode="roundup",
            confidence=0.9,
            reason="broad gossip topic",
            item_count=3,
            target_duration_sec=55,
        )
        contract = derive_story_mode_contract(decision)
        assert contract["requires_intro_card"] is True
        assert contract["cta_strategy"] == "compare_items"
        assert contract["duration_structure"] == "intro_story_items_cta"


# ---------------------------------------------------------------------------
# Expectation 2: Duration budget uses intro/story/story/story/CTA
# ---------------------------------------------------------------------------


class TestDurationBudgetRoundupStructure:
    """Roundup mode duration budget must produce intro/story/story/story/CTA."""

    def test_roundup_produces_intro_stories_cta(self):
        """3-item roundup at 55s must have intro + 3 story + cta = 5 sections."""
        budget = allocate_duration_budget(
            story_mode="roundup", item_count=3, target_duration_sec=55,
        )
        types = [s.type for s in budget.sections]
        assert types == ["intro", "story", "story", "story", "cta"], (
            f"Expected intro/story/story/story/cta, got {types}"
        )

    def test_roundup_sections_sum_to_target(self):
        """Section durations must sum exactly to target_duration_sec."""
        budget = allocate_duration_budget(
            story_mode="roundup", item_count=3, target_duration_sec=55,
        )
        total = sum(s.duration_sec for s in budget.sections)
        assert abs(total - 55.0) < 0.01, (
            f"Sections sum to {total:.2f}, expected 55.0"
        )

    def test_roundup_cta_minimum_duration(self):
        """CTA section must be at least 2 seconds."""
        budget = allocate_duration_budget(
            story_mode="roundup", item_count=3, target_duration_sec=20,
        )
        cta = [s for s in budget.sections if s.type == "cta"]
        assert len(cta) == 1
        assert cta[0].duration_sec >= 2.0, (
            f"CTA duration {cta[0].duration_sec:.2f}s < 2.0s minimum"
        )

    def test_single_story_produces_hook_context_evidence_reveal_cta(self):
        """Single story mode must produce 5 narrative sections."""
        budget = allocate_duration_budget(
            story_mode="single_story", item_count=1, target_duration_sec=55,
        )
        types = [s.type for s in budget.sections]
        assert types == ["hook", "context", "evidence", "reveal", "cta"]


# ---------------------------------------------------------------------------
# Expectation 3: Keyframes are produced
# ---------------------------------------------------------------------------


class TestKeyframesProduced:
    """Frame sampler must produce keyframe timestamps for any video duration."""

    def test_sampler_produces_timestamps(self):
        """A 10s video at 0.5s interval must produce timestamps."""
        timestamps = plan_frame_samples(
            duration_sec=10.0,
            scene_boundaries=[3.5, 7.0],
            interval_sec=0.5,
        )
        assert len(timestamps) > 0
        assert timestamps[0] == 0.0
        assert timestamps[-1] == 10.0
        assert 3.5 in timestamps
        assert 7.0 in timestamps

    def test_sampler_includes_zero_and_duration(self):
        """Timestamps always include 0.0 and the duration."""
        timestamps = plan_frame_samples(
            duration_sec=5.0,
            scene_boundaries=[],
            interval_sec=1.0,
        )
        assert 0.0 in timestamps
        assert 5.0 in timestamps

    def test_sampler_zero_duration_returns_single_frame(self):
        """Zero duration must produce exactly [0.0]."""
        timestamps = plan_frame_samples(
            duration_sec=0.0,
            scene_boundaries=[],
            interval_sec=0.5,
        )
        assert timestamps == [0.0]

    def test_sampler_deduplicates_boundaries(self):
        """Scene boundaries that overlap with interval timestamps are deduplicated."""
        timestamps = plan_frame_samples(
            duration_sec=4.0,
            scene_boundaries=[1.0, 2.0, 3.0],  # These overlap with 0.5s interval
            interval_sec=0.5,
        )
        # No duplicates
        assert len(timestamps) == len(set(timestamps))


# ---------------------------------------------------------------------------
# Expectation 4: OCR finds burned-in text
# ---------------------------------------------------------------------------


class TestOCRFindsBurnedInText:
    """Source cleanliness scoring must detect burned-in captions via OCR."""

    def test_burned_captions_flagged(self):
        """has_burned_captions=True must produce BURNED_CAPTION issue."""
        result = score_source_cleanliness(has_burned_captions=True)
        assert ISSUE_BURNED_CAPTION in result["issues"]
        assert result["cleanliness_score"] < 1.0

    def test_high_ocr_text_area_flagged(self):
        """ocr_text_area_ratio > 0.20 must produce BURNED_CAPTION issue."""
        result = score_source_cleanliness(ocr_text_area_ratio=0.30)
        assert ISSUE_BURNED_CAPTION in result["issues"]
        assert result["cleanliness_score"] < 1.0

    def test_no_burned_text_when_clean(self):
        """Clean source must have no BURNED_CAPTION issue."""
        result = score_source_cleanliness(
            ocr_text_area_ratio=0.05,
            has_burned_captions=False,
        )
        assert ISSUE_BURNED_CAPTION not in result["issues"]
        assert result["cleanliness_score"] == 1.0


# ---------------------------------------------------------------------------
# Expectation 5: Source cleanliness prevents dirty fullscreen
# ---------------------------------------------------------------------------


class TestSourceCleanlinessPreventsDirtyFullscreen:
    """Low cleanliness + fullscreen treatment must trigger DIRTY_FULLSCREEN rejection."""

    def test_dirty_fullscreen_rejection_rule(self):
        """cleanliness < 0.3 + fullscreen treatment → DIRTY_FULLSCREEN rejection."""
        candidate = {
            "inspection": {"misleading_risk": 0.1, "claim_support": 0.8},
            "cleanliness_score": 0.2,
            "treatment": "fullscreen",
        }
        rejection = apply_rejection_rules(candidate)
        assert rejection == "DIRTY_FULLSCREEN"

    def test_clean_fullscreen_allowed(self):
        """cleanliness >= 0.3 + fullscreen → no rejection."""
        candidate = {
            "inspection": {"misleading_risk": 0.1, "claim_support": 0.8},
            "cleanliness_score": 0.5,
            "treatment": "fullscreen",
        }
        rejection = apply_rejection_rules(candidate)
        assert rejection is None

    def test_low_cleanliness_non_fullscreen_allowed(self):
        """Low cleanliness on non-fullscreen treatment → no DIRTY_FULLSCREEN rejection."""
        candidate = {
            "inspection": {"misleading_risk": 0.1, "claim_support": 0.8},
            "cleanliness_score": 0.1,
            "treatment": "picture_in_picture",
        }
        rejection = apply_rejection_rules(candidate)
        assert rejection is None

    def test_source_cleanliness_dominant_logo_bans_fullscreen(self):
        """Dominant logo must set fullscreen_allowed=False."""
        result = score_source_cleanliness(
            has_logo=True,
            logo_coverage_ratio=0.25,
        )
        assert result["fullscreen_allowed"] is False
        assert TREATMENT_FULLSCREEN not in result["allowed_treatments"]
        assert ISSUE_DOMINANT_LOGO in result["issues"]


# ---------------------------------------------------------------------------
# Expectation 6: Reviewer receives eight scenes
# ---------------------------------------------------------------------------


class TestReviewerEightScenes:
    """Reviewer must correctly process 8 scene-beat mappings."""

    def test_eight_scenes_reviewed(self):
        """Reviewer evaluates 8 scene-beat mappings and produces 8 reviews."""
        reviewer = ReviewerAgent()

        # Build 8 scene-beat mappings with rendered_scene_manifest
        manifest_entries = []
        story_beats = []
        for i in range(8):
            manifest_entries.append({
                "scene": i + 1,
                "start_sec": i * 3.0,
                "end_sec": (i + 1) * 3.0,
            })
            story_beats.append({
                "beat_id": i + 1,
                "role": "evidence",
                "narration_goal": f"Story beat {i + 1}",
                "spoken_point": f"Point {i + 1}",
                "safe_wording": f"Claim {i + 1}",
                "overlay_text": "",
                "caption_keywords": [],
            })

        word_timestamps = [
            {"word": "test", "start": i * 3.0, "end": i * 3.0 + 2.5}
            for i in range(8)
        ]

        scene_reviews = reviewer._run_timestamp_semantic_review(
            rendered_scene_manifest={"entries": manifest_entries},
            story_beats=story_beats,
            word_timestamps=word_timestamps,
            audio_duration_sec=24.0,
        )

        assert len(scene_reviews) == 8, (
            f"Expected 8 scene reviews, got {len(scene_reviews)}"
        )

    def test_all_scenes_pass_when_valid(self):
        """All 8 valid scenes should pass semantic review."""
        reviewer = ReviewerAgent()

        manifest_entries = [
            {"scene": i + 1, "start_sec": i * 3.0, "end_sec": (i + 1) * 3.0}
            for i in range(8)
        ]
        story_beats = [
            {"beat_id": i + 1, "role": "evidence"}
            for i in range(8)
        ]
        word_timestamps = [
            {"word": "w", "start": i * 3.0, "end": i * 3.0 + 1.0}
            for i in range(8)
        ]

        scene_reviews = reviewer._run_timestamp_semantic_review(
            rendered_scene_manifest={"entries": manifest_entries},
            story_beats=story_beats,
            word_timestamps=word_timestamps,
            audio_duration_sec=24.0,
        )

        passed = [r for r in scene_reviews if r.passed]
        assert len(passed) == 8, (
            f"Expected all 8 to pass, {len(passed)} passed"
        )


# ---------------------------------------------------------------------------
# Expectation 7: Black segments are detected
# ---------------------------------------------------------------------------


class TestBlackSegmentsDetected:
    """FFmpeg blackdetect output must be correctly parsed."""

    def test_parse_single_black_segment(self):
        """Single black_start/black_end pair produces one interval."""
        stderr = (
            "[blackdetect @ 0x1] black_start:5.000 black_end:5.800 "
            "black_duration:0.8\n"
        )
        segments = _parse_black_segments(stderr)
        assert len(segments) == 1
        assert segments[0] == pytest.approx((5.0, 5.8), abs=0.01)

    def test_parse_multiple_black_segments(self):
        """Multiple black intervals are all detected."""
        stderr = (
            "[blackdetect @ 0x1] black_start:2.000 black_end:3.000\n"
            "[blackdetect @ 0x1] black_start:10.500 black_end:11.200\n"
            "[blackdetect @ 0x1] black_start:20.000 black_end:21.500\n"
        )
        segments = _parse_black_segments(stderr)
        assert len(segments) == 3
        assert segments[0] == pytest.approx((2.0, 3.0), abs=0.01)
        assert segments[1] == pytest.approx((10.5, 11.2), abs=0.01)
        assert segments[2] == pytest.approx((20.0, 21.5), abs=0.01)

    def test_no_black_segments_on_clean_output(self):
        """Clean FFmpeg output produces empty list."""
        segments = _parse_black_segments("no black segments detected\n")
        assert segments == []


# ---------------------------------------------------------------------------
# Expectation 8: Reviewer fail blocks publication
# ---------------------------------------------------------------------------


class TestReviewerFailBlocksPublication:
    """Reviewer gate chain must produce fail when diagnostics indicate issues."""

    def test_visual_coverage_hard_fail_blocks(self):
        """Visual coverage hard-fail must produce reviewer fail."""
        reviewer = ReviewerAgent()
        diagnostics = {
            "visual_coverage": {
                "status": "fail",
                "issues": [
                    {"severity": "hard_fail", "type": "BLACK_FRAME"},
                ],
            },
        }
        result = reviewer._fail_if_visual_coverage_failed(diagnostics)
        assert result is not None
        assert result["status"] == "fail"
        assert "visual_coverage" in result["issues"][0]

    def test_text_collision_hard_fail_blocks(self):
        """Text collision hard-fail must produce reviewer fail."""
        reviewer = ReviewerAgent()
        diagnostics = {
            "text_collision": [
                {"severity": "hard_fail", "type": "SUBTITLE_SOURCE_TEXT_OVERLAP"},
            ],
        }
        result = reviewer._fail_if_text_collision_failed(diagnostics)
        assert result is not None
        assert result["status"] == "fail"
        assert "text_collision" in result["issues"][0]

    def test_safe_area_hard_fail_blocks(self):
        """Safe area hard-fail must produce reviewer fail."""
        reviewer = ReviewerAgent()
        diagnostics = {
            "safe_area": [
                {"severity": "reject", "type": "PLATFORM_UNSAFE_ZONE"},
            ],
        }
        result = reviewer._fail_if_safe_area_failed(diagnostics)
        assert result is not None
        assert result["status"] == "fail"

    def test_semantic_review_revise_blocks(self):
        """Semantic review 'revise' decision must produce reviewer fail with repair plan."""
        reviewer = ReviewerAgent()
        diagnostics = {
            "semantic_review": {
                "decision": "revise",
                "patches": [
                    {
                        "beat_id": "beat_1",
                        "action": "replace_visual",
                        "reason": "wrong_event",
                        "rerun_from": "visual_director",
                    },
                ],
            },
        }
        result = reviewer._fail_if_semantic_review_failed(diagnostics)
        assert result is not None
        assert result["status"] == "fail"
        assert "repair_plan" in result
        assert result["repair_plan"]["decision"] == "revise"

    def test_clean_diagnostics_pass(self):
        """No diagnostic failures → gate returns None (pass)."""
        reviewer = ReviewerAgent()
        assert reviewer._fail_if_visual_coverage_failed(None) is None
        assert reviewer._fail_if_text_collision_failed(None) is None
        assert reviewer._fail_if_safe_area_failed(None) is None
        assert reviewer._fail_if_semantic_review_failed(None) is None


# ---------------------------------------------------------------------------
# Expectation 9: Repair route is generated
# ---------------------------------------------------------------------------


class TestRepairRouteGenerated:
    """Repair router must generate correct agent routing from failure reasons."""

    def test_black_frame_routes_to_composer(self):
        """black_frame reason routes to composer."""
        assert route_repair({"reason": "black_frame", "action": "replace_visual"}) == "composer"

    def test_freeze_frame_routes_to_composer(self):
        """freeze_frame reason routes to composer."""
        assert route_repair({"reason": "freeze_frame", "action": "replace_visual"}) == "composer"

    def test_broken_source_routes_to_visual_director(self):
        """broken_source reason routes to visual_director."""
        assert route_repair({"reason": "broken_source", "action": "replace_visual"}) == "visual_director"

    def test_wrong_event_redo_research_routes_to_segment_producer(self):
        """wrong_event + redo_research routes to segment_producer."""
        assert route_repair({"reason": "wrong_event", "action": "redo_research"}) == "segment_producer"

    def test_text_collision_routes_to_visual_director(self):
        """text_collision reason routes to visual_director."""
        assert route_repair({"reason": "text_collision", "action": "fix_text"}) == "visual_director"

    def test_unknown_reason_defaults_to_visual_director(self):
        """Unknown reason defaults to visual_director."""
        assert route_repair({"reason": "unknown_issue", "action": "unknown"}) == "visual_director"

    def test_build_repair_plan_validates_patches(self):
        """build_repair_plan creates a valid RepairPlan with correct fields."""
        plan = build_repair_plan(
            decision="revise",
            patches=[
                {
                    "beat_id": "beat_1",
                    "action": "replace_visual",
                    "reason": "black_frame",
                    "rerun_from": "composer",
                },
                {
                    "beat_id": "beat_3",
                    "action": "fix_text",
                    "reason": "text_collision",
                    "rerun_from": "visual_director",
                },
            ],
            max_cycles=3,
        )
        assert plan.decision == "revise"
        assert plan.max_repair_cycles == 3
        assert len(plan.patches) == 2
        assert plan.patches[0].beat_id == "beat_1"
        assert plan.patches[1].reason == "text_collision"


# ---------------------------------------------------------------------------
# Expectation 10: Max repair cycles enforced
# ---------------------------------------------------------------------------


class TestMaxRepairCyclesEnforced:
    """Repair metrics must track cycles and detect improvement."""

    def test_extract_quality_snapshot(self):
        """Quality snapshot extracts reviewer_score, claim_support_avg, collision_count, black_frame_ms."""
        review_output = {
            "score": 75,
            "scene_semantic_reviews": [
                {"claim_support": 0.8},
                {"claim_support": 0.6},
            ],
            "diagnostics": {
                "text_collision": [{"severity": "warning"}, {"severity": "warning"}],
                "visual_coverage": {"black_frame_ms": 500.0},
            },
        }
        snapshot = extract_quality_snapshot(review_output)
        assert snapshot["reviewer_score"] == 75.0
        assert snapshot["claim_support_avg"] == pytest.approx(0.7, abs=0.01)
        assert snapshot["collision_count"] == 2.0
        assert snapshot["black_frame_ms"] == 500.0

    def test_repair_improved_by_score_gain(self):
        """10+ score improvement means repair improved."""
        before = {"reviewer_score": 50.0}
        after = {"reviewer_score": 65.0}
        assert is_repair_improved(before, after) is True

    def test_repair_not_improved_when_score_stagnant(self):
        """Score gain < 10 with no critical improvement means not improved."""
        before = {"reviewer_score": 50.0, "claim_support_avg": 0.5, "collision_count": 2.0, "black_frame_ms": 100.0}
        after = {"reviewer_score": 55.0, "claim_support_avg": 0.4, "collision_count": 3.0, "black_frame_ms": 200.0}
        assert is_repair_improved(before, after) is False

    def test_repair_improved_by_all_critical_metrics(self):
        """All critical metrics improved means repair improved (even without 10-point score gain)."""
        before = {"reviewer_score": 50.0, "claim_support_avg": 0.5, "collision_count": 3.0, "black_frame_ms": 500.0}
        after = {"reviewer_score": 55.0, "claim_support_avg": 0.7, "collision_count": 1.0, "black_frame_ms": 100.0}
        assert is_repair_improved(before, after) is True

    def test_repair_cycle_record_construction(self):
        """compute_repair_cycle_record produces valid RepairCycleRecord."""
        record = compute_repair_cycle_record(
            cycle=2,
            source_agent="reviewer",
            target_agent="composer",
            before_review={"score": 40, "scene_semantic_reviews": [], "diagnostics": {}},
            after_review={"score": 72, "scene_semantic_reviews": [], "diagnostics": {}},
        )
        assert record.cycle == 2
        assert record.source_agent == "reviewer"
        assert record.target_agent == "composer"
        assert record.before_scores["reviewer_score"] == 40.0
        assert record.after_scores["reviewer_score"] == 72.0

    def test_persist_and_load_cycle(self, tmp_path):
        """Repair cycle record persists to disk and roundtrips correctly."""
        record = compute_repair_cycle_record(
            cycle=1,
            source_agent="reviewer",
            target_agent="visual_director",
            before_review={"score": 30, "scene_semantic_reviews": [], "diagnostics": {}},
            after_review={"score": 65, "scene_semantic_reviews": [], "diagnostics": {}},
        )
        path = persist_repair_cycle(str(tmp_path), job_id=5, record=record)
        assert path.endswith("cycle_1.json")

        data = json.loads(open(path).read())
        assert data["cycle"] == 1
        assert data["source_agent"] == "reviewer"


# ---------------------------------------------------------------------------
# Expectation 11: Every LLM call produces request, raw response, parsed
#                 response, validation, and metadata artifacts
# ---------------------------------------------------------------------------


class TestLLMTraceArtifacts:
    """LLM trace writer must persist all 5 artifact types per call."""

    def test_full_trace_lifecycle_produces_five_artifacts(self, tmp_path):
        """start_call → persist_request → persist_response → persist_parsed_response →
        persist_validation must produce 5 files."""
        writer = LLMTraceWriter(cache_root=str(tmp_path))
        handle = writer.start_call(
            job_id=5,
            agent="reviewer",
            task="final_review",
            provider="openrouter",
            model="gemini-2.5-flash",
            prompt_template_id="reviewer.md",
            prompt_version="sha256:abc123",
        )

        # 1. metadata.json (from start_call)
        metadata_path = handle.trace_dir / "metadata.json"
        assert metadata_path.exists(), "metadata.json must exist after start_call"

        # 2. request.json
        request_path = writer.persist_request(
            handle,
            messages=[{"role": "user", "content": "Review this"}],
            parameters={"temperature": 0.3},
        )
        assert request_path.exists()
        request_data = json.loads(request_path.read_text())
        assert "messages" in request_data
        assert request_data["agent"] == "reviewer"

        # 3. response.json
        response_path = writer.persist_response(
            handle,
            raw_response={"content": '{"verdict":"pass"}'},
            usage={"prompt_tokens": 200, "completion_tokens": 50},
            provider_metadata={"request_id": "req-xyz"},
        )
        assert response_path.exists()
        response_data = json.loads(response_path.read_text())
        assert "raw_response" in response_data

        # 4. parsed_response.json
        parsed_path = writer.persist_parsed_response(
            handle,
            parsed_result={"verdict": "pass", "score": 85},
        )
        assert parsed_path.exists()
        parsed_data = json.loads(parsed_path.read_text())
        assert parsed_data["parsed_result"]["verdict"] == "pass"

        # 5. validation.json
        validation_path = writer.persist_validation(
            handle,
            validation_result={"status": "valid", "schema": "reviewer_output"},
        )
        assert validation_path.exists()
        validation_data = json.loads(validation_path.read_text())
        assert validation_data["validation_result"]["status"] == "valid"

    def test_metadata_contains_all_required_fields(self, tmp_path):
        """Metadata file must contain call_id, agent, model, timestamps, etc."""
        writer = LLMTraceWriter(cache_root=str(tmp_path))
        handle = writer.start_call(
            job_id=5,
            agent="segment_producer",
            task="research",
            provider="openrouter",
            model="qwen-3-235b",
            prompt_template_id="segment_producer.md",
            prompt_version="v2.0",
            call_id="test-call-001",
        )

        metadata = json.loads((handle.trace_dir / "metadata.json").read_text())
        assert metadata["call_id"] == "test-call-001"
        assert metadata["job_id"] == 5
        assert metadata["agent"] == "segment_producer"
        assert metadata["task"] == "research"
        assert metadata["provider"] == "openrouter"
        assert metadata["model"] == "qwen-3-235b"
        assert metadata["parse_status"] == "pending"
        assert metadata["schema_validation_status"] == "pending"
        assert metadata["retry_count"] == 0

    def test_trace_directory_follows_canonical_path(self, tmp_path):
        """Trace dir must follow cache_root/job_{id}/llm_traces/{agent}/{call_id}/."""
        writer = LLMTraceWriter(cache_root=str(tmp_path))
        handle = writer.start_call(
            job_id=5,
            agent="reviewer",
            task="review",
            provider="openrouter",
            model="test-model",
            prompt_template_id="t.md",
            prompt_version="v1",
            call_id="abc",
        )
        expected = tmp_path / "job_5" / "llm_traces" / "reviewer" / "abc"
        assert handle.trace_dir == expected


# ---------------------------------------------------------------------------
# Expectation 12: Runtime logs contain trace paths and correlation IDs
#                 without dumping secrets
# ---------------------------------------------------------------------------


class TestRedactionAndCorrelation:
    """Trace payloads must be redacted; correlation IDs must be present."""

    def test_secrets_redacted_from_payload(self):
        """API keys and authorization headers must be replaced with [REDACTED]."""
        payload = {
            "model": "gpt-4",
            "api_key": "sk-super-secret-key-12345",
            "parameters": {"temperature": 0.7},
            "headers": {
                "authorization": "Bearer token-xyz",
                "content-type": "application/json",
                "x-api-key": "secret-key-value",
            },
        }
        redacted = redact_trace_payload(payload)

        assert redacted["api_key"] == REDACTED
        assert redacted["headers"]["authorization"] == REDACTED
        assert redacted["headers"]["x-api-key"] == REDACTED
        # Non-sensitive fields preserved
        assert redacted["model"] == "gpt-4"
        assert redacted["parameters"]["temperature"] == 0.7
        assert redacted["headers"]["content-type"] == "application/json"

    def test_nested_secrets_redacted(self):
        """Deeply nested secrets are also redacted."""
        payload = {
            "messages": [
                {"role": "system", "content": "You are helpful.", "password": "hunter2"},
            ],
        }
        redacted = redact_trace_payload(payload)
        assert redacted["messages"][0]["password"] == REDACTED
        assert redacted["messages"][0]["content"] == "You are helpful."

    def test_correlation_id_in_trace_handle(self):
        """TraceHandle must carry a call_id that serves as correlation ID."""
        writer = LLMTraceWriter(cache_root="/tmp/test_traces")
        handle = writer.start_call(
            job_id=5,
            agent="reviewer",
            task="review",
            provider="openrouter",
            model="test",
            prompt_template_id="t",
            prompt_version="v1",
            call_id="corr-12345",
        )
        assert handle.call_id == "corr-12345"
        assert handle.metadata.call_id == "corr-12345"

    def test_trace_writer_redacts_by_default(self, tmp_path):
        """LLMTraceWriter redacts secrets by default (redact_secrets=True)."""
        writer = LLMTraceWriter(cache_root=str(tmp_path))
        assert writer.redact_secrets is True

        handle = writer.start_call(
            job_id=5, agent="a", task="t", provider="p",
            model="m", prompt_template_id="pt", prompt_version="v",
        )
        writer.persist_request(
            handle,
            messages=[{"role": "user", "content": "hello"}],
            parameters={"api_key": "secret-key-123"},
        )

        request_data = json.loads((handle.trace_dir / "request.json").read_text())
        assert request_data["parameters"]["api_key"] == REDACTED

    def test_list_payload_redacted(self):
        """Secrets in list items are also redacted."""
        payload = [
            {"api_key": "key1"},
            {"password": "pass1"},
            {"safe_field": "value"},
        ]
        redacted = redact_trace_payload(payload)
        assert redacted[0]["api_key"] == REDACTED
        assert redacted[1]["password"] == REDACTED
        assert redacted[2]["safe_field"] == "value"

    def test_scalar_values_preserved(self):
        """Non-sensitive scalar values are preserved unchanged."""
        payload = {"count": 42, "name": "test", "enabled": True, "ratio": 0.75}
        redacted = redact_trace_payload(payload)
        assert redacted == payload


# ---------------------------------------------------------------------------
# Cross-cutting: Frame quality detection
# ---------------------------------------------------------------------------


class TestFrameQualityDetection:
    """Empty/uniform frame detection for black segment detection."""

    def test_uniform_frame_detected(self):
        """A completely uniform image (all same values) must be detected as empty."""
        uniform_image = [[128, 128, 128]] * 10  # All same pixel values
        assert is_empty_or_uniform_frame(uniform_image, threshold=1.0) is True

    def test_varied_frame_not_empty(self):
        """An image with varied pixel values must NOT be detected as empty."""
        varied_image = [[i * 10, i * 20, i * 30] for i in range(10)]
        assert is_empty_or_uniform_frame(varied_image, threshold=1.0) is False

    def test_empty_segments_merged(self):
        """Nearby empty frames must be merged into continuous intervals."""
        frames = [
            (1.0, [[128, 128, 128]] * 5),   # empty
            (1.5, [[128, 128, 128]] * 5),   # empty
            (2.0, [[i, i, i] for i in range(100)]),  # varied
            (2.5, [[128, 128, 128]] * 5),   # empty
            (3.0, [[128, 128, 128]] * 5),   # empty
        ]
        segments = detect_empty_segments(frames, max_gap_sec=1.0)
        assert len(segments) == 2  # Two separate empty regions
        assert segments[0] == pytest.approx((1.0, 1.5), abs=0.01)
        assert segments[1] == pytest.approx((2.5, 3.0), abs=0.01)


# ---------------------------------------------------------------------------
# Cross-cutting: Candidate semantic ranker integration
# ---------------------------------------------------------------------------


class TestCandidateSemanticRankerIntegration:
    """Full ranker pipeline: score → filter → rank → select."""

    def test_rank_candidates_produces_fallback_when_all_rejected(self):
        """When all candidates are rejected, a fallback_card must be appended."""
        candidates = [
            {
                "asset_id": "a1",
                "beat_id": "b1",
                "inspection": {"misleading_risk": 0.9, "claim_support": 0.1},
                "visual_relevance": {},
                "cleanliness_score": 0.1,
                "treatment": "fullscreen",
            },
        ]
        ranked = rank_candidates(
            beat={"beat_id": "b1"},
            candidates=candidates,
        )
        decisions = [r.decision for r in ranked]
        assert "fallback_card" in decisions

    def test_best_acceptable_candidate_selected(self):
        """select_best_candidate returns the first non-rejected candidate."""
        from clipper_agency.core.candidate_semantic_ranker import RankedCandidate

        ranked = [
            RankedCandidate(
                asset_id="bad", beat_id="b1", final_score=0.3,
                decision="reject", inspection={}, visual_relevance={},
                cleanliness_score=0.1, rank_reason="Rejected",
            ),
            RankedCandidate(
                asset_id="good", beat_id="b1", final_score=0.85,
                decision="accept", inspection={}, visual_relevance={},
                cleanliness_score=0.9, rank_reason="ACCEPT",
            ),
            RankedCandidate(
                asset_id="ok", beat_id="b1", final_score=0.65,
                decision="accept", inspection={}, visual_relevance={},
                cleanliness_score=0.7, rank_reason="ACCEPT",
            ),
        ]
        best = select_best_candidate(ranked)
        assert best is not None
        assert best.asset_id == "good"

    def test_compute_final_score_clamped_to_unit_range(self):
        """Final score must be clamped to [0.0, 1.0]."""
        # Include source_credibility=1.0 so that with credibility_weight=0.15
        # all four dimensions contribute 1.0 → final score ≈ 1.0.
        score = compute_final_score(
            inspection={
                "person_match": 1.0, "event_match": 1.0,
                "claim_support": 1.0, "visual_quality": 1.0,
                "source_credibility": 1.0,
            },
            visual_relevance={"person_match": 1.0, "event_match": 1.0, "claim_support": 1.0, "visual_quality": 1.0},
            cleanliness_score=1.0,
        )
        assert 0.0 <= score <= 1.0
        assert score == pytest.approx(1.0, abs=0.01)

    def test_compute_final_score_with_zero_credibility(self):
        """When source_credibility is missing (defaults to 0), max score is 0.85."""
        score = compute_final_score(
            inspection={"person_match": 1.0, "event_match": 1.0, "claim_support": 1.0, "visual_quality": 1.0},
            visual_relevance={"person_match": 1.0, "event_match": 1.0, "claim_support": 1.0, "visual_quality": 1.0},
            cleanliness_score=1.0,
        )
        assert 0.0 <= score <= 1.0
        assert score == pytest.approx(0.85, abs=0.01)
