"""Rule-based intent classification for Claude Code interactions."""

import re
from .models import Message, ActivityBlock
from datetime import datetime

RULE_PATTERNS: dict[str, list[re.Pattern]] = {
    "debug": [
        re.compile(r"\b(fix|bug|error|exception|crash|not working|broken|issue|fails?)\b", re.I),
        re.compile(r"\b(why (is|does|isn't|doesn't))\b", re.I),
        re.compile(r"\b(traceback|stack trace|undefined|null pointer)\b", re.I),
        re.compile(r"\b(TypeError|ValueError|KeyError|IndexError|AttributeError)\b"),
        re.compile(r"\b(NaN|ENOENT|EACCES|segfault|panic)\b", re.I),
    ],
    "coding": [
        re.compile(r"\b(implement|write|create|add|build|generate|refactor|migrate)\b", re.I),
        re.compile(r"\b(function|class|method|api|endpoint|component|module)\b", re.I),
        re.compile(r"\b(feature|functionality|integrate)\b", re.I),
    ],
    "design": [
        re.compile(r"\b(design|architect|structure|plan|approach|tradeoff|best (way|practice))\b", re.I),
        re.compile(r"\b(how should|should (i|we)|what('s| is) the best)\b", re.I),
        re.compile(r"\b(compare|pros and cons|alternatives?)\b", re.I),
    ],
    "review": [
        re.compile(r"\b(review|feedback|looks good|lgtm|code review)\b", re.I),
        re.compile(r"\b(explain|walk me through|what does this)\b", re.I),
    ],
    "devops": [
        re.compile(r"\b(deploy|pipeline|ci|cd|docker|k8s|kubernetes|terraform|ansible)\b", re.I),
        re.compile(r"\b(build fail|test fail|lint|github actions|vercel|netlify)\b", re.I),
        re.compile(r"\b(nginx|ssl|dns|certificate|env var|secret)\b", re.I),
    ],
}

# Tool-use signals — maps tool names to category weights
TOOL_SIGNALS: dict[str, dict[str, float]] = {
    "Edit": {"coding": 1.5},
    "Write": {"coding": 1.5},
    "MultiEdit": {"coding": 1.5},
    "Read": {"design": 0.5, "review": 0.5},
    "Bash": {"debug": 0.5, "devops": 0.5},
    "Grep": {"debug": 0.3, "review": 0.3},
    "Glob": {"design": 0.2},
    "WebSearch": {"design": 0.5},
    "WebFetch": {"design": 0.5},
}


def classify_message(message: Message) -> str:
    """Classify a single user message into an activity category.

    Returns one of: coding, debug, design, review, devops, other
    """
    text = message.content
    scores: dict[str, float] = {
        "coding": 0,
        "debug": 0,
        "design": 0,
        "review": 0,
        "devops": 0,
        "other": 0,
    }

    # Score based on text patterns
    for category, patterns in RULE_PATTERNS.items():
        for pattern in patterns:
            matches = pattern.findall(text)
            scores[category] += len(matches)

    # Score based on tool uses (from the following assistant response)
    for tool in message.tool_uses:
        signals = TOOL_SIGNALS.get(tool, {})
        for category, weight in signals.items():
            scores[category] += weight

    # Pick the highest-scoring category
    best = max(scores, key=lambda k: scores[k])

    # If no signal at all, return "other"
    if scores[best] == 0:
        return "other"

    return best


def classify_interaction(user_msg: Message, assistant_msg: Message | None) -> str:
    """Classify a user-assistant interaction pair.

    Uses the user message text + assistant message tool uses.
    """
    # Build a combined message with user text + assistant tools
    combined_tools = assistant_msg.tool_uses if assistant_msg else []
    combined = Message(
        role="user",
        content=user_msg.content,
        timestamp=user_msg.timestamp,
        tool_uses=combined_tools,
    )
    return classify_message(combined)


def classify_session(messages: list[Message]) -> list[tuple[Message, str]]:
    """Classify all interactions in a session.

    Pairs each user message with the following assistant message to get tool signals.
    Returns list of (user_message, category) tuples.
    """
    results = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.role == "user":
            # Find the next assistant message
            assistant_msg = None
            if i + 1 < len(messages) and messages[i + 1].role == "assistant":
                assistant_msg = messages[i + 1]
            category = classify_interaction(msg, assistant_msg)
            results.append((msg, category))
        i += 1
    return results
