# AI Engineering Efficiency Metrics Framework

## Goal

Define **what to measure** and **how to implement it** to understand how efficiently an engineer uses AI-assisted coding tools (Claude Code) across the entire engineering lifecycle.

## Core Principle

> Efficiency = Valuable surviving output / Time and effort spent

In AI-assisted development, "effort" includes:
- **Human effort** — prompting, reviewing, debugging, context-switching
- **AI effort** — iterations, tool calls, rework cycles

All metrics are **per-project** by default. Projects vary in nature (greenfield vs maintenance, frontend vs backend), so comparing within a project over time is more meaningful than comparing across projects.

---

## Engineering Lifecycle Overview

The engineering lifecycle has 4 stages. We track **duration** for all stages, but only deep-dive into **Coding** — the stage where AI assistance has the most measurable impact.

| Stage | What We Measure | Why Duration Only |
|---|---|---|
| **Feature Design** | Design Duration (hours/days) | Design quality is subjective; duration is the only reliable signal from session logs. |
| **Coding** | *Deep dive below* | This is where AI assistance is most active and measurable. |
| **Testing** | Testing Duration (hours/days) | Test pass/fail data isn't in JSONL logs. Duration shows testing investment. |
| **Deployment** | Deployment Duration (hours/days) | Deployment is mostly devops overhead. Duration tracks friction. |

**How durations are calculated:**
- From classified activity blocks, sum `duration_seconds` for blocks matching each stage
- Feature Design = blocks classified as `design`
- Testing = blocks classified as `testing` (or coding blocks touching test files)
- Deployment = blocks classified as `devops`

---

## Coding Stage: Deep Dive

### Unified Efficiency Score

> **AI Engineering Efficiency Score** = Avg Task Resolution Efficiency × Focus Ratio

This single number captures both *how well* the engineer uses AI (resolution efficiency) and *how much* of their time is spent on high-value work (focus). It ranges from 0 to 1, where higher is better.

- **Task Resolution Efficiency** measures iteration quality: does AI get it right quickly?
- **Focus Ratio** measures time allocation: is time spent on engineering, not overhead?

The score degrades when either dimension is weak — a focused engineer who needs many iterations scores lower, as does an efficient prompter who spends half their time on devops.

---

### Output Metrics (3 KPIs)

These are the top-level indicators a VP looks at to assess coding efficiency.

---

#### Output 1: Task Resolution Efficiency

> "How many attempts does it take to get code right?"

| Metric | Definition | Formula | Unit |
|---|---|---|---|
| **Task Resolution Efficiency** | Average efficiency across all coding tasks in a session. Each task's efficiency is `1/attempts`, where attempts = number of coding+debug iterations before moving on. A one-shot success scores 1.0; needing 3 attempts scores 0.33. | `mean(1/attempts_per_task)` | ratio (0–1) |

**How to calculate:**
1. From classified activity blocks, identify "task sequences": consecutive coding/debug blocks for the same project, separated by gaps >10 min or a non-coding/debug block
2. Count the number of blocks (attempts) in each task sequence
3. For each task: `efficiency = 1 / attempts`
4. `task_resolution_efficiency = mean(efficiency across all tasks)`

**What "good" looks like:**
- 0.7+ = Most tasks resolved in 1-2 attempts (strong prompting)
- 0.4–0.7 = Average, some iteration needed
- <0.4 = Frequent rework cycles, prompts may need improvement

---

#### Output 2: Focus Ratio

> "Is engineering time spent on high-value work?"

| Metric | Definition | Formula | Unit |
|---|---|---|---|
| **Focus Ratio** | Percentage of active time spent on core engineering activities (coding, design, debugging) vs overhead (chat, devops, data tasks). | `(coding_seconds + design_seconds + debug_seconds) / total_active_seconds` | % |

**How to calculate:**
1. From classified activity blocks, sum `duration_seconds` for each category per project
2. Core categories: `coding`, `design`, `debug`
3. Total: sum of all categories
4. `focus_ratio = (coding + design + debug) / total`

**What "good" looks like:**
- 80%+ = Highly focused, minimal overhead
- 60–80% = Normal, some process overhead
- <60% = Too much time on non-engineering tasks

---

#### Output 3: Rework Rate

> "Does AI-generated code stick, or does it need immediate fixing?"

| Metric | Definition | Formula | Unit |
|---|---|---|---|
| **Rework Rate** | Percentage of files modified in 2+ commits within the same session. High rework means AI output needed multiple correction passes. | `files_with_2plus_commits_in_session / total_files_touched_in_session` | % |

**How to calculate:**
1. From codegen module, get AI commits grouped by session (using session time windows)
2. For each session, collect all files touched across its commits (`git log --numstat`)
3. Count files that appear in 2+ commits within that session
4. `rework_rate = reworked_files / total_unique_files`

**Why Rework Rate over Survival Rate:**
Survival rate (git blame) is noisy — code gets deleted for many healthy reasons (refactoring, feature pivots, scaffolding replacement). Rework rate only measures files re-edited within the same session, which unambiguously means the first attempt wasn't good enough.

**What "good" looks like:**
- <15% = AI output is reliable on first pass
- 15–30% = Normal iteration
- 30%+ = Too much churn, review prompting strategy

---

### Input Metrics (7 Drivers)

These are the levers that move the output metrics. Organized by which output they primarily drive.

---

#### Inputs driving Task Resolution Efficiency & Rework Rate

| Metric | Definition | Formula | Why it matters |
|---|---|---|---|
| **Debug Tax** | Hours of debugging per hour of coding. Measures the debugging overhead attached to each hour of productive coding. | `debug_seconds / coding_seconds` | High debug tax = coding sessions are frequently interrupted by debugging. Either AI output quality is low, or prompts are underspecified. |
| **Debug Loop Depth** | The length of the longest consecutive chain of debug-classified interactions without a coding/design break. Also tracked as average depth. | Max and mean of consecutive debug interaction counts. | Deep debug loops (>5 turns) indicate either a hard problem or an ineffective debugging approach. |
| **One-Shot Success Rate** | Percentage of coding activity blocks that are NOT immediately followed by a debug block within 10 minutes. | `coding_blocks_without_debug_followup / total_coding_blocks` | Higher one-shot rate = fewer iteration cycles = better resolution efficiency. |
| **Prompt Effectiveness** | Correlation between user message length and one-shot success rate. Measured as average message length for successful one-shots vs failed one-shots. | `avg_msg_length_for_successful_oneshots - avg_msg_length_for_failed_oneshots` | If longer prompts correlate with higher success, the engineer should invest more in upfront specification. |

**How to calculate One-Shot Success Rate:**
1. Get ordered list of activity blocks per project, sorted by start_time
2. For each block classified as `coding`:
   - Look at the next block in the same project
   - If the next block is `debug` AND starts within 10 minutes of the coding block's end → "failed" one-shot
   - Otherwise → "successful" one-shot
3. `one_shot_rate = successful / total_coding_blocks`

**How to calculate Debug Loop Depth:**
1. From classified session messages, extract the sequence of categories for user messages
2. Find consecutive runs of `debug` classifications
3. `max_depth` = length of longest debug run
4. `avg_depth` = mean length across all debug runs

---

#### Inputs driving Focus Ratio

| Metric | Definition | Formula | Why it matters |
|---|---|---|---|
| **Interaction Density** | Number of user messages per active hour. Measures the pace of human-AI interaction. | `user_message_count / active_hours` | Too high (>25/h) = micro-managing AI with tiny prompts. Too low (<5/h) = long waits or disengagement. Sweet spot: 8–15/h. |
| **Context Switch Frequency** | Number of project changes within a single session. A context switch is when consecutive activity blocks belong to different projects. | Count project transitions within each session. | Frequent switches fragment attention. Sessions with 3+ project switches typically have lower focus ratio. |
| **Chat & Devops Overhead** | Combined percentage of active time spent on chat and devops categories. | `(chat_seconds + devops_seconds) / total_active_seconds` | High overhead = too much time on non-coding activities. May indicate process issues. |

---

## Metric Relationships

```
UNIFIED SCORE
  AI Engineering Efficiency = Task Resolution Efficiency × Focus Ratio

OUTPUT                              INPUT DRIVERS
──────────────────────────         ──────────────────────────────────

Task Resolution Efficiency    <--  Debug Tax
  (1/attempts)                <--  Debug Loop Depth
                              <--  One-Shot Success Rate
                              <--  Prompt Effectiveness

Focus Ratio                   <--  Interaction Density
  (core time / total time)    <--  Context Switch Frequency
                              <--  Chat & Devops Overhead

Rework Rate                   <--  Debug Tax (shared driver)
  (files re-edited/session)   <--  One-Shot Success Rate (shared driver)
```

---

## Data Sources

All metrics are computed from two local data sources. No external APIs, no cloud services, no tokens.

| Source | What it provides | Used by |
|---|---|---|
| `~/.claude/projects/**/*.jsonl` | User messages, assistant responses, tool uses, timestamps, session boundaries | All input metrics, all output metrics |
| Git history (`git log --numstat`) | Commits, timestamps, lines added/removed per file | Rework rate |

---

## Implementation

### Current State (v0.4.0)

| Component | Status |
|---|---|
| JSONL parser + session discovery | Done |
| Rule-based classifier (7 categories) | Done |
| LLM fallback (`claude -p`) + SQLite cache | Done |
| Time aggregator (idle gap detection) | Done |
| Git-based AI code volume (log + numstat) | Done |
| CLI report (colored, per-project) | Done |
| React + Recharts dashboard | Done |
| PII guardrail (auto-redact project names) | Done |
| 575 tests | Done |

---

### Phase 4a: Output Metrics + Simple Inputs

**Goal:** Add Focus Ratio, simple input metrics, lifecycle stage durations, and a partial unified score to CLI report and dashboard.

#### New Module: `efficiency.py`

```python
@dataclass
class EfficiencyMetrics:
    # Output metrics
    focus_ratio: float             # (coding+design+debug) / total
    efficiency_score: float        # task_resolution_efficiency × focus_ratio (placeholder until 4b)

    # Input metrics (computable from block durations alone)
    debug_tax: float               # debug_seconds / coding_seconds
    interaction_density: float     # user_messages / active_hours
    chat_devops_overhead: float    # (chat+devops) / total_active_seconds

    # Lifecycle stage durations
    design_hours: float
    testing_hours: float
    deployment_hours: float

def compute_efficiency(
    blocks: list[ActivityBlock],
    message_count: int,
    active_hours: float,
) -> EfficiencyMetrics
```

#### Coverage

| Framework Metric | Type | Included |
|---|---|---|
| Focus Ratio | Output | Yes |
| Debug Tax | Input | Yes |
| Interaction Density | Input | Yes |
| Chat & Devops Overhead | Input | Yes |
| Lifecycle stage durations | Context | Yes |
| Unified Efficiency Score | Unified | Partial — `1.0 × focus_ratio` until Phase 4b |

#### Changes

| File | Change |
|---|---|
| `src/claude_analytics/efficiency.py` | New module: focus ratio, debug tax, interaction density, overhead, stage durations |
| `src/claude_analytics/reporter.py` | Add "Engineering Efficiency" section to CLI report |
| `src/claude_analytics/main.py` | Wire efficiency computation into `cmd_report` and `_collect_data` |
| `src/claude_analytics/dashboard/index.html` | Add efficiency cards and stage duration bars per project |
| `tests/test_efficiency.py` | Unit tests for all ratio computations |

#### Edge Cases

- `coding_time = 0` → debug_tax = 0 (no coding, no tax)
- `active_hours = 0` → all ratios = 0
- `total_active_seconds = 0` → focus_ratio = 0, overhead = 0
- Single-category project → focus_ratio is 100% or 0% depending on category

---

### Phase 4b: Resolution & Rework Metrics

**Goal:** Add Task Resolution Efficiency, Rework Rate, and input metrics that require sequence analysis or git data. Update unified score with real task_resolution_efficiency.

#### New Module: `quality.py`

```python
@dataclass
class QualityMetrics:
    # Output metrics
    task_resolution_efficiency: float  # mean(1/attempts_per_task)
    rework_rate: float                 # files in 2+ session commits / total files

    # Input metrics (require sequence analysis or git data)
    one_shot_success_rate: float       # coding blocks without debug follow-up / total
    debug_loop_max_depth: int          # deepest consecutive debug chain
    debug_loop_avg_depth: float        # mean debug chain length
    context_switch_frequency: float    # project transitions per session
    prompt_effectiveness: float        # msg length delta (successful vs failed one-shots)

def compute_quality(
    blocks: list[ActivityBlock],
    sessions: list[Session],
    codegen: CodeGenStats,
) -> QualityMetrics
```

#### Coverage

| Framework Metric | Type | Included |
|---|---|---|
| Task Resolution Efficiency | Output | Yes |
| Rework Rate | Output | Yes |
| One-Shot Success Rate | Input | Yes |
| Debug Loop Depth | Input | Yes |
| Prompt Effectiveness | Input | Yes |
| Context Switch Frequency | Input | Yes |
| Unified Efficiency Score | Unified | Full — updates `efficiency_score = task_resolution × focus_ratio` |

#### Algorithms

**Task Resolution Efficiency:**
1. From classified session data, get ordered activity blocks per project
2. Identify "task sequences": consecutive coding/debug blocks, separated by >10min gap or non-coding/debug block
3. Count attempts (blocks) per task sequence
4. For each task: `efficiency = 1 / attempts`
5. `task_resolution_efficiency = mean(efficiency across all tasks)`

**Rework Rate:**
1. From git log, group commits by session (using session time windows)
2. For each session, count files appearing in 2+ commits
3. `rework_rate = reworked_files / total_files_touched`

**One-Shot Success Rate:**
1. Get ordered list of activity blocks per project, sorted by start_time
2. For each `coding` block, check if next block (within 10min) is `debug`
3. `one_shot_rate = coding_blocks_without_debug_followup / total_coding_blocks`

**Debug Loop Depth:**
1. From classified session messages, extract sequence of categories
2. Find consecutive runs of `debug` classifications
3. `max_depth` = length of longest run; `avg_depth` = mean of all runs

**Context Switch Frequency:**
1. For each session, get ordered activity blocks
2. Count transitions where consecutive blocks belong to different projects
3. `context_switch_frequency = transitions / session_count`

**Prompt Effectiveness:**
1. For each coding block, get the triggering user message length (characters)
2. Split into successful one-shots vs failed one-shots
3. `prompt_effectiveness = avg_msg_length_successful - avg_msg_length_failed`

#### Changes

| File | Change |
|---|---|
| `src/claude_analytics/quality.py` | New module: task resolution, rework, one-shot, debug loops, context switches, prompt effectiveness |
| `src/claude_analytics/efficiency.py` | Update unified score to use real task_resolution_efficiency |
| `src/claude_analytics/reporter.py` | Add quality metrics to CLI report per project |
| `src/claude_analytics/main.py` | Wire quality metrics into report and dashboard |
| `src/claude_analytics/dashboard/index.html` | Task resolution gauge, rework bar, one-shot chart, debug loop visualization |
| `tests/test_quality.py` | Unit tests with synthetic git repos and block sequences |

#### Edge Cases

- No coding blocks → one_shot_success = 1.0, task_resolution = 1.0
- No task sequences → task_resolution = 1.0
- Single-project sessions → context_switch_frequency = 0
- No successful/failed one-shots → prompt_effectiveness = 0

---

### Phase 4c: Behavioral Insights

**Goal:** Add pattern analysis and actionable recommendations per project, combining metrics from Phases 4a and 4b.

#### New Module: `insights.py`

```python
@dataclass
class Insight:
    project: str       # project name, or "Overall" for global
    observation: str   # what was observed
    suggestion: str    # actionable recommendation (optional)

def generate_insights(
    efficiency: dict[str, EfficiencyMetrics],
    quality: dict[str, QualityMetrics],
    blocks: list[ActivityBlock],
    sessions: list[Session],
) -> list[Insight]
```

#### Insight Rules

| Trigger | Observation | Suggestion |
|---|---|---|
| efficiency_score > 0.7 | "Efficiency score is {x} — strong AI-assisted workflow." | — |
| efficiency_score < 0.3 | "Efficiency score is {x} — significant room for improvement." | "Focus on reducing iteration cycles and minimizing overhead." |
| focus_ratio > 85% | "Focus ratio is {x}% — highly focused project." | — |
| focus_ratio < 50% | "Only {x}% of time on core engineering." | "Consider batching devops/chat tasks." |
| debug_tax > 0.3 | "Debug tax is {x}h per coding hour." | "Try more detailed prompts or break tasks smaller." |
| one_shot < 50% | "One-shot success rate is {x}%." | "Consider providing more context in initial prompts." |
| debug_loop_max > 5 | "{n} debug loops exceeded 5 turns." | "Consider stepping back and re-prompting from scratch." |
| rework_rate > 30% | "{x}% of files were reworked within the same session." | "Spend more time on the initial prompt specification." |
| task_resolution < 0.4 | "Average task takes {x} attempts." | "Break complex tasks into smaller, clearer prompts." |
| interaction_density > 25 | "{x} messages/hour — potentially micro-managing AI." | "Try longer, more detailed prompts instead of many short ones." |
| context_switches > 3 | "{n} project switches in one session." | "Batch work by project to reduce context switching." |

#### Additional Analysis

**Peak Productivity Hours:**
1. For each activity block, extract hour-of-day (0-23) in KST timezone
2. Compute focus_ratio per hour bucket
3. Find top 2 contiguous productive windows

**Context Switch Cost:**
1. Identify sessions with 2+ different projects
2. Measure focus_ratio of multi-project sessions vs single-project sessions
3. Estimate recovery time: gap after project switch to next coding block

#### New CLI Command: `claude-analytics insights`

```bash
claude-analytics insights                    # all projects, last 30 days
claude-analytics insights --project MewtwoAI # single project
claude-analytics insights --from 2026-02-01  # date range
```

#### Changes

| File | Change |
|---|---|
| `src/claude_analytics/insights.py` | New module: insight generation, rules engine |
| `src/claude_analytics/reporter.py` | Format insights for CLI output |
| `src/claude_analytics/main.py` | Add `insights` subcommand |
| `src/claude_analytics/dashboard/index.html` | Insights panel with per-project cards |
| `tests/test_insights.py` | Unit tests for each insight rule |

---

### Implementation Order

```
Phase 4a (Outputs + Simple)   Phase 4b (Resolution + Rework)   Phase 4c (Insights)
───────────────────────────   ────────────────────────────────  ─────────────────
efficiency.py            -->  quality.py                   -->  insights.py
  focus_ratio                   task_resolution_efficiency        peak_hours
  debug_tax                     rework_rate                       context_switch_cost
  interaction_density           one_shot_success_rate             insight_rules
  chat_devops_overhead          debug_loop_depth
  stage_durations               context_switch_frequency
  efficiency_score (partial)    prompt_effectiveness
                                efficiency_score (full)
```

Each phase is independently shippable. Phase 4a can land without 4b/4c.

### Framework Coverage by Phase

| Framework Metric | Type | Phase |
|---|---|---|
| Focus Ratio | Output | 4a |
| Task Resolution Efficiency | Output | 4b |
| Rework Rate | Output | 4b |
| Debug Tax | Input | 4a |
| Interaction Density | Input | 4a |
| Chat & Devops Overhead | Input | 4a |
| One-Shot Success Rate | Input | 4b |
| Debug Loop Depth | Input | 4b |
| Prompt Effectiveness | Input | 4b |
| Context Switch Frequency | Input | 4b |
| Unified Efficiency Score | Unified | 4a (partial) → 4b (full) |
| Insight Rules | Insights | 4c |

---

### Testing Strategy

| Phase | Test approach |
|---|---|
| 4a | Unit tests with synthetic ActivityBlock lists — verify focus_ratio, debug_tax, interaction_density, overhead, stage durations |
| 4b | Synthetic git repos (init + commits) in tmp_path fixtures — verify rework_rate, one-shot, debug loops, task resolution, context switches |
| 4c | Mock efficiency/quality inputs, verify generated insight text matches rules |

---

### Files Summary

New files:
- `src/claude_analytics/efficiency.py`
- `src/claude_analytics/quality.py`
- `src/claude_analytics/insights.py`
- `tests/test_efficiency.py`
- `tests/test_quality.py`
- `tests/test_insights.py`

Modified files:
- `src/claude_analytics/reporter.py` — new sections
- `src/claude_analytics/main.py` — new subcommand, wiring
- `src/claude_analytics/dashboard/index.html` — new cards/charts

---

## What This Framework Does NOT Measure

- **Code correctness** — Rework rate is a proxy for quality, not a guarantee of correctness.
- **Business impact** — We don't know if the shipped feature was valuable. That's a product question.
- **Lines of code as value** — More code ≠ more value. A well-designed system may need fewer lines.
- **Token/cost efficiency** — Claude Code subscription is flat-rate; token usage is not exposed in JSONL logs.
- **Cross-engineer comparison** — This is a personal observability tool, not a performance review system.
- **Non-Claude AI tools** — Only measures Claude Code sessions.
