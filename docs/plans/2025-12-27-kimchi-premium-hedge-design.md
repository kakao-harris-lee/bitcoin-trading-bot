# Kimchi Premium Hedged Trading Design

**Date:** 2025-12-27
**Status:** Phase 1 & 2 Complete
**Goal:** Test hedged trading utilizing Kimchi Premium by running concurrent long (Upbit) and short (Binance) positions

## Overview

The Kimchi Premium represents the price difference between Korean exchanges (Upbit, KRW) and international exchanges (Binance, USDT). By running hedged positions:
- **Long on Upbit** (v35_long or va02_long) - profits from premium + BTC upside
- **Short on Binance** (SHORT_V1) - offsets BTC price volatility

This creates a market-neutral position that captures the premium differential while minimizing directional exposure.

## Current Architecture

### What Exists

| Component | Status | Location |
|-----------|--------|----------|
| Dual exchange engine | Ready | `trading/engine.py` |
| Concurrent Upbit strategies | Ready | `_execute_upbit_strategies_concurrent()` |
| Binance SHORT_V1 strategy | Ready | `execute_binance_strategy()` |
| Allocation config | Partial | `config/strategies/allocation.json` |
| Risk controls | Ready | `trading/risk/risk_controls.py` |
| Kill-switch via Telegram | Ready | `/kill_on`, `/kill_off` commands |

### Current Limitations

1. `allocation.json` only defines Upbit strategies - no Binance allocation
2. `binance_gate_mode` default is `bear_only` - hedging disabled in BULL/SIDEWAYS

## Configuration Changes

### 1. Extended allocation.json

```json
{
  "capital_split": {
    "upbit_ratio": 0.6,
    "binance_ratio": 0.4,
    "description": "60% Upbit spot, 40% Binance futures"
  },
  "upbit": {
    "v35": {
      "ratio": 0.5,
      "enabled": true,
      "regimes": ["BULL"]
    },
    "va02": {
      "ratio": 0.5,
      "enabled": true,
      "regimes": ["BULL", "SIDEWAYS"]
    }
  },
  "binance": {
    "short_v1": {
      "ratio": 1.0,
      "enabled": true,
      "regimes": ["SIDEWAYS", "BEAR"],
      "hedge_mode": true,
      "description": "Hedge Upbit longs when premium capture active"
    }
  }
}
```

### 2. Engine Launch Parameters

```bash
# Paper trading with hedging enabled
python run.py --mode paper \
  --binance-gate-mode sideways_and_bear \
  --telegram-commands
```

### 3. Risk Configuration

Update `config/tuned/selected_candidate.json`:

```json
{
  "risk_config": {
    "daily_max_loss_pct": 5.0,
    "max_upbit_entry_fraction": 0.6,
    "max_binance_entry_fraction": 0.4,
    "recommend_kill_on_daily_loss_pct": 4.0
  }
}
```

## Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    DualPaperTradingEngine                       │
├─────────────────────────────────────────────────────────────────┤
│  1. Fetch prices: Upbit (KRW), Binance (USDT)                   │
│  2. Calculate regime via RegimeRouter (MFI + ADX)               │
│  3. Execute strategies concurrently:                            │
│     ┌─────────────────────┐    ┌─────────────────────┐          │
│     │   Upbit (Spot)      │    │   Binance (Futures) │          │
│     │   v35 / va02 LONG   │    │   SHORT_V1          │          │
│     │   60% capital       │    │   40% capital       │          │
│     └─────────────────────┘    └─────────────────────┘          │
│  4. Independent P&L tracking per exchange                       │
│  5. Risk checks: daily loss guard, kill-switch                  │
└─────────────────────────────────────────────────────────────────┘
```

## Hedge Ratio Logic

Current implementation tracks hedge ratio dynamically:

```python
hedge_ratio = short_exposure / long_exposure
# Bounded: 0.3 <= hedge_ratio <= 0.7
```

For Kimchi Premium capture, target hedge ratio should be ~1.0 (fully hedged):

| Regime | Target Hedge | Upbit Action | Binance Action |
|--------|--------------|--------------|----------------|
| BULL | 0.4-0.6 | v35/va02 active | SHORT_V1 partial |
| SIDEWAYS | 0.8-1.0 | va02 active | SHORT_V1 full |
| BEAR | 0.3-0.5 | Hold/reduce | SHORT_V1 full |

## Risk Management

### Safety Guards

1. **Kill-Switch**: File-based (`analysis/KILL_SWITCH`) + Telegram commands
2. **Daily Loss Limit**: 5% combined P&L triggers entry block
3. **Per-Exchange Caps**: 60% Upbit, 40% Binance max entry fraction
4. **Leverage Limit**: Binance SHORT_V1 max 2x (ISOLATED margin)

### Monitoring

```bash
# Start with Telegram commands enabled
./bot.sh start paper --telegram-commands

# Manual intervention
/kill_on   - Enable kill switch
/kill_off  - Disable kill switch
/kill_status - Check status
```

## Validation Criteria

### Paper Trading Phase

1. Run minimum 2 weeks in paper mode
2. Monitor hedge ratio stability
3. Verify independent P&L tracking per exchange
4. Confirm Telegram commands work

### Backtesting Standard (Before Live)

| Metric | Requirement |
|--------|-------------|
| Period | 2025-01-01 ~ present (OOS) |
| Sharpe Ratio | >= 1.5 |
| Max Drawdown | <= 20% |
| Win Rate | >= 45% |

### Backtest Command

```bash
python scripts/backtest.py \
  --strategy hedged_premium \
  --start 2025-01-01 \
  --end 2025-12-27 \
  --upbit-strategy v35,va02 \
  --binance-strategy short_v1 \
  --hedge-mode
```

## Implementation Phases

### Phase 1: Configuration Only (No Code Changes)

1. Update `config/strategies/allocation.json` with Binance section
2. Launch paper trading with `--binance-gate-mode sideways_and_bear`
3. Monitor via dashboard

### Phase 2: Hedge Ratio Tuning (Minor Code Changes)

1. Adjust `min_hedge_ratio` and `max_hedge_ratio` in `RiskConfig`
2. Add per-regime hedge ratio targets
3. Log premium differential for analysis

### Phase 3: Premium Tracking (Future Enhancement)

1. Calculate real-time Kimchi Premium: `(upbit_price_usd - binance_price) / binance_price`
2. Incorporate premium volatility into hedge ratio adjustment
3. Alert when premium exceeds historical norms

## Files to Modify

| File | Change |
|------|--------|
| `config/strategies/allocation.json` | Add Binance section, capital_split |
| `config/tuned/selected_candidate.json` | Update risk_config |
| `trading/engine.py` | Read Binance allocation (Phase 2) |
| `trading/risk/risk_controls.py` | Per-regime hedge targets (Phase 2) |

## Quick Start

```bash
# 1. Update allocation.json (see above)

# 2. Start paper trading
./bot.sh start paper

# Or with explicit hedge mode
python run.py --mode paper --binance-gate-mode sideways_and_bear --telegram-commands

# 3. Monitor dashboard
python -m web.app

# 4. View logs
./bot.sh logs
```

## Open Questions

1. **Capital split ratio**: 60/40 or 50/50?
2. **Hedge ratio bounds**: Should they vary by regime?
3. **Premium threshold**: At what premium level should hedging activate?
