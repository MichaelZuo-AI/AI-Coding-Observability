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


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------


def _html_escape(s: str) -> str:
    """Escape HTML special characters."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def render_html_report(
    orchestration_sessions: list[OrchestrationSession],
    blocks: list[ActivityBlock],
    codegen_stats: CodeGenStats | None = None,
    insights: list | None = None,
) -> str:
    """Generate a self-contained HTML report with Neon Gradient design."""
    import json as _json

    if not orchestration_sessions:
        return "<html><body><p>No orchestration sessions found.</p></body></html>"

    redactor = ProjectRedactor()

    # --- Compute data ---
    total_sessions = len(orchestration_sessions)
    avg_precision = sum(s.precision_score for s in orchestration_sessions) / total_sessions
    zero_touch = sum(1 for s in orchestration_sessions if s.steering_count == 0)
    zero_touch_rate = zero_touch / total_sessions

    # Tier label (no ANSI)
    def _tier_name(score: float) -> str:
        for threshold, label, _ in PRECISION_TIERS:
            if score >= threshold:
                return label
        return "Heavy"

    tier_label = _tier_name(avg_precision)

    # Date range
    earliest = min(b.start_time for b in blocks) if blocks else None
    latest = max(b.start_time for b in blocks) if blocks else None
    date_range_str = ""
    if earliest and latest:
        date_range_str = f"{earliest.strftime('%Y-%m-%d')} ~ {latest.strftime('%Y-%m-%d')}"

    user = os.environ.get("USER", "engineer")

    # Streaks
    current_streak, longest_streak = compute_streaks(blocks)

    # Tier counts
    tier_counts: dict[str, int] = {"flawless": 0, "clean": 0, "guided": 0, "heavy": 0}
    for s in orchestration_sessions:
        tier_counts[s.tier] = tier_counts.get(s.tier, 0) + 1

    tier_total = sum(tier_counts.values())

    # Project data
    proj_sessions: dict[str, list[OrchestrationSession]] = {}
    for s in orchestration_sessions:
        proj_name = redactor.redact(s.project)
        proj_sessions.setdefault(proj_name, []).append(s)

    sorted_projects = sorted(
        proj_sessions.items(),
        key=lambda x: sum(s.precision_score for s in x[1]) / len(x[1]),
        reverse=True,
    )

    # --- Heatmap data ---
    heatmap_json = "[]"
    if blocks:
        daily: dict = defaultdict(int)
        for b in blocks:
            daily[b.start_time.date()] += b.duration_seconds

        if daily:
            min_date = min(daily.keys())
            max_date = max(daily.keys())
            start = min_date - timedelta(days=min_date.weekday())
            end = max_date + timedelta(days=6 - max_date.weekday())
            total_days = (end - start).days + 1
            max_weeks = 20
            total_weeks = total_days // 7
            if total_weeks > max_weeks:
                start = end - timedelta(days=max_weeks * 7 - 1)
                start = start - timedelta(days=start.weekday())

            values = [v for v in daily.values() if v > 0]
            if values:
                sorted_vals = sorted(values)
                p33 = sorted_vals[len(sorted_vals) // 3]
                p66 = sorted_vals[2 * len(sorted_vals) // 3]
            else:
                p33 = p66 = 0

            heatmap_cells = []
            day = start
            while day <= end:
                secs = daily.get(day, 0)
                if secs <= 0:
                    level = 0
                elif secs <= p33:
                    level = 1
                elif secs <= p66:
                    level = 2
                else:
                    level = 3
                heatmap_cells.append({
                    "date": day.strftime("%b %d"),
                    "dow": day.weekday(),
                    "week": (day - start).days // 7,
                    "secs": secs,
                    "level": level,
                    "label": format_duration(secs) if secs > 0 else "none",
                })
                day += timedelta(days=1)

            heatmap_json = _json.dumps(heatmap_cells)

    # --- Projects table JSON ---
    projects_data = []
    for proj_name, sessions in sorted_projects[:20]:
        avg = sum(s.precision_score for s in sessions) / len(sessions)
        t = _tier_name(avg)
        projects_data.append({
            "name": proj_name,
            "precision": round(avg, 2),
            "tier": t,
            "sessions": len(sessions),
        })
    projects_json = _json.dumps(projects_data)

    # --- Codegen data ---
    has_codegen = bool(
        codegen_stats and (codegen_stats.ai_commits > 0 or codegen_stats.ai_lines > 0)
    )
    cg_commits_ai = codegen_stats.ai_commits if has_codegen else 0
    cg_commits_total = codegen_stats.total_commits if has_codegen else 0
    cg_files = len(codegen_stats.files_touched) if has_codegen else 0
    cg_lines_ai = codegen_stats.ai_lines if has_codegen else 0
    cg_lines_total = codegen_stats.total_lines if has_codegen else 0

    # --- Insights HTML ---
    insights_html = ""
    if insights:
        grouped: dict[str, list] = {}
        for ins in insights:
            proj = redactor.redact(getattr(ins, "project", "General"))
            grouped.setdefault(proj, []).append(ins)

        parts = []
        for proj, items in grouped.items():
            for i, ins in enumerate(items):
                obs = getattr(ins, "observation", str(ins))
                sug = getattr(ins, "suggestion", "")
                sug_html = (
                    f'<p class="insight-suggestion">{_html_escape(sug)}</p>'
                    if sug else ""
                )
                parts.append(
                    f'<div class="insight-card">'
                    f'<div class="insight-header" onclick="this.parentElement.classList.toggle(\'open\')">'
                    f'<span class="insight-project">{_html_escape(proj)}</span>'
                    f'<span class="insight-toggle">+</span>'
                    f'</div>'
                    f'<div class="insight-body">'
                    f'<p class="insight-obs">{_html_escape(obs)}</p>'
                    f'{sug_html}'
                    f'</div></div>'
                )
        insights_html = "\n".join(parts)

    # --- Tier bar segments ---
    tier_colors_html = {
        "flawless": "#00d2ff", "clean": "#00ff88",
        "guided": "#ffd700", "heavy": "#ff4757",
    }
    tier_bar_segments = []
    for t_name in ["flawless", "clean", "guided", "heavy"]:
        count = tier_counts[t_name]
        pct = (count / tier_total * 100) if tier_total > 0 else 0
        if pct > 0:
            tier_bar_segments.append(
                f'<div class="tier-seg" style="width:{pct:.1f}%;'
                f'background:{tier_colors_html[t_name]}" '
                f'title="{t_name.capitalize()}: {count} ({pct:.0f}%)"></div>'
            )

    tier_bar_html = "\n".join(tier_bar_segments)

    # --- Codegen section ---
    codegen_section = ""
    if has_codegen:
        codegen_section = f"""
<div class="section-title">Agent Throughput</div>
<div class="codegen-stats">
  <div class="cg-stat"><div class="val">{cg_commits_ai}/{cg_commits_total}</div><div class="desc">Commits (AI/total)</div></div>
  <div class="cg-stat"><div class="val">{cg_files}</div><div class="desc">Files touched</div></div>
  <div class="cg-stat"><div class="val">{cg_lines_ai:,}/{cg_lines_total:,}</div><div class="desc">Lines (AI/total)</div></div>
</div>"""

    # --- Insights section ---
    insights_section = ""
    if insights_html:
        insights_section = f"""
<div class="section-title">Insights</div>
{insights_html}"""

    # --- Streak badge ---
    streak_badge = ""
    if longest_streak > 0:
        streak_badge = (
            f'<div class="badge">&#x1F525; {current_streak}d current / '
            f'{longest_streak}d longest</div>'
        )

    # --- Build full HTML ---
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code Analytics</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  background:linear-gradient(135deg,#1a1a2e,#16213e);
  color:#e0e0e0;
  font-family:system-ui,-apple-system,sans-serif;
  min-height:100vh;
  padding:2rem;
}}
.container{{max-width:1100px;margin:0 auto}}
h1{{
  font-size:2.2rem;font-weight:800;
  background:linear-gradient(135deg,#00d2ff,#7b2ff7);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;
  margin-bottom:0.3rem;
}}
.subtitle{{color:#888;font-size:0.95rem;margin-bottom:0.15rem}}
.badge{{
  display:inline-block;background:rgba(255,215,0,0.15);
  color:#ffd700;border:1px solid rgba(255,215,0,0.3);
  border-radius:20px;padding:0.2rem 0.8rem;font-size:0.85rem;margin-top:0.4rem;
}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem;margin:1.8rem 0}}
.card{{
  background:rgba(255,255,255,0.04);
  border-radius:12px;padding:1.5rem;text-align:center;
  border:1px solid rgba(0,210,255,0.15);
  box-shadow:0 0 20px rgba(0,210,255,0.05);
  transition:box-shadow 0.3s;
}}
.card:hover{{box-shadow:0 0 30px rgba(0,210,255,0.15)}}
.card .num{{font-size:2.5rem;font-weight:800;color:#00d2ff;line-height:1.1}}
.card .label{{font-size:0.85rem;color:#888;margin-top:0.4rem}}
.card .sublabel{{font-size:0.75rem;color:#666;margin-top:0.2rem}}
.card:nth-child(2) .num{{color:#00ff88}}
.card:nth-child(3) .num{{color:#7b2ff7}}
.section-title{{font-size:1.1rem;font-weight:700;color:#ccc;margin:1.8rem 0 0.8rem}}
.tier-bar{{display:flex;height:28px;border-radius:8px;overflow:hidden;margin-bottom:0.5rem}}
.tier-seg{{transition:opacity 0.2s;cursor:default;min-width:2px}}
.tier-seg:hover{{opacity:0.8}}
.tier-legend{{display:flex;gap:1.2rem;flex-wrap:wrap;margin-bottom:1.5rem}}
.tier-legend span{{font-size:0.8rem;color:#aaa;display:flex;align-items:center;gap:0.3rem}}
.tier-legend .dot{{width:10px;height:10px;border-radius:3px;display:inline-block}}
.heatmap-wrap{{overflow-x:auto;margin:0.5rem 0 1.5rem}}
.heatmap{{display:inline-grid;grid-template-rows:repeat(7,1fr);grid-auto-flow:column;gap:3px}}
.hm-cell{{width:14px;height:14px;border-radius:3px;cursor:default;transition:transform 0.15s}}
.hm-cell:hover{{transform:scale(1.4)}}
.hm-0{{background:#1a1a2e}}
.hm-1{{background:#0e4429}}
.hm-2{{background:#006d32}}
.hm-3{{background:#00ff88}}
.day-labels{{display:inline-grid;grid-template-rows:repeat(7,1fr);gap:3px;margin-right:6px;vertical-align:top}}
.day-labels span{{font-size:0.7rem;color:#666;height:14px;line-height:14px}}
.proj-table{{width:100%;border-collapse:collapse;margin:0.5rem 0 1.5rem}}
.proj-table th{{
  text-align:left;padding:0.6rem 0.8rem;color:#888;font-size:0.8rem;
  border-bottom:1px solid rgba(255,255,255,0.08);cursor:pointer;user-select:none;
}}
.proj-table th:hover{{color:#00d2ff}}
.proj-table td{{padding:0.5rem 0.8rem;font-size:0.9rem;border-bottom:1px solid rgba(255,255,255,0.04)}}
.proj-table tr{{transition:background 0.2s}}
.proj-table tr:hover{{background:rgba(255,255,255,0.03)}}
.tier-border{{border-left:3px solid;padding-left:0.8rem}}
.codegen-stats{{display:flex;gap:2rem;flex-wrap:wrap;margin:0.5rem 0 1.5rem}}
.cg-stat .val{{font-size:1.6rem;font-weight:800;color:#00d2ff}}
.cg-stat .desc{{font-size:0.8rem;color:#888}}
.insight-card{{
  background:rgba(255,255,255,0.03);border-radius:8px;margin-bottom:0.6rem;
  border:1px solid rgba(123,47,247,0.15);overflow:hidden;
}}
.insight-header{{
  padding:0.7rem 1rem;cursor:pointer;display:flex;justify-content:space-between;align-items:center;
}}
.insight-header:hover{{background:rgba(255,255,255,0.03)}}
.insight-project{{font-size:0.85rem;color:#7b2ff7;font-weight:600}}
.insight-toggle{{color:#666;font-size:1.1rem;transition:transform 0.2s}}
.insight-card.open .insight-toggle{{transform:rotate(45deg)}}
.insight-body{{display:none;padding:0 1rem 0.8rem}}
.insight-card.open .insight-body{{display:block}}
.insight-obs{{font-size:0.9rem;color:#ccc}}
.insight-suggestion{{font-size:0.85rem;color:#00ff88;margin-top:0.3rem}}
.tooltip{{
  position:fixed;background:rgba(0,0,0,0.9);color:#fff;padding:0.3rem 0.6rem;
  border-radius:6px;font-size:0.8rem;pointer-events:none;display:none;z-index:99;
  border:1px solid rgba(0,210,255,0.3);
}}
@media(max-width:900px){{
  .cards{{grid-template-columns:1fr}}
  body{{padding:1rem}}
}}
</style>
</head>
<body>
<div class="container">

<h1>Claude Code Analytics</h1>
<div class="subtitle">{_html_escape(date_range_str)}</div>
<div class="subtitle">Engineer: {_html_escape(user)}</div>
{streak_badge}

<div class="cards">
  <div class="card">
    <div class="num" data-count="{avg_precision:.2f}">{avg_precision:.2f}</div>
    <div class="label">Precision Score</div>
    <div class="sublabel">{_html_escape(tier_label)}</div>
  </div>
  <div class="card">
    <div class="num" data-count="{zero_touch_rate * 100:.0f}">{zero_touch_rate * 100:.0f}%</div>
    <div class="label">Zero-Touch Rate</div>
    <div class="sublabel">{zero_touch}/{total_sessions} sessions</div>
  </div>
  <div class="card">
    <div class="num" data-count="{total_sessions}">{total_sessions}</div>
    <div class="label">Sessions</div>
    <div class="sublabel">total analyzed</div>
  </div>
</div>

<div class="section-title">Session Breakdown</div>
<div class="tier-bar">
{tier_bar_html}
</div>
<div class="tier-legend">
  <span><span class="dot" style="background:#00d2ff"></span>Flawless {tier_counts['flawless']}</span>
  <span><span class="dot" style="background:#00ff88"></span>Clean {tier_counts['clean']}</span>
  <span><span class="dot" style="background:#ffd700"></span>Guided {tier_counts['guided']}</span>
  <span><span class="dot" style="background:#ff4757"></span>Heavy {tier_counts['heavy']}</span>
</div>

<div class="section-title">Activity Heatmap</div>
<div class="heatmap-wrap">
  <div style="display:inline-flex">
    <div class="day-labels">
      <span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span><span>Su</span>
    </div>
    <div class="heatmap" id="heatmap"></div>
  </div>
</div>

<div class="section-title">Projects by Precision</div>
<table class="proj-table" id="proj-table">
<thead><tr>
  <th data-col="name">Project</th>
  <th data-col="precision">Precision</th>
  <th data-col="tier">Tier</th>
  <th data-col="sessions">Sessions</th>
</tr></thead>
<tbody id="proj-tbody"></tbody>
</table>

{codegen_section}
{insights_section}

</div>

<div class="tooltip" id="tooltip"></div>

<script>
(function(){{
  var cells={heatmap_json};
  var grid=document.getElementById("heatmap");
  if(!cells.length) return;
  var tip=document.getElementById("tooltip");
  cells.forEach(function(c){{
    var el=document.createElement("div");
    el.className="hm-cell hm-"+c.level;
    el.setAttribute("data-tip",c.date+" \\u2014 "+c.label);
    el.addEventListener("mouseenter",function(e){{
      tip.textContent=this.getAttribute("data-tip");
      tip.style.display="block";
      tip.style.left=(e.clientX+10)+"px";
      tip.style.top=(e.clientY-30)+"px";
    }});
    el.addEventListener("mousemove",function(e){{
      tip.style.left=(e.clientX+10)+"px";
      tip.style.top=(e.clientY-30)+"px";
    }});
    el.addEventListener("mouseleave",function(){{tip.style.display="none"}});
    grid.appendChild(el);
  }});
}})();

(function(){{
  var data={projects_json};
  var tierColors={{"Flawless":"#00d2ff","Clean":"#00ff88","Guided":"#ffd700","Heavy":"#ff4757"}};
  var tbody=document.getElementById("proj-tbody");
  var sortCol="precision",sortAsc=false;
  function render(){{
    tbody.innerHTML="";
    var sorted=data.slice().sort(function(a,b){{
      var va=a[sortCol],vb=b[sortCol];
      if(typeof va==="string"){{va=va.toLowerCase();vb=vb.toLowerCase()}}
      if(va<vb)return sortAsc?-1:1;
      if(va>vb)return sortAsc?1:-1;
      return 0;
    }});
    sorted.forEach(function(p){{
      var tr=document.createElement("tr");
      var c=tierColors[p.tier]||"#888";
      tr.innerHTML='<td class="tier-border" style="border-left-color:'+c+'">'+p.name+'</td>'
        +'<td style="font-weight:700;color:'+c+'">'+p.precision.toFixed(2)+'</td>'
        +'<td style="color:'+c+'">'+p.tier+'</td>'
        +'<td>'+p.sessions+'</td>';
      tbody.appendChild(tr);
    }});
  }}
  document.querySelectorAll("#proj-table th").forEach(function(th){{
    th.addEventListener("click",function(){{
      var col=this.getAttribute("data-col");
      if(sortCol===col)sortAsc=!sortAsc;
      else{{sortCol=col;sortAsc=true}}
      render();
    }});
  }});
  render();
}})();

(function(){{
  document.querySelectorAll(".card .num").forEach(function(el){{
    var final=el.textContent;
    var isPercent=final.indexOf("%")>=0;
    var target=parseFloat(final);
    if(isNaN(target))return;
    var isFloat=final.indexOf(".")>=0&&!isPercent;
    var duration=800,start=performance.now();
    function step(now){{
      var t=Math.min((now-start)/duration,1);
      t=t<0.5?2*t*t:(1-Math.pow(-2*t+2,2)/2);
      var v=t*target;
      el.textContent=isFloat?v.toFixed(2):Math.round(v)+(isPercent?"%":"");
      if(t<1)requestAnimationFrame(step);
      else el.textContent=final;
    }}
    el.textContent=isFloat?"0.00":"0"+(isPercent?"%":"");
    requestAnimationFrame(step);
  }});
}})();
</script>
</body>
</html>"""

    return html
