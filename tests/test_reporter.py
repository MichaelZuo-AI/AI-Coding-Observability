"""Tests for CLI report formatting (reporter.py)."""

import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from claude_analytics.reporter import (
    format_duration,
    _bar,
    _use_color,
    _c,
    format_codegen_section,
    print_report,
    BAR_WIDTH,
    RESET,
    BOLD,
    DIM,
    CATEGORY_COLORS,
    CATEGORY_ORDER,
)
from claude_analytics.models import ActivityBlock
from claude_analytics.codegen import CodeGenStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block(
    category: str,
    duration_seconds: int,
    project: str = "my-project",
    start: datetime | None = None,
) -> ActivityBlock:
    if start is None:
        start = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    return ActivityBlock(
        category=category,
        start_time=start,
        duration_seconds=duration_seconds,
        message_count=2,
        project=project,
    )


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_zero_seconds(self):
        assert format_duration(0) == "0s"

    def test_single_second(self):
        assert format_duration(1) == "1s"

    def test_59_seconds(self):
        assert format_duration(59) == "59s"

    def test_exactly_60_seconds(self):
        assert format_duration(60) == "1m"

    def test_90_seconds_rounds(self):
        # 90s = 1.5 min → "2m" (rounds to nearest)
        assert format_duration(90) == "2m"

    def test_45_minutes(self):
        assert format_duration(45 * 60) == "45m"

    def test_59_minutes_59_seconds(self):
        # 3599s < 3600 — still "minutes" range
        assert format_duration(3599) == "60m"

    def test_exactly_one_hour(self):
        assert format_duration(3600) == "1h"

    def test_two_hours(self):
        assert format_duration(7200) == "2h"

    def test_large_hours(self):
        assert format_duration(36000) == "10h"

    def test_fractional_hours_round_down(self):
        # 5400s = 1.5 h → "2h" (rounds to nearest)
        assert format_duration(5400) == "2h"

    def test_returns_string(self):
        result = format_duration(100)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _bar (no-color path — stdout is not a tty in pytest)
# ---------------------------------------------------------------------------

class TestBar:
    def _call_no_color(self, fraction: float, category: str, width: int = BAR_WIDTH) -> str:
        """Force no-color by patching _use_color to return False."""
        with patch("claude_analytics.reporter._use_color", return_value=False):
            return _bar(fraction, category, width)

    def test_full_bar(self):
        result = self._call_no_color(1.0, "coding", 10)
        assert result == "\u2588" * 10

    def test_empty_bar(self):
        result = self._call_no_color(0.0, "coding", 10)
        assert result == "\u2591" * 10

    def test_half_bar(self):
        result = self._call_no_color(0.5, "coding", 10)
        assert result == "\u2588" * 5 + "\u2591" * 5

    def test_width_respected(self):
        result = self._call_no_color(0.5, "coding", 20)
        assert len(result) == 20

    def test_unknown_category_falls_back(self):
        # Should not raise — unknown category just gets no ANSI color
        result = self._call_no_color(0.5, "unknown_cat", 10)
        filled = result.count("\u2588")
        empty = result.count("\u2591")
        assert filled + empty == 10

    def test_bar_with_color(self):
        """When color is enabled, the output contains ANSI codes."""
        with patch("claude_analytics.reporter._use_color", return_value=True):
            result = _bar(0.5, "coding", 10)
        # ANSI codes present
        assert "\033[" in result
        assert RESET in result

    def test_bar_no_color_plain_chars_only(self):
        result = self._call_no_color(0.25, "debug", 8)
        # No ANSI escape sequences in no-color mode
        assert "\033[" not in result
        # 0.25 * 8 = 2 filled, 6 empty
        assert result == "\u2588" * 2 + "\u2591" * 6


# ---------------------------------------------------------------------------
# _use_color and _c
# ---------------------------------------------------------------------------

class TestColorHelpers:
    def test_use_color_returns_bool(self):
        result = _use_color()
        assert isinstance(result, bool)

    def test_c_no_color_returns_plain_text(self):
        with patch("claude_analytics.reporter._use_color", return_value=False):
            result = _c(BOLD, "hello")
        assert result == "hello"

    def test_c_with_color_wraps_in_ansi(self):
        with patch("claude_analytics.reporter._use_color", return_value=True):
            result = _c(BOLD, "hello")
        assert result.startswith(BOLD)
        assert result.endswith(RESET)
        assert "hello" in result


# ---------------------------------------------------------------------------
# format_codegen_section
# ---------------------------------------------------------------------------

class TestFormatCodegenSection:
    """Always test in no-color mode so output is predictable."""

    def _fmt(self, stats: CodeGenStats, project_stats=None) -> str:
        with patch("claude_analytics.reporter._use_color", return_value=False):
            return format_codegen_section(stats, project_stats)

    def test_zero_total_lines_shows_ai_lines_count(self):
        stats = CodeGenStats(ai_lines=150, total_lines=0)
        result = self._fmt(stats)
        assert "150" in result
        assert "AI lines" in result

    def test_with_total_lines_shows_percentage(self):
        stats = CodeGenStats(ai_lines=50, total_lines=100)
        result = self._fmt(stats)
        # 50% expected
        assert "50%" in result

    def test_header_present(self):
        stats = CodeGenStats(ai_lines=10, total_lines=20)
        result = self._fmt(stats)
        assert "AI Code Generation" in result

    def test_commit_counts_shown(self):
        stats = CodeGenStats(ai_commits=5, total_commits=12)
        result = self._fmt(stats)
        assert "5" in result
        assert "12" in result

    def test_files_touched_count(self):
        stats = CodeGenStats(files_touched={"a.py", "b.ts"})
        result = self._fmt(stats)
        assert "2" in result

    def test_no_project_stats_no_project_section(self):
        stats = CodeGenStats(ai_lines=100, total_lines=200)
        result = self._fmt(stats, project_stats=None)
        assert "AI % by Project" not in result

    def test_empty_project_stats_no_project_section(self):
        stats = CodeGenStats(ai_lines=100, total_lines=200)
        result = self._fmt(stats, project_stats={})
        assert "AI % by Project" not in result

    def test_with_project_stats_shows_project_section(self):
        stats = CodeGenStats(ai_lines=200, total_lines=400)
        proj_stats = {
            "my-project": CodeGenStats(ai_lines=200, total_lines=400),
        }
        result = self._fmt(stats, project_stats=proj_stats)
        assert "AI % by Project" in result
        assert "my-project" in result

    def test_project_with_zero_ai_lines_skipped(self):
        stats = CodeGenStats(ai_lines=100, total_lines=200)
        proj_stats = {
            "active-project": CodeGenStats(ai_lines=100, total_lines=200),
            "idle-project": CodeGenStats(ai_lines=0, total_lines=500),
        }
        result = self._fmt(stats, project_stats=proj_stats)
        assert "active-project" in result
        assert "idle-project" not in result

    def test_project_zero_total_lines_fallback(self):
        """Project with ai_lines > 0 but total_lines == 0 uses fallback display."""
        stats = CodeGenStats(ai_lines=50, total_lines=0)
        proj_stats = {
            "new-project": CodeGenStats(ai_lines=50, total_lines=0),
        }
        result = self._fmt(stats, project_stats=proj_stats)
        assert "new-project" in result
        assert "50" in result

    def test_project_stats_sorted_by_ai_lines_descending(self):
        """Projects should appear largest first."""
        stats = CodeGenStats(ai_lines=300, total_lines=600)
        proj_stats = {
            "small": CodeGenStats(ai_lines=50, total_lines=100),
            "large": CodeGenStats(ai_lines=250, total_lines=500),
        }
        result = self._fmt(stats, project_stats=proj_stats)
        large_pos = result.index("large")
        small_pos = result.index("small")
        assert large_pos < small_pos

    def test_returns_string(self):
        stats = CodeGenStats()
        result = self._fmt(stats)
        assert isinstance(result, str)

    def test_capped_at_100_percent(self):
        """ai_percentage is capped at 100 by CodeGenStats property."""
        stats = CodeGenStats(ai_lines=9999, total_lines=100)
        result = self._fmt(stats)
        # Should show 100% not >100%
        assert "100%" in result


# ---------------------------------------------------------------------------
# print_report
# ---------------------------------------------------------------------------

class TestPrintReport:
    """Test print_report in no-color mode for predictable assertions."""

    def _report(self, blocks, from_date=None, to_date=None, codegen=None, by_proj=None) -> str:
        with patch("claude_analytics.reporter._use_color", return_value=False):
            return print_report(blocks, from_date, to_date, codegen, by_proj)

    # --- Empty / No-data cases ---

    def test_empty_blocks_returns_no_data_message(self):
        result = self._report([])
        assert "No activity data found" in result

    def test_all_blocks_filtered_by_date_returns_no_data(self):
        block = _block("coding", 300, start=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc))
        # Date filter completely excludes the block
        future = datetime(2026, 3, 1, tzinfo=timezone.utc)
        result = self._report([block], from_date=future)
        assert "No activity data found" in result

    def test_blocks_with_zero_duration_returns_no_active_time(self):
        block = _block("coding", 0)
        result = self._report([block])
        assert "No active time recorded" in result

    # --- Header content ---

    def test_report_contains_claude_analytics_header(self):
        block = _block("coding", 3600)
        result = self._report([block])
        assert "Claude Code Analytics" in result

    def test_report_shows_date_range(self):
        block = _block("coding", 3600, start=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc))
        result = self._report([block])
        assert "2026-02-10" in result

    def test_report_shows_engineer_name(self):
        block = _block("coding", 1800)
        with patch.dict("os.environ", {"USER": "testuser"}):
            result = self._report([block])
        assert "testuser" in result

    def test_report_shows_default_engineer_when_no_user_env(self):
        block = _block("coding", 1800)
        env_without_user = {k: v for k, v in __import__("os").environ.items() if k != "USER"}
        with patch.dict("os.environ", env_without_user, clear=True):
            result = self._report([block])
        assert "engineer" in result

    # --- Category breakdown ---

    def test_single_category_shows_100_percent(self):
        block = _block("coding", 3600)
        result = self._report([block])
        assert "100%" in result
        assert "coding" in result

    def test_multiple_categories_shown(self):
        blocks = [
            _block("coding", 1800),
            _block("debug", 1800),
        ]
        result = self._report(blocks)
        assert "coding" in result
        assert "debug" in result

    def test_zero_duration_category_excluded(self):
        """A category with 0 seconds should not appear in the breakdown."""
        block = _block("coding", 3600)
        result = self._report([block])
        # "debug" should not appear since there are no debug blocks
        assert "debug" not in result

    def test_total_active_time_shown(self):
        block = _block("coding", 3600)
        result = self._report([block])
        assert "Total Active" in result
        assert "1h" in result

    def test_category_order_respected(self):
        """Categories should appear in CATEGORY_ORDER, not arbitrary order."""
        blocks = [
            _block("review", 600),
            _block("coding", 1200),
            _block("debug", 900),
        ]
        result = self._report(blocks)
        # Find positions
        coding_pos = result.index("coding")
        debug_pos = result.index("debug")
        review_pos = result.index("review")
        # CATEGORY_ORDER: coding, debug, design, devops, review ...
        assert coding_pos < debug_pos < review_pos

    # --- Project breakdown ---

    def test_project_shown_in_report(self):
        block = _block("coding", 1800, project="alpha-project")
        result = self._report([block])
        assert "alpha-project" in result

    def test_multiple_projects_shown(self):
        blocks = [
            _block("coding", 1800, project="proj-a"),
            _block("debug", 900, project="proj-b"),
        ]
        result = self._report(blocks)
        assert "proj-a" in result
        assert "proj-b" in result

    def test_top_projects_section_present(self):
        block = _block("coding", 1800)
        result = self._report([block])
        assert "Top Projects" in result

    def test_projects_sorted_by_total_time(self):
        blocks = [
            _block("coding", 600, project="small"),
            _block("coding", 3000, project="big"),
        ]
        result = self._report(blocks)
        big_pos = result.index("big")
        small_pos = result.index("small")
        assert big_pos < small_pos

    # --- Date filtering ---

    def test_from_date_filters_early_blocks(self):
        early = _block("coding", 1800, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        late = _block("coding", 900, start=datetime(2026, 3, 1, tzinfo=timezone.utc))
        from_date = datetime(2026, 2, 1, tzinfo=timezone.utc)
        result = self._report([early, late], from_date=from_date)
        # After filtering, only late block remains (30min = 900s)
        assert "15m" in result  # 900s = 15m

    def test_to_date_filters_late_blocks(self):
        early = _block("coding", 1800, start=datetime(2026, 1, 15, tzinfo=timezone.utc))
        late = _block("debug", 3600, start=datetime(2026, 3, 1, tzinfo=timezone.utc))
        to_date = datetime(2026, 2, 1, tzinfo=timezone.utc)
        result = self._report([early, late], to_date=to_date)
        assert "coding" in result
        assert "debug" not in result

    def test_date_range_both_ends_filtering(self):
        blocks = [
            _block("coding", 600, start=datetime(2026, 1, 1, tzinfo=timezone.utc)),   # before
            _block("debug", 1800, start=datetime(2026, 2, 15, tzinfo=timezone.utc)),  # inside
            _block("devops", 900, start=datetime(2026, 4, 1, tzinfo=timezone.utc)),   # after
        ]
        from_date = datetime(2026, 2, 1, tzinfo=timezone.utc)
        to_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
        result = self._report(blocks, from_date=from_date, to_date=to_date)
        assert "debug" in result
        assert "coding" not in result
        assert "devops" not in result

    # --- AI Code Generation section ---

    def test_codegen_section_included_when_ai_lines_present(self):
        block = _block("coding", 1800)
        codegen = CodeGenStats(ai_lines=500, total_lines=1000)
        result = self._report([block], codegen=codegen)
        assert "AI Code Generation" in result

    def test_codegen_section_excluded_when_no_ai_lines(self):
        block = _block("coding", 1800)
        codegen = CodeGenStats(ai_lines=0, total_lines=1000)
        result = self._report([block], codegen=codegen)
        assert "AI Code Generation" not in result

    def test_codegen_section_excluded_when_codegen_is_none(self):
        block = _block("coding", 1800)
        result = self._report([block], codegen=None)
        assert "AI Code Generation" not in result

    def test_codegen_by_project_passed_to_section(self):
        block = _block("coding", 1800)
        codegen = CodeGenStats(ai_lines=200, total_lines=400)
        proj_stats = {
            "my-project": CodeGenStats(ai_lines=200, total_lines=400),
        }
        result = self._report([block], codegen=codegen, by_proj=proj_stats)
        assert "AI % by Project" in result

    # --- All CATEGORY_ORDER categories ---

    def test_all_known_categories_render(self):
        """Each known category should appear in the report when given blocks."""
        blocks = [_block(cat, 600) for cat in CATEGORY_ORDER]
        result = self._report(blocks)
        for cat in CATEGORY_ORDER:
            assert cat in result

    # --- Return type ---

    def test_returns_string(self):
        block = _block("coding", 1800)
        result = self._report([block])
        assert isinstance(result, str)

    def test_report_date_range_uses_block_extremes(self):
        """The date range shown should be earliest and latest block start_time."""
        blocks = [
            _block("coding", 600, start=datetime(2026, 1, 5, tzinfo=timezone.utc)),
            _block("debug", 600, start=datetime(2026, 3, 20, tzinfo=timezone.utc)),
        ]
        result = self._report(blocks)
        assert "2026-01-05" in result
        assert "2026-03-20" in result
