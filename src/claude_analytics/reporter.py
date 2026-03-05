"""CLI output formatting for analytics reports."""

import os
import sys
from datetime import datetime
from .models import ActivityBlock
from .codegen import CodeGenStats

CATEGORY_ORDER = ["coding", "debug", "design", "devops", "review", "other"]
BAR_WIDTH = 20

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Category colors
CATEGORY_COLORS = {
    "coding": "\033[38;5;82m",   # green
    "debug": "\033[38;5;203m",   # red
    "design": "\033[38;5;141m",  # purple
    "devops": "\033[38;5;208m",  # orange
    "review": "\033[38;5;81m",   # cyan
    "other": "\033[38;5;245m",   # gray
}

HEADER_COLOR = "\033[38;5;75m"   # bright blue
ACCENT_COLOR = "\033[38;5;228m"  # yellow
LINE_COLOR = "\033[38;5;240m"    # dark gray


def _use_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(color: str, text: str) -> str:
    if not _use_color():
        return text
    return f"{color}{text}{RESET}"


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable duration like '12h' or '45m'."""
    if seconds >= 3600:
        hours = seconds / 3600
        return f"{hours:.0f}h"
    elif seconds >= 60:
        minutes = seconds / 60
        return f"{minutes:.0f}m"
    else:
        return f"{seconds}s"


def _bar(fraction: float, category: str, width: int = BAR_WIDTH) -> str:
    filled = int(fraction * width)
    color = CATEGORY_COLORS.get(category, "")
    bar_filled = "\u2588" * filled
    bar_empty = "\u2591" * (width - filled)
    if _use_color():
        return f"{color}{bar_filled}{RESET}{DIM}{bar_empty}{RESET}"
    return bar_filled + bar_empty


def format_codegen_section(
    stats: CodeGenStats,
    project_stats: dict[str, CodeGenStats] | None = None,
) -> str:
    """Generate the AI Code Generation section of the report."""
    lines: list[str] = []

    GREEN = CATEGORY_COLORS["coding"]

    lines.append(f"  {_c(BOLD, 'AI Code Generation')}")
    lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

    # Overall AI percentage
    if stats.total_lines > 0:
        pct = stats.ai_percentage
        bar = _bar(pct / 100, "coding", BAR_WIDTH)
        lines.append(f"  {_c(BOLD, 'AI-generated')}  {bar}  {_c(BOLD + ACCENT_COLOR, f'{pct:.0f}%')}")
        lines.append(f"  {_c(DIM, f'  {stats.ai_lines:,} AI lines / {stats.total_lines:,} total lines')}")
    else:
        lines.append(f"  {_c(BOLD, 'AI lines')}        {_c(BOLD + ACCENT_COLOR, f'{stats.ai_lines:>8,}')}")

    lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
    lines.append(f"  {_c(DIM, 'AI commits')}          {_c(BOLD, str(stats.ai_commits))}")
    lines.append(f"  {_c(DIM, 'Total commits')}       {_c(BOLD, str(stats.total_commits))}")
    lines.append(f"  {_c(DIM, 'Files touched')}       {_c(BOLD, str(len(stats.files_touched)))}")
    lines.append("")

    # Per-project breakdown with percentages
    if project_stats:
        lines.append(f"  {_c(BOLD, 'AI % by Project')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

        sorted_projects = sorted(
            project_stats.items(),
            key=lambda x: x[1].ai_lines,
            reverse=True,
        )
        for proj_name, pstats in sorted_projects[:10]:
            if pstats.ai_lines <= 0:
                continue
            if pstats.total_lines > 0:
                pct = pstats.ai_percentage
                mini_bar = _bar(pct / 100, "coding", 10)
                pct_str = _c(BOLD + ACCENT_COLOR, f"{pct:>3.0f}%")
                lines.append(
                    f"  {_c(HEADER_COLOR, f'{proj_name:<18}')} {mini_bar} {pct_str}"
                    f"  {_c(DIM, f'{pstats.ai_lines:,}/{pstats.total_lines:,}')}"
                )
            else:
                lines.append(
                    f"  {_c(HEADER_COLOR, f'{proj_name:<18}')} "
                    f"{_c(BOLD, f'{pstats.ai_lines:>6,}')} lines"
                )
        lines.append("")

    return "\n".join(lines)


def print_report(
    blocks: list[ActivityBlock],
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    codegen_stats: CodeGenStats | None = None,
    codegen_by_project: dict[str, CodeGenStats] | None = None,
) -> str:
    """Generate and return the full CLI report string."""
    if not blocks:
        return "No activity data found for the specified period."

    # Filter by date range
    if from_date:
        blocks = [b for b in blocks if b.start_time >= from_date]
    if to_date:
        blocks = [b for b in blocks if b.start_time <= to_date]

    if not blocks:
        return "No activity data found for the specified period."

    # Category totals
    cat_totals: dict[str, int] = {}
    for b in blocks:
        cat_totals[b.category] = cat_totals.get(b.category, 0) + b.duration_seconds
    total_seconds = sum(cat_totals.values())

    if total_seconds == 0:
        return "No active time recorded for the specified period."

    # Project totals
    proj_totals: dict[str, dict[str, int]] = {}
    for b in blocks:
        if b.project not in proj_totals:
            proj_totals[b.project] = {}
        p = proj_totals[b.project]
        p[b.category] = p.get(b.category, 0) + b.duration_seconds

    # Date range
    earliest = min(b.start_time for b in blocks)
    latest = max(b.start_time for b in blocks)

    user = os.environ.get("USER", "engineer")
    lines: list[str] = []

    # Header
    lines.append("")
    lines.append(_c(LINE_COLOR, "\u2550" * 50))
    lines.append(f"  {_c(HEADER_COLOR + BOLD, 'Claude Code Analytics')}")
    lines.append(f"  {_c(ACCENT_COLOR, earliest.strftime('%Y-%m-%d'))} ~ {_c(ACCENT_COLOR, latest.strftime('%Y-%m-%d'))}")
    lines.append(f"  Engineer: {_c(HEADER_COLOR, user)}")
    lines.append(_c(LINE_COLOR, "\u2550" * 50))
    lines.append("")

    # Category breakdown
    lines.append(f"  {_c(BOLD, 'Active Time Breakdown')}")
    lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

    for cat in CATEGORY_ORDER:
        secs = cat_totals.get(cat, 0)
        if secs == 0:
            continue
        frac = secs / total_seconds
        pct = frac * 100
        color = CATEGORY_COLORS.get(cat, "")
        bar = _bar(frac, cat)
        dur = format_duration(secs)
        cat_label = _c(color, f"{cat:<10}")
        pct_str = _c(ACCENT_COLOR, f"{pct:4.0f}%")
        dur_str = _c(BOLD, f"{dur:>5}")
        lines.append(f"  {cat_label} {bar}  {pct_str}  {dur_str}")

    lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
    total_label = _c(BOLD, "Total Active")
    total_dur = _c(BOLD + ACCENT_COLOR, format_duration(total_seconds))
    lines.append(f"  {total_label:<34}  {_c(ACCENT_COLOR, '100%')}  {total_dur:>5}")
    lines.append("")

    # Top projects
    if proj_totals:
        lines.append(f"  {_c(BOLD, 'Top Projects by Active Time')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

        sorted_projects = sorted(
            proj_totals.items(),
            key=lambda x: sum(x[1].values()),
            reverse=True,
        )

        for proj_name, cats in sorted_projects[:10]:
            proj_total = sum(cats.values())
            dur = format_duration(proj_total)
            # Top 2 categories for this project
            top_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)[:2]
            cat_parts = []
            for c, v in top_cats:
                color = CATEGORY_COLORS.get(c, "")
                cat_parts.append(_c(color, f"{c}({v * 100 // proj_total}%)"))
            cat_str = " ".join(cat_parts)
            lines.append(f"  {_c(HEADER_COLOR, f'{proj_name:<20}')} {_c(BOLD, f'{dur:>5}')}  {cat_str}")

        lines.append("")

    # AI Code Generation section
    if codegen_stats and codegen_stats.ai_lines > 0:
        lines.append(format_codegen_section(codegen_stats, codegen_by_project))

    return "\n".join(lines)
