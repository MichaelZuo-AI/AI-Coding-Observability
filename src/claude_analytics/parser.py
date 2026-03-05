"""Parse Claude Code JSONL session logs into structured Session objects."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from .models import Message, Session

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def discover_sessions(
    projects_dir: Path = CLAUDE_PROJECTS_DIR,
    project_filter: str | None = None,
) -> list[Path]:
    """Find all JSONL session files under the Claude projects directory."""
    if not projects_dir.exists():
        return []

    jsonl_files = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        if project_filter and project_filter not in project_dir.name:
            continue
        for f in sorted(project_dir.glob("*.jsonl")):
            jsonl_files.append(f)

    return jsonl_files


def _extract_project_name(project_dir_name: str) -> str:
    """Convert directory name like '-Users-michael-Engineering-MyProject' to 'MyProject'.

    For simple names like 'test-project', return as-is.
    For Claude Code style paths starting with '-', the name encodes a filesystem
    path with '/' replaced by '-'. We resolve against the real filesystem to find
    where parent directories end and the project name begins, preserving hyphens
    in project names like 'AI-Coding-Observability'.
    """
    if not project_dir_name.startswith("-"):
        return project_dir_name
    parts = project_dir_name.strip("-").split("-")
    if not parts:
        return project_dir_name

    # Walk the filesystem greedily to find how deep the parent path goes.
    # e.g. for ["Users","michaelzuo","Engineering","AIDreamWorks","AI","Coding","Observability"]
    # /Users/michaelzuo/Engineering/AIDreamWorks exists but .../AI doesn't,
    # so remaining "AI-Coding-Observability" is the project name.
    current = Path("/")
    last_valid_depth = 0
    for i, part in enumerate(parts):
        candidate = current / part
        if candidate.is_dir():
            current = candidate
            last_valid_depth = i + 1
        else:
            break

    if last_valid_depth > 0 and last_valid_depth < len(parts):
        return "-".join(parts[last_valid_depth:])

    # Fallback: if the entire path resolved (project dir exists) or nothing
    # resolved (deleted/moved), return the last segment
    return parts[-1] if parts else project_dir_name


def _extract_tool_names(content: list | str) -> list[str]:
    """Extract tool names from assistant message content blocks."""
    if not isinstance(content, list):
        return []
    tools = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "")
            if name:
                tools.append(name)
    return tools


def _extract_text(content: list | str) -> str:
    """Extract text content from message content (string or content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    # Tool results from user messages — skip content
                    pass
        return " ".join(texts)
    return ""


def parse_session(jsonl_path: Path) -> Session | None:
    """Parse a single JSONL file into a Session object.

    Returns None if the session has fewer than 2 user messages.
    """
    project_dir_name = jsonl_path.parent.name
    project = _extract_project_name(project_dir_name)
    session_id = jsonl_path.stem

    messages: list[Message] = []

    if not jsonl_path.exists():
        return None

    with open(jsonl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            if entry_type not in ("user", "assistant"):
                continue

            timestamp_str = entry.get("timestamp")
            if not timestamp_str:
                continue

            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            msg_data = entry.get("message", {})
            role = msg_data.get("role", entry_type)
            raw_content = msg_data.get("content", "")

            text = _extract_text(raw_content)
            tool_uses = _extract_tool_names(raw_content) if role == "assistant" else []

            # Skip tool_result-only user messages (they have no meaningful text)
            if role == "user" and not text.strip():
                continue

            # Deduplicate streaming assistant chunks: keep the last one per uuid
            # (Claude Code logs multiple chunks for the same message as it streams)
            msg = Message(
                role=role,
                content=text.strip(),
                timestamp=timestamp,
                tool_uses=tool_uses,
            )
            messages.append(msg)

    # Deduplicate: Claude Code emits multiple JSONL lines for the same assistant message
    # as it streams. We keep only the last entry per timestamp for assistant messages,
    # and merge tool_uses across all entries sharing the same parent message.
    messages = _deduplicate_messages(messages)

    # Filter sessions with fewer than 2 user messages
    user_msg_count = sum(1 for m in messages if m.role == "user")
    if user_msg_count < 2:
        return None

    if not messages:
        return None

    session = Session(
        session_id=session_id,
        project=project,
        messages=messages,
        start_time=messages[0].timestamp,
        end_time=messages[-1].timestamp,
    )
    return session


def _deduplicate_messages(messages: list[Message]) -> list[Message]:
    """Merge consecutive assistant messages (streaming chunks) into single messages."""
    if not messages:
        return []

    result: list[Message] = []
    for msg in messages:
        if (
            result
            and msg.role == "assistant"
            and result[-1].role == "assistant"
            and abs((msg.timestamp - result[-1].timestamp).total_seconds()) < 2
        ):
            # Same assistant turn — merge: keep latest content, accumulate tools
            prev = result[-1]
            merged_tools = list(prev.tool_uses)
            for t in msg.tool_uses:
                if t not in merged_tools:
                    merged_tools.append(t)
            result[-1] = Message(
                role="assistant",
                content=msg.content if msg.content else prev.content,
                timestamp=max(prev.timestamp, msg.timestamp),
                tool_uses=merged_tools,
            )
        else:
            result.append(msg)

    return result


def parse_all_sessions(
    projects_dir: Path = CLAUDE_PROJECTS_DIR,
    project_filter: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[Session]:
    """Parse all session files in parallel and return valid sessions.

    on_progress: optional callback(done, total) called as each file completes.
    """
    paths = discover_sessions(projects_dir, project_filter)
    if not paths:
        return []

    total = len(paths)
    sessions = []
    done = 0
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(parse_session, path): path for path in paths}
        for future in as_completed(futures):
            done += 1
            if on_progress:
                on_progress(done, total)
            session = future.result()
            if session is not None:
                sessions.append(session)
    return sessions
