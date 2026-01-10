# Repository Guidelines

## Project Structure & Module Organization
Production code lives in `src/`. Core plumbing (signal bus, budget manager, PnL tracker, MCP/Gamma clients) is in `src/core/`, strategies live in `src/strategies/`, while `src/news/` ingests headlines and `src/ai/` houses LLM/RAG helpers. `src/swarm/` orchestrates agents, `src/ui/` renders dashboards, and `src/arena/` plus `src/backtest/` support simulations. Standalone utilities (`run_swarm.py`, `start_swarm.sh`, `run_simulation.py`) boot the system. Tests you must keep green sit in `tests/` (e.g., `tests/test_mcp_history.py`, `tests/test_allocation_manager.py`) with extra scenario assets in `data/` and long-form docs in `docs/`. Runtime artifacts belong in `logs/`.

## Build, Test, and Development Commands
Set up a virtualenv, then install dependencies with `python3 -m pip install -r requirements.txt`. Use `./start_swarm.sh --dry-run` for the canonical local launch; pass `--bots news_scalper arbhunter statarb` or `--budget 250` to scope experiments. For single-run debugging you can call `python3 run_swarm.py --dry-run --ui`. Keep unit and integration suites green with `python3 -m pytest tests/test_mcp_history.py tests/test_allocation_manager.py`; add targeted invocations (for example `python3 -m pytest tests/test_mcp_history.py::test_history_api_prefers_mcp`) to reproduce regressions quickly. Capture logs via `python3 run_swarm.py --dry-run > logs/smoke.log`.

## Coding Style & Naming Conventions
The repository is asyncio-first with 4-space indentation, type hints, and dataclasses for structured payloads (`MarketSignal`, allocation configs). Keep modules and functions in `snake_case`, classes in `PascalCase`, and constants in ALL_CAPS. Follow the existing `logging.getLogger(__name__)` pattern so swarm dashboards and telemetry stay uniform; avoid ad-hoc prints. Place configuration flags in shared config modules or `.env` accessors rather than scattering literals, and keep network/IO functions cancellable via timeouts.

## Testing Guidelines
Write pytest tests with descriptive `test_<behavior>` names and `@pytest.mark.anyio` for async coroutines (the history suite already uses this). When touching MCP/Gamma integrations add fixtures or stubs in `tests/` to avoid live calls. Backtest helpers and allocation math belong under `tests/test_allocation_manager.py`; history client changes require new assertions in `tests/test_mcp_history.py`. Capture failure modes with synthetic data under `data/` whenever possible to keep CI deterministic.

## Commit & Pull Request Guidelines
Use Conventional Commit prefixes (`feat:`, `fix:`, `chore:`, `docs:`) and write imperative subjects (“feat: add MCP fallback cache”). Every PR should list impacted bots or subsystems, mention new env vars/config toggles, and attach `pytest` output plus (for runtime work) a trimmed `./start_swarm.sh --dry-run` log excerpt or dashboard screenshot. Never push secrets; update `.env.example` and document rotation steps in `docs/` when credentials change.

## Security & Configuration Tips
Secrets load via `.env`; keep a sanitized `.env.example` current and remind reviewers to source it. Validate network dependencies (Polygon RPC, Telegram) before live runs, and prefer `--dry-run` with conservative budgets until a strategy records multiple wins. Use read-only API keys for MCP/Gamma where possible and ensure any webhooks/PM2 configs reference the least-privileged credentials. Keep Redis or other stateful services local (via Docker) when prototyping to avoid leaking production data.
