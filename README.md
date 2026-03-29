# Agent Autonomy Score

A [Claude Code skill](https://docs.anthropic.com/en/docs/claude-code) that measures how effectively you orchestrate AI coding agents. Parses session logs and scores each session by **orchestration precision** — how many corrections you needed after stating your initial intent.

![Agent Autonomy Score Dashboard](docs/dashboard.png)

## Usage

In any Claude Code session, run:

```
/analytics
```

The skill auto-detects your current project and generates a precision report with an interactive HTML dashboard saved to `reports/YYYY-MM-DD.html`.

## How It Works

1. **Parses** `~/.claude/projects/**/*.jsonl` session logs (read-only, never modified)
2. **Classifies** each user message as `intent`, `steering`, `clarification`, or `acknowledgment`
3. **Scores** each session: `precision = 1 / (1 + steering_count)` — fewer corrections = higher score
4. **Tiers** sessions: Flawless (1.0), Clean (0.50+), Guided (0.25+), Heavy (<0.25)
5. **Reports** per-project precision, activity heatmap, agent throughput, and actionable insights

## The Idea

If you direct AI agents rather than code yourself, the question isn't "how much did AI help me code" — it's **"how precisely did I translate intent into shipped code?"**

A session where you say "build X" and the AI delivers with zero corrections scores 1.0 (Flawless). A session where you correct the AI 4 times scores 0.2 (Heavy). Over time, your precision score tells you whether your prompts are getting better.

## Install

```bash
pip install "git+https://github.com/MichaelZuo-AI/AI-Coding-Observability.git"
```

Then add the skill to your Claude Code config at `~/.claude/skills/analytics/SKILL.md`. See [SKILL.md](https://github.com/MichaelZuo-AI/AI-Coding-Observability/blob/main/.claude/skills/analytics/SKILL.md) for the skill definition.

The CLI also works standalone:

```bash
# Full report
claude-analytics report

# Filter by date range
claude-analytics report --from 2026-02-01 --to 2026-02-28

# Filter by project
claude-analytics report --project MyProject

# List recent sessions
claude-analytics sessions
```

## Message Classification

Each user message after the initial prompt is classified:

| Role | Detection | Examples |
|------|-----------|---------|
| **intent** | First message, or first after idle gap (>10 min) | "Build a login page with OAuth" |
| **steering** | Negation, correction, rejection patterns | "No, use Postgres not SQLite", "Revert that" |
| **clarification** | Response to AI's question | AI: "Which DB?" → User: "Postgres" |
| **acknowledgment** | Default — approval or continuation | "yes", "looks good", "go ahead" |

Only `steering` messages count against your precision score. Clarifications and acknowledgments are neutral.

## Privacy

- All processing is **100% local** — no data leaves your machine
- Session logs are read-only, never modified
- No API keys required — fully offline
- Project names are auto-redacted when matching sensitive patterns (financial, medical, etc.)
- Set `"redact_all": true` in `~/.claude-analytics/privacy.json` to mask all project names

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v   # 247 tests
```
