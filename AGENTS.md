# AGENTS.md

## Mission

This repository is a local, explainable A-share post-market selector. It updates daily bars, scores the market, sectors and stocks, applies configurable strategies and risk penalties, then generates Excel and responsive web reports. It never submits orders.

## Start Here

Read these files before changing behavior:

1. `README.md` for user workflows
2. `docs/ARCHITECTURE.md` for module boundaries and data flow
3. `docs/STRATEGIES.md` for strategy semantics
4. `docs/CONFIGURATION.md` for every supported setting and unit
5. `config/strategy.yml`, `config/stock_pool.yml`, and `config/custom_strategies.yml` for active values

Main entry points:

- `run_daily.py` delegates to `src.run_daily.run`
- `python -m src.panel` starts the FastAPI panel
- `scripts/bootstrap.py` owns one-click environment setup
- `scripts/publish_pages.py` publishes only `site/`

## Architecture

- `src/fetch_data.py`: provider adapters and parallel TDX backfill
- `src/database.py`: SQLite schema, upserts, health, run and selection history
- `src/build_pool.py`: eligibility filters
- `src/market_score.py`, `sector_score.py`: environment factors
- `src/stock_character.py`, `volume_price_score.py`: stock factors
- `src/stock_context.py`: cached industry, concept, limit-up clue, and sector-stage narratives for ranked candidates
- `src/strategies/`: independent strategy signals and shared feature cache
- `src/custom_formulas.py`: safe declarative formula validation, evaluation, and result projection
- `src/risk_filter.py`, `scoring.py`: penalties and ranking
- `src/report.py`: styled Excel output
- `src/web_report.py`: JSON/static report output
- `src/panel.py`: local API and background task runner
- `src/scheduler.py`: fixed-command Windows scheduled-task boundary
- `web/`: build-free HTML/CSS/JS shared by local panel and Pages
- `site/`: generated, publishable static output

## Non-Negotiable Behavior

- Default provider is `tdx`, which needs no account login.
- Keep Baostock optional and conservative. Do not increase its concurrency or retry loops; upstream blacklisting is a known operational risk.
- Initialization must remain resumable and validate stock coverage, row count and index count.
- Daily updates must remain incremental.
- A single symbol failure must not abort the whole universe unless a circuit breaker identifies systemic provider failure.
- Do not commit `data/*.db`, logs, Excel reports or virtual environments.
- GitHub Pages may receive only generated static files under `site/`.
- The panel binds to `127.0.0.1` by default. Public server deployment requires reverse-proxy authentication and HTTPS.
- Scheduled-task management must keep the task name and script paths fixed. Never accept arbitrary shell commands from the panel.
- Strategy scores are aggregated by family maximum, then summed across families. Do not restore naive summation of related strategies.
- Every selected stock must retain an explainable reason and risk warning.
- Custom formulas are an independent observation surface and must not silently alter the main ranking.
- Custom formulas must remain declarative and allowlisted. Never add `eval`, arbitrary Python expressions, uploaded scripts, or dynamic imports.
- Treat concept and limit-up context as best-effort enrichment. Label inferred relationships as clues, never as confirmed news causes.
- Market-board exclusion must recognize both current and legacy Beijing Exchange code prefixes.

## Strategy Development

All strategies subclass `src.strategies.base.Strategy` and define:

- `key`
- `name`
- `family`
- `description`
- `score`
- `evaluate(...)`

Use the shared frame from `build_strategy_features`. Avoid recalculating moving averages, volatility or breakouts inside each strategy. Register new strategies in `src/strategies/registry.py`, assign a family and add focused tests.

Current families: `breakout`, `trend`, `pullback`, `event`, `sector`.

Custom chart-derived rules live in `config/custom_strategies.yml`. Add indicator fields to the shared feature builder only when a requested formula cannot be expressed with existing fields. Formula failures must be isolated so the main daily report still completes.

## Data and Schema

SQLite tables include market data plus:

- `stock_sync_status` for resumable provider migration/backfill
- `stock_context`, `stock_event`, and `sector_context` for cached candidate narratives
- `selection_history` for Top N snapshots and forward returns
- `run_history` for panel and scheduled-run visibility

Schema changes must be additive and safe for an existing `data/stock.db`. `CREATE TABLE IF NOT EXISTS` is the current migration mechanism.

## Frontend Rules

The interface is an operational dashboard, not a marketing page.

- Preserve responsive desktop/mobile layouts.
- Keep local-only controls marked with `local-only` so Pages stays read-only.
- Avoid build tooling unless it solves a real maintenance problem.
- Keep the JSON contract in `src/web_report.py` backward compatible or increment `schema_version`.
- Keep built-in strategy configuration and custom-formula results as separate navigation and data contracts.
- Test desktop and mobile layouts after meaningful UI changes.

## Verification

Run the focused tests while editing, then the full suite:

```powershell
.\.venv\Scripts\python.exe -m compileall -q src scripts
.\.venv\Scripts\python.exe -m pytest -q
```

For pipeline changes, run against the existing database with a known date and verify:

- Excel opens and required sheets exist
- `site/data/latest.json` is valid JSON
- the panel serves `/api/status` and `/api/latest`
- no unexpected full-history fetch occurs on a daily run

For deployment changes, validate `docker compose config` and inspect the Pages workflow.

## Git and Generated Files

The user may have unrelated work in the tree. Never revert it.

Generated static reports under `site/` are intentionally trackable for Pages. Historical JSON retention is controlled by `report.history_days`. The publish script stages only `site/`.

Before committing, scan Chinese text files for replacement characters or accidental question-mark corruption.
