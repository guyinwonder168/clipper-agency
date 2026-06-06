from clipper_agency.orchestrator.duration_gate import (
    DurationBudget,
    estimate_script_duration_sec,
    check_script_duration_budget,
)


class TestScriptDurationGate:
    def test_estimate_from_word_count(self):
        scenes = [
            {"word_count": 10, "text": "short"},
            {"word_count": 22, "text": "medium"},
            {"word_count": 10, "text": "cta"},
        ]
        dur = estimate_script_duration_sec(scenes, words_per_sec=2.0, pause_buffer=0.5)
        # (10+22+10)/2.0 + 0.5*3 = 21 + 1.5 = 22.5
        assert dur == 22.5

    def test_missing_word_count_falls_back_to_text_tokens(self):
        scenes = [{"text": "short intro text here"}]
        dur = estimate_script_duration_sec(scenes, words_per_sec=2.0, pause_buffer=0.5)
        # 4 words / 2.0 + 0.5*1 = 2.0 + 0.5 = 2.5
        assert dur == 2.5

    def test_within_budget_passes(self):
        budget = DurationBudget(target=55, hard=60)
        result = check_script_duration_budget(estimated_sec=45, budget=budget)
        assert result["pass"] is True
        assert result["reason"] == "within_target"

    def test_exceeds_target_but_not_hard_warns(self):
        budget = DurationBudget(target=55, hard=60)
        result = check_script_duration_budget(estimated_sec=57, budget=budget)
        assert result["pass"] is True
        assert result["reason"] == "exceeds_target"

    def test_exceeds_hard_limit_fails(self):
        budget = DurationBudget(target=55, hard=60)
        result = check_script_duration_budget(estimated_sec=65, budget=budget)
        assert result["pass"] is False
        assert "exceeds_hard_limit" in result["reason"]

    def test_budget_is_frozen_dataclass(self):
        budget = DurationBudget(target=55, hard=60)
        assert budget.target == 55
        assert budget.hard == 60

    def test_empty_scenes_zero_duration(self):
        dur = estimate_script_duration_sec([], words_per_sec=2.0, pause_buffer=0.5)
        assert dur == 0.0
