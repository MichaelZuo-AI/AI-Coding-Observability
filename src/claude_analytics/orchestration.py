"""Orchestration effectiveness classification and scoring.

Classifies each user message into one of 4 roles:
- intent: initial prompt or first message after idle gap
- steering: correction, rejection, or redirect
- clarification: answering AI's question
- acknowledgment: approval or continuation (default)
"""

from __future__ import annotations

import re
from .models import Message

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
