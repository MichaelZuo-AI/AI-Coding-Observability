"""Additional edge-case tests for parser internals not covered by test_parser.py."""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from claude_analytics.parser import (
    _extract_project_name,
    _extract_text,
    _extract_tool_names,
    _deduplicate_messages,
    parse_session,
    discover_sessions,
)
from claude_analytics.models import Message


# ---------------------------------------------------------------------------
# _extract_project_name
# ---------------------------------------------------------------------------

class TestExtractProjectName:
    def test_simple_name_returned_as_is(self):
        assert _extract_project_name("my-project") == "my-project"

    def test_simple_name_no_leading_dash(self):
        assert _extract_project_name("test-project") == "test-project"

    def test_claude_style_path_extracts_last_segment(self):
        # "-Users-michael-Engineering-MyProject" → "MyProject"
        assert _extract_project_name("-Users-michael-Engineering-MyProject") == "MyProject"

    def test_claude_style_path_short(self):
        # "-Users-michael-Work" → "Work"
        assert _extract_project_name("-Users-michael-Work") == "Work"

    def test_single_dash_prefix(self):
        # "-SomeProject" → after stripping dash: "SomeProject", split on "-" → ["SomeProject"]
        assert _extract_project_name("-SomeProject") == "SomeProject"

    def test_empty_string(self):
        # Edge: empty string should not raise
        result = _extract_project_name("")
        assert isinstance(result, str)

    def test_only_dashes(self):
        # "---" → strip("-") → "", split("-") → [""], parts[-1] = ""
        result = _extract_project_name("---")
        assert isinstance(result, str)

    def test_project_without_leading_dash_with_internal_dashes(self):
        # "my-long-project-name" → no leading dash → returned as-is
        assert _extract_project_name("my-long-project-name") == "my-long-project-name"


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_string_content_returned_directly(self):
        assert _extract_text("hello world") == "hello world"

    def test_empty_string(self):
        assert _extract_text("") == ""

    def test_list_with_text_block(self):
        content = [{"type": "text", "text": "Hello"}]
        assert _extract_text(content) == "Hello"

    def test_list_with_multiple_text_blocks(self):
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result = _extract_text(content)
        assert "Hello" in result
        assert "World" in result

    def test_list_with_tool_result_skipped(self):
        content = [
            {"type": "tool_result", "content": "tool output"},
            {"type": "text", "text": "User text"},
        ]
        result = _extract_text(content)
        assert "User text" in result
        assert "tool output" not in result

    def test_list_with_tool_use_block_ignored(self):
        content = [
            {"type": "tool_use", "name": "Bash", "input": {}},
            {"type": "text", "text": "Done"},
        ]
        result = _extract_text(content)
        assert "Done" in result

    def test_empty_list_returns_empty_string(self):
        assert _extract_text([]) == ""

    def test_non_dict_items_in_list(self):
        content = ["raw string", {"type": "text", "text": "actual"}]
        result = _extract_text(content)
        # Should not raise; "actual" should still be extracted
        assert "actual" in result

    def test_other_type_returns_empty(self):
        # Passing a number — not str or list
        result = _extract_text(42)  # type: ignore
        assert result == ""


# ---------------------------------------------------------------------------
# _extract_tool_names
# ---------------------------------------------------------------------------

class TestExtractToolNames:
    def test_string_content_returns_empty(self):
        assert _extract_tool_names("no tools here") == []

    def test_empty_list_returns_empty(self):
        assert _extract_tool_names([]) == []

    def test_single_tool_use(self):
        content = [{"type": "tool_use", "name": "Write", "id": "x", "input": {}}]
        assert _extract_tool_names(content) == ["Write"]

    def test_multiple_tool_uses(self):
        content = [
            {"type": "tool_use", "name": "Read", "id": "1", "input": {}},
            {"type": "tool_use", "name": "Edit", "id": "2", "input": {}},
        ]
        result = _extract_tool_names(content)
        assert "Read" in result
        assert "Edit" in result
        assert len(result) == 2

    def test_non_tool_use_blocks_skipped(self):
        content = [
            {"type": "text", "text": "some text"},
            {"type": "tool_use", "name": "Bash", "id": "3", "input": {}},
        ]
        result = _extract_tool_names(content)
        assert result == ["Bash"]

    def test_tool_use_without_name_skipped(self):
        content = [{"type": "tool_use", "id": "4", "input": {}}]
        result = _extract_tool_names(content)
        assert result == []

    def test_non_dict_items_in_list_ignored(self):
        content = ["raw string", {"type": "tool_use", "name": "Grep", "id": "5", "input": {}}]
        result = _extract_tool_names(content)
        assert result == ["Grep"]


# ---------------------------------------------------------------------------
# _deduplicate_messages
# ---------------------------------------------------------------------------

class TestDeduplicateMessages:
    def _msg(self, role: str, content: str, ts_seconds: int, tools: list[str] | None = None) -> Message:
        return Message(
            role=role,
            content=content,
            timestamp=datetime(2026, 2, 10, 10, 0, ts_seconds, tzinfo=timezone.utc),
            tool_uses=tools or [],
        )

    def test_empty_list_returns_empty(self):
        assert _deduplicate_messages([]) == []

    def test_single_message_unchanged(self):
        msgs = [self._msg("user", "hello", 0)]
        result = _deduplicate_messages(msgs)
        assert len(result) == 1
        assert result[0].content == "hello"

    def test_user_messages_not_merged(self):
        """Consecutive user messages should NOT be merged."""
        msgs = [
            self._msg("user", "first", 0),
            self._msg("user", "second", 1),
        ]
        result = _deduplicate_messages(msgs)
        assert len(result) == 2

    def test_assistant_chunks_within_2s_merged(self):
        """Two assistant messages within 2 seconds → merged into one."""
        msgs = [
            self._msg("assistant", "Hello", 0, tools=["Read"]),
            self._msg("assistant", "Hello world", 1, tools=["Write"]),
        ]
        result = _deduplicate_messages(msgs)
        assert len(result) == 1
        # Last content wins
        assert result[0].content == "Hello world"
        # Tools accumulated
        assert "Read" in result[0].tool_uses
        assert "Write" in result[0].tool_uses

    def test_assistant_chunks_beyond_2s_not_merged(self):
        """Two assistant messages > 2 seconds apart → kept separate."""
        msgs = [
            self._msg("assistant", "First", 0),
            self._msg("assistant", "Second", 3),
        ]
        result = _deduplicate_messages(msgs)
        assert len(result) == 2

    def test_interleaved_user_assistant_not_merged(self):
        msgs = [
            self._msg("user", "question", 0),
            self._msg("assistant", "answer", 1),
            self._msg("user", "follow up", 2),
            self._msg("assistant", "follow answer", 3),
        ]
        result = _deduplicate_messages(msgs)
        assert len(result) == 4

    def test_duplicate_tools_not_doubled(self):
        """If both chunks have the same tool, it should appear only once."""
        msgs = [
            self._msg("assistant", "step 1", 0, tools=["Edit"]),
            self._msg("assistant", "step 2", 1, tools=["Edit"]),
        ]
        result = _deduplicate_messages(msgs)
        assert result[0].tool_uses.count("Edit") == 1

    def test_last_content_wins_on_merge(self):
        """Later chunk's content replaces earlier chunk's content."""
        msgs = [
            self._msg("assistant", "partial response", 0),
            self._msg("assistant", "full complete response", 1),
        ]
        result = _deduplicate_messages(msgs)
        assert result[0].content == "full complete response"

    def test_empty_content_falls_back_to_previous(self):
        """If the later chunk has empty content, keep the previous content."""
        msgs = [
            self._msg("assistant", "complete", 0),
            self._msg("assistant", "", 1),
        ]
        result = _deduplicate_messages(msgs)
        assert result[0].content == "complete"

    def test_timestamp_is_max_on_merge(self):
        msgs = [
            self._msg("assistant", "a", 0),
            self._msg("assistant", "b", 1),
        ]
        result = _deduplicate_messages(msgs)
        # Timestamp should be the later one (ts_seconds=1)
        assert result[0].timestamp.second == 1


# ---------------------------------------------------------------------------
# parse_session edge cases
# ---------------------------------------------------------------------------

class TestParseSessionEdgeCases:
    def test_malformed_json_lines_skipped(self, tmp_path):
        """Lines that are not valid JSON should be silently skipped."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        session_file = project_dir / "test-session.jsonl"
        lines = [
            '{"not valid json',  # malformed
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:00:00.000Z",
                "message": {"role": "user", "content": "hello there"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:05:00.000Z",
                "message": {"role": "user", "content": "second message"},
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        result = parse_session(session_file)
        assert result is not None
        assert len([m for m in result.messages if m.role == "user"]) == 2

    def test_missing_timestamp_lines_skipped(self, tmp_path):
        """Entries without a timestamp field should be skipped."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        session_file = project_dir / "test-session.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                # no "timestamp"
                "message": {"role": "user", "content": "no timestamp"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:00:00.000Z",
                "message": {"role": "user", "content": "has timestamp"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:05:00.000Z",
                "message": {"role": "user", "content": "second timestamped"},
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        result = parse_session(session_file)
        assert result is not None
        user_msgs = [m for m in result.messages if m.role == "user"]
        assert len(user_msgs) == 2

    def test_unknown_entry_types_skipped(self, tmp_path):
        """Entries with type not 'user' or 'assistant' are ignored."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        session_file = project_dir / "test-session.jsonl"
        lines = [
            json.dumps({
                "type": "system",
                "timestamp": "2026-02-10T10:00:00.000Z",
                "message": {"role": "system", "content": "system message"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:01:00.000Z",
                "message": {"role": "user", "content": "real user message 1"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:06:00.000Z",
                "message": {"role": "user", "content": "real user message 2"},
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        result = parse_session(session_file)
        assert result is not None
        assert len([m for m in result.messages if m.role == "user"]) == 2

    def test_empty_user_message_skipped(self, tmp_path):
        """User messages with only whitespace content are excluded."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        session_file = project_dir / "test-session.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:00:00.000Z",
                "message": {"role": "user", "content": "   "},  # only whitespace
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:05:00.000Z",
                "message": {"role": "user", "content": "real content"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:10:00.000Z",
                "message": {"role": "user", "content": "more real content"},
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        result = parse_session(session_file)
        assert result is not None
        user_msgs = [m for m in result.messages if m.role == "user"]
        assert len(user_msgs) == 2

    def test_invalid_timestamp_format_skipped(self, tmp_path):
        """Entries with unparseable timestamps are silently skipped."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        session_file = project_dir / "test-session.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "not-a-date",
                "message": {"role": "user", "content": "bad timestamp"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:00:00.000Z",
                "message": {"role": "user", "content": "valid msg 1"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:05:00.000Z",
                "message": {"role": "user", "content": "valid msg 2"},
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        result = parse_session(session_file)
        assert result is not None

    def test_project_name_extracted_from_directory(self, tmp_path):
        """Project name should come from the parent directory name."""
        project_dir = tmp_path / "my-cool-project"
        project_dir.mkdir()
        session_file = project_dir / "session-abc.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:00:00.000Z",
                "message": {"role": "user", "content": "message 1"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:05:00.000Z",
                "message": {"role": "user", "content": "message 2"},
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        result = parse_session(session_file)
        assert result is not None
        assert result.project == "my-cool-project"

    def test_session_id_from_filename_stem(self, tmp_path):
        """Session ID should be the filename stem (without extension)."""
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()
        session_file = project_dir / "unique-session-xyz.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:00:00.000Z",
                "message": {"role": "user", "content": "first"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:05:00.000Z",
                "message": {"role": "user", "content": "second"},
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        result = parse_session(session_file)
        assert result is not None
        assert result.session_id == "unique-session-xyz"

    def test_start_and_end_time_set(self, tmp_path):
        """start_time should be the first message, end_time the last."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        session_file = project_dir / "session.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:00:00.000Z",
                "message": {"role": "user", "content": "first message"},
            }),
            json.dumps({
                "type": "user",
                "timestamp": "2026-02-10T10:30:00.000Z",
                "message": {"role": "user", "content": "second message"},
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")
        result = parse_session(session_file)
        assert result is not None
        assert result.start_time == datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
        assert result.end_time == datetime(2026, 2, 10, 10, 30, tzinfo=timezone.utc)

    def test_empty_file_returns_none(self, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        session_file = project_dir / "empty.jsonl"
        session_file.write_text("")
        result = parse_session(session_file)
        assert result is None


# ---------------------------------------------------------------------------
# discover_sessions edge cases
# ---------------------------------------------------------------------------

class TestDiscoverSessionsExtra:
    def test_nonexistent_directory_returns_empty(self, tmp_path):
        result = discover_sessions(tmp_path / "does-not-exist")
        assert result == []

    def test_empty_directory_returns_empty(self, tmp_path):
        result = discover_sessions(tmp_path)
        assert result == []

    def test_only_non_jsonl_files_ignored(self, tmp_path):
        proj_dir = tmp_path / "my-project"
        proj_dir.mkdir()
        (proj_dir / "notes.txt").write_text("not a session")
        (proj_dir / "data.csv").write_text("1,2,3")
        result = discover_sessions(tmp_path)
        assert result == []

    def test_nested_structure_discovered(self, tmp_path):
        proj_dir = tmp_path / "proj-a"
        proj_dir.mkdir()
        (proj_dir / "session-1.jsonl").write_text("{}\n")
        (proj_dir / "session-2.jsonl").write_text("{}\n")
        result = discover_sessions(tmp_path)
        assert len(result) == 2

    def test_project_filter_partial_match(self, tmp_path):
        """Filter matches substrings — 'proj' should match 'my-proj-xyz'."""
        (tmp_path / "my-proj-xyz").mkdir()
        (tmp_path / "my-proj-xyz" / "s1.jsonl").write_text("{}\n")
        (tmp_path / "other-thing").mkdir()
        (tmp_path / "other-thing" / "s2.jsonl").write_text("{}\n")
        result = discover_sessions(tmp_path, project_filter="proj")
        assert len(result) == 1
        assert "my-proj-xyz" in str(result[0])
