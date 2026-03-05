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
  coding     █████████░░░░░░░░░░░   42%    68h
  debug      ████░░░░░░░░░░░░░░░░   21%    34h
  design     ███░░░░░░░░░░░░░░░░░   16%    26h
  devops     ██░░░░░░░░░░░░░░░░░░   11%    18h
  review     █░░░░░░░░░░░░░░░░░░░    8%    13h
  other      ░░░░░░░░░░░░░░░░░░░░    2%     3h
  ──────────────────────────────────────────────
  Total Active                       100%   162h
```

## How It Works

1. **Parses** `~/.claude/projects/**/*.jsonl` session logs (read-only, never modified)
2. **Classifies** each interaction by intent using regex patterns + tool-use signals
3. **Calculates** active time with idle gap detection (10-min threshold)
4. **Reports** per-category and per-project breakdowns with colored terminal output

## Install

```bash
# Requires Python 3.11+
git clone https://github.com/MichaelZuo-AI/AI-Coding-Observability.git
cd AI-Coding-Observability
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
# Activity report (all time)
claude-analytics report

# Filter by date range
claude-analytics report --from 2026-02-01 --to 2026-02-28

# Filter by project
claude-analytics report --project MewtwoAI

# List recent sessions
claude-analytics sessions
claude-analytics sessions --limit 10
```

## Classification Categories

| Category | Signal |
|----------|--------|
| **coding** | implement, create, refactor + heavy Edit/Write tool use |
| **debug** | fix, error, crash, TypeError + heavy Bash/Grep tool use |
| **design** | architecture, plan, "how should" + heavy Read tool use |
| **devops** | deploy, docker, CI/CD, pipeline |
| **review** | explain, review, "walk me through" |
| **other** | general conversation, portfolio mgmt, etc. |

## Privacy

- All processing is **100% local** — no data leaves your machine
- Session logs are read-only, never modified
- No API keys required (Phase 1 is fully offline)

## Testing

```bash
pytest tests/ -v   # 30 tests
```

## Roadmap

- [x] **Phase 1** — Parser + rule-based classifier + colored CLI report
- [ ] **Phase 2** — Claude Haiku API fallback for low-confidence classification + SQLite cache
- [ ] **Phase 3** — React + Recharts dashboard
