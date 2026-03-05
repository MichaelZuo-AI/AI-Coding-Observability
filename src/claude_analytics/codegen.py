"""Measure AI-generated code by matching git commits to Claude Code sessions."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass, field

from .parser import discover_sessions, CLAUDE_PROJECTS_DIR

# Directories to skip when counting codebase lines
SKIP_DIRS = {
    "node_modules", ".next", ".git", ".venv", "venv", "__pycache__",
    "dist", "build", ".cache", "coverage", ".turbo", "target",
    ".pytest_cache", "site-packages", ".egg-info",
}

# Source code file extensions only
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala",
    ".sh", ".bash", ".zsh", ".sql", ".vue", ".svelte",
}

# Files to skip entirely
SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "Cargo.lock", "poetry.lock", "Pipfile.lock", "composer.lock",
    "CLAUDE.md", "README.md", "MEMORY.md", "CHANGELOG.md", "LICENSE",
}

# Paths to skip
SKIP_PATTERNS = [
    "/.claude/",
    "/node_modules/",
    "/tmp/",
    ".md",
]

# Buffer time around sessions — commits may happen slightly after session ends
SESSION_BUFFER_MINUTES = 5


@dataclass
class CodeGenStats:
    ai_lines: int = 0          # lines added in commits during AI sessions
    total_lines: int = 0       # total lines in codebase on disk
    ai_commits: int = 0        # number of commits during AI sessions
    total_commits: int = 0     # total commits in repo
    files_touched: set = field(default_factory=set)

    @property
    def ai_percentage(self) -> float:
        if self.total_lines == 0:
            return 0.0
        return min(self.ai_lines / self.total_lines * 100, 100.0)


def _is_code_file(file_path: str) -> bool:
    """Check if a file path looks like a source code file."""
    if not file_path:
        return False
    p = Path(file_path)
    if p.name in SKIP_FILENAMES:
        return False
    for pattern in SKIP_PATTERNS:
        if pattern in file_path:
            return False
    return p.suffix.lower() in CODE_EXTENSIONS


def count_codebase_lines(project_dir: Path) -> int:
    """Count total non-empty lines of source code files in a project directory."""
    if not project_dir.exists():
        return 0

    total = 0
    for root, dirs, files in project_dir.walk():
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            fpath = root / fname
            if not _is_code_file(str(fpath)):
                continue
            try:
                text = fpath.read_text(errors="ignore")
                total += sum(1 for line in text.split("\n") if line.strip())
            except (OSError, UnicodeDecodeError):
                continue
    return total


def _find_git_root(path: Path) -> Path:
    """Walk up from path to find the git root directory."""
    current = path
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return path


def _extract_session_windows(
    projects_dir: Path,
    project_filter: str | None = None,
) -> list[tuple[datetime, datetime]]:
    """Extract (start, end) time windows from all sessions."""
    from .parser import parse_all_sessions

    sessions = parse_all_sessions(projects_dir, project_filter)
    windows = []
    for session in sessions:
        if session.start_time and session.end_time:
            start = session.start_time
            end = session.end_time + timedelta(minutes=SESSION_BUFFER_MINUTES)
            windows.append((start, end))
    return windows


def _merge_windows(windows: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Merge overlapping time windows."""
    if not windows:
        return []
    sorted_windows = sorted(windows, key=lambda w: w[0])
    merged = [sorted_windows[0]]
    for start, end in sorted_windows[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _is_during_session(
    commit_time: datetime, windows: list[tuple[datetime, datetime]]
) -> bool:
    """Check if a commit timestamp falls within any session window."""
    for start, end in windows:
        if start <= commit_time <= end:
            return True
    return False


def _get_git_commits(git_root: Path) -> list[tuple[str, datetime, list[tuple[int, int, str]]]]:
    """Get all commits with their numstat from a git repo.

    Returns list of (hash, timestamp, [(added, removed, filepath), ...])
    """
    try:
        result = subprocess.run(
            ["git", "log", "--numstat", "--format=COMMIT %H %aI", "--no-merges"],
            cwd=git_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    commits = []
    current_hash = ""
    current_time = None
    current_files: list[tuple[int, int, str]] = []

    for line in result.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("COMMIT "):
            # Save previous commit
            if current_hash and current_time:
                commits.append((current_hash, current_time, current_files))
            parts = line.split(" ", 2)
            current_hash = parts[1]
            try:
                current_time = datetime.fromisoformat(parts[2])
                # Ensure timezone-aware
                if current_time.tzinfo is None:
                    current_time = current_time.replace(tzinfo=timezone.utc)
            except (ValueError, IndexError):
                current_time = None
            current_files = []
        else:
            # numstat line: "added\tremoved\tfilepath"
            parts = line.split("\t", 2)
            if len(parts) == 3:
                try:
                    added = int(parts[0]) if parts[0] != "-" else 0
                    removed = int(parts[1]) if parts[1] != "-" else 0
                    current_files.append((added, removed, parts[2]))
                except ValueError:
                    continue

    # Save last commit
    if current_hash and current_time:
        commits.append((current_hash, current_time, current_files))

    return commits


def analyze_codegen(
    projects_dir: Path = CLAUDE_PROJECTS_DIR,
    project_filter: str | None = None,
) -> CodeGenStats:
    """Analyze AI code generation across all projects using git + session matching."""
    project_dirs = extract_project_dirs(projects_dir)
    session_windows = _extract_session_windows(projects_dir, project_filter)
    merged_windows = _merge_windows(session_windows)

    stats = CodeGenStats()

    seen_repos: set[str] = set()
    for proj_name, git_root in project_dirs.items():
        repo_key = str(git_root)
        if repo_key in seen_repos:
            continue
        seen_repos.add(repo_key)

        if project_filter and project_filter not in proj_name:
            continue

        proj_stats = _analyze_repo(git_root, merged_windows)
        stats.ai_lines += proj_stats.ai_lines
        stats.total_lines += proj_stats.total_lines
        stats.ai_commits += proj_stats.ai_commits
        stats.total_commits += proj_stats.total_commits
        stats.files_touched.update(proj_stats.files_touched)

    return stats


def analyze_codegen_by_project(
    projects_dir: Path = CLAUDE_PROJECTS_DIR,
) -> dict[str, CodeGenStats]:
    """Analyze code generation per project."""
    project_dirs = extract_project_dirs(projects_dir)

    # Get per-project session windows
    from .parser import _extract_project_name, parse_all_sessions
    all_sessions = parse_all_sessions(projects_dir)

    project_sessions: dict[str, list[tuple[datetime, datetime]]] = {}
    for session in all_sessions:
        if session.start_time and session.end_time:
            proj = session.project
            if proj not in project_sessions:
                project_sessions[proj] = []
            start = session.start_time
            end = session.end_time + timedelta(minutes=SESSION_BUFFER_MINUTES)
            project_sessions[proj].append((start, end))

    result: dict[str, CodeGenStats] = {}
    for proj_name, git_root in project_dirs.items():
        windows = project_sessions.get(proj_name, [])
        merged = _merge_windows(windows)
        result[proj_name] = _analyze_repo(git_root, merged)

    return result


def _analyze_repo(
    git_root: Path,
    session_windows: list[tuple[datetime, datetime]],
) -> CodeGenStats:
    """Analyze a single git repo against session time windows."""
    stats = CodeGenStats()
    stats.total_lines = count_codebase_lines(git_root)

    commits = _get_git_commits(git_root)
    stats.total_commits = len(commits)

    for commit_hash, commit_time, file_stats in commits:
        is_ai = _is_during_session(commit_time, session_windows)

        for added, removed, filepath in file_stats:
            if not _is_code_file(filepath):
                continue

            if is_ai:
                stats.ai_lines += added
                stats.ai_commits += 1
                stats.files_touched.add(filepath)
                break  # count commit once, not per file

    # Re-count ai_lines properly (the break above was wrong)
    stats.ai_lines = 0
    stats.ai_commits = 0
    for commit_hash, commit_time, file_stats in commits:
        if not _is_during_session(commit_time, session_windows):
            continue
        stats.ai_commits += 1
        for added, removed, filepath in file_stats:
            if _is_code_file(filepath):
                stats.ai_lines += added
                stats.files_touched.add(filepath)

    return stats


def extract_project_dirs(
    projects_dir: Path = CLAUDE_PROJECTS_DIR,
) -> dict[str, Path]:
    """Extract project name -> git root path mapping from session logs."""
    from .parser import _extract_project_name

    result: dict[str, Path] = {}
    paths = discover_sessions(projects_dir)

    for jsonl_path in paths:
        project = _extract_project_name(jsonl_path.parent.name)
        if project in result:
            continue
        with open(jsonl_path, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("type") == "user" and "cwd" in entry:
                        cwd = Path(entry["cwd"])
                        result[project] = _find_git_root(cwd)
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

    return result
