# SHORT_V2: Hedge Strategy Design

> Archived note (2026-04-24): this document describes a retired futures/short/hedge path. The active runtime is now Binance spot-only. Keep this file only as historical reference, not as an implementation guide.


**Date**: 2026-01-05
**Status**: Approved for Implementation

---

## 1. Overview

SHORT_V2 is a **defensive hedge strategy**, not a profit-seeking strategy. Its sole purpose is to offset V35 long position losses during strong bear markets.

### Key Differences from SHORT_V1

| Aspect | SHORT_V1 | SHORT_V2 |
|--------|----------|----------|
| Purpose | Independent profits | Hedge long positions |
| Entry | Any death cross + ADX 25 | BEAR_STRONG regime only |
| EMA | 50/200 | 30/100 (faster) |
| ADX threshold | 25 | 20 (looser) |
| Sizing | Fixed allocation | Match long exposure |
| Take-profit | Yes (R:R 2.5) | None |
| Leverage | 3x | 2x |

---

## 2. Entry Conditions

All conditions must be true:

1. **BEAR_STRONG regime** - RegimeRouter classifies market as BEAR_STRONG
2. **EMA 30 < EMA 100** - Death cross or bearish EMA alignment
3. **ADX >= 20** - Trend strength confirmation
4. **-DI > +DI** - Bearish directional movement dominance
5. **V35 long position exists** - Must have something to hedge

Entry triggers immediately when RegimeRouter switches to BEAR_STRONG and EMA/ADX conditions are met.

---

## 3. Position Sizing

**Mode**: Match long exposure

- Query V35 long position value
- Open equivalent short position on Binance
- Example: V35 has ₩10M deployed → Open ~$10M-equivalent USDT short

If no long position is active, no hedge opens.

---

## 4. Exit Conditions

Whichever comes first:

| Condition | Action | Reason |
|-----------|--------|--------|
| Regime exits BEAR_STRONG | Close 100% | Bear is over, hedge no longer needed |
| Stop-loss hit (5%) | Close 100% | Prevent hedge from becoming major loss |
| Long position closed | Close 100% | Nothing left to hedge |

**No take-profit** - Hedge runs as long as BEAR_STRONG continues.

**No re-entry** in same BEAR_STRONG period if stopped out - prevents repeated losses in choppy markets.

---

## 5. Risk Parameters

```
Leverage: 2x
Stop-loss: 5%
Take-profit: None
Max position: Match long exposure (no amplification)
```

With 2x leverage, 5% stop-loss triggers on ~2.5% adverse BTC move.

---

## 6. Configuration

**File**: `config/strategies/short_v2.json`

```json
{
  "strategy_name": "SHORT_V2",
  "description": "BEAR_STRONG hedge strategy - offsets long position losses",
  "symbol": "BTCUSDT",
  "timeframe": "4h",
  "indicators": {
    "ema_fast": 30,
    "ema_slow": 100,
    "adx_period": 14
  },
  "entry": {
    "regime_required": "BEAR_STRONG",
    "adx_min": 20,
    "di_negative_dominant": true
  },
  "exit": {
    "stop_loss_pct": 5.0,
    "take_profit": null,
    "exit_on_regime_change": true,
    "exit_on_long_close": true
  },
  "sizing": {
    "mode": "match_long_exposure"
  },
  "risk_management": {
    "margin_type": "ISOLATED",
    "leverage": 2,
    "no_reentry_after_stop": true
  }
}
```

---

## 7. Implementation Plan

### Files to Create
- `trading/strategy/short_v2.py` - Strategy class

### Files to Modify
- `trading/execution/multi_asset_alpha_manager.py` - Query long exposure, coordinate hedge
- `config/strategies/allocation.json` - Enable short_v2
- `config/strategies/short_v2.json` - New config file

### Integration Flow

```
RegimeRouter detects BEAR_STRONG
         ↓
MultiAssetAlphaManager queries V35 long exposure
         ↓
SHORT_V2.generate_signal() returns open_short with matched size
         ↓
Binance adapter opens short position
         ↓
On regime change / stop-loss / long close → close hedge
```

---

## 8. Expected Behavior

| Scenario | V35 Long | SHORT_V2 Action |
|----------|----------|-----------------|
| BULL market | ₩10M deployed | No action |
| BEAR (not strong) | ₩10M deployed | No action |
| BEAR_STRONG starts | ₩10M deployed | Open ~$10M short |
| BTC drops 15% in BEAR_STRONG | Long loses ~₩1.5M | Hedge gains ~$3M (2x leverage) |
| BEAR_STRONG ends | - | Close hedge |
| Hedge hits -5% | - | Close hedge |
| Long closed | - | Close hedge |

---

## 9. Success Criteria

- Reduces portfolio max drawdown during BEAR_STRONG periods
- Does NOT aim for standalone profitability
- Minimal impact during non-BEAR_STRONG periods (no trades)

---

## 10. Out of Scope

- Profit optimization (this is a hedge, not alpha)
- Multiple re-entries after stop-loss
- Partial position sizing
- Independent operation without long position
