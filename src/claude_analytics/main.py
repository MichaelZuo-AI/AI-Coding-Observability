"""CLI entrypoint for Claude Code Analytics."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .parser import parse_all_sessions, CLAUDE_PROJECTS_DIR
from .aggregator import build_activity_blocks
from .codegen import analyze_codegen, analyze_codegen_by_project
from .reporter import print_report


def parse_date(s: str) -> datetime:
    """Parse a date string like '2026-02-01' into a timezone-aware datetime."""
    dt = datetime.strptime(s, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def cmd_report(args: argparse.Namespace) -> None:
    projects_dir = Path(args.projects_dir) if args.projects_dir else CLAUDE_PROJECTS_DIR
    sessions = parse_all_sessions(projects_dir, project_filter=args.project)

    if not sessions:
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
        print("No sessions found for the specified date range.")
        return

    all_blocks = []
    for session in sessions:
        blocks = build_activity_blocks(session)
        all_blocks.extend(blocks)

    codegen_stats = analyze_codegen(projects_dir, project_filter=args.project)
    codegen_by_project = analyze_codegen_by_project(projects_dir) if not args.project else None

    report = print_report(all_blocks, from_date, to_date, codegen_stats, codegen_by_project)
    print(report)


def cmd_sessions(args: argparse.Namespace) -> None:
    projects_dir = Path(args.projects_dir) if args.projects_dir else CLAUDE_PROJECTS_DIR
    sessions = parse_all_sessions(projects_dir, project_filter=args.project)

    if not sessions:
        print("No sessions found.")
        return

    # Sort by start time, most recent first
    sessions.sort(key=lambda s: s.start_time or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    limit = args.limit or 20
    for session in sessions[:limit]:
        user_msgs = sum(1 for m in session.messages if m.role == "user")
        start = session.start_time.strftime("%Y-%m-%d %H:%M") if session.start_time else "unknown"
        print(f"  {start}  {session.project:<25} {user_msgs:>3} msgs  {session.session_id[:8]}")


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
