# Repository Guidelines

## Project Structure & Module Organization
Source code lives in `src/` with clear domains: `core/` holds primitives (see `src/core/signal_bus.py`), `strategies/` + `swarm/` orchestrate live agents, `news/` and `ai/` ingest signals, `ui/` provides the dashboard, and `src/arena/` plus `src/backtest/` power simulations. Framework-level tests run from `tests/`, while targeted module tests live in `src/tests/`. Keep reusable samples in `data/`, documentation in `docs/`, and runtime output inside `logs/`.

## Build, Test, and Development Commands
Install dependencies with `python3 -m pip install -r requirements.txt`. Launch the unified swarm via `python3 run_swarm.py --dry-run --ui --budget 1000.0`; scope experiments with `--bots news_scalper arbhunter pure_arb`. Run the full suite using `python3 -m pytest tests/test_swarm.py -v`, or target scenarios such as `python3 -m pytest tests/test_swarm.py::test_signal_publish_subscribe -v`. Bring up Redis locally through `docker run -d -p 6379:6379 --name redis redis:alpine` before exercising BudgetManager code.

## Coding Style & Naming Conventions
Write asynchronous Python with 4-space indentation, descriptive module docstrings, and type hints on public functions. Prefer dataclasses for structured payloads (`MarketSignal`) and keep async APIs cancellable with timeouts. Stick to `snake_case` for modules/functions and `PascalCase` for classes, and centralize configuration constants in shared config modules. Use the provided `logging` instances so CLI dashboards and PM2 logs stay consistent.

## Testing Guidelines
Pytest drives validation, so new behavior should come with `test_<behavior>` functions and `@pytest.mark.asyncio` blocks for cooperative coroutines. Extend `tests/test_swarm.py` whenever SignalBus, BudgetManager, or cross-agent flows change, capturing latency expectations and Redis fallbacks. Module-level checks can sit under `src/tests/` with lightweight fixtures or static files from `data/` to avoid external API calls.

## Commit & Pull Request Guidelines
History follows Conventional Commit prefixes (`feat:`, `fix:`, `chore:`) with imperative subjects, so continue that pattern and keep the body focused on agent or infrastructure impact. PRs should list affected bots, configuration toggles, and linked issues, plus attach `pytest` output and at least one `run_swarm.py --dry-run` log excerpt or dashboard screenshot. Never commit secrets; update `.env.example` and reference the change in docs instead.

## Security & Configuration Tips
Secrets load from `.env`; regenerate `.env.example` whenever new keys are required and remind reviewers in PR descriptions. Confirm Redis availability with `redis-cli ping` before launching agents, and prefer `--dry-run` with conservative budgets when validating new strategies.
