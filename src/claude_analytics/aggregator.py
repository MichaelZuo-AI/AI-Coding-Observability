"""Time aggregation from sessions."""

from datetime import datetime
from .models import Session, ActivityBlock, Message

IDLE_THRESHOLD_SECONDS = 600


def calculate_active_time(messages: list[Message]) -> int:
    active = 0
    for i in range(1, len(messages)):
        gap = (messages[i].timestamp - messages[i - 1].timestamp).total_seconds()
        if gap < IDLE_THRESHOLD_SECONDS:
            active += gap
    return int(active)


def build_activity_blocks(session: Session) -> list[ActivityBlock]:
    if not session.messages:
        return []
    user_messages = [m for m in session.messages if m.role == "user"]
    if not user_messages:
        return []
    blocks: list[ActivityBlock] = []
    current_msgs: list[Message] = [user_messages[0]]
    for i in range(1, len(user_messages)):
        gap = (user_messages[i].timestamp - user_messages[i - 1].timestamp).total_seconds()
        if gap >= IDLE_THRESHOLD_SECONDS:
            blocks.append(_finalize_block(current_msgs, session.project))
            current_msgs = [user_messages[i]]
        else:
            current_msgs.append(user_messages[i])
    if current_msgs:
        blocks.append(_finalize_block(current_msgs, session.project))
    return blocks


def _finalize_block(messages: list[Message], project: str) -> ActivityBlock:
    all_tools: list[str] = []
    for msg in messages:
        for t in msg.tool_uses:
            if t not in all_tools:
                all_tools.append(t)
    duration = calculate_active_time(messages)
    return ActivityBlock(
        category="session",
        start_time=messages[0].timestamp,
        duration_seconds=duration,
        message_count=len(messages),
        tool_uses=all_tools,
        project=project,
    )
