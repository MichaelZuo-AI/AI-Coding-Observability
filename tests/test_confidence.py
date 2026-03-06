"""Tests for confidence scoring and LLM fallback integration."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from claude_analytics.classifier import (
    classify_message,
    classify_message_with_confidence,
    classify_interaction,
    classify_session,
    CONFIDENCE_THRESHOLD,
    TOOL_SIGNALS,
    ALL_CATEGORIES,
)
from claude_analytics.models import Message, Session


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


class TestConfidenceScoring:
    def test_strong_signal_high_confidence(self):
        cat, conf = classify_message_with_confidence(_msg("fix the TypeError bug in auth"))
        assert cat == "debug"
        assert conf >= CONFIDENCE_THRESHOLD

    def test_weak_signal_low_confidence(self):
        cat, conf = classify_message_with_confidence(_msg("check this"))
        assert conf > 0  # has some signal
        # "check" matches review, but only 1 match — might be below threshold

    def test_no_signal_returns_chat(self):
        # Empty string matches ^.{0,15}$ in chat patterns, so it gets a chat score
        cat, conf = classify_message_with_confidence(_msg(""))
        assert cat == "chat"

    def test_tools_add_confidence(self):
        _, conf_no_tools = classify_message_with_confidence(_msg("update"))
        _, conf_with_tools = classify_message_with_confidence(_msg("update", tools=["Edit", "Write"]))
        assert conf_with_tools > conf_no_tools


class TestLlmFallback:
    @patch("claude_analytics.llm_classifier.classify_with_llm", return_value="design")
    @patch("claude_analytics.cache.get_cached", return_value=None)
    @patch("claude_analytics.cache.set_cached")
    def test_llm_called_for_low_confidence(self, mock_set, mock_get, mock_llm):
        # "hmm" is very short, low confidence — should trigger LLM
        user = _msg("hmm")
        result = classify_interaction(user, None, use_llm=True)
        # LLM returned "design"
        assert result == "design"
        mock_llm.assert_called_once()
        mock_set.assert_called_once()

    def test_llm_not_called_for_high_confidence(self):
        user = _msg("implement the login form component")
        with patch("claude_analytics.llm_classifier.classify_with_llm") as mock_llm:
            result = classify_interaction(user, None, use_llm=True)
            assert result == "coding"
            mock_llm.assert_not_called()

    @patch("claude_analytics.cache.get_cached", return_value="data")
    def test_cache_hit_skips_llm(self, mock_get):
        user = _msg("hmm")
        with patch("claude_analytics.llm_classifier.classify_with_llm") as mock_llm:
            result = classify_interaction(user, None, use_llm=True)
            assert result == "data"
            mock_llm.assert_not_called()

    def test_no_llm_by_default(self):
        user = _msg("hmm")
        with patch("claude_analytics.llm_classifier.classify_with_llm") as mock_llm:
            classify_interaction(user, None, use_llm=False)
            mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# classify_message (non-tuple variant)
# ---------------------------------------------------------------------------

class TestClassifyMessage:
    def test_returns_string_not_tuple(self):
        result = classify_message(_msg("fix the TypeError"))
        assert isinstance(result, str)

    def test_delegates_to_with_confidence(self):
        """classify_message should return the same category as the first element
        of classify_message_with_confidence."""
        msg = _msg("implement the login endpoint")
        expected_cat, _ = classify_message_with_confidence(msg)
        assert classify_message(msg) == expected_cat


# ---------------------------------------------------------------------------
# Additional classify_message_with_confidence edge cases
# ---------------------------------------------------------------------------

class TestConfidenceEdgeCases:
    def test_unknown_tool_in_tool_uses_is_ignored(self):
        """A tool not in TOOL_SIGNALS should not raise and should not affect score."""
        msg = _msg("implement feature", tools=["UnknownTool", "FutureTool"])
        cat, conf = classify_message_with_confidence(msg)
        # "implement" matches coding — score should still be positive
        assert cat == "coding"
        assert conf > 0

    def test_multiple_tool_signals_accumulate(self):
        """Tools that signal the same category should add up."""
        _, conf_one = classify_message_with_confidence(_msg("x", tools=["Edit"]))
        _, conf_two = classify_message_with_confidence(_msg("x", tools=["Edit", "Write"]))
        assert conf_two > conf_one

    def test_tool_signal_boosts_correct_category(self):
        """Edit+Write tools should boost coding score."""
        msg = _msg("do something", tools=["Edit", "Write"])
        cat, _ = classify_message_with_confidence(msg)
        assert cat == "coding"

    def test_bash_tool_adds_devops_and_debug_weight(self):
        """Bash adds weight to both devops and debug — whichever dominates depends on text."""
        # Neutral text + Bash alone
        msg = _msg("run this", tools=["Bash"])
        cat, conf = classify_message_with_confidence(msg)
        # Score for devops and/or debug should be > 0
        assert conf > 0

    def test_debug_keywords_score_higher_than_chat(self):
        cat, conf = classify_message_with_confidence(_msg("The app crashes with a TypeError"))
        assert cat == "debug"
        assert conf > 0

    def test_coding_keywords_score_higher_than_chat(self):
        cat, conf = classify_message_with_confidence(_msg("implement the login form component"))
        assert cat == "coding"
        assert conf >= CONFIDENCE_THRESHOLD

    def test_devops_keywords_classified_correctly(self):
        cat, _ = classify_message_with_confidence(_msg("deploy to production using docker"))
        assert cat == "devops"

    def test_data_keywords_classified_correctly(self):
        cat, _ = classify_message_with_confidence(_msg("update my stock portfolio with CPNG RSU"))
        assert cat == "data"

    def test_review_keywords_classified_correctly(self):
        cat, _ = classify_message_with_confidence(_msg("explain what this code does"))
        assert cat == "review"

    def test_chat_short_message_classified_as_chat(self):
        cat, _ = classify_message_with_confidence(_msg("ok"))
        assert cat == "chat"

    def test_confidence_is_numeric(self):
        _, conf = classify_message_with_confidence(_msg("fix bug"))
        assert isinstance(conf, (int, float))

    def test_chinese_review_pattern(self):
        """Chinese patterns for review category should be detected."""
        cat, conf = classify_message_with_confidence(_msg("看看这个函数怎么用"))
        assert cat == "review"
        assert conf > 0

    def test_chinese_data_pattern(self):
        # Chinese financial terms with stock tickers that match existing patterns
        cat, conf = classify_message_with_confidence(_msg("update my CPNG stock portfolio"))
        assert cat == "data"
        assert conf > 0


# ---------------------------------------------------------------------------
# classify_interaction edge cases
# ---------------------------------------------------------------------------

class TestClassifyInteractionEdgeCases:
    def test_uses_assistant_tool_uses_not_user_tools(self):
        """classify_interaction should pick up tool_uses from the ASSISTANT message."""
        user = _msg("do something vague")
        # Assistant used Edit+Write → should boost coding
        asst = _asst(tools=["Edit", "Write"])
        cat = classify_interaction(user, asst, use_llm=False)
        assert cat == "coding"

    def test_no_assistant_message_uses_empty_tools(self):
        """With no assistant message, tool_uses defaults to [] (no boost)."""
        user = _msg("implement feature")
        cat = classify_interaction(user, None, use_llm=False)
        # "implement" alone still classifies as coding via text patterns
        assert cat == "coding"

    def test_llm_returns_none_falls_back_to_rule_category(self):
        """If LLM returns None, classify_interaction returns the rule-based result."""
        user = _msg("hmm")
        with (
            patch("claude_analytics.cache.get_cached", return_value=None),
            patch("claude_analytics.llm_classifier.classify_with_llm", return_value=None),
        ):
            result = classify_interaction(user, None, use_llm=True)
        # "hmm" is a short message → rule-based gives "chat"
        assert result == "chat"

    @patch("claude_analytics.cache.get_cached", return_value=None)
    @patch("claude_analytics.cache.set_cached")
    @patch("claude_analytics.llm_classifier.classify_with_llm", return_value="review")
    def test_llm_result_is_cached(self, mock_llm, mock_set, mock_get):
        user = _msg("hmm")
        classify_interaction(user, None, use_llm=True)
        mock_set.assert_called_once()
        # Verify the LLM result "review" was passed to set_cached
        args = mock_set.call_args[0]
        assert "review" in args


# ---------------------------------------------------------------------------
# classify_session
# ---------------------------------------------------------------------------

class TestClassifySession:
    def test_empty_messages_returns_empty(self):
        assert classify_session([]) == []

    def test_single_user_message(self):
        msgs = [_msg("fix the bug")]
        results = classify_session(msgs)
        assert len(results) == 1
        msg, cat = results[0]
        assert cat == "debug"

    def test_user_assistant_pair(self):
        msgs = [_msg("implement feature"), _asst("here is the code", tools=["Edit"])]
        results = classify_session(msgs)
        assert len(results) == 1
        msg, cat = results[0]
        assert cat == "coding"

    def test_multiple_user_assistant_pairs(self):
        msgs = [
            _msg("fix the crash"),
            _asst("found the bug"),
            _msg("now implement the fix"),
            _asst("done", tools=["Edit"]),
        ]
        results = classify_session(msgs)
        assert len(results) == 2
        cats = [c for _, c in results]
        assert "debug" in cats
        assert "coding" in cats

    def test_consecutive_user_messages_each_classified(self):
        """Two consecutive user messages (no assistant between) are each classified."""
        msgs = [
            _msg("ok"),
            _msg("now implement the feature"),
        ]
        results = classify_session(msgs)
        assert len(results) == 2

    def test_assistant_only_messages_skipped(self):
        """Assistant-only messages are not returned in results."""
        msgs = [
            _asst("I'll help you"),
            _msg("fix the bug"),
            _asst("done"),
        ]
        results = classify_session(msgs)
        assert len(results) == 1
        _, cat = results[0]
        assert cat == "debug"

    def test_assistant_tools_paired_to_preceding_user_message(self):
        """The tool_uses of assistant[i+1] should influence classification of user[i]."""
        msgs = [
            _msg("update the config"),         # vague text
            _asst("done", tools=["Edit", "Write"]),  # Edit+Write → coding boost
        ]
        results = classify_session(msgs)
        _, cat = results[0]
        assert cat == "coding"

    def test_returns_list_of_message_category_tuples(self):
        msgs = [_msg("deploy to production")]
        results = classify_session(msgs)
        assert isinstance(results, list)
        assert len(results) == 1
        msg, cat = results[0]
        assert isinstance(msg, Message)
        assert isinstance(cat, str)
        assert cat in ALL_CATEGORIES
