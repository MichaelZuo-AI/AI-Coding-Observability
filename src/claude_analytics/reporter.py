"""CLI output formatting for analytics reports (orchestration model)."""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from .models import ActivityBlock, OrchestrationSession
from .codegen import CodeGenStats
from .privacy import ProjectRedactor

BAR_WIDTH = 20

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

HEADER_COLOR = "\033[38;5;75m"   # bright blue
ACCENT_COLOR = "\033[38;5;228m"  # yellow
LINE_COLOR = "\033[38;5;240m"    # dark gray

# Orchestration tier colors
TIER_COLORS = {
    "flawless": "\033[38;5;75m",   # blue
    "clean": "\033[38;5;82m",      # green
    "guided": "\033[38;5;228m",    # yellow
    "heavy": "\033[38;5;203m",     # red
}

PRECISION_TIERS = [
    (1.0, "Flawless", "\033[38;5;75m"),
    (0.50, "Clean", "\033[38;5;82m"),
    (0.25, "Guided", "\033[38;5;228m"),
    (0.0, "Heavy", "\033[38;5;203m"),
]


def precision_tier_label(score: float) -> tuple[str, str]:
    """Map a precision score (0-1) to a tier label and ANSI color."""
    for threshold, label, color in PRECISION_TIERS:
        if score >= threshold:
            return label, color
    return "Heavy", "\033[38;5;203m"


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


def _bar(fraction: float, tier: str = "clean", width: int = BAR_WIDTH) -> str:
    filled = int(fraction * width)
    color = TIER_COLORS.get(tier, "")
    bar_filled = "\u2588" * filled
    bar_empty = "\u2591" * (width - filled)
    if _use_color():
        return f"{color}{bar_filled}{RESET}{DIM}{bar_empty}{RESET}"
    return bar_filled + bar_empty


def compute_streaks(blocks: list[ActivityBlock]) -> tuple[int, int]:
    """Compute current and longest consecutive-day streaks from activity blocks.

    Returns (current_streak, longest_streak) in days.
    """
    if not blocks:
        return 0, 0

    active_dates = sorted({b.start_time.date() for b in blocks})
    if not active_dates:
        return 0, 0

    longest = 1
    current = 1
    for i in range(1, len(active_dates)):
        if active_dates[i] - active_dates[i - 1] == timedelta(days=1):
            current += 1
            longest = max(longest, current)
        else:
            current = 1

    # current streak = streak ending on the most recent active date
    return current, longest


HEATMAP_CHARS = ["\u2591", "\u2592", "\u2593", "\u2588"]  # light to heavy
HEATMAP_COLORS = [
    "\033[38;5;236m",  # very dim (no activity)
    "\033[38;5;107m",  # light green
    "\033[38;5;71m",   # medium green
    "\033[38;5;40m",   # bright green
]
DAY_LABELS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def format_heatmap(blocks: list[ActivityBlock], max_weeks: int = 20) -> str:
    """Render a GitHub-style ASCII contribution heatmap from activity blocks."""
    if not blocks:
        return ""

    daily: dict[datetime, int] = defaultdict(int)
    for b in blocks:
        daily[b.start_time.date()] += b.duration_seconds

    if not daily:
        return ""

    min_date = min(daily.keys())
    max_date = max(daily.keys())

    start = min_date - timedelta(days=min_date.weekday())
    end = max_date + timedelta(days=6 - max_date.weekday())

    total_days = (end - start).days + 1
    total_weeks = total_days // 7
    if total_weeks > max_weeks:
        start = end - timedelta(days=max_weeks * 7 - 1)
        start = start - timedelta(days=start.weekday())

    values = [v for v in daily.values() if v > 0]
    if not values:
        return ""
    p33 = sorted(values)[len(values) // 3]
    p66 = sorted(values)[2 * len(values) // 3]

    def intensity(secs: int) -> int:
        if secs <= 0:
            return 0
        if secs <= p33:
            return 1
        if secs <= p66:
            return 2
        return 3

    lines: list[str] = []
    lines.append(f"  {_c(BOLD, 'Activity Heatmap')}")
    lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

    for dow in range(7):
        row_chars: list[str] = []
        day = start + timedelta(days=dow)
        while day <= end:
            secs = daily.get(day, 0)
            level = intensity(secs)
            char = HEATMAP_CHARS[level]
            if _use_color():
                row_chars.append(f"{HEATMAP_COLORS[level]}{char}{RESET}")
            else:
                row_chars.append(char)
            day += timedelta(days=7)
        label = _c(DIM, f"{DAY_LABELS[dow]}")
        lines.append(f"  {label} {''.join(row_chars)}")

    lines.append("")
    return "\n".join(lines)


def _trend_arrow(current: float, previous: float) -> str:
    """Return a colored trend arrow comparing current vs previous period."""
    if previous == 0:
        return ""
    pct_change = (current - previous) / previous
    if pct_change > 0.1:
        return _c("\033[38;5;82m", "\u2191")   # green up
    elif pct_change < -0.1:
        return _c("\033[38;5;203m", "\u2193")  # red down
    else:
        return _c("\033[38;5;228m", "\u2192")  # yellow flat


def print_report(
    orchestration_sessions: list[OrchestrationSession],
    blocks: list[ActivityBlock],
    codegen_stats: CodeGenStats | None = None,
    insights: list | None = None,
) -> str:
    """Generate and return the full CLI report string (orchestration model)."""
    if not orchestration_sessions:
        return "No orchestration sessions found."

    redactor = ProjectRedactor()

    # Date range from blocks
    earliest = None
    latest = None
    if blocks:
        earliest = min(b.start_time for b in blocks)
        latest = max(b.start_time for b in blocks)

    user = os.environ.get("USER", "engineer")
    lines: list[str] = []

    # --- Header ---
    lines.append("")
    lines.append(_c(LINE_COLOR, "\u2550" * 50))
    lines.append(f"  {_c(HEADER_COLOR + BOLD, 'Claude Code Analytics')}")
    if earliest and latest:
        lines.append(f"  {_c(ACCENT_COLOR, earliest.strftime('%Y-%m-%d'))} ~ {_c(ACCENT_COLOR, latest.strftime('%Y-%m-%d'))}")
    lines.append(f"  Engineer: {_c(HEADER_COLOR, user)}")

    current_streak, longest_streak = compute_streaks(blocks)
    if longest_streak > 0:
        lines.append(f"  Streak: {_c(ACCENT_COLOR, f'{current_streak}d')} current  {_c(DIM, f'{longest_streak}d longest')}")

    lines.append(_c(LINE_COLOR, "\u2550" * 50))
    lines.append("")

    # --- Orchestration Precision ---
    total_sessions = len(orchestration_sessions)
    avg_precision = sum(s.precision_score for s in orchestration_sessions) / total_sessions
    zero_touch = sum(1 for s in orchestration_sessions if s.steering_count == 0)
    zero_touch_rate = zero_touch / total_sessions

    tier_label, tier_color = precision_tier_label(avg_precision)

    lines.append(f"  {_c(BOLD, 'Orchestration Precision')}")
    lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

    bar = _bar(avg_precision, tier_label.lower())
    score_str = _c(tier_color + BOLD, f"{avg_precision:.2f}")
    tier_str = _c(tier_color, f"[{tier_label}]")
    lines.append(f"  {_c(BOLD, 'Score')}       {bar}  {score_str} {tier_str}")
    lines.append(f"  {_c(DIM, 'Zero-touch')}   {_c(ACCENT_COLOR, f'{zero_touch_rate:.0%}')} ({zero_touch}/{total_sessions} sessions)")
    lines.append(f"  {_c(DIM, 'Sessions')}     {_c(BOLD, str(total_sessions))}")
    lines.append("")

    # --- Session Breakdown ---
    tier_counts: dict[str, int] = {"flawless": 0, "clean": 0, "guided": 0, "heavy": 0}
    for s in orchestration_sessions:
        tier_counts[s.tier] = tier_counts.get(s.tier, 0) + 1

    lines.append(f"  {_c(BOLD, 'Session Breakdown')}")
    lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

    for tier_name in ["flawless", "clean", "guided", "heavy"]:
        count = tier_counts[tier_name]
        frac = count / total_sessions if total_sessions > 0 else 0
        bar = _bar(frac, tier_name)
        color = TIER_COLORS[tier_name]
        label = _c(color, f"{tier_name.capitalize():<10}")
        pct_str = _c(ACCENT_COLOR, f"{frac * 100:4.0f}%")
        lines.append(f"  {label} {bar}  {pct_str}  {_c(BOLD, str(count))}")

    lines.append("")

    # --- Activity Heatmap ---
    heatmap = format_heatmap(blocks)
    if heatmap:
        lines.append(heatmap)

    # --- Top Projects by Precision ---
    proj_sessions: dict[str, list[OrchestrationSession]] = {}
    for s in orchestration_sessions:
        proj_name = redactor.redact(s.project)
        proj_sessions.setdefault(proj_name, []).append(s)

    if proj_sessions:
        lines.append(f"  {_c(BOLD, 'Top Projects by Precision')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

        sorted_projects = sorted(
            proj_sessions.items(),
            key=lambda x: sum(s.precision_score for s in x[1]) / len(x[1]),
            reverse=True,
        )

        for proj_name, sessions in sorted_projects[:10]:
            avg = sum(s.precision_score for s in sessions) / len(sessions)
            tier_l, tier_c = precision_tier_label(avg)
            count = len(sessions)
            lines.append(
                f"  {_c(HEADER_COLOR, f'{proj_name:<20}')} "
                f"{_c(tier_c + BOLD, f'{avg:.2f}')} "
                f"{_c(tier_c, f'[{tier_l}]')}"
                f"  {_c(DIM, f'{count} sessions')}"
            )

        lines.append("")

    # --- Agent Throughput ---
    if codegen_stats and (codegen_stats.ai_commits > 0 or codegen_stats.ai_lines > 0):
        lines.append(f"  {_c(BOLD, 'Agent Throughput')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
        lines.append(f"  {_c(DIM, 'Commits')}         {_c(BOLD, f'{codegen_stats.ai_commits}')} AI / {codegen_stats.total_commits} total")
        lines.append(f"  {_c(DIM, 'Files touched')}   {_c(BOLD, str(len(codegen_stats.files_touched)))}")
        lines.append(f"  {_c(DIM, 'Lines produced')}  {_c(BOLD, f'{codegen_stats.ai_lines:,}')} AI / {codegen_stats.total_lines:,} total")
        lines.append("")

    # --- Insights ---
    if insights is not None:
        from .orchestration_insights import format_orchestration_insights
        lines.append(f"  {_c(BOLD, 'Insights')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
        lines.append(format_orchestration_insights(insights))
        lines.append("")

    return "\n".join(lines)
