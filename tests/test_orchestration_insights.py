"""Tests for orchestration insights engine."""

import pytest
from claude_analytics.models import OrchestrationSession
from claude_analytics.orchestration_insights import generate_orchestration_insights, Insight


def _orch(
    project: str = "test",
    steering_count: int = 0,
    precision_score: float = 1.0,
    tier: str = "flawless",
    has_outcome: bool = True,
    intent_length: int = 100,
    total_duration: int = 600,
) -> OrchestrationSession:
    return OrchestrationSession(
        session_id="s1",
        project=project,
        total_duration=total_duration,
        intent_length=intent_length,
        steering_count=steering_count,
        precision_score=precision_score,
        tier=tier,
        has_outcome=has_outcome,
        phase_sequence=["intent"] + ["steering"] * steering_count + ["acknowledgment"],
        message_count=2 + steering_count,
    )


class TestGenerateInsights:
    def test_high_zero_touch_rate(self):
        sessions = [_orch() for _ in range(6)] + [_orch(steering_count=1, precision_score=0.5, tier="clean") for _ in range(4)]
        insights = generate_orchestration_insights(sessions)
        obs = [i.observation for i in insights]
        assert any("zero correction" in o.lower() or "zero-touch" in o.lower() for o in obs)

    def test_underspecified_project(self):
        sessions = [_orch(project="bad-proj", steering_count=5, precision_score=0.17, tier="heavy") for _ in range(5)]
        insights = generate_orchestration_insights(sessions)
        obs = [i.observation for i in insights]
        assert any("bad-proj" in o for o in obs)

    def test_no_outcome_sessions(self):
        sessions = [_orch(has_outcome=False) for _ in range(3)]
        insights = generate_orchestration_insights(sessions)
        obs = [i.observation for i in insights]
        assert any("no commits" in o.lower() or "no outcome" in o.lower() for o in obs)

    def test_intent_length_correlation(self):
        short = [_orch(intent_length=50, steering_count=3, precision_score=0.25, tier="guided") for _ in range(5)]
        long = [_orch(intent_length=600, steering_count=0, precision_score=1.0, tier="flawless") for _ in range(5)]
        insights = generate_orchestration_insights(short + long)
        obs = [i.observation for i in insights]
        assert any("longer" in o.lower() or "prompt" in o.lower() for o in obs)

    def test_empty_sessions(self):
        insights = generate_orchestration_insights([])
        assert insights == []

    def test_format_insights(self):
        from claude_analytics.orchestration_insights import format_orchestration_insights
        insights = [
            Insight(project="Overall", observation="60% zero-touch rate", suggestion="Strong intent clarity."),
            Insight(project="my-proj", observation="Avg 4.3 steerings/session", suggestion="Intents may need more context."),
        ]
        output = format_orchestration_insights(insights)
        assert "Overall" in output
        assert "my-proj" in output
        assert "60%" in output
