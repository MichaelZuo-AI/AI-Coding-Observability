"""Tests for orchestration classification and scoring."""

import pytest
from datetime import datetime, timezone
from claude_analytics.models import Message, Session, OrchestrationSession


def _msg(content: str, role: str = "user", tools: list[str] | None = None, ts: datetime | None = None) -> Message:
    return Message(
        role=role,
        content=content,
        timestamp=ts or datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
        tool_uses=tools or [],
    )


class TestOrchestrationSessionModel:
    def test_default_values(self):
        s = OrchestrationSession(
            session_id="abc",
            project="my-project",
            total_duration=600,
            intent_length=100,
            steering_count=0,
            precision_score=1.0,
            tier="flawless",
            has_outcome=True,
            phase_sequence=["intent", "acknowledgment"],
            message_count=5,
        )
        assert s.precision_score == 1.0
        assert s.tier == "flawless"
        assert s.time_to_first_commit is None

    def test_with_commit_time(self):
        s = OrchestrationSession(
            session_id="abc",
            project="my-project",
            total_duration=600,
            intent_length=100,
            steering_count=2,
            precision_score=0.33,
            tier="guided",
            has_outcome=True,
            phase_sequence=["intent", "steering", "steering", "acknowledgment"],
            message_count=10,
            time_to_first_commit=300,
        )
        assert s.time_to_first_commit == 300
        assert s.steering_count == 2
