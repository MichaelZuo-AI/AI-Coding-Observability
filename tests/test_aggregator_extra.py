"""Additional edge-case tests for aggregator internals not covered by test_aggregator.py."""

import pytest
from datetime import datetime, timedelta, timezone
from claude_analytics.models import Message, Session, ActivityBlock
from claude_analytics.aggregator import (
    calculate_active_time,
    build_activity_blocks,
    _finalize_block,
    IDLE_THRESHOLD_SECONDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 2, 10, 10, 0, 0, tzinfo=timezone.utc)


def _msg(
    role: str,
    content: str,
    ts: datetime,
    tools: list[str] | None = None,
) -> Message:
    return Message(role=role, content=content, timestamp=ts, tool_uses=tools or [])


def _ts(hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 2, 10, hour, minute, second, tzinfo=timezone.utc)


def _offset(seconds: int) -> datetime:
    """Return a datetime that is `seconds` after the base time."""
    return _BASE + timedelta(seconds=seconds)


def _session(messages: list[Message], project: str = "test-proj") -> Session:
    start = messages[0].timestamp if messages else None
    end = messages[-1].timestamp if messages else None
    return Session(
        session_id="test-session",
        project=project,
        messages=messages,
        start_time=start,
        end_time=end,
    )


# ---------------------------------------------------------------------------
# calculate_active_time
# ---------------------------------------------------------------------------

class TestCalculateActiveTime:
    def test_empty_messages_returns_zero(self):
        assert calculate_active_time([]) == 0

    def test_single_message_returns_zero(self):
        msgs = [_msg("user", "hi", _ts())]
        assert calculate_active_time(msgs) == 0

    def test_consecutive_messages_counted(self):
        msgs = [
            _msg("user", "a", _ts(10, 0, 0)),
            _msg("assistant", "b", _ts(10, 0, 5)),  # 5 seconds gap
        ]
        result = calculate_active_time(msgs)
        assert result == 5

    def test_idle_gap_excluded(self):
        """Gap >= IDLE_THRESHOLD_SECONDS should not be counted."""
        msgs = [
            _msg("user", "a", _offset(0)),
            _msg("user", "b", _offset(IDLE_THRESHOLD_SECONDS)),  # exactly threshold -- excluded
        ]
        result = calculate_active_time(msgs)
        assert result == 0

    def test_just_under_threshold_included(self):
        gap = IDLE_THRESHOLD_SECONDS - 1
        msgs = [
            _msg("user", "a", _offset(0)),
            _msg("user", "b", _offset(gap)),
        ]
        result = calculate_active_time(msgs)
        assert result == gap

    def test_multiple_active_intervals_summed(self):
        msgs = [
            _msg("user", "a", _ts(10, 0, 0)),
            _msg("user", "b", _ts(10, 0, 30)),   # +30s active
            _msg("user", "c", _ts(10, 1, 0)),    # +30s active
        ]
        result = calculate_active_time(msgs)
        assert result == 60

    def test_mix_active_and_idle_gaps(self):
        msgs = [
            _msg("user", "a", _ts(10, 0, 0)),
            _msg("user", "b", _ts(10, 0, 30)),   # +30s active
            _msg("user", "c", _ts(10, 20, 0)),   # +20min idle -- excluded
            _msg("user", "d", _ts(10, 20, 30)),  # +30s active
        ]
        result = calculate_active_time(msgs)
        assert result == 60

    def test_returns_integer(self):
        msgs = [
            _msg("user", "a", _ts(10, 0, 0)),
            _msg("user", "b", _ts(10, 0, 45)),
        ]
        result = calculate_active_time(msgs)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# build_activity_blocks
# ---------------------------------------------------------------------------

class TestBuildActivityBlocks:
    def test_empty_session_returns_empty(self):
        session = _session([])
        assert build_activity_blocks(session) == []

    def test_no_user_messages_returns_empty(self):
        """A session with only assistant messages produces no blocks."""
        messages = [
            _msg("assistant", "Hello", _ts(10, 0)),
            _msg("assistant", "Done", _ts(10, 5)),
        ]
        session = _session(messages)
        result = build_activity_blocks(session)
        assert result == []

    def test_single_user_message_makes_one_block(self):
        messages = [
            _msg("user", "implement login", _ts(10, 0)),
        ]
        session = _session(messages)
        result = build_activity_blocks(session)
        assert len(result) == 1
        assert result[0].category == "session"

    def test_no_idle_gap_one_block(self):
        """Two user messages within threshold -> should be 1 block."""
        messages = [
            _msg("user", "implement login", _ts(10, 0)),
            _msg("assistant", "Done", _ts(10, 0, 5), ["Write"]),
            _msg("user", "add tests", _ts(10, 3)),
            _msg("assistant", "Tests added", _ts(10, 3, 5), ["Write"]),
        ]
        session = _session(messages)
        blocks = build_activity_blocks(session)
        assert len(blocks) == 1
        assert blocks[0].category == "session"

    def test_idle_gap_creates_separate_blocks(self):
        """A gap >= IDLE_THRESHOLD_SECONDS between user messages -> 2 blocks."""
        idle_gap_minutes = (IDLE_THRESHOLD_SECONDS // 60) + 1
        messages = [
            _msg("user", "implement login", _ts(10, 0)),
            _msg("assistant", "Done", _ts(10, 0, 5), ["Write"]),
            _msg("user", "fix bug", _ts(10, idle_gap_minutes)),
            _msg("assistant", "Fixed", _ts(10, idle_gap_minutes, 5), ["Bash"]),
        ]
        session = _session(messages)
        blocks = build_activity_blocks(session)
        assert len(blocks) == 2

    def test_block_project_name_set(self):
        messages = [
            _msg("user", "implement x", _ts(10, 0)),
            _msg("user", "add tests", _ts(10, 3)),
        ]
        session = _session(messages, project="my-cool-project")
        blocks = build_activity_blocks(session)
        assert all(b.project == "my-cool-project" for b in blocks)

    def test_block_start_time_is_first_message(self):
        messages = [
            _msg("user", "implement x", _ts(10, 0)),
            _msg("assistant", "Done", _ts(10, 0, 5)),
        ]
        session = _session(messages)
        blocks = build_activity_blocks(session)
        assert blocks[0].start_time == _ts(10, 0)

    def test_all_blocks_have_session_category(self):
        """All blocks should have category 'session'."""
        messages = [
            _msg("user", "implement login", _ts(10, 0)),
            _msg("assistant", "Done", _ts(10, 0, 5), ["Write"]),
            _msg("user", "implement logout", _ts(10, 3)),
            _msg("assistant", "Done", _ts(10, 3, 5), ["Edit"]),
            _msg("user", "fix the bug", _ts(10, 6)),
            _msg("assistant", "Fixed", _ts(10, 6, 5), ["Bash"]),
        ]
        session = _session(messages)
        blocks = build_activity_blocks(session)
        assert all(b.category == "session" for b in blocks)

    def test_block_message_count(self):
        messages = [
            _msg("user", "task 1", _ts(10, 0)),
            _msg("assistant", "done 1", _ts(10, 0, 5)),
            _msg("user", "task 2", _ts(10, 3)),
            _msg("assistant", "done 2", _ts(10, 3, 5)),
        ]
        session = _session(messages)
        blocks = build_activity_blocks(session)
        # message_count is user messages in the block
        assert blocks[0].message_count >= 2

    def test_tool_uses_aggregated_in_block(self):
        messages = [
            _msg("user", "code task", _ts(10, 0), tools=["Write"]),
            _msg("assistant", "done", _ts(10, 0, 5)),
            _msg("user", "another task", _ts(10, 3), tools=["Edit"]),
            _msg("assistant", "done", _ts(10, 3, 5)),
        ]
        session = _session(messages)
        blocks = build_activity_blocks(session)
        assert len(blocks) == 1
        assert "Write" in blocks[0].tool_uses or "Edit" in blocks[0].tool_uses


# ---------------------------------------------------------------------------
# _finalize_block
# ---------------------------------------------------------------------------

class TestFinalizeBlock:
    def test_single_message_block(self):
        msg = _msg("user", "implement feature", _ts(10, 0))
        block = _finalize_block([msg], "my-project")
        assert block.category == "session"
        assert block.project == "my-project"
        assert block.message_count == 1

    def test_tool_uses_deduplicated(self):
        msgs = [
            _msg("user", "a", _ts(10, 0), ["Write", "Read"]),
            _msg("user", "b", _ts(10, 3), ["Write", "Edit"]),
        ]
        block = _finalize_block(msgs, "proj")
        assert block.tool_uses.count("Write") == 1

    def test_start_time_is_first_message(self):
        t1 = _ts(10, 0)
        t2 = _ts(10, 5)
        msgs = [
            _msg("user", "a", t1),
            _msg("user", "b", t2),
        ]
        block = _finalize_block(msgs, "proj")
        assert block.start_time == t1

    def test_duration_calculated(self):
        msgs = [
            _msg("user", "a", _ts(10, 0, 0)),
            _msg("user", "b", _ts(10, 0, 30)),
        ]
        block = _finalize_block(msgs, "proj")
        assert block.duration_seconds == 30
