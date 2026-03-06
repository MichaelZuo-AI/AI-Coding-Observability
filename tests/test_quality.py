"""Tests for Phase 4b: quality metrics."""

import pytest
from datetime import datetime, timezone, timedelta
from claude_analytics.quality import (
    compute_task_resolution,
    compute_one_shot_success,
    compute_debug_loop_depth,
    compute_context_switches,
    compute_prompt_effectiveness,
    compute_quality,
    QualityMetrics,
)
from claude_analytics.models import ActivityBlock, Message, Session


def _block(
    category: str,
    duration: int = 300,
    offset_min: int = 0,
    project: str = "TestProj",
) -> ActivityBlock:
    start = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=offset_min)
    return ActivityBlock(
        category=category,
        start_time=start,
        duration_seconds=duration,
        message_count=3,
        project=project,
    )


def _msg(content: str, category: str, offset_min: int = 0) -> tuple:
    ts = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=offset_min)
    msg = Message(role="user", content=content, timestamp=ts)
    return (msg, category)


class TestTaskResolution:
    def test_single_coding_block(self):
        blocks = [_block("coding")]
        assert compute_task_resolution(blocks) == pytest.approx(1.0)

    def test_coding_then_debug(self):
        blocks = [
            _block("coding", duration=300, offset_min=0),
            _block("debug", duration=300, offset_min=6),
        ]
        # One task with 2 attempts → 1/2 = 0.5
        assert compute_task_resolution(blocks) == pytest.approx(0.5)

    def test_three_attempts(self):
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("debug", duration=60, offset_min=2),
            _block("debug", duration=60, offset_min=4),
        ]
        assert compute_task_resolution(blocks) == pytest.approx(1 / 3)

    def test_gap_splits_tasks(self):
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("coding", duration=60, offset_min=20),  # >10min gap
        ]
        # Two separate tasks, each 1 attempt → mean(1, 1) = 1.0
        assert compute_task_resolution(blocks) == pytest.approx(1.0)

    def test_non_task_block_splits(self):
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("chat", duration=60, offset_min=2),
            _block("coding", duration=60, offset_min=4),
        ]
        # chat splits into two tasks, each 1 attempt
        assert compute_task_resolution(blocks) == pytest.approx(1.0)

    def test_no_blocks(self):
        assert compute_task_resolution([]) == 1.0

    def test_no_coding_blocks(self):
        blocks = [_block("chat"), _block("devops")]
        assert compute_task_resolution(blocks) == 1.0

    def test_mixed_efficiencies(self):
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("debug", duration=60, offset_min=2),  # task 1: 2 attempts
            _block("chat", duration=60, offset_min=5),    # separator
            _block("coding", duration=60, offset_min=7),  # task 2: 1 attempt
        ]
        # mean(1/2, 1/1) = 0.75
        assert compute_task_resolution(blocks) == pytest.approx(0.75)


class TestOneShotSuccess:
    def test_all_success(self):
        blocks = [
            _block("coding", duration=300, offset_min=0),
            _block("coding", duration=300, offset_min=20),
        ]
        assert compute_one_shot_success(blocks) == pytest.approx(1.0)

    def test_all_failure(self):
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("debug", duration=60, offset_min=2),
        ]
        assert compute_one_shot_success(blocks) == pytest.approx(0.0)

    def test_mixed(self):
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("debug", duration=60, offset_min=2),   # fail
            _block("coding", duration=60, offset_min=5),   # success (next is chat)
            _block("chat", duration=60, offset_min=7),
        ]
        assert compute_one_shot_success(blocks) == pytest.approx(0.5)

    def test_no_coding(self):
        blocks = [_block("debug"), _block("chat")]
        assert compute_one_shot_success(blocks) == 1.0

    def test_debug_after_long_gap(self):
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("debug", duration=60, offset_min=20),  # >10min gap = success
        ]
        assert compute_one_shot_success(blocks) == pytest.approx(1.0)


class TestDebugLoopDepth:
    def test_no_debug(self):
        msgs = [_msg("write code", "coding")]
        assert compute_debug_loop_depth(msgs) == (0, 0.0)

    def test_single_debug(self):
        msgs = [_msg("fix bug", "debug")]
        assert compute_debug_loop_depth(msgs) == (1, 1.0)

    def test_long_chain(self):
        msgs = [
            _msg("fix", "debug"),
            _msg("still broken", "debug"),
            _msg("try again", "debug"),
            _msg("code", "coding"),
            _msg("fix again", "debug"),
        ]
        assert compute_debug_loop_depth(msgs) == (3, 2.0)

    def test_empty(self):
        assert compute_debug_loop_depth([]) == (0, 0.0)

    def test_alternating(self):
        msgs = [
            _msg("fix", "debug"),
            _msg("code", "coding"),
            _msg("fix", "debug"),
            _msg("code", "coding"),
        ]
        # Two runs of 1 each
        assert compute_debug_loop_depth(msgs) == (1, 1.0)


class TestContextSwitches:
    def test_single_project(self):
        blocks = [
            _block("coding", project="A"),
            _block("coding", project="A"),
        ]
        assert compute_context_switches(blocks, session_count=1) == 0.0

    def test_two_projects(self):
        blocks = [
            _block("coding", project="A"),
            _block("coding", project="B"),
            _block("coding", project="A"),
        ]
        assert compute_context_switches(blocks, session_count=1) == 2.0

    def test_zero_sessions(self):
        blocks = [_block("coding")]
        assert compute_context_switches(blocks, session_count=0) == 0.0

    def test_multiple_sessions(self):
        blocks = [
            _block("coding", project="A"),
            _block("coding", project="B"),
        ]
        assert compute_context_switches(blocks, session_count=2) == pytest.approx(0.5)


class TestPromptEffectiveness:
    def test_no_data(self):
        assert compute_prompt_effectiveness([], []) == 0.0

    def test_no_coding_messages(self):
        blocks = [_block("debug")]
        msgs = [_msg("fix this", "debug")]
        assert compute_prompt_effectiveness(blocks, msgs) == 0.0


class TestComputeQuality:
    def test_basic(self):
        blocks = [
            _block("coding", duration=300, offset_min=0),
            _block("debug", duration=300, offset_min=6),
        ]
        result = compute_quality(blocks, sessions=[], session_count=1)
        assert result.task_resolution_efficiency == pytest.approx(0.5)
        assert result.one_shot_success_rate == pytest.approx(0.0)
        assert result.rework_rate == 0.0  # no git root

    def test_all_success(self):
        blocks = [
            _block("coding", duration=300, offset_min=0),
            _block("coding", duration=300, offset_min=20),
        ]
        result = compute_quality(blocks, sessions=[], session_count=1)
        assert result.task_resolution_efficiency == pytest.approx(1.0)
        assert result.one_shot_success_rate == pytest.approx(1.0)

    def test_with_debug_loops(self):
        msgs = [
            _msg("fix", "debug"),
            _msg("still broken", "debug"),
            _msg("try again", "debug"),
        ]
        result = compute_quality(
            blocks=[_block("debug")],
            sessions=[],
            classified_messages=msgs,
            session_count=1,
        )
        assert result.debug_loop_max_depth == 3
        assert result.debug_loop_avg_depth == pytest.approx(3.0)

    def test_empty_blocks_returns_defaults(self):
        result = compute_quality([], sessions=[], session_count=0)
        assert result.task_resolution_efficiency == pytest.approx(1.0)
        assert result.one_shot_success_rate == pytest.approx(1.0)
        assert result.debug_loop_max_depth == 0
        assert result.debug_loop_avg_depth == pytest.approx(0.0)
        assert result.rework_rate == 0.0

    def test_no_git_root_rework_rate_zero(self):
        blocks = [_block("coding")]
        result = compute_quality(blocks, sessions=[], git_root=None)
        assert result.rework_rate == 0.0

    def test_quality_metrics_default_values(self):
        m = QualityMetrics()
        assert m.task_resolution_efficiency == pytest.approx(1.0)
        assert m.rework_rate == pytest.approx(0.0)
        assert m.one_shot_success_rate == pytest.approx(1.0)
        assert m.debug_loop_max_depth == 0
        assert m.debug_loop_avg_depth == pytest.approx(0.0)
        assert m.context_switch_frequency == pytest.approx(0.0)
        assert m.prompt_effectiveness == pytest.approx(0.0)


class TestTaskResolutionEdgeCases:
    def test_only_debug_blocks_no_sequences(self):
        """Pure debug blocks without preceding coding still count as task blocks."""
        blocks = [
            _block("debug", duration=60, offset_min=0),
            _block("debug", duration=60, offset_min=2),
        ]
        # One sequence of 2 debug blocks → 1/2 = 0.5
        assert compute_task_resolution(blocks) == pytest.approx(0.5)

    def test_trailing_sequence_counted(self):
        """A task sequence at the end of the block list (no terminating gap) is counted."""
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("debug", duration=60, offset_min=2),
            _block("debug", duration=60, offset_min=4),
        ]
        # One sequence of 3 blocks → 1/3
        assert compute_task_resolution(blocks) == pytest.approx(1 / 3)

    def test_gap_boundary_within_window_keeps_sequence(self):
        """A gap < 10 min between task blocks keeps them in the same sequence."""
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("debug", duration=60, offset_min=8),  # gap = 8min - 1min duration = 7min
        ]
        # One sequence of 2 → 0.5
        assert compute_task_resolution(blocks) == pytest.approx(0.5)


class TestOneShotSuccessEdgeCases:
    def test_last_block_is_coding_counts_as_success(self):
        """A coding block with no following block is a success."""
        blocks = [_block("coding", duration=300, offset_min=0)]
        assert compute_one_shot_success(blocks) == pytest.approx(1.0)

    def test_coding_followed_by_non_debug_is_success(self):
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("devops", duration=60, offset_min=2),
        ]
        assert compute_one_shot_success(blocks) == pytest.approx(1.0)

    def test_two_coding_blocks_second_is_last(self):
        """Second coding block has no follower → both count as success."""
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("coding", duration=60, offset_min=20),
        ]
        assert compute_one_shot_success(blocks) == pytest.approx(1.0)

    def test_empty_coding_blocks_returns_one(self):
        assert compute_one_shot_success([]) == 1.0


class TestDebugLoopDepthEdgeCases:
    def test_trailing_debug_run_counted(self):
        """A debug run at the end of the message list should be included."""
        msgs = [
            _msg("code", "coding"),
            _msg("fix 1", "debug"),
            _msg("fix 2", "debug"),
        ]
        max_d, avg_d = compute_debug_loop_depth(msgs)
        assert max_d == 2
        assert avg_d == pytest.approx(2.0)

    def test_multiple_runs_avg_depth(self):
        msgs = [
            _msg("fix", "debug"),           # run of 1
            _msg("code", "coding"),
            _msg("fix1", "debug"),
            _msg("fix2", "debug"),
            _msg("fix3", "debug"),           # run of 3
        ]
        max_d, avg_d = compute_debug_loop_depth(msgs)
        assert max_d == 3
        assert avg_d == pytest.approx(2.0)  # (1 + 3) / 2

    def test_all_debug_messages_single_run(self):
        msgs = [_msg("fix", "debug") for _ in range(5)]
        max_d, avg_d = compute_debug_loop_depth(msgs)
        assert max_d == 5
        assert avg_d == pytest.approx(5.0)


class TestContextSwitchesEdgeCases:
    def test_single_block_no_transitions(self):
        blocks = [_block("coding", project="A")]
        assert compute_context_switches(blocks, session_count=1) == 0.0

    def test_empty_blocks_no_transitions(self):
        assert compute_context_switches([], session_count=1) == 0.0

    def test_many_rapid_switches(self):
        blocks = [
            _block("coding", project="A"),
            _block("coding", project="B"),
            _block("coding", project="A"),
            _block("coding", project="B"),
        ]
        # 3 transitions / 3 sessions
        assert compute_context_switches(blocks, session_count=3) == pytest.approx(1.0)


class TestPromptEffectivenessEdgeCases:
    def test_success_longer_than_failure_positive(self):
        """Longer prompts on successes → positive value."""
        blocks = [
            _block("coding", duration=60, offset_min=0),
            _block("chat", duration=60, offset_min=2),   # no debug follow → success
            _block("coding", duration=60, offset_min=5),
            _block("debug", duration=60, offset_min=7),  # debug follow within window → failure
        ]
        msgs = [
            _msg("A" * 200, "coding", offset_min=1),  # success message, long
            _msg("B" * 50, "coding", offset_min=6),   # failure message, short
        ]
        result = compute_prompt_effectiveness(blocks, msgs)
        assert result > 0

    def test_only_success_messages_returns_zero(self):
        """If only successes (no failures), returns 0.0."""
        blocks = [
            _block("coding", duration=60, offset_min=0),
            # no following debug block
        ]
        msgs = [_msg("write this feature", "coding", offset_min=1)]
        result = compute_prompt_effectiveness(blocks, msgs)
        assert result == 0.0
