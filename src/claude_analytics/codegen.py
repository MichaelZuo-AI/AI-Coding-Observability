"""Measure AI-generated code from Edit/Write tool calls in session logs."""

import json
from pathlib import Path
from dataclasses import dataclass, field

from .parser import discover_sessions, CLAUDE_PROJECTS_DIR

# File extensions we count as "code" (not docs, configs, plans, etc.)
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".sh",
    ".bash", ".zsh", ".sql", ".html", ".css", ".scss", ".sass", ".less",
    ".vue", ".svelte", ".yaml", ".yml", ".toml", ".json", ".xml",
}

# Paths to skip (docs, plans, memory, etc.)
SKIP_PATTERNS = [
    "/.claude/",
    "/node_modules/",
    "/tmp/",
    "CLAUDE.md",
    "README.md",
    "MEMORY.md",
    ".md",  # skip all markdown by default
]


@dataclass
class CodeGenStats:
    total_lines_written: int = 0  # lines from Write tool (new files)
    total_lines_added: int = 0    # net new lines from Edit tool
    total_lines_removed: int = 0  # lines replaced by Edit tool
    files_created: int = 0        # Write tool calls
    files_edited: int = 0         # Edit tool calls
    files_touched: set = field(default_factory=set)

    @property
    def net_lines(self) -> int:
        return self.total_lines_written + self.total_lines_added - self.total_lines_removed

    @property
    def total_ai_lines(self) -> int:
        """Total lines of code produced by AI (written + added via edits)."""
        return self.total_lines_written + self.total_lines_added


def _is_code_file(file_path: str) -> bool:
    """Check if a file path looks like a code file."""
    if not file_path:
        return False
    for pattern in SKIP_PATTERNS:
        if pattern in file_path:
            return False
    ext = Path(file_path).suffix.lower()
    return ext in CODE_EXTENSIONS


def _count_lines(text: str) -> int:
    """Count non-empty lines in a string."""
    if not text:
        return 0
    return sum(1 for line in text.split("\n") if line.strip())


def analyze_codegen(
    projects_dir: Path = CLAUDE_PROJECTS_DIR,
    project_filter: str | None = None,
) -> CodeGenStats:
    """Analyze all session logs to measure AI code generation."""
    stats = CodeGenStats()
    paths = discover_sessions(projects_dir, project_filter)

    for jsonl_path in paths:
        _analyze_file(jsonl_path, stats)

    return stats


def analyze_codegen_by_project(
    projects_dir: Path = CLAUDE_PROJECTS_DIR,
) -> dict[str, CodeGenStats]:
    """Analyze code generation grouped by project."""
    from .parser import _extract_project_name

    result: dict[str, CodeGenStats] = {}
    paths = discover_sessions(projects_dir)

    for jsonl_path in paths:
        project = _extract_project_name(jsonl_path.parent.name)
        if project not in result:
            result[project] = CodeGenStats()
        _analyze_file(jsonl_path, result[project])

    return result


def _analyze_file(jsonl_path: Path, stats: CodeGenStats) -> None:
    """Process a single JSONL file and accumulate stats."""
    with open(jsonl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue

            content = entry.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue

                tool_name = block.get("name", "")
                inp = block.get("input", {})

                if tool_name == "Write":
                    file_path = inp.get("file_path", "")
                    if not _is_code_file(file_path):
                        continue
                    content_text = inp.get("content", "")
                    lines = _count_lines(content_text)
                    stats.total_lines_written += lines
                    stats.files_created += 1
                    stats.files_touched.add(file_path)

                elif tool_name == "Edit":
                    file_path = inp.get("file_path", "")
                    if not _is_code_file(file_path):
                        continue
                    old_text = inp.get("old_string", "")
                    new_text = inp.get("new_string", "")
                    old_lines = _count_lines(old_text)
                    new_lines = _count_lines(new_text)
                    stats.total_lines_added += new_lines
                    stats.total_lines_removed += old_lines
                    stats.files_edited += 1
                    stats.files_touched.add(file_path)

                elif tool_name == "MultiEdit":
                    file_path = inp.get("file_path", "")
                    if not _is_code_file(file_path):
                        continue
                    edits = inp.get("edits", [])
                    for edit in edits:
                        old_text = edit.get("old_string", "")
                        new_text = edit.get("new_string", "")
                        old_lines = _count_lines(old_text)
                        new_lines = _count_lines(new_text)
                        stats.total_lines_added += new_lines
                        stats.total_lines_removed += old_lines
                    stats.files_edited += 1
                    stats.files_touched.add(file_path)
