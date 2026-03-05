"""Additional edge-case tests for classifier internals not covered by test_classifier.py."""

import pytest
from datetime import datetime, timezone
from claude_analytics.classifier import (
    classify_message,
    classify_interaction,
    classify_session,
    TOOL_SIGNALS,
    RULE_PATTERNS,
)
from claude_analytics.models import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(content: str, tools: list[str] | None = None, role: str = "user") -> Message:
    return Message(
        role=role,
        content=content,
        timestamp=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
        tool_uses=tools or [],
    )


def _asst(tools: list[str] | None = None) -> Message:
    return _msg("", tools=tools, role="assistant")


# ---------------------------------------------------------------------------
# No-signal messages → "chat"
# ---------------------------------------------------------------------------

class TestNoSignalFallsToChat:
    def test_completely_empty_content(self):
        # Empty message → no signal → chat
        result = classify_message(_msg(""))
        assert result == "chat"

    def test_only_whitespace(self):
        result = classify_message(_msg("   "))
        assert result == "chat"

    def test_random_word_no_match(self):
        # A word that matches nothing in the patterns
        result = classify_message(_msg("zxqwerty"))
        assert result == "chat"

    def test_very_short_message_is_chat(self):
        # The chat pattern ^.{0,15}$ covers short messages
        assert classify_message(_msg("fine")) == "chat"

    def test_short_message_boundary_15_chars(self):
        # Exactly 15 chars → still chat via the short-message pattern
        msg_15 = "a" * 15
        assert classify_message(_msg(msg_15)) == "chat"

    def test_message_16_chars_no_keyword_not_chat_from_length(self):
        # 16 chars with no pattern keywords → 0 score for all → "chat" via fallback
        result = classify_message(_msg("a" * 16))
        assert result == "chat"


# ---------------------------------------------------------------------------
# Tool signals influence classification
# ---------------------------------------------------------------------------

class TestToolSignals:
    def test_write_tool_boosts_coding(self):
        # Neutral content + Write tool → coding wins
        msg = _msg("update something", tools=["Write"])
        result = classify_message(msg)
        assert result == "coding"

    def test_edit_tool_boosts_coding(self):
        msg = _msg("change the value", tools=["Edit"])
        result = classify_message(msg)
        assert result == "coding"

    def test_bash_tool_boosts_devops_or_debug(self):
        # Content must be > 15 chars to avoid the short-message chat pattern (score=1)
        # that would beat the Bash tool signal (devops=0.5, debug=0.3)
        msg = _msg("execute this command please", tools=["Bash"])
        result = classify_message(msg)
        # Bash gives: devops 0.5, debug 0.3 → devops wins over neutral content
        assert result in ("devops", "debug")

    def test_websearch_boosts_data(self):
        # Content must be > 15 chars to avoid the short-message chat pattern
        msg = _msg("please search for this information", tools=["WebSearch"])
        result = classify_message(msg)
        # WebSearch gives: data 0.5, design 0.3 → data wins
        assert result in ("data", "design")

    def test_grep_tool_alone_neutral(self):
        # Grep gives: debug 0.3, review 0.3 → tied → either is acceptable
        msg = _msg("search", tools=["Grep"])
        result = classify_message(msg)
        assert result in ("debug", "review", "chat")

    def test_multiple_coding_tools_accumulate(self):
        msg = _msg("work on this", tools=["Write", "Edit"])
        # 1.5 + 1.5 = 3.0 for coding
        assert classify_message(msg) == "coding"


# ---------------------------------------------------------------------------
# classify_interaction edge cases
# ---------------------------------------------------------------------------

class TestClassifyInteractionExtra:
    def test_both_user_and_assistant_tools_combined(self):
        """classify_interaction combines user text + assistant tools."""
        user = _msg("push to production", tools=[])
        assistant = _asst(tools=["Bash"])
        # "push" hits devops patterns, Bash adds more weight
        result = classify_interaction(user, assistant)
        assert result == "devops"

    def test_none_assistant_falls_back_to_user_signal(self):
        user = _msg("implement login form")
        result = classify_interaction(user, None)
        assert result == "coding"

    def test_assistant_tools_override_weak_user_signal(self):
        """Neutral user text + strong Write tool signal → coding."""
        user = _msg("please handle this")  # weak signal
        assistant = _asst(tools=["Write", "Edit"])
        result = classify_interaction(user, assistant)
        assert result == "coding"


# ---------------------------------------------------------------------------
# classify_session edge cases
# ---------------------------------------------------------------------------

class TestClassifySessionExtra:
    def test_empty_messages_returns_empty(self):
        result = classify_session([])
        assert result == []

    def test_only_assistant_messages_returns_empty(self):
        msgs = [_asst(["Write"]), _asst(["Edit"])]
        result = classify_session(msgs)
        assert result == []

    def test_user_message_without_following_assistant(self):
        """Last user message with no following assistant still gets classified."""
        msgs = [
            _msg("implement the login form"),
        ]
        result = classify_session(msgs)
        assert len(result) == 1
        assert result[0][1] == "coding"

    def test_all_pairs_classified(self):
        msgs = [
            _msg("implement feature"),
            _asst(["Write"]),
            _msg("fix the bug in auth"),
            _asst(["Bash", "Grep"]),
            _msg("deploy to production"),
            _asst(["Bash"]),
        ]
        result = classify_session(msgs)
        assert len(result) == 3
        categories = [cat for _, cat in result]
        assert "coding" in categories
        assert "debug" in categories or "devops" in categories

    def test_user_messages_only_pairs_returned(self):
        """Result should only contain user messages, not assistant messages."""
        msgs = [
            _msg("implement x"),
            _asst(["Write"]),
            _msg("debug y"),
            _asst(["Bash"]),
        ]
        result = classify_session(msgs)
        for msg, cat in result:
            assert msg.role == "user"

    def test_consecutive_user_messages_both_classified(self):
        """Two consecutive user messages (no assistant between) → both classified."""
        msgs = [
            _msg("first user message"),
            _msg("second user message"),
        ]
        result = classify_session(msgs)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Pattern coverage checks
# ---------------------------------------------------------------------------

class TestPatternCoverage:
    """Ensure all expected categories have patterns registered."""

    def test_all_expected_categories_have_patterns(self):
        expected = {"debug", "coding", "design", "review", "devops", "data", "chat"}
        assert expected.issubset(set(RULE_PATTERNS.keys()))

    def test_all_tool_signals_have_valid_categories(self):
        valid_cats = {"coding", "debug", "design", "review", "devops", "data", "chat", "other"}
        for tool, signals in TOOL_SIGNALS.items():
            for cat in signals:
                assert cat in valid_cats, f"Unknown category '{cat}' for tool '{tool}'"

    def test_chinese_review_pattern(self):
        # 看看 should match review
        result = classify_message(_msg("看看这个代码"))
        assert result == "review"

    def test_chinese_data_pattern(self):
        # The data pattern uses \b which in Python regex matches between a word char
        # (\w includes CJK) and a non-word char. "净资产" embedded between other CJK
        # chars won't match \b, but standalone or adjacent to non-word chars will.
        # Use a short message with the keyword isolated to trigger the match.
        result = classify_message(_msg("净资产 report please show me"))
        assert result == "data"

    def test_command_init_is_chat(self):
        result = classify_message(_msg("<command-name>/init</command-name>"))
        assert result == "chat"

    def test_interrupted_request_is_chat(self):
        result = classify_message(_msg("[Request interrupted by user for some reason]"))
        assert result == "chat"

    def test_stock_ticker_is_data(self):
        result = classify_message(_msg("how is CPNG doing today?"))
        assert result == "data"

    def test_debug_traceback_keyword(self):
        result = classify_message(_msg("the traceback shows a KeyError in line 42"))
        assert result == "debug"

    def test_devops_docker_keyword(self):
        result = classify_message(_msg("build the docker image for production"))
        assert result == "devops"
