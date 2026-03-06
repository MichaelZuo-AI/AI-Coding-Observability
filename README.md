# Claude Code Analytics

A local-first CLI tool that parses Claude Code session logs to analyze how engineers spend their AI-assisted development time — coding, debugging, design, devops, and more.

```
══════════════════════════════════════════════════
  Claude Code Analytics
  2026-02-07 ~ 2026-03-05
  Engineer: michaelzuo
══════════════════════════════════════════════════

  Active Time Breakdown
  ──────────────────────────────────────────────
  coding     █░░░░░░░░░░░░░░░░░░░   10%     4h
  debug      ░░░░░░░░░░░░░░░░░░░░    1%    32m
  design     ░░░░░░░░░░░░░░░░░░░░    3%     1h
  devops     ███░░░░░░░░░░░░░░░░░   16%     6h
  review     ░░░░░░░░░░░░░░░░░░░░    3%     1h
  data       ████░░░░░░░░░░░░░░░░   24%     9h
  chat       ████████░░░░░░░░░░░░   43%    17h
  ──────────────────────────────────────────────
  Total Active                       100%    39h

  AI Code Generation
  ──────────────────────────────────────────────
  AI-generated  ████████████░░░░░░░░  61%
    58,983 AI lines / 96,867 total lines
  ──────────────────────────────────────────────
  AI commits          229
  Total commits       241
  Files touched       3257
```

## How It Works

1. **Parses** `~/.claude/projects/**/*.jsonl` session logs (read-only, never modified)
2. **Classifies** each interaction by intent using regex patterns + tool-use signals
3. **Calculates** active time with idle gap detection (10-min threshold)
4. **Measures** AI code generation by matching git commits to session time windows
5. **Reports** per-category and per-project breakdowns with colored terminal output

## Install

```bash
# One-liner with pipx (recommended)
pipx install "git+https://github.com/MichaelZuo-AI/AI-Coding-Observability.git"

# Or with pip
pip install "git+https://github.com/MichaelZuo-AI/AI-Coding-Observability.git"

# Or from source
git clone https://github.com/MichaelZuo-AI/AI-Coding-Observability.git
cd AI-Coding-Observability
python -m claude_analytics report
```

To upgrade: `pipx install --force "git+https://github.com/MichaelZuo-AI/AI-Coding-Observability.git"`

## Usage

```bash
# Full activity report
claude-analytics report

# Filter by date range
claude-analytics report --from 2026-02-01 --to 2026-02-28

# Filter by project
claude-analytics report --project MewtwoAI

# List recent sessions
claude-analytics sessions
claude-analytics sessions --limit 10

# Use LLM reclassification for low-confidence interactions (uses your Claude Code subscription)
claude-analytics report --llm

# Launch interactive dashboard
claude-analytics dashboard
claude-analytics dashboard --port 8080
```

## Classification Categories

| Category | Signal |
|----------|--------|
| **coding** | implement, create, refactor, UI components + Edit/Write tool use |
| **debug** | fix, error, crash, "still not work" + Bash/Grep tool use |
| **design** | architecture, plan, "how should", tradeoffs |
| **devops** | deploy, commit, push, install, setup, CI/CD |
| **review** | explain, "show me", "how to use", "walk me through" |
| **data** | stock analysis, portfolio, financial, images, email |
| **chat** | short replies (yes/ok/go ahead), greetings, slash commands |

## Privacy

- All processing is **100% local** — no data leaves your machine
- Session logs are read-only, never modified
- No API keys required — fully offline

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v   # 87 tests
```

## Changelog

### v0.4.0
- **Phase 2**: `claude -p` reclassification for low-confidence interactions (`--llm` flag)
- SQLite cache at `~/.claude-analytics/classification_cache.db` — each interaction classified only once
- Confidence scoring on rule-based classifier (threshold: 1.5)
- **Phase 3**: Interactive React + Recharts dashboard (`claude-analytics dashboard`)
- Dark-themed dashboard with pie charts, stacked area charts, bar charts
- Daily activity time series, per-project breakdowns, AI code generation stats
- 87 tests

### v0.3.1
- Fixed ZeroDivisionError when a project has zero active time (#1)
- Added progress indicators for large `~/.claude` directories (#1)

### v0.3.0
- Improved classifier: replaced 75% "other" with specific **data** and **chat** categories
- Added patterns for financial terms, image shares, short replies, slash commands
- Better coding/devops/review detection (commit, push, install, "show me", "how to use")
- 63 tests

### v0.2.0
- Git-based AI code generation tracking (replaces Write/Edit counting)
- Matches git commit timestamps to Claude Code session time windows
- Captures all AI code including Bash scaffolding (npx create-next-app, etc.)
- Shows AI% per project with progress bars

### v0.1.0
- Initial release: JSONL parser, rule-based classifier, time aggregator
- Colored CLI report with per-category and per-project breakdowns
- Write/Edit tool-based AI line counting

## Roadmap

- [x] **Phase 1** — Parser + rule-based classifier + colored CLI report
- [x] **Phase 1.5** — AI code generation metrics (git-based, per-project AI%)
- [x] **Phase 2** — `claude -p` fallback for low-confidence classification + SQLite cache
- [x] **Phase 3** — React + Recharts dashboard
