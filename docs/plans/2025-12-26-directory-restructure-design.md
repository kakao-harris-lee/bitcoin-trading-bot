# Directory Restructure Design

**Date:** 2025-12-26
**Status:** Approved
**Goal:** Full domain restructure for development clarity, production stability, and maintenance reduction

## Current Problems

1. **Strategy duplication** - Same strategies in `strategies/` and `trading/modules/`
2. **Archive bloat** - 78M of archived strategies in working tree
3. **Market classification scattered** - 4 different implementations
4. **Inconsistent module organization** - Strategies in multiple places
5. **Config scattered** - 5+ locations for configuration
6. **Thin core library** - Most logic in `trading/` instead of shared

## New Structure

```
bitcoin-trading-bot/
├── run.py                      # Single entry point
├── trading/                    # All trading engine code
│   ├── engine.py               # Orchestrator (slimmed down)
│   ├── data/                   # Data loading, feeds, market data
│   │   ├── __init__.py
│   │   ├── feed_handler.py
│   │   ├── market_data.py
│   │   └── candle_builder.py
│   ├── strategy/               # Legacy strategy logic (non-component)
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── classifier.py       # Unified MarketClassifier
│   │   ├── regime_router.py
│   │   ├── short_v1.py
│   │   ├── sideways_v2.py
│   │   ├── h4_conservative.py
│   │   └── h4_short.py
│   ├── strategies/             # Component strategies
│   │   └── components/
│   │       ├── v35_classic_entry.py
│   │       ├── v35_classic_exit.py
│   │       ├── v35_entry.py
│   │       └── v35_trailing_exit.py
│   ├── execution/              # Order execution, position management
│   │   ├── __init__.py
│   │   ├── order_manager.py
│   │   ├── position_manager.py
│   │   ├── execution_manager.py
│   │   └── paper_account.py
│   ├── risk/                   # Risk controls, limits, kill switches
│   │   ├── __init__.py
│   │   ├── risk_manager.py
│   │   ├── risk_controls.py
│   │   └── trade_logger.py
│   ├── notification/           # Telegram alerts & commands
│   │   ├── __init__.py
│   │   ├── telegram_notifier.py
│   │   └── telegram_commands.py
│   └── adapters/               # Exchange adapters
│       ├── __init__.py
│       ├── base.py
│       ├── upbit.py
│       ├── binance.py
│       └── live_adapters.py
├── core/                       # Shared utilities
│   ├── __init__.py
│   ├── backtester.py
│   ├── data_loader.py
│   ├── indicators.py
│   └── types.py
├── config/                     # All configuration files
│   ├── trading.json
│   ├── strategies/
│   │   └── allocation.json
│   ├── tuned/
│   │   └── tuned_v35_long_v2_core_overlay_v2.json
│   └── exchanges/
│       ├── upbit.json
│       └── binance.json
├── scripts/                    # CLI tools
│   ├── __init__.py
│   ├── backtest.py
│   ├── optimize.py
│   ├── collect_data.py
│   ├── validate.py
│   └── tune.py
├── tests/                      # Mirrors trading/ structure
│   ├── conftest.py
│   ├── trading/
│   │   ├── data/
│   │   ├── strategy/
│   │   ├── execution/
│   │   ├── risk/
│   │   └── adapters/
│   ├── core/
│   └── integration/
├── web/                        # Dashboard
├── data/                       # Database files
│   ├── upbit_bitcoin.db
│   └── trading_results.db
└── docs/                       # Documentation
```

## Migration Plan

### Phase 1: Clean Archives
- Delete `_archive/`, `_deprecated/` directories
- Delete `strategies/v-a-*`, `strategies/v31-v45`
- Delete `validation/` directory
- **Commit:** "chore: remove archived files from working tree"

### Phase 2: Create New Structure
- Create new directories
- **Commit:** "chore: create new directory structure"

### Phase 3: Move Files
- Move files to new locations without modifying content
- Update `__init__.py` files
- **Commit:** "refactor: move files to new locations"

### Phase 4: Fix Imports
- Update all import statements
- Run tests after each update
- **Commit:** "refactor: update import paths"

### Phase 5: Consolidate Duplicates
- Merge MarketClassifier implementations into `trading/strategy/classifier.py`
- Consolidate strategy configs into `config/strategies/`
- **Commit:** "refactor: consolidate duplicated code"

### Phase 6: Slim Down engine.py
- Extract large functions into submodules
- Keep as orchestrator only
- **Commit:** "refactor: simplify engine.py"

### Phase 7: Update Documentation
- Update `CLAUDE.md`, `docs/DEPLOYMENT.md`
- **Commit:** "docs: update for new structure"

## File Mapping

| Current Location | New Location |
|-----------------|--------------|
| `trading/modules/v35_long_strategy.py` | `trading/strategies/components/v35_entry.py` + `trading/strategies/components/v35_trailing_exit.py` |
| `trading/modules/short_v1_strategy.py` | `trading/strategy/short_v1.py` |
| `trading/modules/strategies/sideways_v2.py` | `trading/strategy/sideways_v2.py` |
| `trading/modules/strategies/h4_*.py` | `trading/strategy/h4_*.py` |
| `trading/modules/regime_router.py` | `trading/strategy/regime_router.py` |
| `trading/modules/base_strategy.py` | `trading/strategy/base.py` |
| `trading/modules/feed_handler.py` | `trading/streams/binance_feed.py` |
| `trading/modules/position_manager.py` | `trading/strategies/components/context_builder.py` |
| `trading/modules/execution_manager.py` | `trading/execution/execution_manager.py` |
| `trading/modules/risk_manager.py` | `trading/risk/risk_manager.py` |
| `trading/adapters/paper_account.py` | `trading/executor/paper_executor.py` |
| `trading/core/risk_controls.py` | `trading/risk/risk_controls.py` |
| `trading/core/trade_logger.py` | `trading/risk/trade_logger.py` |
| `trading/core/message_types.py` | `core/types.py` |
| `strategies/v35_optimized/config_optimized.json` | `config/strategies/allocation.json` |
| `strategies/SHORT_V1/config.json` | `config/strategies/short_v1.json` |
| `analysis/selected_candidate.json` | `config/tuned/tuned_v35_long_v2_core_overlay_v2.json` |
| `upbit_history_db/upbit_bitcoin.db` | `data/upbit_bitcoin.db` |
| `automation/collect_missing_data.py` | `scripts/collect_data.py` |
| `trading/scripts/backtest_*.py` | `scripts/backtest.py` |

## Files to Delete

| Directory | Size | Reason |
|-----------|------|--------|
| `strategies/_archive/` | ~50M | In git history |
| `strategies/_deprecated/` | ~10M | In git history |
| `strategies/_reports/` | ~5M | In git history |
| `strategies/_library/` | ~2M | Unused |
| `strategies/v-a-*` (01-15) | ~10M | In git history |
| `automation/_archive/` | ~1M | In git history |
| `validation/_archive/` | ~8M | In git history |
| `core/_archive/` | ~0.5M | In git history |

**Total cleanup: ~85M removed**

## Success Criteria

- All tests pass after restructuring
- `python run.py --mode paper` works
- No duplicate strategy implementations
- Single MarketClassifier source
- All configs in `config/` directory
- Clear module boundaries
