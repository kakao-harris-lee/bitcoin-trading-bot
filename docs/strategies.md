# Trading Strategies Reference

> Current scope note (2026-04-24): this document covers the active Binance spot-only runtime. Removed futures, short, hedge, and sideways paths are listed only as archived families at the bottom for clarity.

This document describes the strategies that are active in the current runtime.

## Current Runtime

- Trading, paper execution, backtesting, and dashboard views are spot-only.
- The runtime does not open futures, short, hedge, or sideways-only positions.
- Strategy wiring is driven by `config/strategies/allocation.json` through the component engine.

## Active Strategy Catalog

| Strategy | Symbols | Direction | Entry Source | Exit Source | Notes |
|---|---|---|---|---|---|
| `mlp_direction_btc` | `BTC` | Long | MLP + regime-aware fallback | Hybrid long exit | Conservative major-asset sleeve |
| `mlp_direction_eth` | `ETH` | Long | MLP + regime-aware fallback | Hybrid long exit | Conservative major-asset sleeve |
| `mlp_direction_bnb` | Dynamic universe | Long | Selector + MLP + regime-aware fallback | Hybrid long exit | Rotates into strong spot symbols |

## Shared Architecture

All active strategies use the component engine:

- `CompositeTask`: owns stream I/O, state, persistence, and orchestration.
- `StrategyFactory`: resolves entry/exit components from config.
- `TradingContextBuilder`: builds the shared indicator and regime context.
- `StateManager`: persists component state in Redis.

## Entry Logic

### `mlp_direction_btc` / `mlp_direction_eth`

- Primary signal is the MLP ensemble classification.
- Regime-aware fallback is allowed only under the configured guard rails.
- Entry filters can block trades on regime, volume, freshness, or risk conditions.

### `mlp_direction_bnb`

- Uses `symbol_selector` to rank the tracked spot universe.
- Selector persistence, DQ checks, and per-symbol routing control which symbols are eligible.
- Only selected symbols are allowed to pass through to entry evaluation.
- Fallback entry is stricter than before and is now limited to curated symbols and contexts.

## Exit Logic

All active sleeves use `HybridLong`-style exit control with spot-only semantics.

Common behaviors:

- MLP sell confidence thresholds
- trailing stop and ATR-based stop logic
- regime protection (`EMA120`, bear regime guards)
- drawdown protection with bull-continuation grace rules
- intrabar stop protection with same-candle and bull-wick guards

Recent runtime tuning focuses on:

- letting strong uptrends stay open longer
- reducing premature `regime_protect` exits
- reducing false `intrabar stop` exits from wick noise
- shifting realized exits from risk cuts toward trailing-stop profit capture

## Selector and Rotation

The dynamic universe sleeve is configured in `allocation.json`.

Important selector controls:

- `top_n`
- `entry_ready_score`
- `min_consecutive_eligible`
- `entry_ready_min_consecutive`
- `symbol_score_multipliers`
- `stale` / `data quality` gating

Operational intent:

- suppress noisy or persistently weak symbols
- boost symbols with stronger forward and paper evidence
- avoid churn from one-refresh candidates
- bias toward symbols entering bullish continuation phases

## Data and Regime Dependencies

The active runtime depends on:

- Binance spot book ticker / mini ticker feeds
- shared OHLCV indicator context
- regime classification from the component context
- Redis-backed state and event streams
- paper/live trade logs in `logs/` and `data/`

## Archived Strategy Families

The following are not part of the active runtime anymore:

- futures execution
- `short_v1`
- `sideways_v2`
- hedge / premium / kimchi subsystems
- liquidation and funding-driven futures controls

Older docs or specs may still mention those designs. Treat them as archived historical references unless they explicitly say they are current.
