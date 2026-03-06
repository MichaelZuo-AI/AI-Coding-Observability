"""Phase 4c: Behavioral insights and actionable recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone, timedelta
from .models import ActivityBlock, Session
from .efficiency import EfficiencyMetrics
from .quality import QualityMetrics

# KST timezone
KST = timezone(timedelta(hours=9))


@dataclass
class Insight:
    project: str
    observation: str
    suggestion: str = ""


def generate_insights(
    efficiency: dict[str, EfficiencyMetrics],
    quality: dict[str, QualityMetrics],
    blocks: list[ActivityBlock] | None = None,
    sessions: list[Session] | None = None,
) -> list[Insight]:
    """Generate actionable insights from efficiency and quality metrics."""
    insights: list[Insight] = []

    for project in sorted(set(list(efficiency.keys()) + list(quality.keys()))):
        eff = efficiency.get(project)
        qual = quality.get(project)

        if eff:
            insights.extend(_efficiency_insights(project, eff))
        if qual:
            insights.extend(_quality_insights(project, qual))

    if blocks:
        insights.extend(_peak_hours_insights(blocks))

    return insights


def _efficiency_insights(project: str, eff: EfficiencyMetrics) -> list[Insight]:
    results: list[Insight] = []

    if eff.efficiency_score > 0.7:
        results.append(Insight(
            project=project,
            observation=f"Efficiency score is {eff.efficiency_score:.2f} — strong AI-assisted workflow.",
        ))
    elif eff.efficiency_score < 0.3:
        results.append(Insight(
            project=project,
            observation=f"Efficiency score is {eff.efficiency_score:.2f} — significant room for improvement.",
            suggestion="Focus on reducing iteration cycles and minimizing overhead.",
        ))

    if eff.focus_ratio > 0.85:
        results.append(Insight(
            project=project,
            observation=f"Focus ratio is {eff.focus_ratio:.0%} — highly focused project.",
        ))
    elif eff.focus_ratio < 0.50:
        results.append(Insight(
            project=project,
            observation=f"Only {eff.focus_ratio:.0%} of time on core engineering.",
            suggestion="Consider batching devops/chat tasks.",
        ))

    if eff.debug_tax > 0.3:
        results.append(Insight(
            project=project,
            observation=f"Debug tax is {eff.debug_tax:.2f}h per coding hour.",
            suggestion="Try more detailed prompts or break tasks smaller.",
        ))

    if eff.interaction_density > 25:
        results.append(Insight(
            project=project,
            observation=f"{eff.interaction_density:.0f} messages/hour — potentially micro-managing AI.",
            suggestion="Try longer, more detailed prompts instead of many short ones.",
        ))

    if eff.chat_devops_overhead > 0.4:
        results.append(Insight(
            project=project,
            observation=f"Chat & devops overhead is {eff.chat_devops_overhead:.0%}.",
            suggestion="Reduce process overhead to increase engineering focus.",
        ))

    return results


def _quality_insights(project: str, qual: QualityMetrics) -> list[Insight]:
    results: list[Insight] = []

    if qual.task_resolution_efficiency < 0.4:
        avg_attempts = 1.0 / qual.task_resolution_efficiency if qual.task_resolution_efficiency > 0 else float("inf")
        results.append(Insight(
            project=project,
            observation=f"Average task takes {avg_attempts:.1f} attempts.",
            suggestion="Break complex tasks into smaller, clearer prompts.",
        ))

    if qual.one_shot_success_rate < 0.5:
        results.append(Insight(
            project=project,
            observation=f"One-shot success rate is {qual.one_shot_success_rate:.0%}.",
            suggestion="Consider providing more context in initial prompts.",
        ))

    if qual.debug_loop_max_depth > 5:
        results.append(Insight(
            project=project,
            observation=f"Debug loops reached {qual.debug_loop_max_depth} turns deep.",
            suggestion="Consider stepping back and re-prompting from scratch.",
        ))

    if qual.rework_rate > 0.3:
        results.append(Insight(
            project=project,
            observation=f"{qual.rework_rate:.0%} of files were reworked within the same session.",
            suggestion="Spend more time on the initial prompt specification.",
        ))

    if qual.context_switch_frequency > 3:
        results.append(Insight(
            project=project,
            observation=f"{qual.context_switch_frequency:.1f} project switches per session.",
            suggestion="Batch work by project to reduce context switching.",
        ))

    return results


def _peak_hours_insights(blocks: list[ActivityBlock]) -> list[Insight]:
    """Identify peak productivity hours from activity blocks."""
    if not blocks:
        return []

    core_cats = {"coding", "design", "debug"}
    hour_core: dict[int, int] = {}
    hour_total: dict[int, int] = {}

    for block in blocks:
        try:
            hour = block.start_time.astimezone(KST).hour
        except (ValueError, OSError):
            hour = block.start_time.hour
        hour_total[hour] = hour_total.get(hour, 0) + block.duration_seconds
        if block.category in core_cats:
            hour_core[hour] = hour_core.get(hour, 0) + block.duration_seconds

    if not hour_total:
        return []

    # Compute focus ratio per hour
    hour_focus: dict[int, float] = {}
    for h in hour_total:
        if hour_total[h] > 0:
            hour_focus[h] = hour_core.get(h, 0) / hour_total[h]

    if not hour_focus:
        return []

    # Find top productive hours
    sorted_hours = sorted(hour_focus.items(), key=lambda x: x[1], reverse=True)
    top_hours = [h for h, f in sorted_hours[:3] if f > 0.5]

    if top_hours:
        top_hours.sort()
        hour_strs = [f"{h}:00" for h in top_hours]
        return [Insight(
            project="Overall",
            observation=f"Peak productivity hours (KST): {', '.join(hour_strs)}.",
            suggestion="Schedule deep work during these hours.",
        )]

    return []


def format_insights(insights: list[Insight]) -> str:
    """Format insights for CLI output."""
    if not insights:
        return "  No insights generated — not enough data."

    lines: list[str] = []
    current_project = ""

    for insight in insights:
        if insight.project != current_project:
            if current_project:
                lines.append("")
            current_project = insight.project
            lines.append(f"  [{current_project}]")

        lines.append(f"    * {insight.observation}")
        if insight.suggestion:
            lines.append(f"      -> {insight.suggestion}")

    return "\n".join(lines)
