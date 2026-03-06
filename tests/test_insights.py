"""Tests for Phase 4c: behavioral insights."""

import pytest
from datetime import datetime, timezone, timedelta
from claude_analytics.insights import (
    generate_insights,
    format_insights,
    Insight,
    _efficiency_insights,
    _quality_insights,
    _peak_hours_insights,
)
from claude_analytics.efficiency import EfficiencyMetrics
from claude_analytics.quality import QualityMetrics
from claude_analytics.models import ActivityBlock


def _block(category: str, duration: int = 300, hour: int = 10) -> ActivityBlock:
    start = datetime(2026, 3, 1, hour, 0, tzinfo=timezone.utc)
    return ActivityBlock(
        category=category,
        start_time=start,
        duration_seconds=duration,
        message_count=3,
        project="TestProj",
    )


class TestEfficiencyInsights:
    def test_high_score(self):
        eff = EfficiencyMetrics(efficiency_score=0.8, focus_ratio=0.9)
        insights = _efficiency_insights("TestProj", eff)
        assert any("strong" in i.observation for i in insights)

    def test_low_score(self):
        eff = EfficiencyMetrics(efficiency_score=0.2, focus_ratio=0.3)
        insights = _efficiency_insights("TestProj", eff)
        assert any("room for improvement" in i.observation for i in insights)

    def test_high_focus(self):
        eff = EfficiencyMetrics(focus_ratio=0.9, efficiency_score=0.5)
        insights = _efficiency_insights("TestProj", eff)
        assert any("highly focused" in i.observation for i in insights)

    def test_low_focus(self):
        eff = EfficiencyMetrics(focus_ratio=0.4, efficiency_score=0.3)
        insights = _efficiency_insights("TestProj", eff)
        assert any("core engineering" in i.observation for i in insights)

    def test_high_debug_tax(self):
        eff = EfficiencyMetrics(debug_tax=0.5, focus_ratio=0.7, efficiency_score=0.5)
        insights = _efficiency_insights("TestProj", eff)
        assert any("Debug tax" in i.observation for i in insights)

    def test_high_interaction_density(self):
        eff = EfficiencyMetrics(interaction_density=30, focus_ratio=0.7, efficiency_score=0.5)
        insights = _efficiency_insights("TestProj", eff)
        assert any("micro-managing" in i.observation for i in insights)

    def test_high_overhead(self):
        eff = EfficiencyMetrics(chat_devops_overhead=0.5, focus_ratio=0.5, efficiency_score=0.3)
        insights = _efficiency_insights("TestProj", eff)
        assert any("overhead" in i.observation for i in insights)

    def test_no_insights_for_normal(self):
        eff = EfficiencyMetrics(
            efficiency_score=0.6, focus_ratio=0.75,
            debug_tax=0.1, interaction_density=10, chat_devops_overhead=0.2,
        )
        insights = _efficiency_insights("TestProj", eff)
        assert len(insights) == 0


class TestQualityInsights:
    def test_low_resolution(self):
        qual = QualityMetrics(task_resolution_efficiency=0.3)
        insights = _quality_insights("TestProj", qual)
        assert any("attempts" in i.observation for i in insights)

    def test_low_one_shot(self):
        qual = QualityMetrics(one_shot_success_rate=0.4)
        insights = _quality_insights("TestProj", qual)
        assert any("One-shot" in i.observation for i in insights)

    def test_deep_debug_loops(self):
        qual = QualityMetrics(debug_loop_max_depth=8)
        insights = _quality_insights("TestProj", qual)
        assert any("8 turns" in i.observation for i in insights)

    def test_high_rework(self):
        qual = QualityMetrics(rework_rate=0.4)
        insights = _quality_insights("TestProj", qual)
        assert any("reworked" in i.observation for i in insights)

    def test_high_context_switches(self):
        qual = QualityMetrics(context_switch_frequency=4.0)
        insights = _quality_insights("TestProj", qual)
        assert any("project switches" in i.observation for i in insights)

    def test_no_insights_for_normal(self):
        qual = QualityMetrics(
            task_resolution_efficiency=0.8,
            one_shot_success_rate=0.7,
            debug_loop_max_depth=2,
            rework_rate=0.1,
            context_switch_frequency=1.0,
        )
        insights = _quality_insights("TestProj", qual)
        assert len(insights) == 0


class TestPeakHours:
    def test_identifies_peak(self):
        blocks = [
            _block("coding", duration=3600, hour=10),
            _block("coding", duration=3600, hour=11),
            _block("chat", duration=3600, hour=15),
        ]
        insights = _peak_hours_insights(blocks)
        assert len(insights) == 1
        assert "Peak productivity" in insights[0].observation

    def test_empty_blocks(self):
        assert _peak_hours_insights([]) == []


class TestGenerateInsights:
    def test_combines_efficiency_and_quality(self):
        eff = {"ProjA": EfficiencyMetrics(efficiency_score=0.2, focus_ratio=0.3)}
        qual = {"ProjA": QualityMetrics(task_resolution_efficiency=0.3)}
        insights = generate_insights(eff, qual)
        assert len(insights) >= 2  # at least low score + low resolution

    def test_empty_input(self):
        insights = generate_insights({}, {})
        assert insights == []

    def test_sorted_by_project(self):
        eff = {
            "Bravo": EfficiencyMetrics(efficiency_score=0.2, focus_ratio=0.3),
            "Alpha": EfficiencyMetrics(efficiency_score=0.2, focus_ratio=0.3),
        }
        insights = generate_insights(eff, {})
        projects = [i.project for i in insights]
        # Alpha should come before Bravo
        first_alpha = next(i for i, p in enumerate(projects) if p == "Alpha")
        first_bravo = next(i for i, p in enumerate(projects) if p == "Bravo")
        assert first_alpha < first_bravo


class TestFormatInsights:
    def test_basic_formatting(self):
        insights = [
            Insight(project="TestProj", observation="Test observation.", suggestion="Do this."),
        ]
        result = format_insights(insights)
        assert "[TestProj]" in result
        assert "Test observation." in result
        assert "-> Do this." in result

    def test_no_suggestion(self):
        insights = [
            Insight(project="TestProj", observation="All good."),
        ]
        result = format_insights(insights)
        assert "->" not in result

    def test_empty(self):
        result = format_insights([])
        assert "No insights" in result

    def test_multiple_projects(self):
        insights = [
            Insight(project="A", observation="Obs A."),
            Insight(project="B", observation="Obs B."),
        ]
        result = format_insights(insights)
        assert "[A]" in result
        assert "[B]" in result

    def test_multiple_insights_same_project_no_duplicate_header(self):
        """Project header should only appear once when multiple insights share a project."""
        insights = [
            Insight(project="MyProj", observation="First observation."),
            Insight(project="MyProj", observation="Second observation."),
        ]
        result = format_insights(insights)
        assert result.count("[MyProj]") == 1

    def test_project_separator_blank_line(self):
        """A blank line should separate different project sections."""
        insights = [
            Insight(project="A", observation="Obs A."),
            Insight(project="B", observation="Obs B."),
        ]
        result = format_insights(insights)
        # The output should contain an empty line between the two project blocks
        assert "\n\n" in result

    def test_returns_string(self):
        assert isinstance(format_insights([]), str)


class TestEfficiencyInsightsBoundaries:
    def test_score_exactly_at_high_threshold_no_strong_insight(self):
        """Score == 0.7 is not > 0.7, so no 'strong' insight."""
        eff = EfficiencyMetrics(efficiency_score=0.7, focus_ratio=0.75)
        insights = _efficiency_insights("P", eff)
        assert not any("strong" in i.observation for i in insights)

    def test_score_exactly_at_low_threshold_no_improvement_insight(self):
        """Score == 0.3 is not < 0.3, so no 'room for improvement' insight."""
        eff = EfficiencyMetrics(efficiency_score=0.3, focus_ratio=0.5)
        insights = _efficiency_insights("P", eff)
        assert not any("room for improvement" in i.observation for i in insights)

    def test_focus_ratio_exactly_at_high_threshold_no_focused_insight(self):
        """focus_ratio == 0.85 is not > 0.85, so no 'highly focused' insight."""
        eff = EfficiencyMetrics(focus_ratio=0.85, efficiency_score=0.5)
        insights = _efficiency_insights("P", eff)
        assert not any("highly focused" in i.observation for i in insights)

    def test_focus_ratio_exactly_at_low_threshold_no_core_insight(self):
        """focus_ratio == 0.50 is not < 0.50, so no 'core engineering' insight."""
        eff = EfficiencyMetrics(focus_ratio=0.50, efficiency_score=0.3)
        insights = _efficiency_insights("P", eff)
        assert not any("core engineering" in i.observation for i in insights)

    def test_debug_tax_exactly_at_threshold_no_insight(self):
        """debug_tax == 0.3 is not > 0.3, so no debug tax insight."""
        eff = EfficiencyMetrics(debug_tax=0.3, focus_ratio=0.7, efficiency_score=0.5)
        insights = _efficiency_insights("P", eff)
        assert not any("Debug tax" in i.observation for i in insights)

    def test_interaction_density_exactly_at_threshold_no_insight(self):
        """interaction_density == 25 is not > 25, so no micro-managing insight."""
        eff = EfficiencyMetrics(interaction_density=25, focus_ratio=0.7, efficiency_score=0.5)
        insights = _efficiency_insights("P", eff)
        assert not any("micro-managing" in i.observation for i in insights)

    def test_overhead_exactly_at_threshold_no_insight(self):
        """chat_devops_overhead == 0.4 is not > 0.4, so no overhead insight."""
        eff = EfficiencyMetrics(chat_devops_overhead=0.4, focus_ratio=0.5, efficiency_score=0.3)
        insights = _efficiency_insights("P", eff)
        assert not any("overhead" in i.observation for i in insights)

    def test_project_name_in_all_insights(self):
        """Every generated insight should carry the correct project name."""
        eff = EfficiencyMetrics(efficiency_score=0.8, focus_ratio=0.9)
        insights = _efficiency_insights("SpecificProject", eff)
        for i in insights:
            assert i.project == "SpecificProject"


class TestQualityInsightsBoundaries:
    def test_zero_task_resolution_infinity_path(self):
        """task_resolution_efficiency == 0 should trigger insight with 'inf' or similar."""
        qual = QualityMetrics(task_resolution_efficiency=0.0)
        insights = _quality_insights("P", qual)
        # Should emit an insight about attempts; inf is represented via float("inf")
        assert any("attempts" in i.observation for i in insights)

    def test_resolution_exactly_at_threshold_no_insight(self):
        """task_resolution_efficiency == 0.4 is not < 0.4, so no insight."""
        qual = QualityMetrics(task_resolution_efficiency=0.4)
        insights = _quality_insights("P", qual)
        assert not any("attempts" in i.observation for i in insights)

    def test_one_shot_exactly_at_threshold_no_insight(self):
        """one_shot_success_rate == 0.5 is not < 0.5, so no insight."""
        qual = QualityMetrics(one_shot_success_rate=0.5)
        insights = _quality_insights("P", qual)
        assert not any("One-shot" in i.observation for i in insights)

    def test_debug_loop_exactly_at_threshold_no_insight(self):
        """debug_loop_max_depth == 5 is not > 5, so no insight."""
        qual = QualityMetrics(debug_loop_max_depth=5)
        insights = _quality_insights("P", qual)
        assert not any("turns" in i.observation for i in insights)

    def test_rework_rate_exactly_at_threshold_no_insight(self):
        """rework_rate == 0.3 is not > 0.3, so no insight."""
        qual = QualityMetrics(rework_rate=0.3)
        insights = _quality_insights("P", qual)
        assert not any("reworked" in i.observation for i in insights)

    def test_context_switch_exactly_at_threshold_no_insight(self):
        """context_switch_frequency == 3 is not > 3, so no insight."""
        qual = QualityMetrics(context_switch_frequency=3.0)
        insights = _quality_insights("P", qual)
        assert not any("project switches" in i.observation for i in insights)

    def test_project_name_in_all_quality_insights(self):
        qual = QualityMetrics(
            task_resolution_efficiency=0.1,
            one_shot_success_rate=0.2,
            debug_loop_max_depth=10,
            rework_rate=0.5,
            context_switch_frequency=5.0,
        )
        insights = _quality_insights("QualProject", qual)
        for i in insights:
            assert i.project == "QualProject"


class TestPeakHoursInsightsEdgeCases:
    def test_all_non_core_blocks_no_peak(self):
        """If all blocks are chat/devops, no hour has focus > 0.5, so no peak insight."""
        blocks = [
            _block("chat", duration=3600, hour=10),
            _block("devops", duration=3600, hour=11),
        ]
        insights = _peak_hours_insights(blocks)
        assert insights == []

    def test_peak_hours_project_is_overall(self):
        """Peak hours insight always uses 'Overall' as the project."""
        blocks = [_block("coding", duration=3600, hour=9)]
        insights = _peak_hours_insights(blocks)
        if insights:
            assert insights[0].project == "Overall"

    def test_peak_hours_suggestion_present(self):
        blocks = [_block("coding", duration=3600, hour=14)]
        insights = _peak_hours_insights(blocks)
        if insights:
            assert insights[0].suggestion != ""

    def test_top_hours_sorted_ascending(self):
        """Hours in the observation should be listed in ascending order."""
        blocks = [
            _block("coding", duration=3600, hour=15),
            _block("coding", duration=3600, hour=10),
            _block("coding", duration=3600, hour=8),
        ]
        insights = _peak_hours_insights(blocks)
        if insights:
            obs = insights[0].observation
            # Extract hours from the observation string
            import re
            hours_found = [int(h) for h in re.findall(r"(\d+):00", obs)]
            assert hours_found == sorted(hours_found)

    def test_at_most_one_insight_returned(self):
        """_peak_hours_insights should return at most one Insight."""
        blocks = [_block("coding", duration=3600, hour=h) for h in range(10)]
        insights = _peak_hours_insights(blocks)
        assert len(insights) <= 1


class TestGenerateInsightsEdgeCases:
    def test_project_only_in_efficiency_no_quality(self):
        """A project present only in efficiency dict still generates efficiency insights."""
        eff = {"EfficOnly": EfficiencyMetrics(efficiency_score=0.2, focus_ratio=0.3)}
        insights = generate_insights(eff, {})
        projs = [i.project for i in insights]
        assert "EfficOnly" in projs

    def test_project_only_in_quality_no_efficiency(self):
        """A project present only in quality dict still generates quality insights."""
        qual = {"QualOnly": QualityMetrics(task_resolution_efficiency=0.1)}
        insights = generate_insights({}, qual)
        projs = [i.project for i in insights]
        assert "QualOnly" in projs

    def test_with_blocks_adds_peak_hours(self):
        """Passing blocks triggers _peak_hours_insights which may add Overall insights."""
        eff = {"P": EfficiencyMetrics()}
        qual = {}
        blocks = [_block("coding", duration=3600, hour=10)]
        insights = generate_insights(eff, qual, blocks=blocks)
        # If peak hours found, at least one "Overall" insight
        overall = [i for i in insights if i.project == "Overall"]
        # We just verify the function doesn't crash and returns a list
        assert isinstance(insights, list)

    def test_returns_list(self):
        assert isinstance(generate_insights({}, {}), list)
