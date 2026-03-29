"""Tests for CLI entrypoint (main.py)."""

import argparse
import pytest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

from claude_analytics.main import (
    parse_date,
    cmd_report,
    cmd_sessions,
    _progress,
    _progress_done,
)
from claude_analytics.models import Session, Message, ActivityBlock, OrchestrationSession
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
    category: str = "session",
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


def _make_orch(
    session_id: str = "sess-001",
    project: str = "test-project",
    precision_score: float = 1.0,
    tier: str = "flawless",
    steering_count: int = 0,
) -> OrchestrationSession:
    return OrchestrationSession(
        session_id=session_id,
        project=project,
        total_duration=600,
        intent_length=100,
        steering_count=steering_count,
        precision_score=precision_score,
        tier=tier,
        has_outcome=True,
        phase_sequence=["intent", "acknowledgment"],
        message_count=4,
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
    """Test cmd_report with mocked dependencies."""

    def _run(self, args_kwargs: dict, sessions, blocks, codegen=None) -> str:
        """Run cmd_report and capture stdout output."""
        args = _make_args(**args_kwargs)
        empty_codegen = codegen if codegen is not None else CodeGenStats()

        captured = StringIO()
        with (
            patch("claude_analytics.main.parse_all_sessions", return_value=sessions),
            patch("claude_analytics.main.build_activity_blocks", return_value=blocks),
            patch("claude_analytics.main.analyze_codegen", return_value=empty_codegen),
            patch("claude_analytics.main.analyze_session", side_effect=lambda s: _make_orch(s.session_id, s.project)),
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

    def test_report_contains_orchestration_section(self):
        session = _make_session()
        block = _make_block()
        output = self._run({}, sessions=[session], blocks=[block])
        assert "Orchestration Precision" in output

    def test_report_does_not_contain_old_sections(self):
        session = _make_session()
        block = _make_block()
        output = self._run({}, sessions=[session], blocks=[block])
        assert "Engineering Efficiency" not in output
        assert "Active Time Breakdown" not in output


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
        session = _make_session(user_msg_count=3)
        output = self._run({}, sessions=[session])
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
        session.start_time = None
        output = self._run({}, sessions=[session])
        assert "unknown" in output


# ---------------------------------------------------------------------------
# _progress / _progress_done -- write to stderr, not stdout
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
        assert len(captured.err) > 0
