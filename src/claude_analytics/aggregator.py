"""Time aggregation and statistics from classified sessions."""

from datetime import datetime
from .models import Session, ActivityBlock, Message
from .classifier import classify_session

IDLE_THRESHOLD_SECONDS = 600  # 10 minutes gap = new activity block


def calculate_active_time(messages: list[Message]) -> int:
    """Calculate total active seconds, excluding idle gaps > threshold."""
    active = 0
    for i in range(1, len(messages)):
        gap = (messages[i].timestamp - messages[i - 1].timestamp).total_seconds()
        if gap < IDLE_THRESHOLD_SECONDS:
            active += gap
    return int(active)


def build_activity_blocks(session: Session, use_llm: bool = False) -> list[ActivityBlock]:
    """Break a session into activity blocks based on idle gaps and classification."""
    if not session.messages:
        return []

    classified = classify_session(session.messages, use_llm=use_llm)
    if not classified:
        return []

    blocks: list[ActivityBlock] = []
    current_msgs: list[tuple[Message, str]] = [classified[0]]

    for i in range(1, len(classified)):
        prev_msg = classified[i - 1][0]
        curr_msg = classified[i][0]
        gap = (curr_msg.timestamp - prev_msg.timestamp).total_seconds()

        if gap >= IDLE_THRESHOLD_SECONDS:
            # Idle gap — finalize current block
            blocks.append(_finalize_block(current_msgs, session.project))
            current_msgs = [classified[i]]
        else:
            current_msgs.append(classified[i])

    if current_msgs:
        blocks.append(_finalize_block(current_msgs, session.project))

    return blocks


def _finalize_block(
    classified_msgs: list[tuple[Message, str]], project: str
) -> ActivityBlock:
    """Create an ActivityBlock from a list of classified messages."""
    messages = [m for m, _ in classified_msgs]
    categories = [c for _, c in classified_msgs]

    # Dominant category by count
    category_counts: dict[str, int] = {}
    for cat in categories:
        category_counts[cat] = category_counts.get(cat, 0) + 1
    dominant = max(category_counts, key=lambda k: category_counts[k])

    all_tools: list[str] = []
    for msg in messages:
        for t in msg.tool_uses:
            if t not in all_tools:
                all_tools.append(t)

    duration = calculate_active_time(messages)

    return ActivityBlock(
        category=dominant,
        start_time=messages[0].timestamp,
        duration_seconds=duration,
        message_count=len(messages),
        tool_uses=all_tools,
        project=project,
    )


def aggregate_by_category(
    blocks: list[ActivityBlock],
) -> dict[str, int]:
    """Sum duration_seconds by category across all blocks."""
    totals: dict[str, int] = {}
    for block in blocks:
        totals[block.category] = totals.get(block.category, 0) + block.duration_seconds
    return totals


def aggregate_by_project(
    blocks: list[ActivityBlock],
) -> dict[str, dict[str, int]]:
    """Sum duration_seconds by project, then by category."""
    result: dict[str, dict[str, int]] = {}
    for block in blocks:
        if block.project not in result:
            result[block.project] = {}
        proj = result[block.project]
        proj[block.category] = proj.get(block.category, 0) + block.duration_seconds
    return result
