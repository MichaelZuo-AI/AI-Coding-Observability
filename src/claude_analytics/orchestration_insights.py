"""Insights engine for orchestration effectiveness metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone, timedelta
from .models import OrchestrationSession

KST = timezone(timedelta(hours=9))


@dataclass
class Insight:
    project: str
    observation: str
    suggestion: str = ""


def generate_orchestration_insights(sessions: list[OrchestrationSession]) -> list[Insight]:
    if not sessions:
        return []

    insights: list[Insight] = []
    total = len(sessions)
    zero_touch = sum(1 for s in sessions if s.steering_count == 0)
    zero_touch_rate = zero_touch / total

    if zero_touch_rate > 0.5:
        insights.append(Insight(
            project="Overall",
            observation=f"{zero_touch_rate:.0%} of sessions needed zero correction.",
            suggestion="Strong intent clarity.",
        ))
    elif zero_touch_rate < 0.2:
        insights.append(Insight(
            project="Overall",
            observation=f"Only {zero_touch_rate:.0%} of sessions needed zero correction.",
            suggestion="Consider investing more time in initial prompts.",
        ))

    proj_sessions: dict[str, list[OrchestrationSession]] = {}
    for s in sessions:
        proj_sessions.setdefault(s.project, []).append(s)

    for proj, proj_list in sorted(proj_sessions.items()):
        if len(proj_list) < 2:
            continue
        avg_steering = sum(s.steering_count for s in proj_list) / len(proj_list)
        avg_precision = sum(s.precision_score for s in proj_list) / len(proj_list)

        if avg_precision < 0.25:
            insights.append(Insight(
                project=proj,
                observation=f"{proj}: Avg {avg_steering:.1f} steerings/session (precision {avg_precision:.2f}).",
                suggestion="Intents for this project may need more context.",
            ))

    no_outcome = sum(1 for s in sessions if not s.has_outcome)
    if no_outcome > 0:
        no_pct = no_outcome / total
        if no_pct > 0.3:
            insights.append(Insight(
                project="Overall",
                observation=f"{no_pct:.0%} of sessions produced no commits.",
                suggestion="Some sessions may have been exploratory or the task too ambiguous.",
            ))

    short_intents = [s for s in sessions if s.intent_length > 0 and s.intent_length < 200]
    long_intents = [s for s in sessions if s.intent_length >= 500]
    if len(short_intents) >= 3 and len(long_intents) >= 3:
        avg_short = sum(s.precision_score for s in short_intents) / len(short_intents)
        avg_long = sum(s.precision_score for s in long_intents) / len(long_intents)
        if avg_long > avg_short + 0.1:
            insights.append(Insight(
                project="Overall",
                observation=f"Longer intents (>500 chars) score {avg_long:.2f} avg vs {avg_short:.2f} for shorter.",
                suggestion="Longer, more detailed prompts correlate with better precision.",
            ))

    heavy_sessions = [s for s in sessions if s.steering_count > 3]
    if heavy_sessions:
        heavy_pct = len(heavy_sessions) / total
        if heavy_pct > 0.1:
            insights.append(Insight(
                project="Overall",
                observation=f"{heavy_pct:.0%} of sessions needed >3 corrections.",
                suggestion="Consider breaking complex tasks into smaller sessions.",
            ))

    return insights


def format_orchestration_insights(insights: list[Insight]) -> str:
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
