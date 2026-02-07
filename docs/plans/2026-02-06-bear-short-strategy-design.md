# Bear Short Strategy Design

**Date**: 2026-02-06
**Status**: Draft
**Author**: Claude + User collaborative brainstorm

## Overview

Conservative futures short strategy that activates only during confirmed BEAR_STRONG regimes with momentum and volume confirmation. Designed to complement the existing MLP Direction (spot long) strategy by generating profits during sustained downtrends.

### Motivation

- Current MLP Direction strategy blocks entries during BEAR regimes, leaving capital idle in downtrends
- Existing `short_v1` opens shorts in unnecessary situations (BEAR_MODERATE, SIDEWAYS with extreme volatility) - too risky
- Need a well-filtered short strategy that only fires in high-conviction bear conditions

### Strategy Name: `bear_short`

## 1. Entry Conditions

**ALL conditions must be true simultaneously:**

| # | Condition | Parameter | Rationale |
|---|-----------|-----------|-----------|
| 1 | Regime Gate | `regime == "BEAR_STRONG"` | MFI <= 34, ADX >= 25. Strictest bear filter - strong directional selling pressure with trend conviction |
| 2 | MACD Bearish Momentum | `MACD < MACD_Signal` | Confirms bearish momentum is active, filters false BEAR_STRONG readings where momentum is recovering |
| 3 | Volume Confirmation | `volume_ratio >= 1.5` | Current volume >= 1.5x the 20-period SMA volume. Ensures institutional participation, not low-liquidity drift |

**MACD Parameters**: fast=12, slow=26, signal=9 (standard, on 1h candles)

**Signal Output**: `side="sell"`, `market="futures"`

### Comparison with short_v1

| Condition | short_v1 | bear_short |
|-----------|----------|------------|
| Regime | BEAR (any) + SIDEWAYS extreme vol | BEAR_STRONG only |
| RSI | Overbought > 70 (mean reversion) | Not used |
| MACD | Not used | MACD < Signal (momentum) |
| Volume | Not used | >= 1.5x average |
| Philosophy | Mean reversion | Trend following |

## 2. Exit Conditions

**Any ONE condition triggers exit:**

| # | Condition | Parameter | Description |
|---|-----------|-----------|-------------|
| 1 | Stop Loss | Price rises **3%** above entry | Hard stop. Example: Entry $95,000 -> SL at $97,850 |
| 2 | Take Profit | Price drops **5%** below entry | Example: Entry $95,000 -> TP at $90,250 |
| 3 | Regime Change | Regime != BEAR_STRONG and != BEAR_MODERATE | If regime transitions to SIDEWAYS_* or BULL_* -> immediate exit. Bear thesis invalidated |

**Risk:Reward Ratio**: 1:1.67 (3% SL / 5% TP)

**Signal Output**: `side="buy"`, `market="futures"` (short cover)

### Comparison with short_v1 Exit

- short_v1: SL 2%, TP 3% (R:R = 1:1.5) + RSI/regime change exit (complex)
- bear_short: SL 3%, TP 5% (R:R = 1:1.67) + regime change exit only (simple)
- Wider SL prevents premature stop-outs from noise; larger TP maximizes profit per trade

## 3. Position Management

| Parameter | Value |
|-----------|-------|
| Leverage | 3x |
| Capital allocation | 10% of futures balance |
| Max concurrent shorts | 1 per symbol |
| Liquidation buffer | ~30% at 3x (safe margin) |

### Risk Calculation Example

```
Capital: $10,000 futures balance
Position: $10,000 x 10% = $1,000 margin
Leveraged exposure: $1,000 x 3x = $3,000
Max loss (3% SL): $3,000 x 3% = $90 (0.9% of total capital)
Max gain (5% TP): $3,000 x 5% = $150 (1.5% of total capital)
```

## 4. Technical Architecture

### New Files

```
trading/strategies/components/
  bear_short_entry.py    # BearShortEntryStrategy (IEntryStrategy)
  bear_short_exit.py     # BearShortExitStrategy (IExitStrategy)
```

### New Indicators Required

1. **MACD** (12, 26, 9): Add to `trading/indicators/`
   - `macd_line`, `macd_signal`, `macd_histogram`
   - Calculated from 1h candle close prices

2. **Volume Ratio**: `current_volume / SMA(volume, 20)`
   - Feed already receives volume data from kline stream
   - Needs 20-period rolling average calculation

### MarketData Extension

```python
@dataclass
class MarketData:
    symbol: str
    close: float
    mfi: float
    adx: float
    rsi: float
    timestamp: int
    macd: float = 0.0           # NEW
    macd_signal: float = 0.0    # NEW
    volume_ratio: float = 1.0   # NEW
```

### Data Flow

```
BinanceFeedTask (1h kline)
    |
    +-- price, mfi, adx, rsi (existing)
    +-- macd, macd_signal      (NEW)
    +-- volume_ratio           (NEW)
    |
    v
MarketData (extended with new fields)
    |
    v
BearShortEntryStrategy.check_entry()
    | regime == BEAR_STRONG
    | AND macd < macd_signal
    | AND volume_ratio >= 1.5
    |
    v
Signal(side="sell", market="futures")
```

### allocation.json Configuration

```json
{
  "strategies": {
    "bear_short": {
      "market": "futures",
      "leverage": 3,
      "position_pct": 0.10,
      "entry": {
        "class": "BearShortEntryStrategy",
        "params": {
          "macd_fast": 12,
          "macd_slow": 26,
          "macd_signal_period": 9,
          "volume_ratio_threshold": 1.5
        }
      },
      "exit": {
        "class": "BearShortExitStrategy",
        "params": {
          "stop_loss_pct": 3.0,
          "take_profit_pct": 5.0
        }
      }
    }
  }
}
```

### Registry Integration

`@entry_strategy` / `@exit_strategy` decorators handle automatic registration. No changes needed to StrategyFactory or registry.py. New config format references class directly via `"class": "BearShortEntryStrategy"`.

## 5. MLP Short Integration (2-Phase Approach)

### Phase 1: Rule-Based Launch

Deploy the rule-based strategy first (Sections 1-4 above):
- Entry: BEAR_STRONG + MACD < Signal + Volume >= 1.5x
- Exit: SL 3% / TP 5% + Regime change
- Purpose: Collect real-world data + establish baseline performance

**Data collection during Phase 1:**
- Feature snapshots at every BEAR_STRONG interval (OHLCV, all indicators)
- Entry/skip decisions and outcomes (P&L)
- False positive records (entries that hit SL)

### Phase 2: MLP Short Model

**Training Target**: 3-class classifier (SHORT_ENTRY / HOLD / SHORT_EXIT)

| Source | Label | Description |
|--------|-------|-------------|
| BEAR_STRONG interval + subsequent 5% drop | SHORT_ENTRY | Successful short opportunity |
| BEAR_STRONG interval + subsequent 3% rise | HOLD | Bear trap, should not enter |
| After short entry, TP/SL reached | SHORT_EXIT | Exit timing |

**Features** (similar to existing MLP Direction):
- MFI, ADX, RSI (existing)
- MACD, MACD_signal, MACD_histogram (added in Phase 1)
- Volume ratio (added in Phase 1)
- ATR (volatility)
- Price change rate (1h, 4h, 24h)
- Funding rate (futures-specific)

**Integration** (Phase 2 replaces MACD+Volume with MLP):

```python
class BearShortEntryStrategy:
    def check_entry(self, ctx: TradingContext) -> Signal | None:
        # Gate 1: Regime (kept from Phase 1)
        if ctx.regime.regime != "BEAR_STRONG":
            return None

        # Gate 2: MLP prediction (replaces Phase 1 MACD+Volume)
        prediction = self.mlp_model.predict(ctx.features)
        if prediction != "SHORT_ENTRY":
            return None

        # Gate 3: Confidence threshold
        if self.mlp_model.confidence < 0.7:
            return None

        return Signal(side="sell", market="futures", ...)
```

**Phase 2 prerequisites** (based on Phase 1 results):
- Phase 1 backtest yields 20+ trades/year minimum
- Sufficient BEAR_STRONG training data (100+ samples)
- Phase 1 establishes win rate baseline; MLP must exceed it

## 6. Backtest Validation Plan

### Step 1: Historical Regime Analysis

Analyze 2024-2025 data:
- BEAR_STRONG occurrence frequency
- How often MACD + Volume conditions are met during BEAR_STRONG
- Expected: 2-5 entry opportunities per month (conservative)

### Step 2: Component Backtest

```bash
python scripts/run_unified_backtest.py \
  --strategy bear_short \
  --symbols BTC ETH SOL \
  --start 2024-01-01 --end 2025-12-31
```

### Step 3: Pass/Fail Criteria

| Metric | Pass Threshold | Rationale |
|--------|---------------|-----------|
| Win Rate | >= 45% | With 3% SL / 5% TP (R:R 1:1.67), 45% is profitable |
| Max Drawdown | <= 8% | Of total capital |
| Avg Trade Duration | 2h - 48h | Too short = noise, too long = capital lock |
| Trade Count | >= 20/year | Statistical significance |
| Sharpe Ratio | >= 0.5 | Risk-adjusted return |

## 7. Risk Analysis

### Known Risks

1. **Bear Trap (highest risk)**
   - V-shape reversal can hit 3% SL quickly
   - Mitigation: BEAR_STRONG regime gate (1st filter) + volume confirmation (2nd filter)

2. **Low Trade Frequency**
   - BEAR_STRONG + MACD + Volume all satisfied simultaneously may be rare
   - Intentional: conservative strategy prioritizes high win rate over frequency

3. **MLP Direction Conflict**
   - MLP may hold spot long while bear_short opens futures short
   - This is **intentional hedging**: spot long losses offset by futures short gains
   - No technical conflict - CompositeTask manages separate symbol/market combinations

4. **Funding Rate**
   - Futures short positions subject to funding rate
   - In BEAR markets, funding is typically negative = favorable for shorts

## 8. Implementation Timeline

| Phase | Step | Task | Effort |
|-------|------|------|--------|
| **1** | 1 | Add MACD/volume_ratio fields to MarketData | Small |
| **1** | 2 | Implement MACD indicator | Medium |
| **1** | 3 | Add volume_ratio calculation to Feed | Small |
| **1** | 4 | Implement BearShortEntryStrategy | Medium |
| **1** | 5 | Implement BearShortExitStrategy | Small |
| **1** | 6 | Write tests | Medium |
| **1** | 7 | Run backtest and validate against pass/fail criteria | Medium |
| **1** | 8 | Add feature snapshot logging for ML training data | Small |
| **2** | 9 | Build Short training dataset from collected data | Medium |
| **2** | 10 | Train MLP Short model (reuse existing MLP pipeline) | Medium |
| **2** | 11 | Integrate MLP into BearShortEntry (replace MACD+Volume) | Medium |
| **2** | 12 | A/B backtest: Rule-based vs MLP comparison | Medium |
