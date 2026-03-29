"""CLI entrypoint for Claude Code Analytics."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .parser import parse_all_sessions, CLAUDE_PROJECTS_DIR
from .aggregator import build_activity_blocks
from .codegen import analyze_codegen
from .orchestration import analyze_session
from .orchestration_insights import generate_orchestration_insights
from .reporter import print_report
from .privacy import ProjectRedactor


_BAR_WIDTH = 20
_CLEAR_LINE = "\r" + " " * 60 + "\r"


def _progress(msg: str, done: int = 0, total: int = 0) -> None:
    """Print a progress bar to stderr (won't interfere with piped output)."""
    if total > 0:
        frac = done / total
        filled = int(frac * _BAR_WIDTH)
        bar = "\u2588" * filled + "\u2591" * (_BAR_WIDTH - filled)
        pct = f"{frac * 100:3.0f}%"
        print(f"\r  {msg} [{bar}] {pct} ({done}/{total})", end="", file=sys.stderr, flush=True)
    else:
        print(f"\r  {msg}...", end="", file=sys.stderr, flush=True)


def _progress_done() -> None:
    print(_CLEAR_LINE, end="", file=sys.stderr, flush=True)


def parse_date(s: str) -> datetime:
    """Parse a date string like '2026-02-01' into a timezone-aware datetime."""
    dt = datetime.strptime(s, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def cmd_report(args: argparse.Namespace) -> None:
    projects_dir = Path(args.projects_dir) if args.projects_dir else CLAUDE_PROJECTS_DIR

    _progress("Discovering sessions")
    sessions = parse_all_sessions(
        projects_dir,
        project_filter=args.project,
        on_progress=lambda done, total: _progress("Parsing sessions", done, total),
    )

    if not sessions:
        _progress_done()
        print("No sessions found.")
        return

    # Date filtering
    from_date = parse_date(args.from_date) if args.from_date else None
    to_date = parse_date(args.to_date) if args.to_date else None

    if from_date:
        sessions = [s for s in sessions if s.end_time and s.end_time >= from_date]
    if to_date:
        sessions = [s for s in sessions if s.start_time and s.start_time <= to_date]

    if not sessions:
        _progress_done()
        print("No sessions found for the specified date range.")
        return

    # Build activity blocks (for heatmap/streaks)
    _progress(f"Building blocks for {len(sessions)} sessions")
    all_blocks = []
    for session in sessions:
        blocks = build_activity_blocks(session)
        all_blocks.extend(blocks)

    # Analyze orchestration
    _progress("Analyzing orchestration")
    orchestration_sessions = [analyze_session(s) for s in sessions]

    # Codegen stats
    codegen_stats = analyze_codegen(
        projects_dir,
        project_filter=args.project,
        sessions=sessions,
        on_progress=lambda done, total: _progress("Analyzing git repos", done, total),
    )

    # Generate insights
    insights_list = generate_orchestration_insights(orchestration_sessions)

    _progress_done()
    report = print_report(
        orchestration_sessions=orchestration_sessions,
        blocks=all_blocks,
        codegen_stats=codegen_stats,
        insights=insights_list,
    )
    print(report)


def cmd_sessions(args: argparse.Namespace) -> None:
    projects_dir = Path(args.projects_dir) if args.projects_dir else CLAUDE_PROJECTS_DIR

    _progress("Discovering sessions")
    sessions = parse_all_sessions(
        projects_dir,
        project_filter=args.project,
        on_progress=lambda done, total: _progress("Parsing sessions", done, total),
    )
    _progress_done()

    if not sessions:
        print("No sessions found.")
        return

    # Sort by start time, most recent first
    sessions.sort(key=lambda s: s.start_time or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    redactor = ProjectRedactor()
    limit = args.limit or 20
    for session in sessions[:limit]:
        user_msgs = sum(1 for m in session.messages if m.role == "user")
        start = session.start_time.strftime("%Y-%m-%d %H:%M") if session.start_time else "unknown"
        proj = redactor.redact(session.project)
        print(f"  {start}  {proj:<25} {user_msgs:>3} msgs  {session.session_id[:8]}")


def app() -> None:
    parser = argparse.ArgumentParser(
        prog="claude-analytics",
        description="Analyze Claude Code session logs",
    )
    parser.add_argument(
        "--projects-dir",
        help="Path to Claude projects directory (default: ~/.claude/projects)",
    )

    subparsers = parser.add_subparsers(dest="command")

    # report
    report_parser = subparsers.add_parser("report", help="Generate activity report")
    report_parser.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    report_parser.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    report_parser.add_argument("--project", help="Filter by project name")

    # sessions
    sessions_parser = subparsers.add_parser("sessions", help="List sessions")
    sessions_parser.add_argument("--limit", type=int, default=20, help="Max sessions to show")
    sessions_parser.add_argument("--project", help="Filter by project name")

    args = parser.parse_args()

    if args.command == "report":
        cmd_report(args)
    elif args.command == "sessions":
        cmd_sessions(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    app()
