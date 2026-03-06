"""Tests for Phase 4a: efficiency metrics."""

import pytest
from datetime import datetime, timezone, timedelta
from claude_analytics.efficiency import compute_efficiency, EfficiencyMetrics
from claude_analytics.models import ActivityBlock


def _block(category: str, duration: int = 300, offset_min: int = 0, project: str = "TestProj") -> ActivityBlock:
    """Helper to create an ActivityBlock."""
    start = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=offset_min)
    return ActivityBlock(
        category=category,
        start_time=start,
        duration_seconds=duration,
        message_count=3,
        project=project,
    )


class TestFocusRatio:
    def test_all_coding(self):
        blocks = [_block("coding", 3600)]
        result = compute_efficiency(blocks, message_count=10, active_hours=1.0)
        assert result.focus_ratio == 1.0

    def test_all_chat(self):
        blocks = [_block("chat", 3600)]
        result = compute_efficiency(blocks, message_count=10, active_hours=1.0)
        assert result.focus_ratio == 0.0

    def test_mixed(self):
        blocks = [
            _block("coding", 600),
            _block("debug", 200),
            _block("chat", 200),
        ]
        result = compute_efficiency(blocks, message_count=10, active_hours=1.0)
        assert result.focus_ratio == pytest.approx(800 / 1000)

    def test_design_counts_as_core(self):
        blocks = [_block("design", 500), _block("devops", 500)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.focus_ratio == pytest.approx(0.5)

    def test_empty_blocks(self):
        result = compute_efficiency([], message_count=0, active_hours=0)
        assert result.focus_ratio == 0.0


class TestDebugTax:
    def test_no_coding(self):
        blocks = [_block("debug", 300)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.debug_tax == 0.0

    def test_equal_coding_debug(self):
        blocks = [_block("coding", 300), _block("debug", 300)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.debug_tax == pytest.approx(1.0)

    def test_low_debug(self):
        blocks = [_block("coding", 600), _block("debug", 60)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.debug_tax == pytest.approx(0.1)


class TestInteractionDensity:
    def test_normal(self):
        blocks = [_block("coding", 3600)]
        result = compute_efficiency(blocks, message_count=10, active_hours=1.0)
        assert result.interaction_density == pytest.approx(10.0)

    def test_zero_hours(self):
        blocks = [_block("coding", 100)]
        result = compute_efficiency(blocks, message_count=10, active_hours=0)
        assert result.interaction_density == 0.0

    def test_high_density(self):
        blocks = [_block("coding", 3600)]
        result = compute_efficiency(blocks, message_count=30, active_hours=1.0)
        assert result.interaction_density == pytest.approx(30.0)


class TestChatDevopsOverhead:
    def test_no_overhead(self):
        blocks = [_block("coding", 1000)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.chat_devops_overhead == 0.0

    def test_all_overhead(self):
        blocks = [_block("chat", 500), _block("devops", 500)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.chat_devops_overhead == pytest.approx(1.0)

    def test_partial_overhead(self):
        blocks = [_block("coding", 700), _block("chat", 200), _block("devops", 100)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.chat_devops_overhead == pytest.approx(300 / 1000)


class TestEfficiencyScore:
    def test_partial_score_without_resolution(self):
        blocks = [_block("coding", 800), _block("chat", 200)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        # Without task_resolution, uses 1.0 × focus_ratio
        assert result.efficiency_score == pytest.approx(0.8)

    def test_full_score_with_resolution(self):
        blocks = [_block("coding", 800), _block("chat", 200)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0, task_resolution_efficiency=0.5)
        assert result.efficiency_score == pytest.approx(0.4)


class TestStageDurations:
    def test_durations(self):
        blocks = [
            _block("design", 100),
            _block("coding", 500),
            _block("devops", 200),
        ]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.design_seconds == 100
        assert result.coding_seconds == 500
        assert result.deployment_seconds == 200
        assert result.testing_seconds == 0

    def test_testing_seconds_always_zero(self):
        """testing_seconds is hardcoded to 0 pending Phase 4b rework detection."""
        blocks = [_block("coding", 300), _block("review", 200)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.testing_seconds == 0

    def test_multiple_blocks_same_category_accumulated(self):
        """Two coding blocks should sum their durations."""
        blocks = [_block("coding", 400), _block("coding", 600)]
        result = compute_efficiency(blocks, message_count=10, active_hours=1.0)
        assert result.coding_seconds == 1000
        assert result.focus_ratio == 1.0

    def test_multiple_debug_blocks_accumulated_for_tax(self):
        """Two debug blocks against one coding block."""
        blocks = [_block("coding", 200), _block("debug", 100), _block("debug", 100)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.debug_tax == pytest.approx(1.0)  # 200 debug / 200 coding

    def test_deployment_seconds_is_devops_not_chat(self):
        """deployment_seconds maps to devops seconds only, not chat."""
        blocks = [_block("devops", 300), _block("chat", 200)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.deployment_seconds == 300

    def test_design_not_counted_in_debug_tax_denominator(self):
        """design seconds do not count as coding for debug_tax."""
        blocks = [_block("design", 600), _block("debug", 300)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        # No coding blocks → debug_tax = 0
        assert result.debug_tax == 0.0

    def test_unknown_category_counted_in_total_but_not_core(self):
        """An unknown category contributes to total but not focus_ratio."""
        blocks = [_block("coding", 500), _block("other", 500)]
        result = compute_efficiency(blocks, message_count=5, active_hours=1.0)
        assert result.focus_ratio == pytest.approx(0.5)


class TestEfficiencyScoreEdgeCases:
    def test_zero_task_resolution_gives_zero_score(self):
        blocks = [_block("coding", 800), _block("chat", 200)]
        result = compute_efficiency(
            blocks, message_count=5, active_hours=1.0, task_resolution_efficiency=0.0
        )
        assert result.efficiency_score == pytest.approx(0.0)

    def test_zero_focus_ratio_gives_zero_score(self):
        blocks = [_block("chat", 1000)]
        result = compute_efficiency(
            blocks, message_count=5, active_hours=1.0, task_resolution_efficiency=0.8
        )
        assert result.efficiency_score == pytest.approx(0.0)

    def test_efficiency_metrics_default_values(self):
        """EfficiencyMetrics() should have sensible zero defaults."""
        m = EfficiencyMetrics()
        assert m.focus_ratio == 0.0
        assert m.efficiency_score == 0.0
        assert m.debug_tax == 0.0
        assert m.interaction_density == 0.0
        assert m.chat_devops_overhead == 0.0
        assert m.design_seconds == 0
        assert m.testing_seconds == 0
        assert m.deployment_seconds == 0
        assert m.coding_seconds == 0
