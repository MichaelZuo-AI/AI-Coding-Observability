"""CLI output formatting for analytics reports."""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from .models import ActivityBlock
from .codegen import CodeGenStats
from .privacy import ProjectRedactor

CATEGORY_ORDER = ["coding", "debug", "design", "devops", "review", "data", "chat", "other"]
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
    "data": "\033[38;5;219m",    # pink
    "chat": "\033[38;5;252m",    # light gray
    "other": "\033[38;5;245m",   # gray
}

HEADER_COLOR = "\033[38;5;75m"   # bright blue
ACCENT_COLOR = "\033[38;5;228m"  # yellow
LINE_COLOR = "\033[38;5;240m"    # dark gray

# Engagement tier thresholds and labels (inspired by copilot-usage-advanced-dashboard)
ENGAGEMENT_TIERS = [
    (0.9, "Power User",  "\033[38;5;75m"),   # blue
    (0.7, "Strong",      "\033[38;5;82m"),   # green
    (0.5, "Productive",  "\033[38;5;228m"),  # yellow
    (0.3, "Developing",  "\033[38;5;208m"),  # orange
    (0.0, "Low",         "\033[38;5;203m"),  # red
]


def engagement_tier(score: float) -> tuple[str, str]:
    """Map an efficiency score (0-1) to an engagement tier name and ANSI color."""
    for threshold, label, color in ENGAGEMENT_TIERS:
        if score >= threshold:
            return label, color
    return "Low", "\033[38;5;203m"


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
    """Render a GitHub-style ASCII contribution heatmap from activity blocks.

    Shows a 7-row (Mon-Sun) x N-week grid using Unicode block characters
    at varying intensities based on daily active seconds.
    """
    if not blocks:
        return ""

    # Aggregate seconds per date
    daily: dict[datetime, int] = defaultdict(int)
    for b in blocks:
        daily[b.start_time.date()] += b.duration_seconds

    if not daily:
        return ""

    # Determine date range
    min_date = min(daily.keys())
    max_date = max(daily.keys())

    # Align to Monday start
    start = min_date - timedelta(days=min_date.weekday())
    end = max_date + timedelta(days=6 - max_date.weekday())

    # Limit to max_weeks
    total_days = (end - start).days + 1
    total_weeks = total_days // 7
    if total_weeks > max_weeks:
        start = end - timedelta(days=max_weeks * 7 - 1)
        start = start - timedelta(days=start.weekday())

    # Compute intensity thresholds from actual data
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


def format_efficiency_section(
    efficiency: dict,
    quality: dict,
) -> str:
    """Generate the Engineering Efficiency section of the report.

    Expects already-redacted project names in dict keys.
    """
    lines: list[str] = []
    lines.append(f"  {_c(BOLD, 'Engineering Efficiency')}")
    lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

    for proj_name in sorted(efficiency.keys()):
        eff = efficiency[proj_name]
        qual = quality.get(proj_name)

        proj_label = _c(HEADER_COLOR, f"{proj_name}")
        tier_name, tier_color = engagement_tier(eff.efficiency_score)
        score_str = _c(tier_color + BOLD, f"{eff.efficiency_score:.2f}")
        tier_str = _c(tier_color, f"[{tier_name}]")
        lines.append(f"  {proj_label}  Score: {score_str} {tier_str}")

        # Output metrics
        focus_str = _c(ACCENT_COLOR, f"{eff.focus_ratio:.0%}")
        lines.append(f"    Focus Ratio: {focus_str}")

        if qual:
            tre_str = _c(ACCENT_COLOR, f"{qual.task_resolution_efficiency:.2f}")
            rework_str = _c(ACCENT_COLOR, f"{qual.rework_rate:.0%}")
            oneshot_str = _c(ACCENT_COLOR, f"{qual.one_shot_success_rate:.0%}")
            lines.append(f"    Task Resolution: {tre_str}  Rework: {rework_str}  One-Shot: {oneshot_str}")

        # Key input metrics
        debug_str = _c(DIM, f"debug_tax={eff.debug_tax:.2f}")
        density_str = _c(DIM, f"msgs/h={eff.interaction_density:.0f}")
        overhead_str = _c(DIM, f"overhead={eff.chat_devops_overhead:.0%}")
        lines.append(f"    {debug_str}  {density_str}  {overhead_str}")

        if qual and qual.debug_loop_max_depth > 0:
            loop_str = _c(DIM, f"debug_loops={qual.debug_loop_max_depth}max/{qual.debug_loop_avg_depth:.1f}avg")
            lines.append(f"    {loop_str}")

        lines.append("")

    return "\n".join(lines)


def print_report(
    blocks: list[ActivityBlock],
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    codegen_stats: CodeGenStats | None = None,
    codegen_by_project: dict[str, CodeGenStats] | None = None,
    efficiency_metrics: dict | None = None,
    quality_metrics: dict | None = None,
    insights: list | None = None,
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

    # Project totals (with PII redaction)
    redactor = ProjectRedactor()
    proj_totals: dict[str, dict[str, int]] = {}
    for b in blocks:
        proj_name = redactor.redact(b.project)
        if proj_name not in proj_totals:
            proj_totals[proj_name] = {}
        p = proj_totals[proj_name]
        p[b.category] = p.get(b.category, 0) + b.duration_seconds

    # Date range
    earliest = min(b.start_time for b in blocks)
    latest = max(b.start_time for b in blocks)

    # Compute half-period totals for trend arrows
    midpoint = earliest + (latest - earliest) / 2
    first_half_secs = sum(b.duration_seconds for b in blocks if b.start_time < midpoint)
    second_half_secs = sum(b.duration_seconds for b in blocks if b.start_time >= midpoint)

    user = os.environ.get("USER", "engineer")
    lines: list[str] = []

    # Header
    lines.append("")
    lines.append(_c(LINE_COLOR, "\u2550" * 50))
    lines.append(f"  {_c(HEADER_COLOR + BOLD, 'Claude Code Analytics')}")
    lines.append(f"  {_c(ACCENT_COLOR, earliest.strftime('%Y-%m-%d'))} ~ {_c(ACCENT_COLOR, latest.strftime('%Y-%m-%d'))}")
    lines.append(f"  Engineer: {_c(HEADER_COLOR, user)}")

    current_streak, longest_streak = compute_streaks(blocks)
    if longest_streak > 0:
        streak_icon = "\U0001f525" if _use_color() else "*"
        lines.append(f"  Streak: {_c(ACCENT_COLOR, f'{current_streak}d')} current  {_c(DIM, f'{longest_streak}d longest')}")

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
    trend = _trend_arrow(second_half_secs, first_half_secs)
    trend_suffix = f" {trend}" if trend else ""
    lines.append(f"  {total_label:<34}  {_c(ACCENT_COLOR, '100%')}  {total_dur:>5}{trend_suffix}")
    lines.append("")

    # Activity heatmap
    heatmap = format_heatmap(blocks)
    if heatmap:
        lines.append(heatmap)

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
            if proj_total == 0:
                continue
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

    # AI Code Generation section (redact project names)
    if codegen_stats and codegen_stats.ai_lines > 0:
        redacted_codegen = redactor.redact_dict(codegen_by_project) if codegen_by_project else None
        lines.append(format_codegen_section(codegen_stats, redacted_codegen))

    # Engineering Efficiency section
    if efficiency_metrics:
        redacted_eff = {redactor.redact(k): v for k, v in efficiency_metrics.items()}
        redacted_qual = {redactor.redact(k): v for k, v in (quality_metrics or {}).items()}
        lines.append(format_efficiency_section(redacted_eff, redacted_qual))

    # Insights section
    if insights:
        from .insights import format_insights
        lines.append(f"  {_c(BOLD, 'Insights')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
        lines.append(format_insights(insights))
        lines.append("")

    return "\n".join(lines)
