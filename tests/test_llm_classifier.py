"""Tests for LLM-based classifier module."""

import pytest
from unittest.mock import patch, MagicMock
from claude_analytics.llm_classifier import classify_with_llm, is_claude_cli_available, PROMPT_TEMPLATE


class TestIsClaudeCliAvailable:
    @patch("shutil.which", return_value="/usr/local/bin/claude")
    def test_available(self, mock_which):
        assert is_claude_cli_available() is True

    @patch("shutil.which", return_value=None)
    def test_not_available(self, mock_which):
        assert is_claude_cli_available() is False


class TestClassifyWithLlm:
    @patch("shutil.which", return_value=None)
    def test_returns_none_when_cli_unavailable(self, mock_which):
        assert classify_with_llm("fix the bug", []) is None

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_returns_category_from_cli(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="debug\n")
        result = classify_with_llm("something broke", ["Bash"])
        assert result == "debug"

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_returns_none_on_failure(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = classify_with_llm("test", [])
        assert result is None

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_returns_none_on_garbage(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="I don't know\n")
        result = classify_with_llm("test", [])
        assert result is None

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_extracts_category_from_sentence(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="The category is coding.\n")
        result = classify_with_llm("build a feature", ["Write"])
        assert result == "coding"

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run", side_effect=TimeoutError)
    def test_handles_timeout(self, mock_run, mock_which):
        result = classify_with_llm("test", [])
        assert result is None

    def test_prompt_includes_tools(self):
        prompt = PROMPT_TEMPLATE.format(content="test", tools_line="Assistant used tools: Edit, Write")
        assert "Edit, Write" in prompt

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_truncates_long_content(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="chat\n")
        long_content = "x" * 1000
        classify_with_llm(long_content, [])
        # Check the prompt passed to subprocess
        call_args = mock_run.call_args[0][0]
        prompt = call_args[2]  # ["claude", "-p", prompt]
        # Content in prompt should be truncated to 500 chars
        assert "x" * 500 in prompt
        assert "x" * 501 not in prompt
