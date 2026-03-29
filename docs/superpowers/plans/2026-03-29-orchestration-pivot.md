# Orchestration Effectiveness Pivot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "human codes with AI help" metrics with an orchestration precision model that measures how effectively the engineer directs AI agents.

**Architecture:** New `orchestration.py` module classifies each user message as intent/steering/acknowledgment/clarification, computes a per-session precision score, and feeds a rewritten reporter. Old classifier, efficiency, quality, and insights modules are removed.

**Tech Stack:** Python 3.11+, pytest, no new dependencies

---

### File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/claude_analytics/models.py` | Modify | Add `OrchestrationSession` dataclass |
| `src/claude_analytics/orchestration.py` | Create | Message role classification + precision scoring + session analysis |
| `src/claude_analytics/orchestration_insights.py` | Create | Insights engine based on orchestration patterns |
| `src/claude_analytics/reporter.py` | Rewrite | New report format: precision, tiers, throughput |
| `src/claude_analytics/main.py` | Modify | Wire new pipeline, remove old imports |
| `src/claude_analytics/classifier.py` | Delete | Replaced by orchestration.py |
| `src/claude_analytics/efficiency.py` | Delete | Replaced by orchestration.py |
| `src/claude_analytics/quality.py` | Delete | Replaced by orchestration.py |
| `src/claude_analytics/insights.py` | Delete | Replaced by orchestration_insights.py |
| `src/claude_analytics/llm_classifier.py` | Delete | No longer needed |
| `tests/test_orchestration.py` | Create | Tests for new classifier + scoring |
| `tests/test_orchestration_insights.py` | Create | Tests for new insights engine |
| `tests/test_reporter.py` | Rewrite | Tests for new report format |
| `tests/test_main.py` | Modify | Update for new pipeline |
| Old test files | Delete | test_classifier.py, test_classifier_extra.py, test_efficiency.py, test_quality.py, test_insights.py, test_llm_classifier.py, test_confidence.py |

---

### Task 1: Add OrchestrationSession model

**Files:**
- Modify: `src/claude_analytics/models.py`
- Test: `tests/test_orchestration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestration.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_orchestration.py::TestOrchestrationSessionModel -v`
Expected: FAIL with `ImportError: cannot import name 'OrchestrationSession'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/claude_analytics/models.py` after the `ActivityBlock` class:

```python
@dataclass
class OrchestrationSession:
    session_id: str
    project: str
    total_duration: int  # wall-clock seconds
    intent_length: int  # chars in initial prompt
    steering_count: int
    precision_score: float  # 1 / (1 + steering_count)
    tier: str  # "flawless" | "clean" | "guided" | "heavy"
    has_outcome: bool  # did session produce commits?
    phase_sequence: list[str] = field(default_factory=list)
    message_count: int = 0
    time_to_first_commit: int | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_orchestration.py::TestOrchestrationSessionModel -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_analytics/models.py tests/test_orchestration.py
git commit -m "feat: add OrchestrationSession model"
```

---

### Task 2: Implement orchestration role classifier

**Files:**
- Create: `src/claude_analytics/orchestration.py`
- Test: `tests/test_orchestration.py`

- [ ] **Step 1: Write failing tests for role classification**

Append to `tests/test_orchestration.py`:

```python
from claude_analytics.orchestration import classify_orchestration_role, IDLE_THRESHOLD_SECONDS


class TestClassifyOrchestrationRole:
    """Test the 4-role classification: intent, steering, clarification, acknowledgment."""

    # --- intent detection (first message or after idle gap) ---

    def test_first_message_is_intent(self):
        msg = _msg("Build a login page with OAuth")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=True, after_idle=False)
        assert result == "intent"

    def test_after_idle_gap_is_intent(self):
        msg = _msg("Now implement the dashboard")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=False, after_idle=True)
        assert result == "intent"

    # --- steering detection ---

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

    # --- clarification detection ---

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

    # --- acknowledgment (default) ---

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

    # --- priority: intent > clarification > steering > ack ---

    def test_first_message_always_intent_even_if_steering_words(self):
        msg = _msg("No, start over and build it differently")
        result = classify_orchestration_role(msg, prev_assistant=None, is_first=True, after_idle=False)
        assert result == "intent"

    def test_steering_wins_over_clarification_when_no_question(self):
        prev = _msg("I've completed the implementation.", role="assistant")
        msg = _msg("No that's wrong, revert it")
        result = classify_orchestration_role(msg, prev_assistant=prev, is_first=False, after_idle=False)
        assert result == "steering"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_orchestration.py::TestClassifyOrchestrationRole -v`
Expected: FAIL with `ImportError: cannot import name 'classify_orchestration_role'`

- [ ] **Step 3: Write the orchestration classifier**

Create `src/claude_analytics/orchestration.py`:

```python
"""Orchestration effectiveness classification and scoring.

Classifies each user message into one of 4 roles:
- intent: initial prompt or first message after idle gap
- steering: correction, rejection, or redirect
- clarification: answering AI's question
- acknowledgment: approval or continuation (default)
"""

from __future__ import annotations

import re
from .models import Message

IDLE_THRESHOLD_SECONDS = 600  # 10 minutes

# Steering patterns — negation, correction, rejection, redirect
STEERING_PATTERNS = [
    re.compile(r"\b(no|nope|wrong|incorrect|that's not)\b", re.I),
    re.compile(r"\b(don'?t|do not|stop|cancel)\b", re.I),
    re.compile(r"\b(revert|undo|go back|roll back)\b", re.I),
    re.compile(r"\b(instead|actually|rather)\b", re.I),
    re.compile(r"\b(change it to|switch to|use .+ (instead|not))\b", re.I),
    re.compile(r"\b(should be|I meant|not what I)\b", re.I),
    re.compile(r"\b(start over|try again|redo)\b", re.I),
    re.compile(r"\b(that's wrong|this is wrong)\b", re.I),
]


def _is_question(message: Message) -> bool:
    """Check if an assistant message contains a question."""
    return "?" in message.content


def _matches_steering(text: str) -> bool:
    """Check if text matches any steering pattern."""
    for pattern in STEERING_PATTERNS:
        if pattern.search(text):
            return True
    return False


def classify_orchestration_role(
    msg: Message,
    prev_assistant: Message | None,
    is_first: bool,
    after_idle: bool,
) -> str:
    """Classify a user message into an orchestration role.

    Priority order:
    1. intent — first message or after idle gap
    2. clarification — answering AI's question (prev assistant has ?)
    3. steering — correction/rejection patterns
    4. acknowledgment — default
    """
    # Priority 1: position-based intent
    if is_first or after_idle:
        return "intent"

    # Priority 2: clarification (AI asked a question, user responds)
    if prev_assistant and _is_question(prev_assistant) and not _matches_steering(msg.content):
        return "clarification"

    # Priority 3: steering patterns
    if _matches_steering(msg.content):
        return "steering"

    # Priority 4: default
    return "acknowledgment"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_orchestration.py::TestClassifyOrchestrationRole -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_analytics/orchestration.py tests/test_orchestration.py
git commit -m "feat: add orchestration role classifier"
```

---

### Task 3: Implement session analysis and precision scoring

**Files:**
- Modify: `src/claude_analytics/orchestration.py`
- Test: `tests/test_orchestration.py`

- [ ] **Step 1: Write failing tests for session analysis**

Append to `tests/test_orchestration.py`:

```python
from claude_analytics.orchestration import analyze_session, compute_precision_score, session_tier
from claude_analytics.models import Session, OrchestrationSession


def _session(messages: list[Message], project: str = "test-project") -> Session:
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
        assert result.precision_score == 1.0  # clarification is NOT steering
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
        # has_outcome detected from "commit" keyword in user message
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
            # 15 min gap — new intent
            _msg("Now add a signup page",
                 ts=datetime(2026, 3, 1, 10, 20, tzinfo=timezone.utc)),
            _msg("Done.", role="assistant",
                 ts=datetime(2026, 3, 1, 10, 25, tzinfo=timezone.utc)),
        ]
        result = analyze_session(_session(msgs))
        assert result.phase_sequence.count("intent") == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_orchestration.py::TestPrecisionScore tests/test_orchestration.py::TestSessionTier tests/test_orchestration.py::TestAnalyzeSession -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement session analysis**

Append to `src/claude_analytics/orchestration.py`:

```python
from .models import Session, OrchestrationSession

# Commit indicators in user messages or tool uses
COMMIT_PATTERNS = [
    re.compile(r"\b(commit|push|ship|merge|deploy)\b", re.I),
]


def compute_precision_score(steering_count: int) -> float:
    """Compute precision score: 1 / (1 + steering_count)."""
    return 1.0 / (1 + steering_count)


def session_tier(score: float) -> str:
    """Map precision score to a named tier."""
    if score >= 1.0:
        return "flawless"
    if score >= 0.50:
        return "clean"
    if score >= 0.25:
        return "guided"
    return "heavy"


def _detect_outcome(messages: list[Message]) -> tuple[bool, int | None]:
    """Detect if the session produced commits. Returns (has_outcome, time_to_first_commit)."""
    if not messages:
        return False, None

    start = messages[0].timestamp
    for msg in messages:
        text = msg.content if msg.content else ""
        for pattern in COMMIT_PATTERNS:
            if pattern.search(text):
                delta = (msg.timestamp - start).total_seconds()
                return True, int(delta)
        # Also check if assistant used Bash with commit-like context
        if msg.role == "assistant" and "Bash" in msg.tool_uses:
            for pattern in COMMIT_PATTERNS:
                if pattern.search(text):
                    delta = (msg.timestamp - start).total_seconds()
                    return True, int(delta)
    return False, None


def analyze_session(session: Session) -> OrchestrationSession:
    """Analyze a session and produce orchestration metrics."""
    if not session.messages:
        return OrchestrationSession(
            session_id=session.session_id,
            project=session.project,
            total_duration=0,
            intent_length=0,
            steering_count=0,
            precision_score=1.0,
            tier="flawless",
            has_outcome=False,
            phase_sequence=[],
            message_count=0,
        )

    user_messages = [(i, m) for i, m in enumerate(session.messages) if m.role == "user"]
    if not user_messages:
        return OrchestrationSession(
            session_id=session.session_id,
            project=session.project,
            total_duration=0,
            intent_length=0,
            steering_count=0,
            precision_score=1.0,
            tier="flawless",
            has_outcome=False,
            phase_sequence=[],
            message_count=len(session.messages),
        )

    phase_sequence: list[str] = []
    steering_count = 0
    intent_length = 0

    for idx, (msg_index, msg) in enumerate(user_messages):
        is_first = idx == 0

        # Check for idle gap from previous message
        after_idle = False
        if msg_index > 0:
            prev_msg = session.messages[msg_index - 1]
            gap = (msg.timestamp - prev_msg.timestamp).total_seconds()
            after_idle = gap >= IDLE_THRESHOLD_SECONDS

        # Find preceding assistant message
        prev_assistant = None
        if msg_index > 0 and session.messages[msg_index - 1].role == "assistant":
            prev_assistant = session.messages[msg_index - 1]

        role = classify_orchestration_role(msg, prev_assistant, is_first, after_idle)
        phase_sequence.append(role)

        if role == "intent" and (is_first or after_idle):
            if intent_length == 0:  # only count first intent
                intent_length = len(msg.content)
        if role == "steering":
            steering_count += 1

    score = compute_precision_score(steering_count)
    tier = session_tier(score)

    total_duration = 0
    if session.start_time and session.end_time:
        total_duration = int((session.end_time - session.start_time).total_seconds())

    has_outcome, time_to_first_commit = _detect_outcome(session.messages)

    return OrchestrationSession(
        session_id=session.session_id,
        project=session.project,
        total_duration=total_duration,
        intent_length=intent_length,
        steering_count=steering_count,
        precision_score=score,
        tier=tier,
        has_outcome=has_outcome,
        phase_sequence=phase_sequence,
        message_count=len(session.messages),
        time_to_first_commit=time_to_first_commit,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_orchestration.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_analytics/orchestration.py tests/test_orchestration.py
git commit -m "feat: add session analysis and precision scoring"
```

---

### Task 4: Implement orchestration insights engine

**Files:**
- Create: `src/claude_analytics/orchestration_insights.py`
- Create: `tests/test_orchestration_insights.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_orchestration_insights.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_orchestration_insights.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement orchestration insights**

Create `src/claude_analytics/orchestration_insights.py`:

```python
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
    """Generate actionable insights from orchestration session data."""
    if not sessions:
        return []

    insights: list[Insight] = []

    # Overall metrics
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

    # Per-project precision
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
                observation=f"Avg {avg_steering:.1f} steerings/session (precision {avg_precision:.2f}).",
                suggestion="Intents for this project may need more context.",
            ))

    # No-outcome sessions
    no_outcome = sum(1 for s in sessions if not s.has_outcome)
    if no_outcome > 0:
        no_pct = no_outcome / total
        if no_pct > 0.3:
            insights.append(Insight(
                project="Overall",
                observation=f"{no_pct:.0%} of sessions produced no commits.",
                suggestion="Some sessions may have been exploratory or the task too ambiguous.",
            ))

    # Intent length correlation
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

    # Excessive steering per session
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_orchestration_insights.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_analytics/orchestration_insights.py tests/test_orchestration_insights.py
git commit -m "feat: add orchestration insights engine"
```

---

### Task 5: Rewrite reporter for orchestration metrics

**Files:**
- Rewrite: `src/claude_analytics/reporter.py`
- Rewrite: `tests/test_reporter.py`

- [ ] **Step 1: Write failing tests for new reporter**

Rewrite `tests/test_reporter.py`:

```python
"""Tests for CLI report formatting (orchestration model)."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from claude_analytics.reporter import (
    format_duration,
    print_report,
    compute_streaks,
    format_heatmap,
    precision_tier_label,
)
from claude_analytics.models import OrchestrationSession, Session, ActivityBlock
from claude_analytics.codegen import CodeGenStats


def _orch(
    project: str = "my-project",
    precision_score: float = 1.0,
    tier: str = "flawless",
    steering_count: int = 0,
    total_duration: int = 600,
    has_outcome: bool = True,
    start_day: int = 1,
) -> OrchestrationSession:
    return OrchestrationSession(
        session_id=f"s-{start_day}",
        project=project,
        total_duration=total_duration,
        intent_length=100,
        steering_count=steering_count,
        precision_score=precision_score,
        tier=tier,
        has_outcome=has_outcome,
        phase_sequence=["intent"] + ["steering"] * steering_count + ["acknowledgment"],
        message_count=2 + steering_count,
    )


def _block(start_day: int = 1, duration: int = 3600, project: str = "my-project") -> ActivityBlock:
    return ActivityBlock(
        category="coding",
        start_time=datetime(2026, 3, start_day, 10, 0, tzinfo=timezone.utc),
        duration_seconds=duration,
        message_count=5,
        project=project,
    )


class TestFormatDuration:
    def test_hours(self):
        assert format_duration(7200) == "2h"

    def test_minutes(self):
        assert format_duration(300) == "5m"

    def test_seconds(self):
        assert format_duration(45) == "45s"


class TestPrecisionTierLabel:
    def test_flawless(self):
        label, _ = precision_tier_label(1.0)
        assert label == "Flawless"

    def test_clean(self):
        label, _ = precision_tier_label(0.5)
        assert label == "Clean"

    def test_guided(self):
        label, _ = precision_tier_label(0.25)
        assert label == "Guided"

    def test_heavy(self):
        label, _ = precision_tier_label(0.2)
        assert label == "Heavy"


class TestComputeStreaks:
    def test_consecutive_days(self):
        blocks = [_block(start_day=d) for d in [1, 2, 3]]
        current, longest = compute_streaks(blocks)
        assert longest == 3

    def test_gap_breaks_streak(self):
        blocks = [_block(start_day=d) for d in [1, 2, 5, 6]]
        current, longest = compute_streaks(blocks)
        assert longest == 2

    def test_empty(self):
        assert compute_streaks([]) == (0, 0)


class TestPrintReport:
    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_contains_precision_section(self, _):
        orchs = [_orch(), _orch(steering_count=1, precision_score=0.5, tier="clean")]
        blocks = [_block()]
        report = print_report(orchestration_sessions=orchs, blocks=blocks)
        assert "Orchestration Precision" in report

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_contains_tier_breakdown(self, _):
        orchs = [_orch(), _orch(steering_count=2, precision_score=0.33, tier="guided")]
        blocks = [_block()]
        report = print_report(orchestration_sessions=orchs, blocks=blocks)
        assert "Flawless" in report or "flawless" in report.lower()

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_contains_project_precision(self, _):
        orchs = [
            _orch(project="proj-a", precision_score=1.0, tier="flawless"),
            _orch(project="proj-b", precision_score=0.5, tier="clean", steering_count=1),
        ]
        blocks = [_block(project="proj-a"), _block(project="proj-b")]
        report = print_report(orchestration_sessions=orchs, blocks=blocks)
        assert "proj-a" in report
        assert "proj-b" in report

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_contains_throughput(self, _):
        orchs = [_orch()]
        blocks = [_block()]
        stats = CodeGenStats(ai_lines=1000, total_lines=5000, ai_commits=10, total_commits=12, files_touched={"a.py", "b.py"})
        report = print_report(orchestration_sessions=orchs, blocks=blocks, codegen_stats=stats)
        assert "Throughput" in report or "Commits" in report

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_empty_sessions(self, _):
        report = print_report(orchestration_sessions=[], blocks=[])
        assert "No" in report

    @patch("claude_analytics.reporter._use_color", return_value=False)
    def test_report_no_old_sections(self, _):
        orchs = [_orch()]
        blocks = [_block()]
        report = print_report(orchestration_sessions=orchs, blocks=blocks)
        assert "Engineering Efficiency" not in report
        assert "Active Time Breakdown" not in report
        assert "debug_tax" not in report
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_reporter.py -v`
Expected: FAIL with `ImportError` (new functions don't exist yet)

- [ ] **Step 3: Rewrite reporter.py**

Replace entire contents of `src/claude_analytics/reporter.py`:

```python
"""CLI output formatting for orchestration analytics reports."""

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

# Tier colors
TIER_COLORS = {
    "flawless": "\033[38;5;75m",   # blue
    "clean": "\033[38;5;82m",      # green
    "guided": "\033[38;5;228m",    # yellow
    "heavy": "\033[38;5;203m",     # red
}

PRECISION_TIERS = [
    (1.0,  "Flawless",  "\033[38;5;75m"),
    (0.50, "Clean",     "\033[38;5;82m"),
    (0.25, "Guided",    "\033[38;5;228m"),
    (0.0,  "Heavy",     "\033[38;5;203m"),
]


def precision_tier_label(score: float) -> tuple[str, str]:
    """Map a precision score to a tier label and ANSI color."""
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


def _bar(fraction: float, color_key: str = "", width: int = BAR_WIDTH) -> str:
    filled = int(fraction * width)
    color = TIER_COLORS.get(color_key, ACCENT_COLOR)
    bar_filled = "\u2588" * filled
    bar_empty = "\u2591" * (width - filled)
    if _use_color():
        return f"{color}{bar_filled}{RESET}{DIM}{bar_empty}{RESET}"
    return bar_filled + bar_empty


def _trend_arrow(current: float, previous: float) -> str:
    """Return a colored trend arrow comparing current vs previous period."""
    if previous == 0:
        return ""
    pct_change = (current - previous) / previous
    if pct_change > 0.1:
        return _c("\033[38;5;82m", "\u2191")
    elif pct_change < -0.1:
        return _c("\033[38;5;203m", "\u2193")
    else:
        return _c("\033[38;5;228m", "\u2192")


def compute_streaks(blocks: list[ActivityBlock]) -> tuple[int, int]:
    """Compute current and longest consecutive-day streaks from activity blocks."""
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

    return current, longest


HEATMAP_CHARS = ["\u2591", "\u2592", "\u2593", "\u2588"]
HEATMAP_COLORS = [
    "\033[38;5;236m",
    "\033[38;5;107m",
    "\033[38;5;71m",
    "\033[38;5;40m",
]
DAY_LABELS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def format_heatmap(blocks: list[ActivityBlock], max_weeks: int = 20) -> str:
    """Render a GitHub-style ASCII contribution heatmap."""
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


def print_report(
    orchestration_sessions: list[OrchestrationSession],
    blocks: list[ActivityBlock],
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    codegen_stats: CodeGenStats | None = None,
    insights: list | None = None,
) -> str:
    """Generate and return the full CLI report string."""
    if not orchestration_sessions and not blocks:
        return "No activity data found for the specified period."

    if not blocks:
        return "No activity data found for the specified period."

    # Filter blocks by date range
    if from_date:
        blocks = [b for b in blocks if b.start_time >= from_date]
    if to_date:
        blocks = [b for b in blocks if b.start_time <= to_date]

    if not blocks:
        return "No activity data found for the specified period."

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

    current_streak, longest_streak = compute_streaks(blocks)
    if longest_streak > 0:
        lines.append(f"  Streak: {_c(ACCENT_COLOR, f'{current_streak}d')} current  {_c(DIM, f'{longest_streak}d longest')}")

    lines.append(_c(LINE_COLOR, "\u2550" * 50))
    lines.append("")

    # Orchestration Precision
    if orchestration_sessions:
        total_sessions = len(orchestration_sessions)

        # Weighted average precision (by duration)
        total_weight = sum(s.total_duration for s in orchestration_sessions) or 1
        weighted_precision = sum(s.precision_score * s.total_duration for s in orchestration_sessions) / total_weight

        zero_touch = sum(1 for s in orchestration_sessions if s.steering_count == 0)
        zero_touch_rate = zero_touch / total_sessions

        # Trend: first half vs second half of sessions
        mid = total_sessions // 2
        sorted_sessions = sorted(orchestration_sessions, key=lambda s: s.session_id)
        first_half_precision = sum(s.precision_score for s in sorted_sessions[:mid]) / max(mid, 1)
        second_half_precision = sum(s.precision_score for s in sorted_sessions[mid:]) / max(total_sessions - mid, 1)

        tier_label, tier_color = precision_tier_label(weighted_precision)
        trend = _trend_arrow(second_half_precision, first_half_precision)
        trend_suffix = f" {trend}" if trend else ""

        lines.append(f"  {_c(BOLD, 'Orchestration Precision')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

        bar = _bar(weighted_precision, tier_label.lower())
        lines.append(f"  {'Overall':<16}{bar}  {_c(tier_color + BOLD, f'{weighted_precision:.2f}')}  {_c(tier_color, f'[{tier_label}]')}{trend_suffix}")

        zt_bar = _bar(zero_touch_rate, "flawless" if zero_touch_rate > 0.5 else "guided")
        lines.append(f"  {'Zero-Touch Rate':<16}{zt_bar}  {_c(ACCENT_COLOR, f'{zero_touch_rate:.0%}')}")
        lines.append(f"  {'Sessions':<40}{_c(BOLD, str(total_sessions))}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
        lines.append("")

        # Session tier breakdown
        tier_counts: dict[str, int] = {"flawless": 0, "clean": 0, "guided": 0, "heavy": 0}
        for s in orchestration_sessions:
            tier_counts[s.tier] = tier_counts.get(s.tier, 0) + 1

        lines.append(f"  {_c(BOLD, 'Session Breakdown')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

        for tier_name in ["flawless", "clean", "guided", "heavy"]:
            count = tier_counts[tier_name]
            frac = count / total_sessions if total_sessions > 0 else 0
            pct = frac * 100
            color = TIER_COLORS.get(tier_name, "")
            bar = _bar(frac, tier_name)
            label = _c(color, f"{tier_name.capitalize():<10}")
            pct_str = _c(ACCENT_COLOR, f"{pct:4.0f}%")
            count_str = _c(BOLD, f"{count:>5}")
            lines.append(f"  {label} {bar}  {pct_str}  {count_str}")

        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
        lines.append("")

    # Activity heatmap
    heatmap = format_heatmap(blocks)
    if heatmap:
        lines.append(heatmap)

    # Top projects by precision
    if orchestration_sessions:
        redactor = ProjectRedactor()
        proj_sessions: dict[str, list[OrchestrationSession]] = {}
        for s in orchestration_sessions:
            proj_name = redactor.redact(s.project)
            proj_sessions.setdefault(proj_name, []).append(s)

        lines.append(f"  {_c(BOLD, 'Top Projects by Precision')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))

        proj_precision = []
        for proj_name, sess_list in proj_sessions.items():
            avg = sum(s.precision_score for s in sess_list) / len(sess_list)
            proj_precision.append((proj_name, avg, len(sess_list)))

        proj_precision.sort(key=lambda x: x[1], reverse=True)

        for proj_name, avg, count in proj_precision[:10]:
            tier_label, tier_color = precision_tier_label(avg)
            score_str = _c(tier_color + BOLD, f"{avg:.2f}")
            tier_str = _c(tier_color, f"[{tier_label}]")
            count_str = _c(DIM, f"{count} sessions")
            lines.append(f"  {_c(HEADER_COLOR, f'{proj_name:<20}')} {score_str} {tier_str}  {count_str}")

        lines.append("")

    # Agent Throughput
    if codegen_stats:
        lines.append(f"  {_c(BOLD, 'Agent Throughput')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
        lines.append(f"  {_c(DIM, 'Commits'):<26}  {_c(BOLD, f'{codegen_stats.ai_commits:,}')}")
        lines.append(f"  {_c(DIM, 'Files touched'):<26}  {_c(BOLD, f'{len(codegen_stats.files_touched):,}')}")
        lines.append(f"  {_c(DIM, 'Lines produced'):<26}  {_c(BOLD, f'{codegen_stats.ai_lines:,}')}")
        lines.append("")

    # Insights
    if insights:
        from .orchestration_insights import format_orchestration_insights
        lines.append(f"  {_c(BOLD, 'Insights')}")
        lines.append("  " + _c(LINE_COLOR, "\u2500" * 46))
        lines.append(format_orchestration_insights(insights))
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_reporter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_analytics/reporter.py tests/test_reporter.py
git commit -m "feat: rewrite reporter for orchestration metrics"
```

---

### Task 6: Wire new pipeline in main.py and remove old modules

**Files:**
- Modify: `src/claude_analytics/main.py`
- Delete: `src/claude_analytics/classifier.py`, `src/claude_analytics/efficiency.py`, `src/claude_analytics/quality.py`, `src/claude_analytics/insights.py`, `src/claude_analytics/llm_classifier.py`
- Delete: `tests/test_classifier.py`, `tests/test_classifier_extra.py`, `tests/test_efficiency.py`, `tests/test_quality.py`, `tests/test_insights.py`, `tests/test_llm_classifier.py`, `tests/test_confidence.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Rewrite main.py to use orchestration pipeline**

Replace `src/claude_analytics/main.py` with:

```python
"""CLI entrypoint for Claude Code Analytics."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import json as json_module

from .parser import parse_all_sessions, CLAUDE_PROJECTS_DIR
from .aggregator import build_activity_blocks
from .codegen import analyze_codegen, extract_project_dirs
from .orchestration import analyze_session
from .orchestration_insights import generate_orchestration_insights
from .reporter import print_report
from .privacy import ProjectRedactor


_BAR_WIDTH = 20
_CLEAR_LINE = "\r" + " " * 60 + "\r"


def _progress(msg: str, done: int = 0, total: int = 0) -> None:
    """Print a progress bar to stderr."""
    if total > 0:
        frac = done / total
        filled = int(frac * _BAR_WIDTH)
        bar = "\u2588" * filled + "\u2591" * (_BAR_WIDTH - filled)
        pct = f"{frac * 100:3.0f}%"
        print(f"\r  {msg} [{bar}] {pct} ({done}/{total})", end="", file=sys.stderr, flush=True)
    else:
        print(f"\r  {msg}...", end="", file=sys.stderr, flush=True)


def _progress_done() -> None:
    print(_CLEAR_LINE, end="", file=sys.stderr, flush=True)


def parse_date(s: str) -> datetime:
    """Parse a date string like '2026-02-01' into a timezone-aware datetime."""
    dt = datetime.strptime(s, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def cmd_report(args: argparse.Namespace) -> None:
    projects_dir = Path(args.projects_dir) if args.projects_dir else CLAUDE_PROJECTS_DIR

    _progress("Discovering sessions")
    sessions = parse_all_sessions(
        projects_dir,
        project_filter=args.project,
        on_progress=lambda done, total: _progress("Parsing sessions", done, total),
    )

    if not sessions:
        _progress_done()
        print("No sessions found.")
        return

    from_date = parse_date(args.from_date) if args.from_date else None
    to_date = parse_date(args.to_date) if args.to_date else None

    if from_date:
        sessions = [s for s in sessions if s.end_time and s.end_time >= from_date]
    if to_date:
        sessions = [s for s in sessions if s.start_time and s.start_time <= to_date]

    if not sessions:
        _progress_done()
        print("No sessions found for the specified date range.")
        return

    _progress(f"Analyzing {len(sessions)} sessions")

    # Build activity blocks (for heatmap/streaks — uses old aggregator but classifier is now unused)
    all_blocks = []
    for session in sessions:
        blocks = build_activity_blocks(session)
        all_blocks.extend(blocks)

    # Orchestration analysis
    orch_sessions = [analyze_session(s) for s in sessions]

    codegen_stats = analyze_codegen(
        projects_dir,
        project_filter=args.project,
        sessions=sessions,
        on_progress=lambda done, total: _progress("Analyzing git repos", done, total),
    )

    _progress("Generating insights")
    insights = generate_orchestration_insights(orch_sessions)

    _progress_done()
    report = print_report(
        orchestration_sessions=orch_sessions,
        blocks=all_blocks,
        from_date=from_date,
        to_date=to_date,
        codegen_stats=codegen_stats,
        insights=insights,
    )
    print(report)


def cmd_sessions(args: argparse.Namespace) -> None:
    projects_dir = Path(args.projects_dir) if args.projects_dir else CLAUDE_PROJECTS_DIR

    _progress("Discovering sessions")
    sessions = parse_all_sessions(
        projects_dir,
        project_filter=args.project,
        on_progress=lambda done, total: _progress("Parsing sessions", done, total),
    )
    _progress_done()

    if not sessions:
        print("No sessions found.")
        return

    sessions.sort(key=lambda s: s.start_time or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    redactor = ProjectRedactor()
    limit = args.limit or 20
    for session in sessions[:limit]:
        user_msgs = sum(1 for m in session.messages if m.role == "user")
        start = session.start_time.strftime("%Y-%m-%d %H:%M") if session.start_time else "unknown"
        proj = redactor.redact(session.project)
        print(f"  {start}  {proj:<25} {user_msgs:>3} msgs  {session.session_id[:8]}")


def app() -> None:
    parser = argparse.ArgumentParser(
        prog="claude-analytics",
        description="Analyze Claude Code session logs",
    )
    parser.add_argument(
        "--projects-dir",
        help="Path to Claude projects directory (default: ~/.claude/projects)",
    )

    subparsers = parser.add_subparsers(dest="command")

    # report
    report_parser = subparsers.add_parser("report", help="Generate activity report")
    report_parser.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    report_parser.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    report_parser.add_argument("--project", help="Filter by project name")

    # sessions
    sessions_parser = subparsers.add_parser("sessions", help="List sessions")
    sessions_parser.add_argument("--limit", type=int, default=20, help="Max sessions to show")
    sessions_parser.add_argument("--project", help="Filter by project name")

    args = parser.parse_args()

    if args.command == "report":
        cmd_report(args)
    elif args.command == "sessions":
        cmd_sessions(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Delete old modules and their tests**

```bash
rm src/claude_analytics/classifier.py
rm src/claude_analytics/efficiency.py
rm src/claude_analytics/quality.py
rm src/claude_analytics/insights.py
rm src/claude_analytics/llm_classifier.py
rm tests/test_classifier.py
rm tests/test_classifier_extra.py
rm tests/test_efficiency.py
rm tests/test_quality.py
rm tests/test_insights.py
rm tests/test_llm_classifier.py
rm tests/test_confidence.py
```

- [ ] **Step 3: Update aggregator.py to remove classifier dependency**

The aggregator currently imports `classify_session` from `classifier.py`. Since we still need `build_activity_blocks` for heatmap/streaks, update `src/claude_analytics/aggregator.py` to use the orchestration classifier instead:

```python
"""Time aggregation and statistics from sessions."""

from datetime import datetime
from .models import Session, ActivityBlock, Message

IDLE_THRESHOLD_SECONDS = 600  # 10 minutes gap = new activity block


def calculate_active_time(messages: list[Message]) -> int:
    """Calculate total active seconds, excluding idle gaps > threshold."""
    active = 0
    for i in range(1, len(messages)):
        gap = (messages[i].timestamp - messages[i - 1].timestamp).total_seconds()
        if gap < IDLE_THRESHOLD_SECONDS:
            active += gap
    return int(active)


def build_activity_blocks(session: Session) -> list[ActivityBlock]:
    """Break a session into activity blocks based on idle gaps.

    In orchestration mode, all blocks get category 'session' since
    we no longer classify into coding/debug/etc. Blocks are used
    for heatmap rendering and streak calculation only.
    """
    if not session.messages:
        return []

    user_messages = [m for m in session.messages if m.role == "user"]
    if not user_messages:
        return []

    blocks: list[ActivityBlock] = []
    current_msgs: list[Message] = [user_messages[0]]

    for i in range(1, len(user_messages)):
        prev = user_messages[i - 1]
        curr = user_messages[i]
        gap = (curr.timestamp - prev.timestamp).total_seconds()

        if gap >= IDLE_THRESHOLD_SECONDS:
            blocks.append(_finalize_block(current_msgs, session.project))
            current_msgs = [curr]
        else:
            current_msgs.append(curr)

    if current_msgs:
        blocks.append(_finalize_block(current_msgs, session.project))

    return blocks


def _finalize_block(messages: list[Message], project: str) -> ActivityBlock:
    """Create an ActivityBlock from a list of messages."""
    all_tools: list[str] = []
    for msg in messages:
        for t in msg.tool_uses:
            if t not in all_tools:
                all_tools.append(t)

    duration = calculate_active_time(messages)

    return ActivityBlock(
        category="session",
        start_time=messages[0].timestamp,
        duration_seconds=duration,
        message_count=len(messages),
        tool_uses=all_tools,
        project=project,
    )
```

- [ ] **Step 4: Update aggregator tests**

The existing `tests/test_aggregator.py` and `tests/test_aggregator_extra.py` test the old category-based block building. Update them to work with the new simplified aggregator. Read the existing test files, then update the assertions to expect `category="session"` instead of specific categories, and remove tests that depend on `classify_session`.

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_e2e.py`
Expected: All PASS (with reduced test count since old test files are deleted)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: wire orchestration pipeline, remove old metrics

Replace classifier/efficiency/quality/insights with orchestration
analysis. Simplify aggregator to session-level blocks for heatmap.
Remove --llm flag, dashboard command (to be re-added later)."
```

---

### Task 7: Update e2e and integration tests

**Files:**
- Modify: `tests/test_e2e.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Update test_main.py for new CLI**

Read `tests/test_main.py`, then update it to:
- Remove references to `--llm` flag
- Remove `dashboard` and `insights` command tests
- Update `report` command test expectations to look for "Orchestration Precision" instead of "Active Time Breakdown"
- Ensure `sessions` command tests still work (unchanged)

- [ ] **Step 2: Update test_e2e.py**

Read `tests/test_e2e.py`, then update to use the new pipeline. The e2e tests should exercise the full flow: parse → orchestration analysis → report, checking for the new report sections.

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: update e2e and integration tests for orchestration model"
```

---

### Task 8: Final verification and cleanup

**Files:**
- All

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run the actual report**

Run: `python3 -m claude_analytics report`
Expected: New orchestration report with Precision, Tier Breakdown, Heatmap, Top Projects by Precision, Agent Throughput, Insights

- [ ] **Step 3: Verify old sections are gone**

Confirm the report output does NOT contain:
- "Active Time Breakdown"
- "Engineering Efficiency"
- "debug_tax"
- "focus_ratio"
- "chat_devops_overhead"
- Category bars (coding, debug, design, etc.)

- [ ] **Step 4: Commit and push**

```bash
git add -A
git commit -m "chore: final cleanup for orchestration pivot"
git push origin main
```
