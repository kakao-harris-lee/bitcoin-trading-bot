# Implementation Plan: Improve Short V1 Strategy

**Branch**: `001-improve-short-v1` | **Date**: 2026-01-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-improve-short-v1/spec.md`

## Summary

Enhance the Binance Short V1 strategy for bear market trading with:
1. Improved entry signal quality (ADX trend direction filter, multi-indicator confirmation)
2. ATR-based stop loss with volatility buffer
3. Two-tier profit taking (50% at 1R, trailing stop for remaining 50%)
4. Edge case handling (conflicting signals, gap openings, extreme volatility)

## Technical Context

**Language/Version**: Python 3.10+ with type hints
**Primary Dependencies**: pandas, numpy, talib (via trading.indicators.technical)
**Storage**: SQLite (data/*.db for market data), JSON (config/strategies/*.json)
**Testing**: pytest (existing test suite in tests/)
**Target Platform**: Linux server (Docker/docker-compose)
**Project Type**: Single project (trading bot)
**Performance Goals**: 4H candle processing, real-time signal generation
**Constraints**: 2x max leverage, 5% max stop loss, 0.14% fee overhead
**Scale/Scope**: Single asset (BTCUSDT), Binance Futures only

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Backtesting-First | ✅ PASS | Validation via 2020-2024 training, 2025+ OOS |
| II. Git-Based Workflow | ✅ PASS | Feature branch 001-improve-short-v1 created |
| III. Risk-Aware Trading | ✅ PASS | 1.4% min profit target, 5% max SL, 2x leverage |
| IV. Reactive Strategies Only | ✅ PASS | Momentum-following (EMA/ADX), no mean-reversion |
| V. Simplicity | ⚠️ CHECK | Uses EMA, ADX, ATR (3 indicators) - at limit |

**Gate Result**: PASS - All principles satisfied. Indicator count at limit (3) but justified for entry quality + volatility-adjusted SL.

## Project Structure

### Documentation (this feature)

```text
specs/001-improve-short-v1/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (internal interfaces)
├── checklists/          # Validation checklists
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
trading/
├── strategy/
│   ├── base.py              # BaseStrategy (unchanged)
│   ├── short_v1.py          # Current implementation (to be enhanced)
│   └── regime_router.py     # RegimeRouter (unchanged)
├── indicators/
│   └── technical.py         # EMA, ADX, ATR functions (existing)
└── core/
    └── types.py             # TradeSignal types (may extend)

config/
└── strategies/
    └── short_v1.json        # Strategy configuration (to be updated)

tests/
├── test_optimize_short_v1.py  # Existing optimization tests
└── trading/
    └── test_short_v1_improved.py  # New tests for improvements
```

**Structure Decision**: Enhance existing `trading/strategy/short_v1.py` and `config/strategies/short_v1.json`. No new files required except tests.

## Complexity Tracking

> No constitution violations requiring justification.

| Item | Status | Notes |
|------|--------|-------|
| 3 indicators (EMA, ADX, ATR) | At limit | ATR needed for volatility-adjusted SL (FR-004) |
| Two-tier exit | Acceptable | Single position, managed exits (not split trading) |
| Trailing stop | Acceptable | Standard risk management technique |
