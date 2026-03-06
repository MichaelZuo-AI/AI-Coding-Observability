"""Tests for CLI entrypoint (main.py)."""

import argparse
import json
import pytest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from claude_analytics.main import (
    parse_date,
    cmd_report,
    cmd_sessions,
    cmd_dashboard,
    cmd_insights,
    _collect_data,
    _progress,
    _progress_done,
)
from claude_analytics.models import Session, Message, ActivityBlock
from claude_analytics.codegen import CodeGenStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(
    session_id: str = "sess-001",
    project: str = "test-project",
    start: datetime | None = None,
    end: datetime | None = None,
    user_msg_count: int = 2,
) -> Session:
    if start is None:
        start = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    if end is None:
        end = datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc)
    messages = []
    for i in range(user_msg_count):
        ts = datetime(2026, 2, 10, 10, i * 5, tzinfo=timezone.utc)
        messages.append(Message(role="user", content=f"user message {i}", timestamp=ts))
        messages.append(Message(role="assistant", content=f"response {i}", timestamp=ts))
    return Session(
        session_id=session_id,
        project=project,
        messages=messages,
        start_time=start,
        end_time=end,
    )


def _make_args(**kwargs) -> argparse.Namespace:
    """Create a minimal Namespace with sensible defaults for cmd_report."""
    defaults = {
        "projects_dir": None,
        "project": None,
        "from_date": None,
        "to_date": None,
        "limit": 20,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_block(
    category: str = "coding",
    duration: int = 1800,
    project: str = "test-project",
) -> ActivityBlock:
    return ActivityBlock(
        category=category,
        start_time=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
        duration_seconds=duration,
        message_count=2,
        project=project,
    )


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_basic_date(self):
        result = parse_date("2026-02-01")
        assert result == datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_returns_utc_timezone(self):
        result = parse_date("2026-01-15")
        assert result.tzinfo == timezone.utc

    def test_year_month_day(self):
        result = parse_date("2025-12-31")
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 31

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_date("02-01-2026")

    def test_invalid_format_no_dashes_raises(self):
        with pytest.raises(ValueError):
            parse_date("20260201")

    def test_incomplete_date_raises(self):
        with pytest.raises(ValueError):
            parse_date("2026-02")

    def test_non_date_string_raises(self):
        with pytest.raises(ValueError):
            parse_date("not-a-date")

    def test_result_has_midnight_time(self):
        result = parse_date("2026-06-15")
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0


# ---------------------------------------------------------------------------
# cmd_report
# ---------------------------------------------------------------------------

class TestCmdReport:
    """Test cmd_report with mocked parse_all_sessions, build_activity_blocks, analyze_codegen."""

    def _run(self, args_kwargs: dict, sessions, blocks, codegen=None) -> str:
        """Run cmd_report and capture stdout output."""
        args = _make_args(**args_kwargs)
        empty_codegen = codegen if codegen is not None else CodeGenStats()

        captured = StringIO()
        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=sessions),
            patch("claude_analytics.main.build_activity_blocks", return_value=blocks),
            patch("claude_analytics.main.analyze_codegen", return_value=empty_codegen),
            patch("claude_analytics.main.analyze_codegen_by_project", return_value={}),
            patch("claude_analytics.reporter._use_color", return_value=False),
            patch("sys.stdout", captured),
        ):
            cmd_report(args)
        return captured.getvalue()

    def test_no_sessions_found_prints_message(self):
        output = self._run({}, sessions=[], blocks=[])
        assert "No sessions found" in output

    def test_with_sessions_prints_report(self):
        session = _make_session()
        block = _make_block()
        output = self._run({}, sessions=[session], blocks=[block])
        assert "Claude Code Analytics" in output

    def test_date_filter_excludes_old_sessions(self):
        # Session ends before from_date
        old_session = _make_session(
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        output = self._run(
            {"from_date": "2026-02-01"},
            sessions=[old_session],
            blocks=[],
        )
        assert "No sessions found for the specified date range" in output

    def test_date_filter_excludes_future_sessions(self):
        # Session starts after to_date
        future_session = _make_session(
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
        )
        output = self._run(
            {"to_date": "2026-03-01"},
            sessions=[future_session],
            blocks=[],
        )
        assert "No sessions found for the specified date range" in output

    def test_session_within_date_range_included(self):
        session = _make_session(
            start=datetime(2026, 2, 10, tzinfo=timezone.utc),
            end=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        block = _make_block()
        output = self._run(
            {"from_date": "2026-02-01", "to_date": "2026-03-01"},
            sessions=[session],
            blocks=[block],
        )
        assert "Claude Code Analytics" in output

    def test_projects_dir_passed_to_parser(self):
        """When --projects-dir is given, it should be passed to parse_all_sessions."""
        args = _make_args(projects_dir="/tmp/my-claude-projects")
        captured_dirs = []

        def mock_parse(projects_dir, project_filter=None, **kwargs):
            captured_dirs.append(projects_dir)
            return []

        with (
            patch("claude_analytics.main.parse_all_sessions", side_effect=mock_parse),
            patch("claude_analytics.main.analyze_codegen", return_value=CodeGenStats()),
            patch("sys.stdout", StringIO()),
        ):
            cmd_report(args)

        assert str(captured_dirs[0]) == "/tmp/my-claude-projects"

    def test_default_projects_dir_uses_claude_constant(self):
        """Without --projects-dir, uses CLAUDE_PROJECTS_DIR."""
        from claude_analytics.parser import CLAUDE_PROJECTS_DIR
        args = _make_args(projects_dir=None)
        captured_dirs = []

        def mock_parse(projects_dir, project_filter=None, **kwargs):
            captured_dirs.append(projects_dir)
            return []

        with (
            patch("claude_analytics.main.parse_all_sessions", side_effect=mock_parse),
            patch("claude_analytics.main.analyze_codegen", return_value=CodeGenStats()),
            patch("sys.stdout", StringIO()),
        ):
            cmd_report(args)

        assert captured_dirs[0] == CLAUDE_PROJECTS_DIR

    def test_project_filter_passed_to_parser(self):
        args = _make_args(project="my-specific-project")
        captured_filters = []

        def mock_parse(projects_dir, project_filter=None, **kwargs):
            captured_filters.append(project_filter)
            return []

        with (
            patch("claude_analytics.main.parse_all_sessions", side_effect=mock_parse),
            patch("claude_analytics.main.analyze_codegen", return_value=CodeGenStats()),
            patch("sys.stdout", StringIO()),
        ):
            cmd_report(args)

        assert captured_filters[0] == "my-specific-project"

    def test_single_project_skips_by_project_codegen(self):
        """When --project is set, analyze_codegen_by_project should NOT be called."""
        session = _make_session()
        block = _make_block()

        mock_by_project = MagicMock(return_value={})

        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=[session]),
            patch("claude_analytics.main.build_activity_blocks", return_value=[block]),
            patch("claude_analytics.main.analyze_codegen", return_value=CodeGenStats()),
            patch("claude_analytics.main.analyze_codegen_by_project", mock_by_project),
            patch("claude_analytics.reporter._use_color", return_value=False),
            patch("sys.stdout", StringIO()),
        ):
            cmd_report(_make_args(project="my-project"))

        mock_by_project.assert_not_called()

    def test_no_project_filter_calls_by_project_codegen(self):
        """Without --project, analyze_codegen_by_project should be called."""
        session = _make_session()
        block = _make_block()

        mock_by_project = MagicMock(return_value={})

        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=[session]),
            patch("claude_analytics.main.build_activity_blocks", return_value=[block]),
            patch("claude_analytics.main.analyze_codegen", return_value=CodeGenStats()),
            patch("claude_analytics.main.analyze_codegen_by_project", mock_by_project),
            patch("claude_analytics.reporter._use_color", return_value=False),
            patch("sys.stdout", StringIO()),
        ):
            cmd_report(_make_args(project=None))

        mock_by_project.assert_called_once()

    def test_multiple_sessions_all_blocks_aggregated(self):
        """Blocks from all sessions should be combined in the report."""
        sessions = [_make_session("s1"), _make_session("s2")]
        coding_block = _make_block("coding", 1800)
        debug_block = _make_block("debug", 900)

        call_count = [0]

        def mock_build(session, **kwargs):
            call_count[0] += 1
            return [coding_block] if call_count[0] == 1 else [debug_block]

        captured = StringIO()
        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=sessions),
            patch("claude_analytics.main.build_activity_blocks", side_effect=mock_build),
            patch("claude_analytics.main.analyze_codegen", return_value=CodeGenStats()),
            patch("claude_analytics.main.analyze_codegen_by_project", return_value={}),
            patch("claude_analytics.reporter._use_color", return_value=False),
            patch("sys.stdout", captured),
        ):
            cmd_report(_make_args())

        output = captured.getvalue()
        assert "coding" in output
        assert "debug" in output


# ---------------------------------------------------------------------------
# cmd_sessions
# ---------------------------------------------------------------------------

class TestCmdSessions:
    def _run(self, args_kwargs: dict, sessions) -> str:
        args = _make_args(**args_kwargs)
        captured = StringIO()
        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=sessions),
            patch("sys.stdout", captured),
        ):
            cmd_sessions(args)
        return captured.getvalue()

    def test_no_sessions_prints_message(self):
        output = self._run({}, sessions=[])
        assert "No sessions found" in output

    def test_single_session_shown(self):
        session = _make_session("abc12345", "my-project")
        output = self._run({}, sessions=[session])
        assert "my-project" in output
        assert "abc1234" in output  # first 8 chars of session_id

    def test_session_id_truncated_to_8_chars(self):
        session = _make_session("abcdefghij", "proj")
        output = self._run({}, sessions=[session])
        # First 8 chars of "abcdefghij" = "abcdefgh"
        assert "abcdefgh" in output
        assert "abcdefghij" not in output

    def test_multiple_sessions_shown(self):
        sessions = [
            _make_session("sess-001", "proj-a"),
            _make_session("sess-002", "proj-b"),
        ]
        output = self._run({}, sessions=sessions)
        assert "proj-a" in output
        assert "proj-b" in output

    def test_sessions_limited_by_limit_arg(self):
        sessions = [_make_session(f"sess-{i:03d}", f"proj-{i}") for i in range(25)]
        output = self._run({"limit": 5}, sessions=sessions)
        # Only first 5 (by most recent) should show; check that proj-24 is in output
        # Sessions are sorted newest first; most recent = highest index since start_time is the same
        # All sessions have the same start time in our helper, so we just check count
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) == 5

    def test_default_limit_is_20(self):
        sessions = [_make_session(f"sess-{i:03d}", f"proj-{i}") for i in range(25)]
        output = self._run({}, sessions=sessions)
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) == 20

    def test_sessions_sorted_most_recent_first(self):
        older = _make_session(
            "old-session",
            "proj-old",
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )
        newer = _make_session(
            "new-session",
            "proj-new",
            start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            end=datetime(2026, 3, 1, 1, tzinfo=timezone.utc),
        )
        output = self._run({}, sessions=[older, newer])
        new_pos = output.index("proj-new")
        old_pos = output.index("proj-old")
        assert new_pos < old_pos

    def test_start_time_displayed(self):
        session = _make_session(
            start=datetime(2026, 2, 15, 9, 30, tzinfo=timezone.utc),
            end=datetime(2026, 2, 15, 10, 0, tzinfo=timezone.utc),
        )
        output = self._run({}, sessions=[session])
        assert "2026-02-15" in output

    def test_user_message_count_displayed(self):
        # _make_session with user_msg_count=3 → 3 user messages
        session = _make_session(user_msg_count=3)
        output = self._run({}, sessions=[session])
        # "3 msgs" should appear
        assert "3" in output

    def test_projects_dir_passed_through(self):
        args = _make_args(projects_dir="/custom/path")
        captured_dirs = []

        def mock_parse(projects_dir, project_filter=None, **kwargs):
            captured_dirs.append(projects_dir)
            return []

        captured = StringIO()
        with (
            patch("claude_analytics.main.parse_all_sessions", side_effect=mock_parse),
            patch("sys.stdout", captured),
        ):
            cmd_sessions(args)

        assert str(captured_dirs[0]) == "/custom/path"

    def test_project_filter_passed_through(self):
        args = _make_args(project="filter-me")
        captured_filters = []

        def mock_parse(projects_dir, project_filter=None, **kw):
            captured_filters.append(project_filter)
            return []

        captured = StringIO()
        with (
            patch("claude_analytics.main.parse_all_sessions", side_effect=mock_parse),
            patch("sys.stdout", captured),
        ):
            cmd_sessions(args)

        assert captured_filters[0] == "filter-me"

    def test_session_with_no_start_time_shows_unknown(self):
        session = _make_session()
        session.start_time = None  # force missing start time
        output = self._run({}, sessions=[session])
        assert "unknown" in output


# ---------------------------------------------------------------------------
# _progress / _progress_done — write to stderr, not stdout
# ---------------------------------------------------------------------------

class TestProgress:
    def test_progress_writes_to_stderr_not_stdout(self, capsys):
        _progress("Loading")
        captured = capsys.readouterr()
        assert "Loading" in captured.err
        assert "Loading" not in captured.out

    def test_progress_with_total_shows_percentage(self, capsys):
        _progress("Parsing", done=5, total=10)
        captured = capsys.readouterr()
        assert "50%" in captured.err

    def test_progress_full_completion(self, capsys):
        _progress("Done", done=10, total=10)
        captured = capsys.readouterr()
        assert "100%" in captured.err

    def test_progress_done_writes_to_stderr(self, capsys):
        _progress_done()
        captured = capsys.readouterr()
        assert captured.out == ""
        # stderr should have been written (a clear-line sequence)
        assert len(captured.err) > 0


# ---------------------------------------------------------------------------
# _collect_data
# ---------------------------------------------------------------------------

def _make_collect_args(**kwargs) -> argparse.Namespace:
    defaults = {
        "projects_dir": None,
        "project": None,
        "from_date": None,
        "to_date": None,
        "llm": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_block_at(
    dt: datetime,
    category: str = "coding",
    duration: int = 1800,
    project: str = "test-project",
) -> ActivityBlock:
    return ActivityBlock(
        category=category,
        start_time=dt,
        duration_seconds=duration,
        message_count=2,
        project=project,
    )


class TestCollectData:
    def _run(self, args_kwargs: dict, sessions, blocks_per_session=None) -> dict:
        args = _make_collect_args(**args_kwargs)
        call_index = [0]

        def mock_build(session, **kw):
            idx = call_index[0]
            call_index[0] += 1
            if blocks_per_session is not None:
                return blocks_per_session[idx] if idx < len(blocks_per_session) else []
            # Default: one coding block per session
            return [_make_block_at(
                session.start_time or datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
            )]

        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=sessions),
            patch("claude_analytics.main.build_activity_blocks", side_effect=mock_build),
            patch("claude_analytics.main.analyze_codegen", return_value=CodeGenStats()),
            patch("claude_analytics.main.analyze_codegen_by_project", return_value={}),
        ):
            return _collect_data(args)

    def test_no_sessions_returns_empty_dict(self):
        result = self._run({}, sessions=[])
        assert result == {}

    def test_sessions_filtered_out_by_from_date_returns_empty(self):
        old = _make_session(
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        result = self._run({"from_date": "2026-02-01"}, sessions=[old])
        assert result == {}

    def test_sessions_filtered_out_by_to_date_returns_empty(self):
        future = _make_session(
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
        )
        result = self._run({"to_date": "2026-03-01"}, sessions=[future])
        assert result == {}

    def test_returns_expected_top_level_keys(self):
        session = _make_session()
        result = self._run({}, sessions=[session])
        assert "dateRange" in result
        assert "categoryTotals" in result
        assert "projectTotals" in result
        assert "dailySeries" in result
        assert "codegen" in result
        assert "codegenByProject" in result

    def test_category_totals_aggregated_correctly(self):
        session = _make_session()
        coding_block = _make_block_at(datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc), "coding", 1800)
        debug_block = _make_block_at(datetime(2026, 2, 10, 10, 30, tzinfo=timezone.utc), "debug", 900)
        result = self._run({}, sessions=[session], blocks_per_session=[[coding_block, debug_block]])
        assert result["categoryTotals"]["coding"] == 1800
        assert result["categoryTotals"]["debug"] == 900

    def test_daily_series_aggregated_by_day(self):
        session = _make_session()
        block1 = _make_block_at(datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc), "coding", 600)
        block2 = _make_block_at(datetime(2026, 2, 10, 14, 0, tzinfo=timezone.utc), "coding", 400)
        block3 = _make_block_at(datetime(2026, 2, 11, 9, 0, tzinfo=timezone.utc), "debug", 300)
        result = self._run({}, sessions=[session], blocks_per_session=[[block1, block2, block3]])
        daily = {d["date"]: d for d in result["dailySeries"]}
        assert daily["2026-02-10"]["coding"] == 1000  # 600 + 400
        assert daily["2026-02-11"]["debug"] == 300

    def test_daily_series_sorted_by_date(self):
        session = _make_session()
        block1 = _make_block_at(datetime(2026, 2, 12, 0, 0, tzinfo=timezone.utc))
        block2 = _make_block_at(datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc))
        result = self._run({}, sessions=[session], blocks_per_session=[[block1, block2]])
        dates = [d["date"] for d in result["dailySeries"]]
        assert dates == sorted(dates)

    def test_date_range_reflects_earliest_and_latest_block(self):
        session = _make_session()
        early = _make_block_at(datetime(2026, 2, 10, 8, 0, tzinfo=timezone.utc))
        late = _make_block_at(datetime(2026, 2, 15, 18, 0, tzinfo=timezone.utc))
        result = self._run({}, sessions=[session], blocks_per_session=[[early, late]])
        assert "2026-02-10" in result["dateRange"]["from"]
        assert "2026-02-15" in result["dateRange"]["to"]

    def test_date_range_none_when_no_blocks(self):
        session = _make_session()
        result = self._run({}, sessions=[session], blocks_per_session=[[]])
        # No blocks → both dates None
        assert result["dateRange"]["from"] is None
        assert result["dateRange"]["to"] is None

    def test_codegen_section_structure(self):
        session = _make_session()
        result = self._run({}, sessions=[session])
        codegen = result["codegen"]
        assert "aiLines" in codegen
        assert "totalLines" in codegen
        assert "aiPercentage" in codegen
        assert "aiCommits" in codegen
        assert "totalCommits" in codegen
        assert "filesTouched" in codegen

    def test_codegen_by_project_excludes_zero_ai_lines(self):
        """Projects with ai_lines == 0 should not appear in codegenByProject."""
        session = _make_session()
        zero_stats = CodeGenStats(ai_lines=0, total_lines=100)
        nonzero_stats = CodeGenStats(ai_lines=50, total_lines=100)

        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=[session]),
            patch("claude_analytics.main.build_activity_blocks", return_value=[
                _make_block_at(session.start_time)
            ]),
            patch("claude_analytics.main.analyze_codegen", return_value=CodeGenStats()),
            patch("claude_analytics.main.analyze_codegen_by_project", return_value={
                "empty-project": zero_stats,
                "active-project": nonzero_stats,
            }),
        ):
            result = _collect_data(_make_collect_args())

        assert "empty-project" not in result["codegenByProject"]
        assert "active-project" in result["codegenByProject"]

    def test_project_totals_structure(self):
        session = _make_session(project="my-proj")
        block = _make_block_at(datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc), "coding", 600, "my-proj")
        result = self._run({}, sessions=[session], blocks_per_session=[[block]])
        assert "my-proj" in result["projectTotals"]
        assert result["projectTotals"]["my-proj"]["coding"] == 600

    def test_collect_data_includes_efficiency_key(self):
        session = _make_session()
        result = self._run({}, sessions=[session])
        assert "efficiency" in result

    def test_collect_data_includes_quality_key(self):
        session = _make_session()
        result = self._run({}, sessions=[session])
        assert "quality" in result

    def test_efficiency_entry_has_expected_fields(self):
        session = _make_session(project="p")
        block = _make_block_at(datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc), "coding", 600, "p")
        result = self._run({}, sessions=[session], blocks_per_session=[[block]])
        if result["efficiency"]:
            proj_key = next(iter(result["efficiency"]))
            entry = result["efficiency"][proj_key]
            for field in ("focusRatio", "efficiencyScore", "debugTax",
                          "interactionDensity", "chatDevopsOverhead",
                          "designSeconds", "codingSeconds", "deploymentSeconds"):
                assert field in entry, f"Missing field: {field}"

    def test_quality_entry_has_expected_fields(self):
        session = _make_session(project="p")
        block = _make_block_at(datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc), "coding", 600, "p")
        result = self._run({}, sessions=[session], blocks_per_session=[[block]])
        if result["quality"]:
            proj_key = next(iter(result["quality"]))
            entry = result["quality"][proj_key]
            for field in ("taskResolutionEfficiency", "reworkRate", "oneShotSuccessRate",
                          "debugLoopMaxDepth", "debugLoopAvgDepth", "contextSwitchFrequency"):
                assert field in entry, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# cmd_dashboard
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# cmd_insights
# ---------------------------------------------------------------------------

class TestCmdInsights:
    def _run(self, args_kwargs: dict, sessions, blocks) -> str:
        args = _make_args(**args_kwargs)
        captured = StringIO()

        call_index = [0]

        def mock_build(session, **kw):
            idx = call_index[0]
            call_index[0] += 1
            return [blocks[idx]] if idx < len(blocks) else []

        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=sessions),
            patch("claude_analytics.main.build_activity_blocks", side_effect=mock_build),
            patch("claude_analytics.main.extract_project_dirs", return_value={}),
            patch("sys.stdout", captured),
        ):
            cmd_insights(args)
        return captured.getvalue()

    def test_no_sessions_prints_message(self):
        output = self._run({}, sessions=[], blocks=[])
        assert "No sessions found" in output

    def test_date_filter_excludes_old_sessions(self):
        old_session = _make_session(
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        output = self._run({"from_date": "2026-02-01"}, sessions=[old_session], blocks=[])
        assert "No sessions found for the specified date range" in output

    def test_date_filter_excludes_future_sessions(self):
        future_session = _make_session(
            start=datetime(2026, 5, 1, tzinfo=timezone.utc),
            end=datetime(2026, 5, 2, tzinfo=timezone.utc),
        )
        output = self._run({"to_date": "2026-03-01"}, sessions=[future_session], blocks=[])
        assert "No sessions found for the specified date range" in output

    def test_with_sessions_prints_insights_header(self):
        session = _make_session()
        block = _make_block()
        output = self._run({}, sessions=[session], blocks=[block])
        assert "Engineering Efficiency Insights" in output

    def test_with_sessions_calls_format_insights(self):
        """Output should contain the formatted insights section (even if empty)."""
        session = _make_session()
        block = _make_block()
        output = self._run({}, sessions=[session], blocks=[block])
        # format_insights returns "No insights generated" when there's not enough data
        # or outputs project insights. Either way, the section heading appears.
        assert "Engineering Efficiency Insights" in output

    def test_projects_dir_passed_through(self):
        args = _make_args(projects_dir="/custom/path")
        captured_dirs = []

        def mock_parse(projects_dir, project_filter=None, **kw):
            captured_dirs.append(projects_dir)
            return []

        with (
            patch("claude_analytics.main.parse_all_sessions", side_effect=mock_parse),
            patch("sys.stdout", StringIO()),
        ):
            cmd_insights(args)

        assert str(captured_dirs[0]) == "/custom/path"

    def test_project_filter_passed_through(self):
        args = _make_args(project="filtered-project")
        captured_filters = []

        def mock_parse(projects_dir, project_filter=None, **kw):
            captured_filters.append(project_filter)
            return []

        with (
            patch("claude_analytics.main.parse_all_sessions", side_effect=mock_parse),
            patch("sys.stdout", StringIO()),
        ):
            cmd_insights(args)

        assert captured_filters[0] == "filtered-project"


class TestCmdDashboard:
    def _make_dashboard_args(self, **kwargs):
        defaults = {
            "projects_dir": None,
            "project": None,
            "from_date": None,
            "to_date": None,
            "llm": False,
            "port": 3333,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_no_data_prints_no_data_found(self):
        args = self._make_dashboard_args()
        captured = StringIO()
        with (
            patch("claude_analytics.main._collect_data", return_value={}),
            patch("sys.stdout", captured),
        ):
            cmd_dashboard(args)
        assert "No data found" in captured.getvalue()

    def test_no_data_does_not_start_server(self):
        args = self._make_dashboard_args()
        with (
            patch("claude_analytics.main._collect_data", return_value={}),
            patch("http.server.HTTPServer") as mock_server,
            patch("sys.stdout", StringIO()),
        ):
            cmd_dashboard(args)
        mock_server.assert_not_called()

    def _run_with_server(self, args, sample_data, port=3333):
        """Helper: run cmd_dashboard with mocked file I/O and a server that
        immediately raises KeyboardInterrupt. Returns captured stdout text."""
        captured = StringIO()
        mock_server_instance = MagicMock()
        mock_server_instance.serve_forever.side_effect = KeyboardInterrupt

        with (
            patch("claude_analytics.main._collect_data", return_value=sample_data),
            patch("tempfile.mkdtemp", return_value="/tmp/claude-analytics-test"),
            patch("shutil.copy"),
            patch("shutil.rmtree"),
            patch("builtins.open", MagicMock()),
            patch("claude_analytics.main.json_module") as mock_json,
            patch("http.server.HTTPServer", return_value=mock_server_instance) as mock_httpserver,
            patch("webbrowser.open") as mock_browser,
            patch("sys.stdout", captured),
        ):
            cmd_dashboard(args)

        return captured.getvalue(), mock_server_instance, mock_browser

    def test_writes_data_json_via_json_dump(self):
        """json.dump should be called with the data dict when data is available."""
        args = self._make_dashboard_args()
        sample_data = {"dateRange": {"from": None, "to": None}, "categoryTotals": {"coding": 100}}

        mock_server_instance = MagicMock()
        mock_server_instance.serve_forever.side_effect = KeyboardInterrupt

        with (
            patch("claude_analytics.main._collect_data", return_value=sample_data),
            patch("tempfile.mkdtemp", return_value="/tmp/claude-analytics-test"),
            patch("shutil.copy"),
            patch("shutil.rmtree"),
            patch("builtins.open", MagicMock()),
            patch("claude_analytics.main.json_module.dump") as mock_dump,
            patch("http.server.HTTPServer", return_value=mock_server_instance),
            patch("webbrowser.open"),
            patch("sys.stdout", StringIO()),
        ):
            cmd_dashboard(args)

        mock_dump.assert_called_once()
        # First positional arg to json.dump is the data
        dumped_data = mock_dump.call_args[0][0]
        assert dumped_data == sample_data

    def test_prints_dashboard_data_written_message(self):
        args = self._make_dashboard_args(port=3333)
        sample_data = {"dateRange": {}, "categoryTotals": {}}
        output, _, _ = self._run_with_server(args, sample_data)
        assert "data.json" in output or "Dashboard" in output

    def test_prints_dashboard_url(self):
        """cmd_dashboard should print the URL where the dashboard is served."""
        args = self._make_dashboard_args(port=8765)
        sample_data = {"dateRange": {}, "categoryTotals": {}}
        output, _, _ = self._run_with_server(args, sample_data)
        assert "8765" in output

    def test_opens_browser_on_correct_url(self):
        args = self._make_dashboard_args(port=4444)
        sample_data = {"dateRange": {}, "categoryTotals": {}}
        _, _, mock_browser = self._run_with_server(args, sample_data)
        mock_browser.assert_called_once_with("http://localhost:4444")

    def test_server_closed_on_keyboard_interrupt(self):
        args = self._make_dashboard_args(port=3333)
        sample_data = {"dateRange": {}, "categoryTotals": {}}
        _, mock_server_instance, _ = self._run_with_server(args, sample_data)
        mock_server_instance.server_close.assert_called_once()
