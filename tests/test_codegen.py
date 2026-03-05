"""Tests for AI code generation analysis."""

import subprocess
import pytest
from pathlib import Path
from claude_analytics.codegen import (
    _is_code_file,
    count_codebase_lines,
    _merge_windows,
    _is_during_session,
    _get_git_commits,
    _analyze_repo,
    CodeGenStats,
)
from datetime import datetime, timezone, timedelta


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

    def test_lock_files_skipped(self):
        assert _is_code_file("/project/package-lock.json") is False
        assert _is_code_file("/project/yarn.lock") is False

    def test_jsx_tsx(self):
        assert _is_code_file("/src/App.tsx") is True
        assert _is_code_file("/src/Button.jsx") is True


class TestMergeWindows:
    def test_no_overlap(self):
        t1 = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 2, 10, 14, 0, tzinfo=timezone.utc)
        t4 = datetime(2026, 2, 10, 15, 0, tzinfo=timezone.utc)
        result = _merge_windows([(t1, t2), (t3, t4)])
        assert len(result) == 2

    def test_overlap(self):
        t1 = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 2, 10, 10, 30, tzinfo=timezone.utc)
        t4 = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
        result = _merge_windows([(t1, t2), (t3, t4)])
        assert len(result) == 1
        assert result[0] == (t1, t4)

    def test_empty(self):
        assert _merge_windows([]) == []


class TestIsDuringSession:
    def test_inside(self):
        t1 = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc)
        commit = datetime(2026, 2, 10, 10, 30, tzinfo=timezone.utc)
        assert _is_during_session(commit, [(t1, t2)]) is True

    def test_outside(self):
        t1 = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc)
        commit = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
        assert _is_during_session(commit, [(t1, t2)]) is False

    def test_boundary(self):
        t1 = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc)
        assert _is_during_session(t1, [(t1, t2)]) is True
        assert _is_during_session(t2, [(t1, t2)]) is True


class TestCountCodebaseLines:
    def test_counts_python_files(self, tmp_path):
        (tmp_path / "app.py").write_text("def main():\n    pass\n")
        (tmp_path / "test.py").write_text("assert True\n")
        assert count_codebase_lines(tmp_path) == 3

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {}\n")
        (tmp_path / "app.js").write_text("console.log('hi')\n")
        assert count_codebase_lines(tmp_path) == 1

    def test_nonexistent_dir(self, tmp_path):
        assert count_codebase_lines(tmp_path / "nope") == 0


class TestAnalyzeRepo:
    def test_with_git_repo(self, tmp_path):
        """Create a real git repo, make commits, and verify analysis."""
        # Init repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )

        # Write a file and commit
        (tmp_path / "app.py").write_text("def hello():\n    print('hi')\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path, capture_output=True,
        )

        # Get the commit time
        result = subprocess.run(
            ["git", "log", "--format=%aI", "-1"],
            cwd=tmp_path, capture_output=True, text=True,
        )
        commit_time = datetime.fromisoformat(result.stdout.strip())

        # Create a session window that covers the commit
        window_start = commit_time - timedelta(minutes=5)
        window_end = commit_time + timedelta(minutes=5)

        stats = _analyze_repo(tmp_path, [(window_start, window_end)])
        assert stats.ai_lines == 2  # 2 lines added
        assert stats.ai_commits == 1
        assert stats.total_commits == 1
        assert stats.total_lines == 2

    def test_commit_outside_session(self, tmp_path):
        """Commits outside session windows should not count as AI."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )

        (tmp_path / "app.py").write_text("print('hello')\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "manual commit"],
            cwd=tmp_path, capture_output=True,
        )

        # Session window far in the future — should not match
        far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        stats = _analyze_repo(tmp_path, [(far_future, far_future + timedelta(hours=1))])
        assert stats.ai_lines == 0
        assert stats.ai_commits == 0
        assert stats.total_commits == 1
        assert stats.total_lines == 1
