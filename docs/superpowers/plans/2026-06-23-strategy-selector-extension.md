# Strategy Selector Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pluggable strategy screening layer inspired by Sequoia-X and merge strategy hits into ranking, Excel output, and documentation.

**Architecture:** Strategies live under `src/strategies/` and expose a uniform `evaluate(daily, report_date, factors)` interface. A registry runs enabled strategies from config, aggregates hits per stock, and the scoring/report layers consume `strategy_score`, `matched_strategies`, and `strategy_reason`.

**Tech Stack:** Python, pandas, pytest, openpyxl, existing SQLite/data pipeline.

---

## Tasks

1. Extend config with `StrategyConfig` and default enabled strategies.
2. Add strategy result model and strategy base helpers.
3. Implement first five strategies: MA volume, turtle breakout, RPS breakout, pullback stable, limit-up shakeout.
4. Add registry aggregation and tests for enabled strategies.
5. Merge strategy columns into `run_daily` factors.
6. Update scoring to include `strategy_score` and append strategy reasons.
7. Update Excel report columns and README.
8. Run full tests, CLI help, merge to `main`, push to GitHub.

## Verification

- `python -m pytest -v`
- `python run_daily.py --help`

