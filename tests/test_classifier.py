"""Tests for intent classification."""

import pytest
from datetime import datetime, timezone
from claude_analytics.classifier import classify_message, classify_interaction, classify_session
from claude_analytics.models import Message


def _msg(content: str, tools: list[str] | None = None) -> Message:
    return Message(
        role="user",
        content=content,
        timestamp=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
        tool_uses=tools or [],
    )


def _asst(text: str = "", tools: list[str] | None = None) -> Message:
    return Message(
        role="assistant",
        content=text,
        timestamp=datetime(2026, 2, 10, 10, 0, 5, tzinfo=timezone.utc),
        tool_uses=tools or [],
    )


class TestClassifyMessage:
    def test_coding_keywords(self):
        assert classify_message(_msg("implement a login form component")) == "coding"

    def test_debug_keywords(self):
        assert classify_message(_msg("fix the TypeError in auth module")) == "debug"

    def test_design_keywords(self):
        assert classify_message(_msg("how should we structure the API?")) == "design"

    def test_devops_keywords(self):
        assert classify_message(_msg("deploy to kubernetes staging")) == "devops"

    def test_review_keywords(self):
        assert classify_message(_msg("explain what this code does")) == "review"

    def test_other_fallback(self):
        assert classify_message(_msg("hello there")) == "other"

    def test_debug_error_words(self):
        assert classify_message(_msg("the app crashes with a null pointer")) == "debug"

    def test_coding_with_tools(self):
        msg = _msg("update the config", tools=["Edit", "Write"])
        assert classify_message(msg) == "coding"


class TestClassifyInteraction:
    def test_user_coding_with_assistant_tools(self):
        user = _msg("add a new endpoint")
        assistant = _asst(tools=["Write", "Edit"])
        assert classify_interaction(user, assistant) == "coding"

    def test_user_debug_with_bash(self):
        user = _msg("fix the error in the build")
        assistant = _asst(tools=["Bash", "Grep"])
        assert classify_interaction(user, assistant) == "debug"

    def test_no_assistant(self):
        user = _msg("implement the search feature")
        assert classify_interaction(user, None) == "coding"


class TestClassifySession:
    def test_session_classification(self):
        messages = [
            _msg("implement login"),
            _asst("Done.", ["Write"]),
            Message(
                role="user",
                content="fix the bug in the form",
                timestamp=datetime(2026, 2, 10, 10, 5, tzinfo=timezone.utc),
                tool_uses=[],
            ),
            Message(
                role="assistant",
                content="Fixed.",
                timestamp=datetime(2026, 2, 10, 10, 5, 3, tzinfo=timezone.utc),
                tool_uses=["Edit", "Bash"],
            ),
        ]
        results = classify_session(messages)
        assert len(results) == 2
        assert results[0][1] == "coding"
        assert results[1][1] == "debug"
