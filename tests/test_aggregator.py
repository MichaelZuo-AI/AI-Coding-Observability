"""Tests for time aggregation."""

import pytest
from pathlib import Path
from claude_analytics.parser import parse_session
from claude_analytics.aggregator import (
    calculate_active_time,
    build_activity_blocks,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PROJECT_DIR = FIXTURES_DIR / "test-project"


@pytest.fixture(autouse=True)
def ensure_fixtures():
    if not PROJECT_DIR.exists():
        from tests.fixtures.generate_fixtures import write_fixtures
        write_fixtures()


def test_calculate_active_time_coding():
    session = parse_session(PROJECT_DIR / "coding-session-001.jsonl")
    assert session is not None
    active = calculate_active_time(session.messages)
    # 4 user msgs at 5-min intervals -> ~15 min = 900s of active time (minus some)
    assert 0 < active <= 1200


def test_calculate_active_time_excludes_idle():
    session = parse_session(PROJECT_DIR / "mixed-session-001.jsonl")
    assert session is not None
    active = calculate_active_time(session.messages)
    # Has a 15-min idle gap which should be excluded
    assert active < 25 * 60


def test_build_activity_blocks_coding():
    session = parse_session(PROJECT_DIR / "coding-session-001.jsonl")
    assert session is not None
    blocks = build_activity_blocks(session)
    assert len(blocks) >= 1
    # All blocks have category "session" in the new aggregator
    assert all(b.category == "session" for b in blocks)


def test_build_activity_blocks_debug():
    session = parse_session(PROJECT_DIR / "debug-session-001.jsonl")
    assert session is not None
    blocks = build_activity_blocks(session)
    assert len(blocks) >= 1
    assert all(b.category == "session" for b in blocks)


def test_build_activity_blocks_with_idle_gap():
    session = parse_session(PROJECT_DIR / "mixed-session-001.jsonl")
    assert session is not None
    blocks = build_activity_blocks(session)
    # Should split into 2+ blocks due to the 15-min idle gap
    assert len(blocks) >= 2


def test_aggregate_by_project():
    session = parse_session(PROJECT_DIR / "coding-session-001.jsonl")
    assert session is not None
    blocks = build_activity_blocks(session)
    assert all(b.project == "test-project" for b in blocks)
