"""Additional edge-case tests for aggregator internals not covered by test_aggregator.py."""

import pytest
from datetime import datetime, timezone
from claude_analytics.models import Message, Session, ActivityBlock
from claude_analytics.aggregator import (
    calculate_active_time,
    build_activity_blocks,
    aggregate_by_category,
    aggregate_by_project,
    _finalize_block,
    IDLE_THRESHOLD_SECONDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(
    role: str,
    content: str,
    ts: datetime,
    tools: list[str] | None = None,
) -> Message:
    return Message(role=role, content=content, timestamp=ts, tool_uses=tools or [])


def _ts(hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 2, 10, hour, minute, second, tzinfo=timezone.utc)


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
            _msg("user", "a", _ts(10, 0)),
            _msg("user", "b", _ts(10, 0, IDLE_THRESHOLD_SECONDS)),  # exactly threshold — excluded
        ]
        result = calculate_active_time(msgs)
        assert result == 0

    def test_just_under_threshold_included(self):
        gap = IDLE_THRESHOLD_SECONDS - 1
        msgs = [
            _msg("user", "a", _ts(10, 0, 0)),
            _msg("user", "b", _ts(10, 0, gap)),
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
            _msg("user", "c", _ts(10, 20, 0)),   # +20min idle — excluded
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
        """A session with only assistant messages produces no blocks (no user interactions)."""
        messages = [
            _msg("assistant", "Hello", _ts(10, 0)),
            _msg("assistant", "Done", _ts(10, 5)),
        ]
        session = _session(messages)
        result = build_activity_blocks(session)
        # No user messages → classify_session returns empty → no blocks
        assert result == []

    def test_single_user_message_makes_one_block(self):
        """Single user message (no assistant following) → 1 block."""
        messages = [
            _msg("user", "implement login", _ts(10, 0)),
        ]
        session = _session(messages)
        # Won't be a valid session (< 2 user msgs), but build_activity_blocks
        # works on the raw message list — it gets called post-parse
        result = build_activity_blocks(session)
        assert len(result) == 1

    def test_no_idle_gap_one_block(self):
        """Two interactions within threshold → should be 1 block."""
        messages = [
            _msg("user", "implement login", _ts(10, 0)),
            _msg("assistant", "Done", _ts(10, 0, 5), ["Write"]),
            _msg("user", "add tests", _ts(10, 3)),
            _msg("assistant", "Tests added", _ts(10, 3, 5), ["Write"]),
        ]
        session = _session(messages)
        blocks = build_activity_blocks(session)
        assert len(blocks) == 1

    def test_idle_gap_creates_separate_blocks(self):
        """A gap >= IDLE_THRESHOLD_SECONDS between interactions → 2 blocks."""
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

    def test_dominant_category_assigned(self):
        """With 2 coding and 1 debug user message, the block should be 'coding'."""
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
        # Both interactions are user messages — coding has 2, debug has 1
        assert len(blocks) == 1
        # The dominant category should be coding (2 vs 1)
        assert blocks[0].category == "coding"

    def test_block_message_count(self):
        messages = [
            _msg("user", "task 1", _ts(10, 0)),
            _msg("assistant", "done 1", _ts(10, 0, 5)),
            _msg("user", "task 2", _ts(10, 3)),
            _msg("assistant", "done 2", _ts(10, 3, 5)),
        ]
        session = _session(messages)
        blocks = build_activity_blocks(session)
        # message_count is total messages in the block (user + assistant)
        assert blocks[0].message_count >= 2

    def test_tool_uses_aggregated_in_block(self):
        messages = [
            _msg("user", "code task", _ts(10, 0)),
            _msg("assistant", "done", _ts(10, 0, 5), ["Write", "Read"]),
            _msg("user", "another task", _ts(10, 3)),
            _msg("assistant", "done", _ts(10, 3, 5), ["Edit"]),
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
        classified = [(msg, "coding")]
        block = _finalize_block(classified, "my-project")
        assert block.category == "coding"
        assert block.project == "my-project"
        assert block.message_count == 1

    def test_dominant_category_by_count(self):
        msgs = [
            (_msg("user", "a", _ts(10, 0)), "coding"),
            (_msg("user", "b", _ts(10, 3)), "coding"),
            (_msg("user", "c", _ts(10, 6)), "debug"),
        ]
        block = _finalize_block(msgs, "proj")
        assert block.category == "coding"

    def test_tool_uses_deduplicated(self):
        msgs = [
            (_msg("user", "a", _ts(10, 0), ["Write", "Read"]), "coding"),
            (_msg("user", "b", _ts(10, 3), ["Write", "Edit"]), "coding"),
        ]
        block = _finalize_block(msgs, "proj")
        assert block.tool_uses.count("Write") == 1

    def test_start_time_is_first_message(self):
        t1 = _ts(10, 0)
        t2 = _ts(10, 5)
        msgs = [
            (_msg("user", "a", t1), "coding"),
            (_msg("user", "b", t2), "coding"),
        ]
        block = _finalize_block(msgs, "proj")
        assert block.start_time == t1

    def test_duration_calculated(self):
        msgs = [
            (_msg("user", "a", _ts(10, 0, 0)), "coding"),
            (_msg("user", "b", _ts(10, 0, 30)), "coding"),
        ]
        block = _finalize_block(msgs, "proj")
        assert block.duration_seconds == 30


# ---------------------------------------------------------------------------
# aggregate_by_category
# ---------------------------------------------------------------------------

class TestAggregateByCategoryExtra:
    def test_empty_blocks(self):
        result = aggregate_by_category([])
        assert result == {}

    def test_single_block(self):
        block = ActivityBlock(
            category="coding",
            start_time=_ts(10, 0),
            duration_seconds=3600,
            message_count=2,
        )
        result = aggregate_by_category([block])
        assert result == {"coding": 3600}

    def test_multiple_same_category(self):
        blocks = [
            ActivityBlock("coding", _ts(10, 0), 1800, 2),
            ActivityBlock("coding", _ts(11, 0), 900, 1),
        ]
        result = aggregate_by_category(blocks)
        assert result == {"coding": 2700}

    def test_multiple_categories(self):
        blocks = [
            ActivityBlock("coding", _ts(10, 0), 1800, 2),
            ActivityBlock("debug", _ts(11, 0), 900, 1),
        ]
        result = aggregate_by_category(blocks)
        assert result["coding"] == 1800
        assert result["debug"] == 900

    def test_zero_duration_included(self):
        block = ActivityBlock("coding", _ts(10, 0), 0, 1)
        result = aggregate_by_category([block])
        assert result["coding"] == 0


# ---------------------------------------------------------------------------
# aggregate_by_project
# ---------------------------------------------------------------------------

class TestAggregateByProjectExtra:
    def test_empty_blocks(self):
        result = aggregate_by_project([])
        assert result == {}

    def test_single_project_single_category(self):
        block = ActivityBlock("coding", _ts(10, 0), 1800, 2, project="proj-a")
        result = aggregate_by_project([block])
        assert "proj-a" in result
        assert result["proj-a"]["coding"] == 1800

    def test_multiple_projects(self):
        blocks = [
            ActivityBlock("coding", _ts(10, 0), 1800, 2, project="proj-a"),
            ActivityBlock("debug", _ts(11, 0), 900, 1, project="proj-b"),
        ]
        result = aggregate_by_project(blocks)
        assert "proj-a" in result
        assert "proj-b" in result

    def test_same_project_different_categories(self):
        blocks = [
            ActivityBlock("coding", _ts(10, 0), 1800, 2, project="proj-a"),
            ActivityBlock("debug", _ts(11, 0), 600, 1, project="proj-a"),
        ]
        result = aggregate_by_project(blocks)
        assert result["proj-a"]["coding"] == 1800
        assert result["proj-a"]["debug"] == 600

    def test_same_project_same_category_accumulated(self):
        blocks = [
            ActivityBlock("coding", _ts(10, 0), 1000, 2, project="proj-a"),
            ActivityBlock("coding", _ts(11, 0), 500, 1, project="proj-a"),
        ]
        result = aggregate_by_project(blocks)
        assert result["proj-a"]["coding"] == 1500

    def test_empty_project_name_handled(self):
        block = ActivityBlock("coding", _ts(10, 0), 600, 1, project="")
        result = aggregate_by_project([block])
        assert "" in result
