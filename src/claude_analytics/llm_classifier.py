"""LLM-based reclassification using `claude -p` for low-confidence interactions."""

import shutil
import subprocess

from .classifier import ALL_CATEGORIES

CATEGORIES_STR = ", ".join(c for c in ALL_CATEGORIES if c != "other")

PROMPT_TEMPLATE = """Classify this Claude Code user message into exactly one category.

Categories:
- coding: implementing features, writing code, creating components, refactoring
- debug: fixing bugs, investigating errors, troubleshooting
- design: architecture decisions, planning, comparing approaches
- devops: deployment, CI/CD, git operations, environment setup
- review: code review, explaining code, walkthroughs
- data: financial analysis, data queries, portfolio updates, email/calendar tasks
- chat: greetings, short acknowledgments, slash commands

User message: {content}
{tools_line}
Reply with ONLY the category name, nothing else."""


def is_claude_cli_available() -> bool:
    """Check if the `claude` CLI is available on PATH."""
    return shutil.which("claude") is not None


def classify_with_llm(content: str, tool_uses: list[str]) -> str | None:
    """Classify a message using `claude -p`.

    Returns the category string, or None if the CLI is unavailable or fails.
    """
    if not is_claude_cli_available():
        return None

    tools_line = ""
    if tool_uses:
        tools_line = f"Assistant used tools: {', '.join(tool_uses)}"

    prompt = PROMPT_TEMPLATE.format(content=content[:500], tools_line=tools_line)

    try:
        result = subprocess.run(
            ["claude", "-p", "--"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None

        response = result.stdout.strip().lower()
        # Prefer exact match
        if response in ALL_CATEGORIES:
            return response
        # Fallback: first whole-word match
        import re
        for cat in ALL_CATEGORIES:
            if re.search(rf'\b{cat}\b', response):
                return cat
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
