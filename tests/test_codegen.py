"""Tests for AI code generation analysis."""

import json
import pytest
from pathlib import Path
from claude_analytics.codegen import (
    analyze_codegen,
    _is_code_file,
    _count_lines,
    CodeGenStats,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def codegen_fixture(tmp_path):
    """Create a fixture JSONL with Write/Edit tool calls."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    lines = [
        # Write a new Python file
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-02-10T10:00:05.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Write", "input": {
                        "file_path": "/test/app.py",
                        "content": "def hello():\n    print('hello')\n\ndef main():\n    hello()\n",
                    }},
                ],
            },
        }),
        # Edit an existing file
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-02-10T10:05:05.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t2", "name": "Edit", "input": {
                        "file_path": "/test/app.py",
                        "old_string": "def hello():\n    print('hello')",
                        "new_string": "def hello(name: str):\n    print(f'hello {name}')\n    return name",
                    }},
                ],
            },
        }),
        # Write a markdown file (should be skipped)
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-02-10T10:10:05.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t3", "name": "Write", "input": {
                        "file_path": "/test/README.md",
                        "content": "# Hello\nThis is a readme\n",
                    }},
                ],
            },
        }),
    ]

    filepath = project_dir / "codegen-session.jsonl"
    filepath.write_text("\n".join(lines) + "\n")
    return tmp_path


class TestIsCodeFile:
    def test_python(self):
        assert _is_code_file("/src/app.py") is True

    def test_typescript(self):
        assert _is_code_file("/src/index.ts") is True

    def test_markdown_skipped(self):
        assert _is_code_file("/docs/README.md") is False

    def test_claude_md_skipped(self):
        assert _is_code_file("/project/CLAUDE.md") is False

    def test_node_modules_skipped(self):
        assert _is_code_file("/node_modules/pkg/index.js") is False

    def test_empty_path(self):
        assert _is_code_file("") is False


class TestCountLines:
    def test_basic(self):
        assert _count_lines("a\nb\nc") == 3

    def test_empty_lines_excluded(self):
        assert _count_lines("a\n\nb\n\n") == 2

    def test_empty_string(self):
        assert _count_lines("") == 0


class TestAnalyzeCodegen:
    def test_counts_write(self, codegen_fixture):
        stats = analyze_codegen(codegen_fixture)
        # 4 non-empty lines in app.py Write (trailing newline = empty last line)
        assert stats.total_lines_written == 4
        assert stats.files_created == 1

    def test_counts_edit(self, codegen_fixture):
        stats = analyze_codegen(codegen_fixture)
        # Edit: 2 old lines -> 3 new lines
        assert stats.total_lines_removed == 2
        assert stats.total_lines_added == 3
        assert stats.files_edited == 1

    def test_skips_markdown(self, codegen_fixture):
        stats = analyze_codegen(codegen_fixture)
        # Only 1 Write (py) counted, not the README.md
        assert stats.files_created == 1

    def test_total_ai_lines(self, codegen_fixture):
        stats = analyze_codegen(codegen_fixture)
        assert stats.total_ai_lines == 4 + 3  # written + added

    def test_net_lines(self, codegen_fixture):
        stats = analyze_codegen(codegen_fixture)
        assert stats.net_lines == 4 + 3 - 2  # written + added - removed

    def test_files_touched(self, codegen_fixture):
        stats = analyze_codegen(codegen_fixture)
        assert "/test/app.py" in stats.files_touched
        assert "/test/README.md" not in stats.files_touched
