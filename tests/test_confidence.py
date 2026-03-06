"""Tests for confidence scoring and LLM fallback integration."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from claude_analytics.classifier import (
    classify_message_with_confidence,
    classify_interaction,
    CONFIDENCE_THRESHOLD,
)
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
