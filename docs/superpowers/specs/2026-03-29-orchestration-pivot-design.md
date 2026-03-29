# Orchestration Effectiveness Pivot

Replace the current "human codes with AI help" metrics model with an "AI orchestration effectiveness" model that measures how precisely an engineer translates intent into shipped code through AI agents.

## Context

The current analytics assume the engineer is coding alongside AI. In practice, the user directs AI agents (via `/feature-crew`, direct prompts, etc.) and rarely writes code themselves. The current report shows 56% "chat" time and labels it overhead — but chat IS the primary work. Efficiency scores penalize the actual workflow.

## Core Concept

One session = one orchestration attempt. The key question per session: **how many corrections did the engineer need to make after stating their initial intent?**

## Classification Model

Replace the 8 activity categories (`coding`, `debug`, `design`, `devops`, `review`, `data`, `chat`, `other`) with 4 message roles:

### Roles

| Role | Detection | Examples |
|---|---|---|
| `intent` | First user message in session, or first after idle gap (>10min) | "Build a login page with OAuth", "/feature-crew implement X" |
| `steering` | Regex: negation, correction, rejection patterns | "No, use Postgres not SQLite", "That's wrong", "Revert that", "Instead do X" |
| `clarification` | Previous assistant message contains a question | User answering AI's question with information |
| `acknowledgment` | Default — short affirmatives not matching steering | "Yes", "Looks good", "Go ahead", "Continue", "Ship it" |

### Steering Detection Patterns

Negation/rejection: `no`, `don't`, `wrong`, `not what I`, `that's incorrect`, `revert`, `undo`, `go back`, `stop`

Correction/redirect: `instead`, `actually`, `change it to`, `switch to`, `use X not Y`, `should be`, `I meant`

Imperative override: `do it this way`, `try again with`, `start over`

### Detection Priority

1. Position check → `intent` (first message, or first after idle gap)
2. Previous-assistant-question check → `clarification`
3. Steering regex match → `steering`
4. Default → `acknowledgment`

## Scoring

### Per-Session Precision Score

```
precision_score = 1 / (1 + steering_count)
```

- 0 steerings = 1.00 (perfect)
- 1 steering = 0.50
- 2 steerings = 0.33
- 5 steerings = 0.17

### Aggregate Metrics

- **Overall Precision**: weighted average of session scores, weighted by session duration (longer sessions count more)
- **Zero-Touch Rate**: percentage of sessions with zero steerings

### Session Tiers

| Score | Tier | Meaning |
|---|---|---|
| 1.00 | Flawless | Zero intervention needed |
| 0.50+ | Clean | 1 correction at most |
| 0.25+ | Guided | Needed a few nudges |
| <0.25 | Heavy | Significant hand-holding |

## Session Anatomy

Each session is decomposed into phases:

```
[intent] -> [execution] -> [steering] -> [execution] -> [ack] -> [execution] -> [commit]
```

### Per-Session Data

| Field | Type | Description |
|---|---|---|
| `session_id` | str | Existing session ID |
| `project` | str | Project name |
| `total_duration` | int | Wall-clock seconds, first to last message |
| `intent_length` | int | Character count of initial prompt |
| `steering_count` | int | Number of steering messages |
| `precision_score` | float | `1 / (1 + steering_count)` |
| `tier` | str | Flawless/Clean/Guided/Heavy |
| `time_to_first_commit` | int or None | Seconds from session start to first commit detection |
| `has_outcome` | bool | Did session produce at least one commit/push? |
| `phase_sequence` | list[str] | Ordered list of roles for timeline visualization |
| `message_count` | int | Total messages in session |

### Commit Detection

Reuse existing logic: detect commits via tool uses containing git operations (Bash calls with `git commit`, `git push`) or commit-related patterns in assistant messages.

## Report Format

```
==================================================
  Claude Code Analytics
  2026-02-26 ~ 2026-03-29
  Engineer: michaelzuo
  Streak: 32d current  32d longest
==================================================

  Orchestration Precision
  ----------------------------------------------
  Overall         [bar]  0.62  [Clean] [trend]
  Zero-Touch Rate [bar]  34%
  Sessions                                 135
  ----------------------------------------------

  Session Breakdown
  ----------------------------------------------
  Flawless   [bar]   34%    46
  Clean      [bar]   22%    30
  Guided     [bar]   26%    35
  Heavy      [bar]   18%    24
  ----------------------------------------------

  Activity Heatmap
  ----------------------------------------------
  Mo [heatmap row]
  Tu [heatmap row]
  ...

  Top Projects by Precision
  ----------------------------------------------
  project-a     1.00 [Flawless]  2 sessions
  project-b     0.67 [Clean]     6 sessions
  project-c     0.40 [Guided]    8 sessions
  ...

  Agent Throughput
  ----------------------------------------------
  Commits              797
  Files touched         764
  Lines produced    148,699

  Insights
  ----------------------------------------------
  * [insight text]
  ...
```

## Insights Engine

| Pattern | Trigger | Output |
|---|---|---|
| Strong clarity | Zero-touch rate > 50% | Positive reinforcement |
| Underspecified project | Project avg precision < 0.25 | "Intents for {project} may need more context" |
| Intent length correlation | Long intents score higher than short | "Longer prompts correlate with better precision" |
| Excessive steering | >3 steerings in a session | "Consider breaking into smaller tasks" |
| No-outcome session | No commits detected | "Session produced no commits" |
| Time-to-commit trend | Avg improving or degrading | Show trend arrow |
| Peak precision hours | Hours with highest avg precision | "Best orchestration at {hour} KST" |
| Project improving | Precision trending up | "{project} precision improved this period" |

## File Changes

### New Files
- `src/claude_analytics/orchestration.py` — new classifier (`classify_orchestration_role`) + precision scoring + session anatomy
- `src/claude_analytics/orchestration_insights.py` — new insights engine

### Modified Files
- `src/claude_analytics/reporter.py` — replace report format entirely
- `src/claude_analytics/main.py` — wire new pipeline, remove old metric flags
- `src/claude_analytics/models.py` — add `OrchestrationSession` dataclass
- `src/claude_analytics/dashboard/index.html` — update to new data schema

### Removed Files
- `src/claude_analytics/classifier.py` — replaced by orchestration.py
- `src/claude_analytics/efficiency.py` — replaced by precision scoring
- `src/claude_analytics/quality.py` — replaced by precision scoring
- `src/claude_analytics/insights.py` — replaced by orchestration_insights.py
- `src/claude_analytics/llm_classifier.py` — no longer needed

### Unchanged Files
- `src/claude_analytics/parser.py` — still reads JSONL the same way
- `src/claude_analytics/aggregator.py` — still computes active time and idle gaps (used for intent detection at idle boundaries)
- `src/claude_analytics/codegen.py` — reframed as "agent throughput" but logic unchanged
- `src/claude_analytics/privacy.py` — unchanged
- `src/claude_analytics/cache.py` — unchanged (may be repurposed or left dormant)

### Test Changes
- Replace tests for removed modules with tests for orchestration.py and orchestration_insights.py
- Update reporter tests for new format
- Update main/CLI tests for new pipeline

## Dashboard Data Schema

```json
{
  "dateRange": { "from": "ISO8601", "to": "ISO8601" },
  "overallPrecision": 0.62,
  "zeroTouchRate": 0.34,
  "sessionCount": 135,
  "tierBreakdown": { "flawless": 46, "clean": 30, "guided": 35, "heavy": 24 },
  "projectPrecision": {
    "project-a": { "precision": 1.00, "sessions": 2, "tier": "flawless" },
    "project-b": { "precision": 0.67, "sessions": 6, "tier": "clean" }
  },
  "dailySeries": [
    { "date": "2026-03-01", "precision": 0.55, "sessions": 4, "steerings": 6 }
  ],
  "throughput": { "commits": 797, "filesTouched": 764, "linesProduced": 148699 },
  "insights": ["insight text 1", "insight text 2"]
}
```
