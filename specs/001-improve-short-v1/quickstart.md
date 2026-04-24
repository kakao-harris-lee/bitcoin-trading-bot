# Quickstart: Improved Short V1 Strategy

> Archived spec note (2026-04-24): the retired short_v1 futures path has been removed from the active runtime. This spec remains only as historical reference and should not be used for current implementation planning.


**Feature**: 001-improve-short-v1
**Date**: 2026-01-09

## Overview

Enhanced Binance Futures short strategy for bear market conditions with:
- ATR-based volatility-adjusted stop loss
- Two-tier profit taking (50% at 1R, trailing stop for remainder)
- ADX trend direction filter to avoid weakening trends
- Extreme volatility protection

## Prerequisites

- Python 3.10+
- Existing trading bot setup with Binance Futures access
- Historical data in `data/binance_bitcoin.db`

## Quick Test

### 1. Run Backtest

```bash
# Activate virtual environment
source .venv/bin/activate

# Run backtest with improved strategy
python scripts/backtest.py \
    --strategy short_v1 \
    --exchange binance \
    --start 2020-01-01 \
    --end 2024-12-31 \
    --config config/strategies/short_v1.json
```

### 2. Validate Against Current

```bash
# Compare improved vs current implementation
python scripts/backtest.py \
    --strategy short_v1 \
    --compare-baseline \
    --start 2025-01-01 \
    --end 2025-12-31
```

### 3. Check Success Criteria

| Metric | Target | Command |
|--------|--------|---------|
| OOS Return | ≥5pp improvement | `--metrics return` |
| Sharpe Ratio | ≥1.5 | `--metrics sharpe` |
| Max Drawdown | ≤20% | `--metrics mdd` |
| Win Rate | ≥45% | `--metrics winrate` |
| R:R Ratio | ≥2.0 | `--metrics rr` |

## Configuration

### Default Config (Enhanced)

```json
{
  "strategy_name": "SHORT_V1",
  "description": "Enhanced EMA/ADX short strategy with ATR stops",
  "symbol": "BTCUSDT",
  "timeframe": "4h",
  "indicators": {
    "ema_fast": 68,
    "ema_slow": 128,
    "adx_period": 14,
    "atr_period": 14
  },
  "entry": {
    "require_death_cross": true,
    "adx_min": 25,
    "adx_slope_bars": 3,
    "require_adx_not_declining": true,
    "di_negative_dominant": true
  },
  "exit": {
    "two_tier_enabled": true,
    "first_tier_pct": 0.5,
    "first_tier_r_multiple": 1.0,
    "second_tier_r_multiple": 2.0,
    "trailing_stop_atr_multiplier": 1.5,
    "exit_on_golden_cross": true
  },
  "stop_loss": {
    "atr_buffer_multiplier": 1.5,
    "max_stop_loss_pct": 5.0
  },
  "risk_management": {
    "max_leverage": 2,
    "extreme_volatility_threshold": 0.10,
    "halt_entries_on_extreme_vol": true
  }
}
```

### Key Parameters to Tune

| Parameter | Range | Impact |
|-----------|-------|--------|
| `adx_min` | 20-35 | Higher = fewer but stronger entries |
| `atr_buffer_multiplier` | 1.0-2.5 | Higher = wider stops, fewer stop-outs |
| `trailing_stop_atr_multiplier` | 1.0-2.0 | Lower = tighter trail, earlier exits |
| `first_tier_r_multiple` | 0.5-1.5 | Lower = earlier partial profit |

## Paper Trading

```bash
# Start in paper mode (default)
./bot.sh start

# Monitor logs
./bot.sh logs

# Check position state
curl http://localhost:8080/api/strategy/short_v1/state
```

## Live Trading

```bash
# Enable live trading (requires explicit flag)
ENABLE_LIVE_TRADING=1 ./bot.sh start --trend=live

# Monitor via Telegram bot commands
# /status - Current position
# /kill_on - Emergency stop
```

## Validation Checklist

Before deploying to live:

- [ ] Backtest OOS return meets target (≥5pp improvement)
- [ ] Sharpe ratio ≥1.5 on validation period
- [ ] Max drawdown ≤20%
- [ ] At least 10 trades in BEAR regime for statistical significance
- [ ] Paper trading confirms signal generation works
- [ ] Telegram notifications functional
- [ ] Kill switch tested

## Troubleshooting

### No Entries Generated

1. Check market regime: `curl http://localhost:8080/api/regime`
2. Verify ADX threshold not too high
3. Check for extreme volatility flag
4. Ensure ADX is not declining

### Premature Stop-Outs

1. Increase `atr_buffer_multiplier` (try 2.0)
2. Verify ATR period matches volatility regime
3. Check max stop loss cap not too tight

### Partial Exit Not Triggering

1. Confirm `two_tier_enabled: true`
2. Verify `first_tier_r_multiple` achievable given stops
3. Check position tracking state

## Files Modified

| File | Changes |
|------|---------|
| `trading/strategy/short_v1.py` | Enhanced entry/exit logic |
| `config/strategies/short_v1.json` | New configuration parameters |
| `tests/trading/test_short_v1_improved.py` | New test cases |
