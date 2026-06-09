"""Tests for editorial duration budget allocator — TDD RED phase."""

import pytest

from clipper_agency.config.schema import DurationBudget, DurationBudgetSection
from clipper_agency.core.duration_budget import allocate_duration_budget


class TestRoundupMode:
    """Roundup mode: intro + N story sections + cta."""

    def test_roundup_duration_budget_allocates_intro_items_and_cta(self):
        budget = allocate_duration_budget(
            story_mode="roundup", item_count=3, target_duration_sec=21
        )
        assert budget.target_duration_sec == 21
        assert [s.type for s in budget.sections] == [
            "intro", "story", "story", "story", "cta",
        ]
        assert sum(s.duration_sec for s in budget.sections) == pytest.approx(21)

    def test_roundup_two_items(self):
        budget = allocate_duration_budget(
            story_mode="roundup", item_count=2, target_duration_sec=20
        )
        assert [s.type for s in budget.sections] == [
            "intro", "story", "story", "cta",
        ]
        assert sum(s.duration_sec for s in budget.sections) == pytest.approx(20)


class TestSingleStoryMode:
    """single_story: hook + context + evidence + reveal + cta."""

    def test_single_story_budget_allocates_hook_context_evidence_reveal_cta(self):
        budget = allocate_duration_budget(
            story_mode="single_story", item_count=1, target_duration_sec=25
        )
        assert [s.type for s in budget.sections] == [
            "hook", "context", "evidence", "reveal", "cta",
        ]
        assert sum(s.duration_sec for s in budget.sections) == pytest.approx(25)


class TestNarrativeAliases:
    """controversy_explainer and breaking_news use same allocation as single_story."""

    def test_controversy_explainer_same_as_single_story(self):
        budget = allocate_duration_budget(
            story_mode="controversy_explainer", item_count=1, target_duration_sec=30
        )
        assert [s.type for s in budget.sections] == [
            "hook", "context", "evidence", "reveal", "cta",
        ]
        assert sum(s.duration_sec for s in budget.sections) == pytest.approx(30)

    def test_breaking_news_same_as_single_story(self):
        budget = allocate_duration_budget(
            story_mode="breaking_news", item_count=1, target_duration_sec=30
        )
        assert [s.type for s in budget.sections] == [
            "hook", "context", "evidence", "reveal", "cta",
        ]
        assert sum(s.duration_sec for s in budget.sections) == pytest.approx(30)


class TestDurationIntegrity:
    """Sums must always equal target_duration_sec."""

    @pytest.mark.parametrize(
        "story_mode,item_count,target",
        [
            ("roundup", 3, 21),
            ("roundup", 5, 60),
            ("single_story", 1, 25),
            ("controversy_explainer", 1, 40),
            ("breaking_news", 1, 15),
            ("unknown_mode", 1, 30),
            ("roundup", 1, 10),
        ],
    )
    def test_durations_sum_to_target(self, story_mode, item_count, target):
        budget = allocate_duration_budget(
            story_mode=story_mode, item_count=item_count, target_duration_sec=target
        )
        assert budget.target_duration_sec == target
        assert sum(s.duration_sec for s in budget.sections) == pytest.approx(
            target, abs=0.01
        )

    def test_unknown_mode_falls_back_to_single_story(self):
        budget = allocate_duration_budget(
            story_mode="nonexistent", item_count=1, target_duration_sec=20
        )
        assert [s.type for s in budget.sections] == [
            "hook", "context", "evidence", "reveal", "cta",
        ]
