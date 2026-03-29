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


from claude_analytics.orchestration import classify_orchestration_role


class TestClassifyOrchestrationRole:
    def test_first_message_is_intent(self):
        msg = _msg("Build a login page with OAuth")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=True, after_idle=False)
        assert result == "intent"

    def test_after_idle_gap_is_intent(self):
        msg = _msg("Now implement the dashboard")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=True)
        assert result == "intent"

    def test_negation_is_steering(self):
        msg = _msg("No, use Postgres not SQLite")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "steering"

    def test_correction_is_steering(self):
        msg = _msg("That's wrong, the API endpoint should be /api/v2")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "steering"

    def test_redirect_is_steering(self):
        msg = _msg("Actually, switch to using Redis instead")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "steering"

    def test_revert_is_steering(self):
        msg = _msg("Revert that change")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "steering"

    def test_undo_is_steering(self):
        msg = _msg("undo")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "steering"

    def test_dont_is_steering(self):
        msg = _msg("don't add error handling there")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "steering"

    def test_instead_is_steering(self):
        msg = _msg("instead use a map")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "steering"

    def test_start_over_is_steering(self):
        msg = _msg("start over with a different approach")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "steering"

    def test_response_to_question_is_clarification(self):
        prev = _msg("Should I use TypeScript or JavaScript for this?", role="assistant")
        msg = _msg("TypeScript please")
        result = classify_orchestration_role(msg, prev_assistant=prev, is_first=False, after_idle=False)
        assert result == "clarification"

    def test_response_to_question_mark_is_clarification(self):
        prev = _msg("Which database do you prefer?", role="assistant")
        msg = _msg("Postgres")
        result = classify_orchestration_role(msg, prev_assistant=prev, is_first=False, after_idle=False)
        assert result == "clarification"

    def test_yes_is_acknowledgment(self):
        msg = _msg("yes")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "acknowledgment"

    def test_looks_good_is_acknowledgment(self):
        msg = _msg("looks good")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "acknowledgment"

    def test_go_ahead_is_acknowledgment(self):
        msg = _msg("go ahead")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "acknowledgment"

    def test_continue_is_acknowledgment(self):
        msg = _msg("continue")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "acknowledgment"

    def test_lgtm_is_acknowledgment(self):
        msg = _msg("lgtm")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=False)
        assert result == "acknowledgment"

    def test_first_message_always_intent_even_if_steering_words(self):
        msg = _msg("No, start over and build it differently")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=True, after_idle=False)
        assert result == "intent"

    def test_steering_wins_over_clarification_when_no_question(self):
        prev = _msg("I've completed the implementation.", role="assistant")
        msg = _msg("No that's wrong, revert it")
        result = classify_orchestration_role(msg, prev_assistant=prev, is_first=False, after_idle=False)
        assert result == "steering"
