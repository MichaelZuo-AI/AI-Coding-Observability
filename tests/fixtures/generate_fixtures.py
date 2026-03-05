"""Generate test fixture JSONL files."""

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def _user_entry(session_id, timestamp, content, cwd="/test/project"):
    return json.dumps({
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": cwd,
        "sessionId": session_id,
        "version": "2.1.37",
        "type": "user",
        "message": {"role": "user", "content": content},
        "uuid": f"user-{timestamp}",
        "timestamp": timestamp,
    })


def _assistant_entry(session_id, timestamp, text="", tool_uses=None, cwd="/test/project"):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    for tool in (tool_uses or []):
        content.append({"type": "tool_use", "id": f"tool-{tool}-{timestamp}", "name": tool, "input": {}})

    return json.dumps({
        "parentUuid": f"user-{timestamp}",
        "isSidechain": False,
        "userType": "external",
        "cwd": cwd,
        "sessionId": session_id,
        "version": "2.1.37",
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-6",
            "id": f"msg-{timestamp}",
            "type": "message",
            "role": "assistant",
            "content": content,
        },
        "uuid": f"asst-{timestamp}",
        "timestamp": timestamp,
    })


def generate_coding_session():
    """A session focused on coding — implementing features."""
    sid = "coding-session-001"
    lines = [
        _user_entry(sid, "2026-02-10T10:00:00.000Z", "implement a login form component with email and password fields"),
        _assistant_entry(sid, "2026-02-10T10:00:05.000Z", "I'll create the login form.", ["Write", "Edit"]),
        _user_entry(sid, "2026-02-10T10:05:00.000Z", "add form validation to the login component"),
        _assistant_entry(sid, "2026-02-10T10:05:03.000Z", "Adding validation.", ["Edit"]),
        _user_entry(sid, "2026-02-10T10:10:00.000Z", "create a unit test for the login form"),
        _assistant_entry(sid, "2026-02-10T10:10:02.000Z", "Writing tests.", ["Write"]),
        _user_entry(sid, "2026-02-10T10:15:00.000Z", "add a password strength indicator function"),
        _assistant_entry(sid, "2026-02-10T10:15:04.000Z", "Done.", ["Edit"]),
    ]
    return sid, lines


def generate_debug_session():
    """A session focused on debugging."""
    sid = "debug-session-001"
    lines = [
        _user_entry(sid, "2026-02-11T14:00:00.000Z", "there's a TypeError in the auth module, the login is broken"),
        _assistant_entry(sid, "2026-02-11T14:00:10.000Z", "Let me look.", ["Read", "Bash"]),
        _user_entry(sid, "2026-02-11T14:03:00.000Z", "it still crashes with a null pointer exception"),
        _assistant_entry(sid, "2026-02-11T14:03:05.000Z", "Found the issue.", ["Read", "Edit"]),
        _user_entry(sid, "2026-02-11T14:08:00.000Z", "why does it fail only on the first request?"),
        _assistant_entry(sid, "2026-02-11T14:08:03.000Z", "Race condition.", ["Bash", "Grep"]),
    ]
    return sid, lines


def generate_design_session():
    """A session focused on architecture/design."""
    sid = "design-session-001"
    lines = [
        _user_entry(sid, "2026-02-12T09:00:00.000Z", "how should we structure the database schema for the new feature?"),
        _assistant_entry(sid, "2026-02-12T09:00:15.000Z", "Here's my recommendation.", ["Read"]),
        _user_entry(sid, "2026-02-12T09:10:00.000Z", "what's the best approach for handling pagination?"),
        _assistant_entry(sid, "2026-02-12T09:10:08.000Z", "Cursor-based.", ["Read"]),
        _user_entry(sid, "2026-02-12T09:20:00.000Z", "compare REST vs GraphQL for this use case"),
        _assistant_entry(sid, "2026-02-12T09:20:05.000Z", "Analysis.", []),
    ]
    return sid, lines


def generate_mixed_session():
    """A session with mixed activities and an idle gap."""
    sid = "mixed-session-001"
    lines = [
        _user_entry(sid, "2026-02-13T10:00:00.000Z", "implement the payment API endpoint"),
        _assistant_entry(sid, "2026-02-13T10:00:03.000Z", "Creating endpoint.", ["Write"]),
        _user_entry(sid, "2026-02-13T10:05:00.000Z", "fix the error in the response handler"),
        _assistant_entry(sid, "2026-02-13T10:05:02.000Z", "Fixed.", ["Edit", "Bash"]),
        # 15-minute idle gap here
        _user_entry(sid, "2026-02-13T10:20:00.000Z", "deploy this to staging"),
        _assistant_entry(sid, "2026-02-13T10:20:05.000Z", "Deploying.", ["Bash"]),
        _user_entry(sid, "2026-02-13T10:25:00.000Z", "set up the docker compose for the new service"),
        _assistant_entry(sid, "2026-02-13T10:25:03.000Z", "Done.", ["Write"]),
    ]
    return sid, lines


def generate_short_session():
    """A session too short to be useful (< 2 user messages)."""
    sid = "short-session-001"
    lines = [
        _user_entry(sid, "2026-02-14T08:00:00.000Z", "hello"),
        _assistant_entry(sid, "2026-02-14T08:00:01.000Z", "Hi!"),
    ]
    return sid, lines


def write_fixtures():
    project_dir = FIXTURES_DIR / "test-project"
    project_dir.mkdir(parents=True, exist_ok=True)

    for gen_func in [
        generate_coding_session,
        generate_debug_session,
        generate_design_session,
        generate_mixed_session,
        generate_short_session,
    ]:
        sid, lines = gen_func()
        filepath = project_dir / f"{sid}.jsonl"
        filepath.write_text("\n".join(lines) + "\n")
        print(f"  wrote {filepath}")


if __name__ == "__main__":
    write_fixtures()
