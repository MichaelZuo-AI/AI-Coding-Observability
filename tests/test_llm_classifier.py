"""Tests for LLM-based classifier module."""

import subprocess

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
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 30))
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
        # Prompt is passed via stdin (input=)
        prompt = mock_run.call_args[1]["input"]
        # Content in prompt should be truncated to 500 chars
        assert "x" * 500 in prompt
        assert "x" * 501 not in prompt

    # ------------------------------------------------------------------
    # Additional edge cases
    # ------------------------------------------------------------------

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_handles_file_not_found(self, mock_run, mock_which):
        """FileNotFoundError (claude binary gone after which check) is handled."""
        result = classify_with_llm("test", [])
        assert result is None

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run", side_effect=OSError("broken pipe"))
    def test_handles_oserror(self, mock_run, mock_which):
        result = classify_with_llm("test", [])
        assert result is None

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_empty_stdout_returns_none(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert classify_with_llm("test", []) is None

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_whitespace_only_stdout_returns_none(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="   \n  ")
        assert classify_with_llm("test", []) is None

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_tools_line_absent_when_no_tools(self, mock_run, mock_which):
        """When tool_uses is empty, the tools_line in the prompt should be empty."""
        mock_run.return_value = MagicMock(returncode=0, stdout="coding\n")
        classify_with_llm("build a feature", [])
        prompt = mock_run.call_args[1]["input"]
        assert "Assistant used tools" not in prompt

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_tools_line_present_when_tools_given(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="devops\n")
        classify_with_llm("deploy to prod", ["Bash", "Edit"])
        prompt = mock_run.call_args[1]["input"]
        assert "Bash, Edit" in prompt or "Edit, Bash" in prompt

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_all_valid_categories_recognized(self, mock_run, mock_which):
        """Every category returned in stdout must be accepted."""
        from claude_analytics.classifier import ALL_CATEGORIES
        for cat in ALL_CATEGORIES:
            mock_run.return_value = MagicMock(returncode=0, stdout=f"{cat}\n")
            result = classify_with_llm("test message", [])
            assert result == cat, f"Category '{cat}' not recognized"

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_category_extracted_case_insensitive(self, mock_run, mock_which):
        """LLM response is lowercased before matching, so CODING → coding."""
        mock_run.return_value = MagicMock(returncode=0, stdout="CODING\n")
        result = classify_with_llm("implement feature", [])
        assert result == "coding"

    def test_prompt_template_contains_all_category_descriptions(self):
        """PROMPT_TEMPLATE should mention core categories."""
        for cat in ["coding", "debug", "design", "devops", "review", "data", "chat"]:
            assert cat in PROMPT_TEMPLATE, f"Category '{cat}' missing from PROMPT_TEMPLATE"

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_exact_content_at_500_char_boundary(self, mock_run, mock_which):
        """Content exactly 500 chars should not be truncated."""
        mock_run.return_value = MagicMock(returncode=0, stdout="chat\n")
        content_500 = "y" * 500
        classify_with_llm(content_500, [])
        prompt = mock_run.call_args[1]["input"]
        assert "y" * 500 in prompt
