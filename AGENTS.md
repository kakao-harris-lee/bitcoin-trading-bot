# Repository Guidelines

## Project Structure
- `trading/` holds engine/strategy components (entry/exit interfaces, StrategyFactory, Redis-backed tasks); `core/` has backtester and shared utilities.
- `config/strategies/allocation.json` controls enabled strategies; `config/tuned/` stores ML-tuned params.
- Scripts and automation live in `scripts/` and `bot.sh`; `web/` is the dashboard; data/log artifacts under `data/` and `logs/`.
- Tests reside in `tests/` (bot) and `lstm_trainer/tests/` (price predictor).

## Build, Run, and Test
- Install deps: `pip install -r requirements.txt` (use `.venv`).
- Paper trading: `python run.py --trend paper` or `./bot.sh start --trend paper`; restart with `./bot.sh restart --trend paper`.
- Live trading (opt-in): set `ENABLE_LIVE_TRADING=1` then `python run.py --trend live`.
- Backtest/optimize: `python scripts/backtest.py` (or `scripts/optimize.py`) with the desired config.
- Tests: `pytest` (unit) or `pytest -m "not integration"` to skip slower suites; Docker option: `docker-compose -f docker-compose.test.yml up --build`.

## Strategy & Config Notes
- Component engine is the default (`use_component_strategies=true`); every strategy in `allocation.json` needs `entry`/`exit` classes or a registry entry.
- Each strategy needs `entry`/`exit` classes or a registry entry; adjust `params` or `regime_routing` in-place.
- Remove or disable any legacy premium/arbitrage configs—the Kimchi premium subsystem is retired.

## Coding Style
- Python 3, 4-space indent, `snake_case` files; prefer typed dataclasses for params.
- Keep I/O async in streams/executor paths; log key decisions (entry/exit reasons, gating).
- Format/lint with `black`, `flake8`, `mypy`; align with existing logging patterns instead of print.

## Testing Guidelines
- Name tests `test_*.py`; use `pytest-asyncio` for coroutine tests.
- Provide fixtures/mocks for Redis and price feeds; tag slow/integration cases with `@pytest.mark.integration`.
- When backtesting new configs, capture the command/commit and attach plots under `logs/` or `trading_results.db`.

## Commit & PR Expectations
- Conventional commits are preferred (`feat(strategy): ...`, `fix(backtest): ...`, `docs: ...`).
- PRs should summarize behavior changes, list test/backtest commands, and call out config modifications (especially `allocation.json` or tuned params).
- Include screenshots/GIFs for dashboard/UI updates when relevant.
