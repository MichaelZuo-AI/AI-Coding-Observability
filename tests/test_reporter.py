"""Tests for CLI report formatting (orchestration model)."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from claude_analytics.reporter import (
    format_duration,
    print_report,
    compute_streaks,
    precision_tier_label,
)
from claude_analytics.models import OrchestrationSession, ActivityBlock
from claude_analytics.codegen import CodeGenStats


def _orch(
    project: str = "my-project",
    precision_score: float = 1.0,
    tier: str = "flawless",
    steering_count: int = 0,
    total_duration: int = 600,
    has_outcome: bool = True,
    start_day: int = 1,
) -> OrchestrationSession:
    return OrchestrationSession(
        session_id=f"s-{start_day}",
        project=project,
        total_duration=total_duration,
        intent_length=100,
        steering_count=steering_count,
        precision_score=precision_score,
        tier=tier,
        has_outcome=has_outcome,
        phase_sequence=["intent"] + ["steering"] * steering_count + ["acknowledgment"],
        message_count=2 + steering_count,
    )


def _block(start_day: int = 1, duration: int = 3600, project: str = "my-project") -> ActivityBlock:
    return ActivityBlock(
        category="session",
        start_time=datetime(2026, 3, start_day, 10, 0, tzinfo=timezone.utc),
        duration_seconds=duration,
        message_count=5,
        project=project,
    )


class TestFormatDuration:
    def test_hours(self):
        assert format_duration(7200) == "2h"

    def test_minutes(self):
        assert format_duration(300) == "5m"

    def test_seconds(self):
        assert format_duration(45) == "45s"


class TestPrecisionTierLabel:
    def test_flawless(self):
        label, _ = precision_tier_label(1.0)
        assert label == "Flawless"

    def test_clean(self):
        label, _ = precision_tier_label(0.5)
        assert label == "Clean"

    def test_guided(self):
        label, _ = precision_tier_label(0.25)
        assert label == "Guided"

    def test_heavy(self):
        label, _ = precision_tier_label(0.2)
        assert label == "Heavy"


class TestComputeStreaks:
    def test_consecutive_days(self):
        blocks = [_block(start_day=d) for d in [1, 2, 3]]
        current, longest = compute_streaks(blocks)
        assert longest == 3

    def test_gap_breaks_streak(self):
        blocks = [_block(start_day=d) for d in [1, 2, 5, 6]]
        current, longest = compute_streaks(blocks)
        assert longest == 2

    def test_empty(self):
        assert compute_streaks([]) == (0, 0)


class TestPrintReport:
    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_contains_precision_section(self, _):
        orchs = [_orch(), _orch(steering_count=1, precision_score=0.5, tier="clean")]
        blocks = [_block()]
        report = print_report(orchestration_sessions=orchs, blocks=blocks)
        assert "Orchestration Precision" in report

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_contains_tier_breakdown(self, _):
        orchs = [_orch(), _orch(steering_count=2, precision_score=0.33, tier="guided")]
        blocks = [_block()]
        report = print_report(orchestration_sessions=orchs, blocks=blocks)
        assert "Flawless" in report or "flawless" in report.lower()

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_contains_project_precision(self, _):
        orchs = [
            _orch(project="proj-a", precision_score=1.0, tier="flawless"),
            _orch(project="proj-b", precision_score=0.5, tier="clean", steering_count=1),
        ]
        blocks = [_block(project="proj-a"), _block(project="proj-b")]
        report = print_report(orchestration_sessions=orchs, blocks=blocks)
        assert "proj-a" in report
        assert "proj-b" in report

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_contains_throughput(self, _):
        orchs = [_orch()]
        blocks = [_block()]
        stats = CodeGenStats(ai_lines=1000, total_lines=5000, ai_commits=10, total_commits=12, files_touched={"a.py", "b.py"})
        report = print_report(orchestration_sessions=orchs, blocks=blocks, codegen_stats=stats)
        assert "Throughput" in report or "Commits" in report

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_empty_sessions(self, _):
        report = print_report(orchestration_sessions=[], blocks=[])
        assert "No" in report

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_no_old_sections(self, _):
        orchs = [_orch()]
        blocks = [_block()]
        report = print_report(orchestration_sessions=orchs, blocks=blocks)
        assert "Engineering Efficiency" not in report
        assert "Active Time Breakdown" not in report
        assert "debug_tax" not in report
