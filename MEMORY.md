# AI-Coding-Observability Project Memory

## Project Overview
- Python 3.12 CLI tool: `claude-analytics`
- Pure stdlib — no external deps except `pytest`
- Test runner: `.venv/bin/python -m pytest tests/ -v`
- Package: `src/claude_analytics/` (setuptools, editable install)

## Test Suite (as of 2026-03-05)
- **267 total tests across 9 test files**
- test_parser.py (10), test_classifier.py (22), test_aggregator.py (8), test_codegen.py (13)
- test_reporter.py (61), test_main.py (42), test_parser_extra.py (48), test_aggregator_extra.py (37), test_classifier_extra.py (33)

## Key Architecture Notes
- `reporter.py`: `_use_color()` checks `sys.stdout.isatty()` — always False in pytest, so all reporter tests naturally run in no-color mode. Use `patch("claude_analytics.reporter._use_color", return_value=False)` explicitly for predictability.
- `main.py`: `cmd_report` / `cmd_sessions` read from filesystem and git — always mock `parse_all_sessions`, `build_activity_blocks`, `analyze_codegen`, `analyze_codegen_by_project` in tests. Capture stdout with `patch("sys.stdout", StringIO())`.
- `aggregator.py`: `_finalize_block` collects `tool_uses` from the user Message objects in the classified list — NOT from assistant messages. Tool uses in ActivityBlocks come from the user message's own `tool_uses` field.
- `IDLE_THRESHOLD_SECONDS = 600` (10 minutes) — use `timedelta` when creating test timestamps that span > 59 seconds.

## Gotchas
- `datetime(y, m, d, h, min, sec)` requires `sec` in 0-59 — use `_BASE + timedelta(seconds=N)` for large gaps
- Chinese characters are `\w` in Python regex → `\b(净资产)\b` won't match when surrounded by other CJK chars. Test with the keyword at start of string or adjacent to ASCII/spaces.
- Short messages (≤ 15 chars) match the chat pattern with score=1 — tool signals (0.3-0.5) won't win. Use longer content (> 15 chars) when testing tool signal effects via `classify_message`.
- `analyze_codegen_by_project` is NOT called when `args.project` is set (single project filter) — the `cmd_report` logic explicitly skips it.
