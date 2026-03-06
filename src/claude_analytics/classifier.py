"""Rule-based intent classification for Claude Code interactions.

Phase 2: Low-confidence interactions are reclassified via `claude -p` (Claude Code CLI)
and cached in SQLite so repeated runs don't re-invoke the CLI.
"""

import re
from .models import Message, ActivityBlock
from datetime import datetime

# Confidence threshold — below this, we try `claude -p` reclassification
CONFIDENCE_THRESHOLD = 1.5

RULE_PATTERNS: dict[str, list[re.Pattern]] = {
    "debug": [
        re.compile(r"\b(fix|bug|error|exception|crash|not working|broken|fails?)\b", re.I),
        re.compile(r"\b(why (is|does|isn't|doesn't))\b", re.I),
        re.compile(r"\b(traceback|stack trace|undefined|null pointer)\b", re.I),
        re.compile(r"\b(TypeError|ValueError|KeyError|IndexError|AttributeError)\b"),
        re.compile(r"\b(NaN|ENOENT|EACCES|segfault|panic)\b", re.I),
        re.compile(r"\b(still not work|doesn't work|can't|cannot)\b", re.I),
        re.compile(r"\b(show nothing|nothing happen|blank page)\b", re.I),
    ],
    "coding": [
        re.compile(r"\b(implement|write|create|add|build|generate|refactor|migrate)\b", re.I),
        re.compile(r"\b(function|class|method|api|endpoint|component|module)\b", re.I),
        re.compile(r"\b(feature|functionality|integrate|modify)\b", re.I),
        re.compile(r"\b(button|page|modal|menu|sidebar|header|footer|widget|dialog)\b", re.I),
        re.compile(r"\b(write tests?|add tests?|run tests?|testing|unit test|e2e test)\b", re.I),
    ],
    "design": [
        re.compile(r"\b(design|architect|structure|plan|approach|tradeoff|best (way|practice))\b", re.I),
        re.compile(r"\b(how should|should (i|we)|what('s| is) the best)\b", re.I),
        re.compile(r"\b(compare|pros and cons|alternatives?)\b", re.I),
        re.compile(r"\b(which part.*(improve|better)|any.*(good )?idea)\b", re.I),
    ],
    "review": [
        re.compile(r"\b(review|feedback|looks good|lgtm|code review)\b", re.I),
        re.compile(r"\b(explain|walk me through|what does this|what is this)\b", re.I),
        re.compile(r"\b(how (does|do) (it|this|that)|how to use)\b", re.I),
        re.compile(r"\b(show me|let me see|check|look at)\b", re.I),
        re.compile(r"(是做什么|怎么用|什么意思|看看|检查)", re.I),
    ],
    "devops": [
        re.compile(r"\b(deploy|pipeline|ci|cd|docker|k8s|kubernetes|terraform|ansible)\b", re.I),
        re.compile(r"\b(build fail|test fail|lint|github actions|vercel|netlify)\b", re.I),
        re.compile(r"\b(nginx|ssl|dns|certificate|env var|secret)\b", re.I),
        re.compile(r"\b(install|setup|config|configure|production|staging)\b", re.I),
        re.compile(r"\b(push|commit|merge|branch|release|version)\b", re.I),
        re.compile(r"\b(production URL|remote|server)\b", re.I),
    ],
    "data": [
        re.compile(r"\b(stock|RSU|option|share|portfolio|cash|account|broker)\b", re.I),
        re.compile(r"\b(update.*(cash|portfolio|account|stock|position))\b", re.I),
        re.compile(r"\b(price|market|trading|invest|dividend|earning|revenue)\b", re.I),
        re.compile(r"\b(分析|净资产|税|纳税|资本|收益|现金|账户)\b"),
        re.compile(r"\b(CPNG|BABA|GOOG|VOO|SPY|DiDi|Tiger)\b"),
        re.compile(r"\b(briefing|report|refresh|wealth|financial)\b", re.I),
        re.compile(r"\b(email|calendar|organize|group|subscribe)\b", re.I),
        re.compile(r"\[Image:\s*source:", re.I),
    ],
    "chat": [
        re.compile(r"^(yes|no|ok|okay|sure|thanks|thank you|got it|go ahead|done|good)\s*$", re.I),
        re.compile(r"^(hey|hi|hello|yo)\b", re.I),
        re.compile(r"<command-name>/(init|login|logout)</command-name>", re.I),
        re.compile(r"\[Request interrupted", re.I),
        re.compile(r"<local-command-", re.I),
        re.compile(r"^.{0,15}$"),  # very short messages
    ],
}

# Tool-use signals — maps tool names to category weights
TOOL_SIGNALS: dict[str, dict[str, float]] = {
    "Edit": {"coding": 1.5},
    "Write": {"coding": 1.5},
    "MultiEdit": {"coding": 1.5},
    "Read": {"review": 0.8},
    "Bash": {"devops": 0.5, "debug": 0.3},
    "Grep": {"debug": 0.3, "review": 0.3},
    "Glob": {"review": 0.2},
    "WebSearch": {"data": 0.5, "design": 0.3},
    "WebFetch": {"data": 0.5, "design": 0.3},
}

ALL_CATEGORIES = ["coding", "debug", "design", "review", "devops", "data", "chat", "other"]


def classify_message(message: Message) -> str:
    """Classify a single user message into an activity category."""
    category, _ = classify_message_with_confidence(message)
    return category


def classify_message_with_confidence(message: Message) -> tuple[str, float]:
    """Classify a message and return (category, confidence_score).

    The confidence score is the raw score of the winning category.
    Higher = more confident. Below CONFIDENCE_THRESHOLD is considered low-confidence.
    """
    text = message.content
    scores: dict[str, float] = {cat: 0 for cat in ALL_CATEGORIES}

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

    # If no signal at all, return "chat" (not "other")
    if scores[best] == 0:
        return "chat", 0.0

    return best, scores[best]


def classify_interaction(
    user_msg: Message,
    assistant_msg: Message | None,
    use_llm: bool = False,
) -> str:
    """Classify a user-assistant interaction pair.

    Uses the user message text + assistant message tool uses.
    If use_llm=True, low-confidence results are reclassified via `claude -p` with caching.
    """
    combined_tools = assistant_msg.tool_uses if assistant_msg else []
    combined = Message(
        role="user",
        content=user_msg.content,
        timestamp=user_msg.timestamp,
        tool_uses=combined_tools,
    )

    category, confidence = classify_message_with_confidence(combined)

    if use_llm and confidence < CONFIDENCE_THRESHOLD:
        from .cache import get_cached, set_cached
        from .llm_classifier import classify_with_llm

        # Check cache first
        cached = get_cached(combined.content, combined.tool_uses)
        if cached:
            return cached

        # Try LLM reclassification
        llm_result = classify_with_llm(combined.content, combined.tool_uses)
        if llm_result:
            set_cached(combined.content, combined.tool_uses, llm_result)
            return llm_result

    return category


def classify_session(
    messages: list[Message], use_llm: bool = False,
) -> list[tuple[Message, str]]:
    """Classify all interactions in a session.

    Pairs each user message with the following assistant message to get tool signals.
    Returns list of (user_message, category) tuples.
    If use_llm=True, low-confidence results are reclassified via `claude -p`.
    """
    results = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.role == "user":
            assistant_msg = None
            if i + 1 < len(messages) and messages[i + 1].role == "assistant":
                assistant_msg = messages[i + 1]
            category = classify_interaction(msg, assistant_msg, use_llm=use_llm)
            results.append((msg, category))
        i += 1
    return results
