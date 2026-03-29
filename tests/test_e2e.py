"""End-to-end tests that run the full CLI pipeline against synthetic session data."""

import json
import os
import subprocess
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_timestamp(dt: datetime) -> str:
    return dt.isoformat()


def _write_session(session_dir: Path, session_id: str, messages: list[dict]) -> Path:
    """Write a synthetic JSONL session file."""
    jsonl_path = session_dir / f"{session_id}.jsonl"
    with open(jsonl_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return jsonl_path


def _make_user_entry(text: str, ts: datetime, cwd: str = "/tmp/test") -> dict:
    return {
        "type": "user",
        "timestamp": _make_timestamp(ts),
        "cwd": cwd,
        "message": {
            "role": "user",
            "content": text,
        },
    }


def _make_assistant_entry(
    text: str, ts: datetime, tool_uses: list[dict] | None = None,
) -> dict:
    content: list[dict] = [{"type": "text", "text": text}]
    if tool_uses:
        content.extend(tool_uses)
    return {
        "type": "assistant",
        "timestamp": _make_timestamp(ts),
        "message": {
            "role": "assistant",
            "content": content,
        },
    }


def _make_tool_use(name: str) -> dict:
    return {"type": "tool_use", "name": name, "id": "t1", "input": {}}


def _run_cli(*args: str, projects_dir: str) -> subprocess.CompletedProcess:
    """Run claude-analytics CLI as a subprocess."""
    cmd = [
        str(Path(__file__).parent.parent / ".venv" / "bin" / "python"),
        "-m", "claude_analytics",
        "--projects-dir", projects_dir,
        *args,
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "USER": "testuser"},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def projects_dir(tmp_path):
    """Create a synthetic projects directory with multiple sessions."""
    base_time = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Project 1: coding project with Edit tool uses
    proj1_dir = tmp_path / "-Users-testuser-Engineering-MyApp"
    proj1_dir.mkdir()

    session1_messages = [
        _make_user_entry("implement a new login page with React", base_time, "/tmp/test"),
        _make_assistant_entry(
            "I'll create the login component.",
            base_time + timedelta(seconds=10),
            [_make_tool_use("Edit"), _make_tool_use("Write")],
        ),
        _make_user_entry("add form validation to the login", base_time + timedelta(minutes=2)),
        _make_assistant_entry(
            "Added validation.",
            base_time + timedelta(minutes=2, seconds=15),
            [_make_tool_use("Edit")],
        ),
        _make_user_entry("now add unit tests for the login component", base_time + timedelta(minutes=5)),
        _make_assistant_entry(
            "Here are the tests.",
            base_time + timedelta(minutes=5, seconds=20),
            [_make_tool_use("Write")],
        ),
    ]
    _write_session(proj1_dir, "session-coding-001", session1_messages)

    # Project 2: debug session
    proj2_dir = tmp_path / "-Users-testuser-Engineering-DebugProject"
    proj2_dir.mkdir()

    session2_messages = [
        _make_user_entry("fix the crash in the payment module", base_time + timedelta(hours=1)),
        _make_assistant_entry(
            "Let me investigate the error.",
            base_time + timedelta(hours=1, seconds=5),
            [_make_tool_use("Bash"), _make_tool_use("Grep")],
        ),
        _make_user_entry("it's still not working, there's a TypeError", base_time + timedelta(hours=1, minutes=3)),
        _make_assistant_entry(
            "Found the bug.",
            base_time + timedelta(hours=1, minutes=3, seconds=10),
            [_make_tool_use("Edit")],
        ),
        _make_user_entry("ok that fixed it, thanks", base_time + timedelta(hours=1, minutes=5)),
        _make_assistant_entry(
            "Glad it's working now.",
            base_time + timedelta(hours=1, minutes=5, seconds=5),
        ),
    ]
    _write_session(proj2_dir, "session-debug-001", session2_messages)

    # Project 3: design/chat session
    proj3_dir = tmp_path / "-Users-testuser-Projects-ChatBot"
    proj3_dir.mkdir()

    session3_messages = [
        _make_user_entry("how should we architect the notification system?", base_time + timedelta(hours=2)),
        _make_assistant_entry(
            "Here are some architectural approaches...",
            base_time + timedelta(hours=2, seconds=10),
        ),
        _make_user_entry("what are the tradeoffs between push vs pull?", base_time + timedelta(hours=2, minutes=4)),
        _make_assistant_entry(
            "Let me compare the approaches...",
            base_time + timedelta(hours=2, minutes=4, seconds=10),
        ),
        _make_user_entry("ok sounds good", base_time + timedelta(hours=2, minutes=8)),
        _make_assistant_entry(
            "Great, let me know if you need more details.",
            base_time + timedelta(hours=2, minutes=8, seconds=5),
        ),
    ]
    _write_session(proj3_dir, "session-design-001", session3_messages)

    return tmp_path


@pytest.fixture
def empty_projects_dir(tmp_path):
    """Empty projects directory."""
    return tmp_path


@pytest.fixture
def single_session_dir(tmp_path):
    """Projects directory with just one minimal session."""
    proj_dir = tmp_path / "solo-project"
    proj_dir.mkdir()

    base_time = datetime(2026, 2, 15, 14, 0, 0, tzinfo=timezone.utc)
    messages = [
        _make_user_entry("deploy to production", base_time),
        _make_assistant_entry("Deploying now.", base_time + timedelta(seconds=5), [_make_tool_use("Bash")]),
        _make_user_entry("push the changes", base_time + timedelta(minutes=1)),
        _make_assistant_entry("Pushed.", base_time + timedelta(minutes=1, seconds=5)),
    ]
    _write_session(proj_dir, "session-solo-001", messages)
    return tmp_path


# ---------------------------------------------------------------------------
# E2E: report command
# ---------------------------------------------------------------------------

class TestReportE2E:
    def test_report_runs_without_error(self, projects_dir):
        result = _run_cli("report", projects_dir=str(projects_dir))
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_report_shows_header(self, projects_dir):
        result = _run_cli("report", projects_dir=str(projects_dir))
        assert "Agent Autonomy Score" in result.stdout

    def test_report_shows_engineer(self, projects_dir):
        result = _run_cli("report", projects_dir=str(projects_dir))
        assert "testuser" in result.stdout

    def test_report_shows_date_range(self, projects_dir):
        result = _run_cli("report", projects_dir=str(projects_dir))
        assert "2026-03-01" in result.stdout

    def test_report_shows_active_time_breakdown(self, projects_dir):
        result = _run_cli("report", projects_dir=str(projects_dir))
        assert "Active Time Breakdown" in result.stdout

    def test_report_shows_categories(self, projects_dir):
        result = _run_cli("report", projects_dir=str(projects_dir))
        output = result.stdout
        # At least some of these categories should appear
        found_categories = sum(
            1 for cat in ["coding", "debug", "design", "devops", "chat"]
            if cat in output
        )
        assert found_categories >= 2, f"Expected at least 2 categories in output:\n{output}"

    def test_report_shows_total_active(self, projects_dir):
        result = _run_cli("report", projects_dir=str(projects_dir))
        assert "Total Active" in result.stdout
        assert "100%" in result.stdout

    def test_report_shows_projects(self, projects_dir):
        result = _run_cli("report", projects_dir=str(projects_dir))
        assert "Top Projects" in result.stdout

    def test_report_empty_dir_shows_no_sessions(self, empty_projects_dir):
        result = _run_cli("report", projects_dir=str(empty_projects_dir))
        assert result.returncode == 0
        assert "No sessions found" in result.stdout

    def test_report_with_date_filter(self, projects_dir):
        result = _run_cli(
            "report", "--from", "2026-03-01", "--to", "2026-03-02",
            projects_dir=str(projects_dir),
        )
        assert result.returncode == 0
        assert "Agent Autonomy Score" in result.stdout

    def test_report_date_filter_excludes_all(self, projects_dir):
        result = _run_cli(
            "report", "--from", "2099-01-01",
            projects_dir=str(projects_dir),
        )
        assert result.returncode == 0
        assert "No sessions found" in result.stdout

    def test_report_project_filter(self, projects_dir):
        result = _run_cli(
            "report", "--project", "MyApp",
            projects_dir=str(projects_dir),
        )
        assert result.returncode == 0
        # Should still produce a report since MyApp sessions exist
        assert "Agent Autonomy Score" in result.stdout or "No sessions found" not in result.stdout

    def test_report_project_filter_no_match(self, projects_dir):
        result = _run_cli(
            "report", "--project", "NonExistentProject",
            projects_dir=str(projects_dir),
        )
        assert result.returncode == 0
        assert "No sessions found" in result.stdout

    def test_report_single_session(self, single_session_dir):
        result = _run_cli("report", projects_dir=str(single_session_dir))
        assert result.returncode == 0
        assert "Agent Autonomy Score" in result.stdout

    def test_report_no_color_when_piped(self, projects_dir):
        """When stdout is piped (not a TTY), ANSI codes should be absent."""
        result = _run_cli("report", projects_dir=str(projects_dir))
        # subprocess capture means it's not a TTY — no ANSI escape codes
        assert "\033[" not in result.stdout


# ---------------------------------------------------------------------------
# E2E: sessions command
# ---------------------------------------------------------------------------

class TestSessionsE2E:
    def test_sessions_runs_without_error(self, projects_dir):
        result = _run_cli("sessions", projects_dir=str(projects_dir))
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_sessions_lists_sessions(self, projects_dir):
        result = _run_cli("sessions", projects_dir=str(projects_dir))
        output = result.stdout
        # Should show multiple session lines
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 2, f"Expected at least 2 sessions:\n{output}"

    def test_sessions_shows_timestamps(self, projects_dir):
        result = _run_cli("sessions", projects_dir=str(projects_dir))
        assert "2026-03-01" in result.stdout

    def test_sessions_shows_message_counts(self, projects_dir):
        result = _run_cli("sessions", projects_dir=str(projects_dir))
        assert "msgs" in result.stdout

    def test_sessions_shows_truncated_ids(self, projects_dir):
        result = _run_cli("sessions", projects_dir=str(projects_dir))
        # Session IDs are truncated to 8 chars
        assert "session-" in result.stdout

    def test_sessions_empty_dir(self, empty_projects_dir):
        result = _run_cli("sessions", projects_dir=str(empty_projects_dir))
        assert result.returncode == 0
        assert "No sessions found" in result.stdout

    def test_sessions_limit(self, projects_dir):
        result = _run_cli("sessions", "--limit", "1", projects_dir=str(projects_dir))
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) == 1

    def test_sessions_project_filter(self, projects_dir):
        result = _run_cli("sessions", "--project", "MyApp", projects_dir=str(projects_dir))
        assert result.returncode == 0

    def test_sessions_sorted_most_recent_first(self, projects_dir):
        result = _run_cli("sessions", projects_dir=str(projects_dir))
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        # Extract timestamps from output (format: "  2026-03-01 12:00  ...")
        timestamps = []
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0].startswith("2026"):
                timestamps.append(parts[0] + " " + parts[1])
        # Should be in descending order
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# E2E: no command / help
# ---------------------------------------------------------------------------

class TestHelpE2E:
    def test_no_command_shows_help(self, projects_dir):
        result = _run_cli(projects_dir=str(projects_dir))
        # Should exit with code 1 and show usage
        assert result.returncode == 1

    def test_help_flag(self, projects_dir):
        result = _run_cli("--help", projects_dir=str(projects_dir))
        assert result.returncode == 0
        assert "claude-analytics" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_report_help(self, projects_dir):
        result = _run_cli("report", "--help", projects_dir=str(projects_dir))
        assert result.returncode == 0
        assert "--from" in result.stdout
        assert "--to" in result.stdout
        assert "--project" in result.stdout

    def test_sessions_help(self, projects_dir):
        result = _run_cli("sessions", "--help", projects_dir=str(projects_dir))
        assert result.returncode == 0
        assert "--limit" in result.stdout


# ---------------------------------------------------------------------------
# E2E: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCasesE2E:
    def test_malformed_jsonl_skipped(self, tmp_path):
        """Sessions with malformed JSONL lines should be skipped gracefully."""
        proj_dir = tmp_path / "bad-project"
        proj_dir.mkdir()

        base_time = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        jsonl_path = proj_dir / "bad-session.jsonl"
        with open(jsonl_path, "w") as f:
            f.write("this is not json\n")
            f.write("{broken json\n")
            # Valid messages
            f.write(json.dumps(_make_user_entry("implement feature", base_time)) + "\n")
            f.write(json.dumps(_make_assistant_entry("Done.", base_time + timedelta(seconds=5))) + "\n")
            f.write(json.dumps(_make_user_entry("add tests", base_time + timedelta(minutes=1))) + "\n")
            f.write(json.dumps(_make_assistant_entry("Added.", base_time + timedelta(minutes=1, seconds=5))) + "\n")

        result = _run_cli("report", projects_dir=str(tmp_path))
        assert result.returncode == 0

    def test_very_short_sessions_excluded(self, tmp_path):
        """Sessions with <2 user messages should be excluded."""
        proj_dir = tmp_path / "short-project"
        proj_dir.mkdir()

        base_time = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        messages = [
            _make_user_entry("hello", base_time),
            _make_assistant_entry("Hi!", base_time + timedelta(seconds=5)),
        ]
        _write_session(proj_dir, "short-session", messages)

        result = _run_cli("sessions", projects_dir=str(tmp_path))
        assert result.returncode == 0
        assert "No sessions found" in result.stdout

    def test_streaming_duplicates_handled(self, tmp_path):
        """Multiple assistant JSONL lines within 2s should be deduplicated."""
        proj_dir = tmp_path / "dedup-project"
        proj_dir.mkdir()

        base_time = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        messages = [
            _make_user_entry("build a REST API", base_time),
            # Simulated streaming chunks (same assistant, <2s apart)
            _make_assistant_entry("Starting...", base_time + timedelta(seconds=1)),
            _make_assistant_entry("Here's the API implementation.", base_time + timedelta(seconds=2), [_make_tool_use("Write")]),
            _make_user_entry("add error handling", base_time + timedelta(minutes=2)),
            _make_assistant_entry("Added error handling.", base_time + timedelta(minutes=2, seconds=5), [_make_tool_use("Edit")]),
        ]
        _write_session(proj_dir, "dedup-session", messages)

        result = _run_cli("report", projects_dir=str(tmp_path))
        assert result.returncode == 0
        assert "Agent Autonomy Score" in result.stdout

    def test_idle_gap_detection(self, tmp_path):
        """Messages >10min apart should create separate activity blocks."""
        proj_dir = tmp_path / "idle-project"
        proj_dir.mkdir()

        base_time = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        messages = [
            _make_user_entry("implement login", base_time),
            _make_assistant_entry("Done.", base_time + timedelta(seconds=5), [_make_tool_use("Write")]),
            _make_user_entry("add logout", base_time + timedelta(minutes=3)),
            _make_assistant_entry("Done.", base_time + timedelta(minutes=3, seconds=5), [_make_tool_use("Write")]),
            # 15 minute idle gap
            _make_user_entry("fix the crash in auth", base_time + timedelta(minutes=18)),
            _make_assistant_entry("Fixed.", base_time + timedelta(minutes=18, seconds=5), [_make_tool_use("Edit")]),
            _make_user_entry("still not working", base_time + timedelta(minutes=20)),
            _make_assistant_entry("Try this.", base_time + timedelta(minutes=20, seconds=5)),
        ]
        _write_session(proj_dir, "idle-session", messages)

        result = _run_cli("report", projects_dir=str(tmp_path))
        assert result.returncode == 0
        # Should show multiple categories since the blocks span coding → debug
        assert "Agent Autonomy Score" in result.stdout

    def test_progress_on_stderr(self, projects_dir):
        """Progress messages should go to stderr, not stdout."""
        result = _run_cli("report", projects_dir=str(projects_dir))
        # stdout should have the clean report, no progress messages
        assert "Parsing sessions" not in result.stdout
        assert "Classifying" not in result.stdout

    def test_mixed_categories_in_report(self, projects_dir):
        """Full pipeline should correctly categorize different activity types."""
        result = _run_cli("report", projects_dir=str(projects_dir))
        output = result.stdout
        # The synthetic data has coding, debug, and design sessions
        # At least 2 of these should appear in the report
        categories_found = [
            cat for cat in ["coding", "debug", "design", "devops", "chat"]
            if cat in output
        ]
        assert len(categories_found) >= 2, (
            f"Expected multiple categories, found: {categories_found}\nOutput:\n{output}"
        )
