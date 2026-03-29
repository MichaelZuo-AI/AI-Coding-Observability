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


from claude_analytics.orchestration import analyze_session, compute_precision_score, session_tier


def _session(messages: list, project: str = "test-project") -> Session:
    return Session(
        session_id="test-session",
        project=project,
        messages=messages,
        start_time=messages[0].timestamp if messages else None,
        end_time=messages[-1].timestamp if messages else None,
        active_seconds=600,
    )


class TestPrecisionScore:
    def test_zero_steerings(self):
        assert compute_precision_score(0) == 1.0

    def test_one_steering(self):
        assert compute_precision_score(1) == pytest.approx(0.5)

    def test_two_steerings(self):
        assert compute_precision_score(2) == pytest.approx(1 / 3)

    def test_five_steerings(self):
        assert compute_precision_score(5) == pytest.approx(1 / 6)


class TestSessionTier:
    def test_flawless(self):
        assert session_tier(1.0) == "flawless"

    def test_clean(self):
        assert session_tier(0.5) == "clean"

    def test_guided(self):
        assert session_tier(0.25) == "guided"

    def test_heavy(self):
        assert session_tier(0.2) == "heavy"

    def test_boundary_clean(self):
        assert session_tier(0.50) == "clean"

    def test_boundary_guided(self):
        assert session_tier(0.25) == "guided"


class TestAnalyzeSession:
    def test_perfect_session_no_steering(self):
        ts = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("Build a login page", ts=ts),
            _msg("Sure, I'll build that.", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 0, 30, tzinfo=timezone.utc)),
            _msg("looks good",
                 ts=datetime(2026, 3, 1, 10, 5, tzinfo=timezone.utc)),
        ]
        result = analyze_session(_session(msgs))
        assert result.precision_score == 1.0
        assert result.tier == "flawless"
        assert result.steering_count == 0
        assert result.phase_sequence == ["intent", "acknowledgment"]

    def test_session_with_steering(self):
        ts = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("Build a login page", ts=ts),
            _msg("Here's the login page.", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 1, tzinfo=timezone.utc)),
            _msg("No, use OAuth instead",
                 ts=datetime(2026, 3, 1, 10, 2, tzinfo=timezone.utc)),
            _msg("Updated with OAuth.", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 3, tzinfo=timezone.utc)),
            _msg("yes",
                 ts=datetime(2026, 3, 1, 10, 4, tzinfo=timezone.utc)),
        ]
        result = analyze_session(_session(msgs))
        assert result.precision_score == pytest.approx(0.5)
        assert result.tier == "clean"
        assert result.steering_count == 1
        assert result.phase_sequence == ["intent", "steering", "acknowledgment"]

    def test_session_with_clarification(self):
        ts = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("Build a dashboard", ts=ts),
            _msg("Which framework do you prefer?", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 1, tzinfo=timezone.utc)),
            _msg("React",
                 ts=datetime(2026, 3, 1, 10, 2, tzinfo=timezone.utc)),
            _msg("Done, here's the React dashboard.", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 5, tzinfo=timezone.utc)),
            _msg("lgtm",
                 ts=datetime(2026, 3, 1, 10, 6, tzinfo=timezone.utc)),
        ]
        result = analyze_session(_session(msgs))
        assert result.precision_score == 1.0
        assert result.steering_count == 0
        assert "clarification" in result.phase_sequence

    def test_intent_length(self):
        ts = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        intent_text = "Build a complete authentication system with OAuth2, JWT tokens, and role-based access control"
        msgs = [
            _msg(intent_text, ts=ts),
            _msg("Done.", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 5, tzinfo=timezone.utc)),
        ]
        result = analyze_session(_session(msgs))
        assert result.intent_length == len(intent_text)

    def test_commit_detection(self):
        ts = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        msgs = [
            _msg("Build a login page", ts=ts),
            _msg("Done.", role="assistant",
                 tools=["Bash"],
                 ts=datetime(2026, 3, 1, 10, 5, tzinfo=timezone.utc)),
            _msg("now commit and push",
                 ts=datetime(2026, 3, 1, 10, 6, tzinfo=timezone.utc)),
            Message(role="assistant", content="Committed and pushed.",
                    timestamp=datetime(2026, 3, 1, 10, 7, tzinfo=timezone.utc),
                    tool_uses=["Bash"]),
        ]
        result = analyze_session(_session(msgs))
        assert result.has_outcome is True

    def test_empty_session(self):
        s = Session(session_id="empty", project="test", messages=[],
                    start_time=None, end_time=None, active_seconds=0)
        result = analyze_session(s)
        assert result.precision_score == 1.0
        assert result.steering_count == 0
        assert result.message_count == 0

    def test_new_intent_after_idle_gap(self):
        msgs = [
            _msg("Build a login page",
                 ts=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)),
            _msg("Done.", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 5, tzinfo=timezone.utc)),
            _msg("Now add a signup page",
                 ts=datetime(2026, 3, 1, 10, 20, tzinfo=timezone.utc)),
            _msg("Done.", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 25, tzinfo=timezone.utc)),
        ]
        result = analyze_session(_session(msgs))
        assert result.phase_sequence.count("intent") == 2
