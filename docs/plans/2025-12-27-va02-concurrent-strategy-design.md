# v-a-02 Concurrent Strategy Design

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


**Status:** Implemented (v0.0.4)
**Last Updated:** 2025-12-27

## Overview

Add v-a-02 strategy as an alternative long strategy on Upbit, with regime-based gating via allocation config.

**v-a-02 Background:**
- 7-dimension score-based strategy (RSI, MFI, volume, volatility, local minima, trend, mean reversion)
- 74% win rate in backtesting
- Tier classification: S (>=28), A (>=18), B (>=12), C (<12)

## Design Decisions

| Decision | Choice | Status |
|----------|--------|--------|
| Signal mode | Concurrent - both strategies execute each cycle | Implemented |
| Capital management | Split capital per allocation.json ratios | Implemented |
| v-a-02 regimes | BULL + SIDEWAYS (not BEAR) | Implemented |
| Position tracking | Per-strategy (independent BTC, cash, entry price) | Implemented |

### Implementation Note

**v0.0.4:** Implemented concurrent execution with split capital:
- Both v35 and va02 execute each cycle with independent position tracking
- Capital split based on `allocation.json` ratios (50/50 default)
- Each strategy has its own BTC balance, cash, and entry price
- Dashboard shows per-strategy position status

## Architecture

### File Structure

```
trading/strategy/
├── va02_long.py         # new - ported from git history
└── ...

trading/strategies/components/
├── v35_classic_entry.py          # V35 classic entry
└── v35_classic_exit.py           # V35 classic exit

config/strategies/
├── va02_long.json       # new - score thresholds, weights
└── allocation.json      # new - capital split config
```

### Capital Allocation Config

```json
// config/strategies/allocation.json
{
  "upbit": {
    "v35": { "ratio": 0.5, "enabled": true, "regimes": ["BULL"] },
    "va02": { "ratio": 0.5, "enabled": true, "regimes": ["BULL", "SIDEWAYS"] }
  }
}
```

## v-a-02 Strategy Implementation

### Score Engine (7 dimensions)

```python
class VA02ScoreEngine:
    weights = {
        'rsi_oversold': 8,      # RSI <= threshold
        'mfi_bullish': 28,      # MFI >= 50 (strongest signal)
        'volume_spike': 8,      # volume_ratio >= 1.5
        'low_vol': 15,          # ATR compression (breakout setup)
        'local_min': 20,        # Price at local bottom
        'trend_following': 12,  # ADX >= 25
        'mean_reversion': 10    # Below BB lower band
    }
```

### Signal Generation

- Calculate score for each candle (sum of weighted conditions)
- Classify into tiers: S (>=28), A (>=18), B (>=12), C (<12)
- Entry: S-Tier or A-Tier signals only
- Exit: Score drops below B-Tier OR trailing stop

### Regime Gating

```python
def generate_signal(self, df, i):
    regime = self._classify_regime(df, i)

    if regime.startswith('BEAR'):
        return {'action': 'hold', 'reason': 'BEAR_REGIME_SKIP'}

    score, tier = self._calculate_score(df, i)
    ...
```

## Engine Modifications

### Position Tracking (per strategy)

```python
self._positions = {
    'upbit': {
        'v35': {'btc_balance': 0, 'entry_price': 0, 'cash': 0},
        'va02': {'btc_balance': 0, 'entry_price': 0, 'cash': 0}
    },
    'binance': {...}
}
```

### Execution Flow

```python
def _run_upbit_strategies(self):
    regime = self._get_current_regime()

    # V35 - BULL only
    if regime.startswith('BULL'):
        signal = self._v35_strategy.generate_signal(df, i)
        self._execute_upbit_signal('v35', signal)

    # VA02 - BULL + SIDEWAYS
    if not regime.startswith('BEAR'):
        signal = self._va02_strategy.generate_signal(df, i)
        self._execute_upbit_signal('va02', signal)
```

### Capital Initialization

```python
def _init_capital_allocation(self):
    config = load_json('config/strategies/allocation.json')
    total = self._upbit_capital

    for strategy, settings in config['upbit'].items():
        if settings['enabled']:
            self._positions['upbit'][strategy]['cash'] = total * settings['ratio']
```

## Dashboard & API Updates

### Signal Logging

```python
self._signal_history = {
    'upbit': {
        'v35': [],
        'va02': []
    },
    'binance': {...}
}
```

### API Response

```json
{
  "upbit": {
    "v35": {
      "enabled": true,
      "position": {"btc_balance": 0.001, "entry_price": 130000000},
      "cash": 2500000,
      "return_pct": 0.015
    },
    "va02": {
      "enabled": true,
      "position": null,
      "cash": 2500000,
      "return_pct": 0.0
    }
  }
}
```

### Dashboard Display

- Upbit section splits into two cards: "Upbit - V35" and "Upbit - VA02"
- Each shows position, cash, return, signal history
- Combined total return in header

## Config Files

### va02_long.json

```json
{
  "tier_threshold": "A",
  "weights": {
    "rsi_oversold": 8,
    "mfi_bullish": 28,
    "volume_spike": 8,
    "low_vol": 15,
    "local_min": 20,
    "trend_following": 12,
    "mean_reversion": 10
  },
  "exit": {
    "take_profit": 0.03,
    "stop_loss": 0.02,
    "tier_exit": "C"
  }
}
```

## Implementation Checklist

- [x] Restore v-a-02 score engine from git history
- [x] Create `trading/strategy/va02_long.py` (port to BaseStrategy)
- [x] Create `config/strategies/va02_long.json`
- [x] Create `config/strategies/allocation.json`
- [x] Modify `trading/engine.py` for multi-strategy support
- [x] Update `web/app.py` API response
- [x] Update `web/templates/dashboard.html` layout
- [x] Update `web/static/js/dashboard.js`
- [x] Add unit tests for VA02 score engine (21 tests)
- [ ] Integration test for dual-strategy execution (deferred)
- [ ] Per-strategy position tracking (deferred - future enhancement)

## Testing

- [x] Unit tests for VA02ScoreEngine (14 tests)
- [x] Unit tests for MarketClassifier (7 tests)
- [ ] Integration test for dual-strategy execution (deferred)
- [ ] Backtest comparison: v35-only vs v35+va02 (future)

## Future Enhancements

If concurrent execution with split capital is needed:
1. Implement per-strategy position tracking in engine
2. Split capital on initialization based on `allocation.json` ratios
3. Update dashboard to show separate cards per strategy
