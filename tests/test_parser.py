"""Tests for the JSONL session parser."""

import pytest
from pathlib import Path
from claude_analytics.parser import parse_session, parse_all_sessions, discover_sessions

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PROJECT_DIR = FIXTURES_DIR / "test-project"


@pytest.fixture(autouse=True)
def ensure_fixtures():
    """Generate fixtures if they don't exist."""
    if not PROJECT_DIR.exists():
        from tests.fixtures.generate_fixtures import write_fixtures
        write_fixtures()


def test_discover_sessions():
    paths = discover_sessions(FIXTURES_DIR)
    assert len(paths) >= 4  # at least our 4 valid sessions + 1 short


def test_discover_sessions_with_filter():
    paths = discover_sessions(FIXTURES_DIR, project_filter="test-project")
    assert len(paths) >= 4


def test_discover_sessions_no_match():
    paths = discover_sessions(FIXTURES_DIR, project_filter="nonexistent")
    assert len(paths) == 0


def test_parse_coding_session():
    session = parse_session(PROJECT_DIR / "coding-session-001.jsonl")
    assert session is not None
    assert session.session_id == "coding-session-001"
    assert session.project == "test-project"
    user_msgs = [m for m in session.messages if m.role == "user"]
    assert len(user_msgs) == 4
    assert session.start_time is not None
    assert session.end_time is not None


def test_parse_debug_session():
    session = parse_session(PROJECT_DIR / "debug-session-001.jsonl")
    assert session is not None
    user_msgs = [m for m in session.messages if m.role == "user"]
    assert len(user_msgs) == 3


def test_parse_session_extracts_tool_uses():
    session = parse_session(PROJECT_DIR / "coding-session-001.jsonl")
    assert session is not None
    assistant_msgs = [m for m in session.messages if m.role == "assistant"]
    # First assistant msg should have Write, Edit
    tools = assistant_msgs[0].tool_uses
    assert "Write" in tools or "Edit" in tools


def test_short_session_excluded():
    session = parse_session(PROJECT_DIR / "short-session-001.jsonl")
    assert session is None  # < 2 user messages


def test_parse_all_sessions():
    sessions = parse_all_sessions(FIXTURES_DIR)
    # Should exclude the short session
    assert len(sessions) >= 4
    for s in sessions:
        user_msgs = [m for m in s.messages if m.role == "user"]
        assert len(user_msgs) >= 2


def test_parse_nonexistent_file():
    session = parse_session(PROJECT_DIR / "nonexistent.jsonl")
    assert session is None


def test_timestamps_are_ordered():
    session = parse_session(PROJECT_DIR / "coding-session-001.jsonl")
    assert session is not None
    for i in range(1, len(session.messages)):
        assert session.messages[i].timestamp >= session.messages[i - 1].timestamp
