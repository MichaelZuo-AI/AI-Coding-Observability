"""Phase 4b: Resolution & rework metrics for engineering efficiency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from .models import ActivityBlock, Session, Message
from .codegen import _get_git_commits, _is_code_file, _extract_session_windows

TASK_GAP_SECONDS = 600  # 10 minutes gap = new task sequence
ONESHOT_WINDOW_SECONDS = 600  # 10 minutes window for debug follow-up


@dataclass
class QualityMetrics:
    # Output metrics
    task_resolution_efficiency: float = 1.0
    rework_rate: float = 0.0

    # Input metrics
    one_shot_success_rate: float = 1.0
    debug_loop_max_depth: int = 0
    debug_loop_avg_depth: float = 0.0
    context_switch_frequency: float = 0.0
    prompt_effectiveness: float = 0.0


def _gap_seconds(block: ActivityBlock, next_block: ActivityBlock) -> float:
    """Compute gap between end of block and start of next_block, clamped to >= 0."""
    raw = (next_block.start_time - block.start_time).total_seconds() - block.duration_seconds
    return max(0.0, raw)


def compute_task_resolution(blocks: list[ActivityBlock]) -> float:
    """Compute task resolution efficiency: mean(1/attempts) across task sequences.

    A task sequence is consecutive coding/debug blocks separated by >10min gap
    or a non-coding/debug block.
    """
    task_blocks = {"coding", "debug"}
    sequences: list[int] = []
    current_count = 0

    for i, block in enumerate(blocks):
        if block.category in task_blocks:
            if current_count == 0:
                current_count = 1
            else:
                prev = blocks[i - 1]
                gap = _gap_seconds(prev, block)
                if prev.category in task_blocks and gap < TASK_GAP_SECONDS:
                    current_count += 1
                else:
                    sequences.append(current_count)
                    current_count = 1
        else:
            if current_count > 0:
                sequences.append(current_count)
                current_count = 0

    if current_count > 0:
        sequences.append(current_count)

    if not sequences:
        return 1.0

    return sum(1.0 / s for s in sequences) / len(sequences)


def compute_one_shot_success(blocks: list[ActivityBlock]) -> float:
    """Percentage of coding blocks NOT followed by a debug block within 10 minutes."""
    coding_blocks = [b for b in blocks if b.category == "coding"]
    if not coding_blocks:
        return 1.0

    successes = 0
    for i, block in enumerate(blocks):
        if block.category != "coding":
            continue

        next_block = blocks[i + 1] if i + 1 < len(blocks) else None

        if next_block is None:
            successes += 1
            continue

        gap = _gap_seconds(block, next_block)
        if next_block.category == "debug" and gap < ONESHOT_WINDOW_SECONDS:
            continue  # failed one-shot
        else:
            successes += 1

    return successes / len(coding_blocks)


def compute_debug_loop_depth(
    classified_messages: list[tuple[Message, str]],
) -> tuple[int, float]:
    """Compute max and average consecutive debug chain depth.

    Returns (max_depth, avg_depth).
    """
    if not classified_messages:
        return 0, 0.0

    runs: list[int] = []
    current_run = 0

    for _, category in classified_messages:
        if category == "debug":
            current_run += 1
        else:
            if current_run > 0:
                runs.append(current_run)
            current_run = 0

    if current_run > 0:
        runs.append(current_run)

    if not runs:
        return 0, 0.0

    return max(runs), sum(runs) / len(runs)


def compute_context_switches(
    blocks: list[ActivityBlock],
    session_count: int,
) -> float:
    """Count project transitions per session."""
    if session_count == 0 or len(blocks) < 2:
        return 0.0

    sorted_blocks = sorted(blocks, key=lambda b: b.start_time)
    transitions = 0
    for i in range(1, len(sorted_blocks)):
        if sorted_blocks[i].project != sorted_blocks[i - 1].project:
            transitions += 1

    return transitions / session_count


def compute_prompt_effectiveness(
    blocks: list[ActivityBlock],
    classified_messages: list[tuple[Message, str]],
) -> float:
    """Compute difference in avg message length between successful and failed one-shots.

    Positive = longer prompts correlate with success.
    """
    if not classified_messages or not blocks:
        return 0.0

    # Build coding blocks with their one-shot success status
    coding_block_results: list[tuple[ActivityBlock, bool]] = []
    for i, block in enumerate(blocks):
        if block.category != "coding":
            continue
        next_block = blocks[i + 1] if i + 1 < len(blocks) else None
        if next_block is None:
            coding_block_results.append((block, True))
        else:
            gap = _gap_seconds(block, next_block)
            success = not (next_block.category == "debug" and gap < ONESHOT_WINDOW_SECONDS)
            coding_block_results.append((block, success))

    if not coding_block_results:
        return 0.0

    # Match coding messages to their containing block by timestamp
    success_lengths: list[int] = []
    failure_lengths: list[int] = []

    for msg, cat in classified_messages:
        if cat != "coding":
            continue
        for block, success in coding_block_results:
            block_end = block.start_time + timedelta(seconds=block.duration_seconds)
            if block.start_time <= msg.timestamp <= block_end:
                if success:
                    success_lengths.append(len(msg.content))
                else:
                    failure_lengths.append(len(msg.content))
                break

    if not success_lengths or not failure_lengths:
        return 0.0

    avg_success = sum(success_lengths) / len(success_lengths)
    avg_failure = sum(failure_lengths) / len(failure_lengths)
    return avg_success - avg_failure


def compute_rework_rate(
    sessions: list[Session],
    git_root: str | None = None,
) -> float:
    """Compute rework rate: files modified in 2+ commits within the same session.

    If git_root is None, returns 0.0.
    """
    if not git_root or not sessions:
        return 0.0

    from pathlib import Path

    commits = _get_git_commits(Path(git_root))
    if not commits:
        return 0.0

    session_windows = _extract_session_windows(sessions)
    if not session_windows:
        return 0.0

    total_files = 0
    reworked_files = 0

    for session in sessions:
        if not session.start_time or not session.end_time:
            continue

        start = session.start_time
        end = session.end_time + timedelta(minutes=5)

        session_file_counts: dict[str, int] = {}
        for commit_hash, commit_time, file_stats in commits:
            if start <= commit_time <= end:
                for added, removed, filepath in file_stats:
                    if _is_code_file(filepath):
                        session_file_counts[filepath] = session_file_counts.get(filepath, 0) + 1

        for filepath, count in session_file_counts.items():
            total_files += 1
            if count >= 2:
                reworked_files += 1

    return reworked_files / total_files if total_files > 0 else 0.0


def compute_quality(
    blocks: list[ActivityBlock],
    sessions: list[Session],
    classified_messages: list[tuple[Message, str]] | None = None,
    git_root: str | None = None,
    session_count: int = 1,
) -> QualityMetrics:
    """Compute all quality metrics."""
    task_resolution = compute_task_resolution(blocks)
    one_shot = compute_one_shot_success(blocks)
    max_depth, avg_depth = compute_debug_loop_depth(classified_messages or [])
    context_switches = compute_context_switches(blocks, session_count)
    prompt_eff = compute_prompt_effectiveness(blocks, classified_messages or [])
    rework = compute_rework_rate(sessions, git_root)

    return QualityMetrics(
        task_resolution_efficiency=task_resolution,
        rework_rate=rework,
        one_shot_success_rate=one_shot,
        debug_loop_max_depth=max_depth,
        debug_loop_avg_depth=avg_depth,
        context_switch_frequency=context_switches,
        prompt_effectiveness=prompt_eff,
    )
