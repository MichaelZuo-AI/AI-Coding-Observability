"""Orchestration effectiveness classification and scoring.

Classifies each user message into one of 4 roles:
- intent: initial prompt or first message after idle gap
- steering: correction, rejection, or redirect
- clarification: answering AI's question
- acknowledgment: approval or continuation (default)
"""

from __future__ import annotations

import re
from .models import Message, Session, OrchestrationSession

IDLE_THRESHOLD_SECONDS = 600

STEERING_PATTERNS = [
    re.compile(r"\b(no|nope|wrong|incorrect|that's not)\b", re.I),
    re.compile(r"\b(don'?t|do not|stop|cancel)\b", re.I),
    re.compile(r"\b(revert|undo|go back|roll back)\b", re.I),
    re.compile(r"\b(instead|actually|rather)\b", re.I),
    re.compile(r"\b(change it to|switch to|use .+ (instead|not))\b", re.I),
    re.compile(r"\b(should be|I meant|not what I)\b", re.I),
    re.compile(r"\b(start over|try again|redo)\b", re.I),
    re.compile(r"\b(that's wrong|this is wrong)\b", re.I),
]


def _is_question(message: Message) -> bool:
    return "?" in message.content


def _matches_steering(text: str) -> bool:
    for pattern in STEERING_PATTERNS:
        if pattern.search(text):
            return True
    return False


COMMIT_PATTERNS = [
    re.compile(r"\b(commit|push|ship|merge|deploy)\b", re.I),
]


def classify_orchestration_role(
    msg: Message,
    prev_assistant: Message | None,
    is_first: bool,
    after_idle: bool,
) -> str:
    """Classify a user message into an orchestration role.

    Priority: intent > clarification > steering > acknowledgment
    """
    if is_first or after_idle:
        return "intent"

    if prev_assistant and _is_question(prev_assistant) and not _matches_steering(msg.content):
        return "clarification"

    if _matches_steering(msg.content):
        return "steering"

    return "acknowledgment"


def compute_precision_score(steering_count: int) -> float:
    return 1.0 / (1 + steering_count)


def session_tier(score: float) -> str:
    if score >= 1.0:
        return "flawless"
    if score >= 0.50:
        return "clean"
    if score >= 0.25:
        return "guided"
    return "heavy"


def _detect_outcome(messages: list[Message]) -> tuple[bool, int | None]:
    if not messages:
        return False, None
    start = messages[0].timestamp
    for msg in messages:
        text = msg.content if msg.content else ""
        for pattern in COMMIT_PATTERNS:
            if pattern.search(text):
                delta = (msg.timestamp - start).total_seconds()
                return True, int(delta)
    return False, None


def analyze_session(session: Session) -> OrchestrationSession:
    if not session.messages:
        return OrchestrationSession(
            session_id=session.session_id, project=session.project,
            total_duration=0, intent_length=0, steering_count=0,
            precision_score=1.0, tier="flawless", has_outcome=False,
            phase_sequence=[], message_count=0,
        )

    user_messages = [(i, m) for i, m in enumerate(session.messages) if m.role == "user"]
    if not user_messages:
        return OrchestrationSession(
            session_id=session.session_id, project=session.project,
            total_duration=0, intent_length=0, steering_count=0,
            precision_score=1.0, tier="flawless", has_outcome=False,
            phase_sequence=[], message_count=len(session.messages),
        )

    phase_sequence: list[str] = []
    steering_count = 0
    intent_length = 0

    for idx, (msg_index, msg) in enumerate(user_messages):
        is_first = idx == 0
        after_idle = False
        if msg_index > 0:
            prev_msg = session.messages[msg_index - 1]
            gap = (msg.timestamp - prev_msg.timestamp).total_seconds()
            after_idle = gap >= IDLE_THRESHOLD_SECONDS

        prev_assistant = None
        if msg_index > 0 and session.messages[msg_index - 1].role == "assistant":
            prev_assistant = session.messages[msg_index - 1]

        role = classify_orchestration_role(msg, prev_assistant, is_first, after_idle)
        phase_sequence.append(role)

        if role == "intent" and intent_length == 0:
            intent_length = len(msg.content)
        if role == "steering":
            steering_count += 1

    score = compute_precision_score(steering_count)
    tier = session_tier(score)

    total_duration = 0
    if session.start_time and session.end_time:
        total_duration = int((session.end_time - session.start_time).total_seconds())

    has_outcome, time_to_first_commit = _detect_outcome(session.messages)

    return OrchestrationSession(
        session_id=session.session_id, project=session.project,
        total_duration=total_duration, intent_length=intent_length,
        steering_count=steering_count, precision_score=score,
        tier=tier, has_outcome=has_outcome,
        phase_sequence=phase_sequence, message_count=len(session.messages),
        time_to_first_commit=time_to_first_commit,
    )
