"""CLI entrypoint for Claude Code Analytics."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import json as json_module

from .parser import parse_all_sessions, CLAUDE_PROJECTS_DIR
from .aggregator import build_activity_blocks, aggregate_by_category, aggregate_by_project
from .codegen import analyze_codegen, analyze_codegen_by_project
from .reporter import print_report


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

    use_llm = getattr(args, "llm", False)
    _progress(f"Classifying {len(sessions)} sessions")
    all_blocks = []
    for session in sessions:
        blocks = build_activity_blocks(session, use_llm=use_llm)
        all_blocks.extend(blocks)

    codegen_stats = analyze_codegen(
        projects_dir,
        project_filter=args.project,
        sessions=sessions,
        on_progress=lambda done, total: _progress("Analyzing git repos", done, total),
    )
    codegen_by_project = analyze_codegen_by_project(projects_dir, sessions=sessions) if not args.project else None

    _progress_done()
    report = print_report(all_blocks, from_date, to_date, codegen_stats, codegen_by_project)
    print(report)


def _collect_data(args: argparse.Namespace) -> dict:
    """Collect analytics data and return as a JSON-serializable dict."""
    projects_dir = Path(args.projects_dir) if args.projects_dir else CLAUDE_PROJECTS_DIR

    sessions = parse_all_sessions(
        projects_dir,
        project_filter=getattr(args, "project", None),
        on_progress=lambda done, total: _progress("Parsing sessions", done, total),
    )

    if not sessions:
        _progress_done()
        return {}

    from_date = parse_date(args.from_date) if args.from_date else None
    to_date = parse_date(args.to_date) if args.to_date else None

    if from_date:
        sessions = [s for s in sessions if s.end_time and s.end_time >= from_date]
    if to_date:
        sessions = [s for s in sessions if s.start_time and s.start_time <= to_date]

    if not sessions:
        _progress_done()
        return {}

    use_llm = getattr(args, "llm", False)
    all_blocks = []
    for session in sessions:
        blocks = build_activity_blocks(session, use_llm=use_llm)
        all_blocks.extend(blocks)

    cat_totals = aggregate_by_category(all_blocks)
    proj_totals = aggregate_by_project(all_blocks)

    codegen_stats = analyze_codegen(
        projects_dir,
        project_filter=getattr(args, "project", None),
        sessions=sessions,
        on_progress=lambda done, total: _progress("Analyzing git repos", done, total),
    )
    codegen_by_project = analyze_codegen_by_project(projects_dir, sessions=sessions)

    _progress_done()

    earliest = min(b.start_time for b in all_blocks) if all_blocks else None
    latest = max(b.start_time for b in all_blocks) if all_blocks else None

    # Build daily time series
    daily: dict[str, dict[str, int]] = {}
    for block in all_blocks:
        day = block.start_time.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {}
        daily[day][block.category] = daily[day].get(block.category, 0) + block.duration_seconds

    daily_series = [
        {"date": day, **{cat: secs for cat, secs in cats.items()}}
        for day, cats in sorted(daily.items())
    ]

    return {
        "dateRange": {
            "from": earliest.isoformat() if earliest else None,
            "to": latest.isoformat() if latest else None,
        },
        "categoryTotals": cat_totals,
        "projectTotals": {
            proj: cats for proj, cats in proj_totals.items()
        },
        "dailySeries": daily_series,
        "codegen": {
            "aiLines": codegen_stats.ai_lines,
            "totalLines": codegen_stats.total_lines,
            "aiPercentage": round(codegen_stats.ai_percentage, 1),
            "aiCommits": codegen_stats.ai_commits,
            "totalCommits": codegen_stats.total_commits,
            "filesTouched": len(codegen_stats.files_touched),
        },
        "codegenByProject": {
            proj: {
                "aiLines": s.ai_lines,
                "totalLines": s.total_lines,
                "aiPercentage": round(s.ai_percentage, 1),
            }
            for proj, s in (codegen_by_project or {}).items()
            if s.ai_lines > 0
        },
    }


def cmd_dashboard(args: argparse.Namespace) -> None:
    _progress("Collecting data")
    data = _collect_data(args)

    if not data:
        print("No data found.")
        return

    import shutil
    import tempfile
    import http.server
    import webbrowser
    import functools

    # Serve from a temp directory to avoid writing into the installed package
    serve_dir = Path(tempfile.mkdtemp(prefix="claude-analytics-"))
    shutil.copy(Path(__file__).parent / "dashboard" / "index.html", serve_dir)
    data_path = serve_dir / "data.json"

    with open(data_path, "w") as f:
        json_module.dump(data, f, indent=2)

    port = args.port
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(serve_dir))

    try:
        server = http.server.HTTPServer(("localhost", port), handler)
    except OSError:
        print(f"Port {port} is in use. Try --port <other>", file=sys.stderr)
        sys.exit(1)

    url = f"http://localhost:{port}"
    print(f"Dashboard running at {url}")
    print("Press Ctrl+C to stop.")
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
    finally:
        shutil.rmtree(serve_dir, ignore_errors=True)


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
    report_parser.add_argument(
        "--llm", action="store_true",
        help="Use claude -p to reclassify low-confidence interactions (cached in SQLite)",
    )

    # sessions
    sessions_parser = subparsers.add_parser("sessions", help="List sessions")
    sessions_parser.add_argument("--limit", type=int, default=20, help="Max sessions to show")
    sessions_parser.add_argument("--project", help="Filter by project name")

    # dashboard
    dash_parser = subparsers.add_parser("dashboard", help="Launch React dashboard")
    dash_parser.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    dash_parser.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    dash_parser.add_argument("--project", help="Filter by project name")
    dash_parser.add_argument("--port", type=int, default=3333, help="Port for dashboard (default: 3333)")
    dash_parser.add_argument(
        "--llm", action="store_true",
        help="Use claude -p to reclassify low-confidence interactions",
    )

    args = parser.parse_args()

    if args.command == "report":
        cmd_report(args)
    elif args.command == "sessions":
        cmd_sessions(args)
    elif args.command == "dashboard":
        cmd_dashboard(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    app()
