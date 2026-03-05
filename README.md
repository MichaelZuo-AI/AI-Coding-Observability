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

  AI Code Generation
  ──────────────────────────────────────────────
  Lines written  (new)  69,799
  Lines added    (edit) 15,554
  Lines removed  (edit) 11,574
  ──────────────────────────────────────────────
  Total AI lines        85,353
  Net lines             73,779
```

## How It Works

1. **Parses** `~/.claude/projects/**/*.jsonl` session logs (read-only, never modified)
2. **Classifies** each interaction by intent using regex patterns + tool-use signals
3. **Calculates** active time with idle gap detection (10-min threshold)
4. **Measures** AI code generation from Write/Edit tool calls
5. **Reports** per-category and per-project breakdowns with colored terminal output

## Install

Requires **Python 3.11+**.

```bash
# One-liner with pipx (recommended)
pipx install git+https://github.com/MichaelZuo-AI/AI-Coding-Observability.git

# Or with pip
pip install git+https://github.com/MichaelZuo-AI/AI-Coding-Observability.git

# Or clone and run directly (no install needed)
git clone https://github.com/MichaelZuo-AI/AI-Coding-Observability.git
cd AI-Coding-Observability
python -m claude_analytics report
```

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
```

## Classification Categories

| Category | Signal |
|----------|--------|
| **coding** | implement, create, refactor + heavy Edit/Write tool use |
| **debug** | fix, error, crash, TypeError + heavy Bash/Grep tool use |
| **design** | architecture, plan, "how should" + heavy Read tool use |
| **devops** | deploy, docker, CI/CD, pipeline |
| **review** | explain, review, "walk me through" |
| **other** | general conversation, etc. |

## Privacy

- All processing is **100% local** — no data leaves your machine
- Session logs are read-only, never modified
- No API keys required — fully offline

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v   # 45 tests
```

## Roadmap

- [x] **Phase 1** — Parser + rule-based classifier + colored CLI report
- [x] **Phase 1.5** — AI code generation metrics (lines written/edited by AI)
- [ ] **Phase 2** — Claude Haiku API fallback for low-confidence classification + SQLite cache
- [ ] **Phase 3** — React + Recharts dashboard
