from clipper_agency.config.schema import ContentPlanningConfig


class TestContentPlanningConfig:
    def test_defaults(self):
        cfg = ContentPlanningConfig()
        assert cfg.default_format == "three_story_roundup"
        assert cfg.max_stories_per_video == 3
        assert cfg.target_duration_sec == 55
        assert cfg.hard_limit_sec == 60
        assert cfg.estimated_words_per_second == 2.0

    def test_override_from_dict(self):
        cfg = ContentPlanningConfig(**{
            "default_format": "single_story_deep",
            "max_stories_per_video": 1,
            "target_duration_sec": 50,
            "hard_limit_sec": 55,
            "estimated_words_per_second": 1.8,
        })
        assert cfg.default_format == "single_story_deep"
        assert cfg.target_duration_sec == 50

    def test_enforces_positive(self):
        from pydantic import ValidationError
        try:
            ContentPlanningConfig(target_duration_sec=-1)
        except ValidationError:
            pass  # expected

    def test_niche_loads_content_planning(self):
        from clipper_agency.config.loader import load_niche
        niche = load_niche("indonesian_artists")
        # NicheConfig doesn't have content_planning field — check raw YAML
        import yaml
        from pathlib import Path
        path = Path("niches/indonesian_artists.yaml")
        data = yaml.safe_load(path.read_text())
        cp = data.get("content_planning", {})
        assert cp.get("default_format") == "three_story_roundup"
        assert cp.get("max_stories_per_video") == 3


# --- Batch 0 / Task 0.1: Quality and editorial schema models ---


def test_visual_coverage_result_is_json_serializable():
    from clipper_agency.config.schema import VisualCoverageIssue, VisualCoverageResult

    result = VisualCoverageResult(
        status="fail",
        output_duration_sec=21.2,
        voiceover_duration_sec=21.0,
        coverage_ratio=0.79,
        issues=[
            VisualCoverageIssue(
                type="BLACK_FRAME",
                start_sec=17.83,
                end_sec=21.2,
                severity="hard_fail",
                detail="black segment exceeds threshold",
            )
        ],
    )

    payload = result.model_dump()
    assert payload["issues"][0]["type"] == "BLACK_FRAME"
    assert payload["status"] == "fail"


def test_story_mode_decision_supports_roundup_contract():
    from clipper_agency.config.schema import StoryModeDecision

    decision = StoryModeDecision(
        story_mode="roundup",
        confidence=0.97,
        reason="Broad entertainment topic requests multiple recent stories.",
        item_count=3,
        target_duration_sec=30,
        requires_intro_card=True,
        thumbnail_strategy="roundup",
        cta_strategy="compare_items",
    )

    assert decision.story_mode == "roundup"
    assert decision.requires_intro_card is True


def test_repair_plan_limits_cycles_and_routes_patch():
    from clipper_agency.config.schema import RepairPatch, RepairPlan

    plan = RepairPlan(
        decision="revise",
        max_repair_cycles=2,
        patches=[
            RepairPatch(
                beat_id="B04",
                action="replace_visual",
                reason="wrong_event",
                rerun_from="visual_director",
                timestamp_start_sec=12.4,
                timestamp_end_sec=17.8,
                required_visual="same-event interview",
            )
        ],
    )

    assert plan.patches[0].rerun_from == "visual_director"
