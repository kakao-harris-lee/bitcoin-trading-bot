# Trading Strategies Reference

This document describes all trading strategies, their data sources, indicators, and entry/exit conditions.

## Quick Reference

| Strategy | Exchange | Direction | Timeframe | Primary Indicators | Entry Method |
|----------|----------|-----------|-----------|-------------------|--------------|
| Short_V1 | Binance | SHORT | 4H | EMA, ADX, DI, ATR | EMA Death Cross + ADX |
| Sideways_V2 | Binance | LONG | Daily | RSI, BB, Stoch, OBV | Multi-method (3 entries) |
| MLP_Direction | Binance | LONG | 4H | MLP Classifier | 3-class prediction |

---

## 1. Short_V1 Strategy

**Components:** `trading/strategies/components/short_entry.py`, `short_exit.py`
**Config:** `config/strategies/short_v1.json`

### Overview

- **Exchange:** Binance Futures (BTCUSDT)
- **Direction:** SHORT
- **Timeframe:** 4H
- **Leverage:** 2x

### Data Sources

| Source | Description |
|--------|-------------|
| OHLCV | 4H candles from Binance Futures |
| Swing High | Recent price highs for stop placement |

### Indicators

| Indicator | Period | Purpose |
|-----------|--------|---------|
| EMA Fast | 68 | Short-term trend |
| EMA Slow | 128 | Long-term trend |
| ADX | 14 | Trend strength |
| +DI / -DI | 14 | Directional movement |
| ATR | 14 | Volatility for stop loss |
| ADX Slope | 3-bar | Trend weakening detection |

### Entry Conditions

All conditions must be met:

| Condition | Requirement | Strength |
|-----------|-------------|----------|
| Death Cross | EMA_fast < EMA_slow | +0.4 |
| Strong ADX | ADX >= 25 | +0.3 |
| Bearish DI | -DI > +DI | +0.2 |
| ADX Not Declining | ADX >= ADX[3 bars ago] | Required |
| No Extreme Volatility | Daily range <= 10% | Required |
| Minimum Confidence | Sum >= 0.7 | Required |

### Exit Conditions

**Two-Tier Exit System:**

| Tier | Trigger | Action |
|------|---------|--------|
| Gap Exit | Open >= Stop Loss | Close 100% at market |
| Stop Loss | High >= Stop Loss | Close 100% |
| First Tier (1R) | Low <= Entry - Risk | Close 50%, activate trailing |
| Trailing Stop | High >= Lowest + ATR×1.5 | Close remaining |
| Second Tier (2R) | Low <= Entry - 2×Risk | Close remaining |
| Golden Cross | EMA_fast > EMA_slow | Close 100% |

**Stop Loss Calculation:**

```
ATR Buffer = ATR × 1.5
Raw Stop = Swing High + ATR Buffer
Max Stop = Entry × 1.05 (5% cap)
Stop Loss = min(Raw Stop, Max Stop)
```

---

## 3. Short_V2 Strategy (Hedge)

**File:** `trading/strategy/short_v2.py`
**Config:** `config/strategies/short_v2.json`

### Overview

- **Exchange:** Binance Futures (BTCUSDT)
- **Direction:** SHORT
- **Timeframe:** 4H
- **Purpose:** Defensive hedge for BEAR_STRONG regime

### Data Sources

| Source | Description |
|--------|-------------|
| OHLCV | 4H candles from Binance |
| Long Exposure | KRW value of long positions |
| Regime | Current market regime from RegimeRouter |

### Indicators

| Indicator | Period | Purpose |
|-----------|--------|---------|
| EMA Fast | 30 | Short-term trend |
| EMA Slow | 100 | Long-term trend |
| ADX | 14 | Trend strength |
| +DI / -DI | 14 | Directional movement |

### Entry Conditions

| Condition | Requirement |
|-----------|-------------|
| Regime | BEAR_STRONG only |
| Long Exposure | long_exposure_krw > 0 |
| No Re-entry | Not stopped out this regime |
| Bearish EMA | EMA_fast < EMA_slow |
| Strong ADX | ADX >= 20 |
| Bearish Momentum | -DI > +DI |

### Exit Conditions

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| Stop Loss | Price rises 5% | Close 100% |
| Regime Change | Regime != BEAR_STRONG | Close 100% |

### Position Sizing

- Matches long exposure: `long_exposure_krw / fx_rate`
- Leverage: 2x

---

## 4. Sideways_V2 Strategy

**Components:** `trading/strategies/components/sideways_entry.py`, `sideways_exit.py`
**Config:** `config/strategies/sideways_v2.json`

### Overview

- **Exchange:** Upbit (KRW-BTC)
- **Direction:** LONG
- **Timeframe:** Daily

### Data Sources

| Source | Description |
|--------|-------------|
| OHLCV | Daily candles from Upbit |
| Volume | For breakout detection |
| OBV | On-Balance Volume for trend |

### Indicators

| Indicator | Period | Purpose |
|-----------|--------|---------|
| RSI | 14 | Oversold detection |
| Bollinger Bands | 20, 2σ | Price range |
| BB Position | - | Normalized position (0-1) |
| Stochastic | 14K, 3D | Oversold/overbought |
| OBV | - | Volume trend |
| OBV MA | 14 | OBV smoothing |
| OBV Slope | 7-bar | Volume trend direction |
| Volume MA | 20 | Average volume |

### Entry Conditions (3 Independent Methods)

| Method | Conditions | Position |
|--------|------------|----------|
| RSI + BB | RSI < 24 AND BB_position < 0.2 | 40% |
| Stochastic | Stoch_K crosses above Stoch_D, K < 30 | 40% |
| Volume Breakout | Volume >= Avg × 1.68 | 40% |

**Entry Filter:**

- OBV Slope >= -0.04 (blocks entries during declining volume)

### Exit Conditions

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| TP1 | +1.125%, hold >= 5 bars | Sell 30% |
| TP2 | +3.327% | Sell 50% of remaining |
| TP3 | +5.519% | Sell remaining |
| Stop Loss | -1.079% | Sell 100% |
| Time Exit | 20 bars, profit > 0 | Sell 100% |

---

## 5. H4_Conservative Strategy

**File:** `trading/strategy/h4_conservative.py`
**Config:** `config/strategies/h4_conservative.json`

### Overview

- **Exchange:** Upbit (KRW-BTC)
- **Direction:** LONG
- **Timeframe:** 4H

### Data Sources

| Source | Description |
|--------|-------------|
| OHLCV | 4H candles from Upbit |
| Recent High | 24-bar (4-day) lookback |

### Indicators

| Indicator | Period | Purpose |
|-----------|--------|---------|
| RSI | 14 | Oversold detection |
| Bollinger Bands | 20, 2σ | Price range |
| EMA Short | 50 | Trend direction |
| EMA Long | 200 | Long-term trend |
| Volume MA | 20 | Average volume |
| % from High | 24-bar | Pullback depth |

### Entry Conditions

All conditions required:

| Condition | Requirement |
|-----------|-------------|
| Uptrend | EMA50 > EMA200 |
| Oversold | RSI < 30 |
| BB Lower Zone | BB_position < 0.2 |
| Drop from High | Price 5%+ below 4-day high |
| Volume Surge | Volume > Avg × 1.5 |

### Exit Conditions

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| Take Profit | +4.0% | Sell 100% |
| Stop Loss | -2.0% | Sell 100% |
| Time Exit | 18 bars, profit > 0 | Sell 100% |
| RSI Overbought | RSI > 70 | Sell 100% |

---

## 6. H4_Short Strategy

**File:** `trading/strategy/h4_short.py`
**Config:** `config/strategies/h4_short.json`

### Overview

- **Exchange:** Binance Futures (BTCUSDT)
- **Direction:** SHORT
- **Timeframe:** 4H

### Data Sources

| Source | Description |
|--------|-------------|
| OHLCV | 4H candles from Binance |
| Recent Low | 24-bar (4-day) lookback |

### Indicators

| Indicator | Period | Purpose |
|-----------|--------|---------|
| RSI | 14 | Overbought detection |
| Bollinger Bands | 20, 2σ | Price range |
| EMA Short | 50 | Trend direction |
| EMA Long | 200 | Long-term trend |
| Volume MA | 20 | Average volume |
| % from Low | 24-bar | Bounce height |

### Entry Conditions

All conditions required:

| Condition | Requirement |
|-----------|-------------|
| Downtrend | EMA50 < EMA200 |
| Overbought | RSI > 72 |
| BB Upper Zone | BB_position > 0.82 |
| Rise from Low | Price 6%+ above 4-day low |
| Volume Surge | Volume > Avg × 1.5 |

### Exit Conditions

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| Take Profit | +5.0% (price drops) | Close 100% |
| Stop Loss | -2.0% (price rises) | Close 100% |
| Time Exit | 18 bars, profit > 0 | Close 100% |
| RSI Oversold | RSI < 30 | Close 100% |

---

## Regime Router Integration

The `RegimeRouter` classifies market conditions and provides context to strategies:

### Market States (7)

| State | MFI | ADX | Regime |
|-------|-----|-----|--------|
| BULL_STRONG | >= 52 | >= 25 | BULL |
| BULL_MODERATE | >= 52 | >= 20 | BULL |
| SIDEWAYS_BULL | >= 52 | < 20 | SIDEWAYS |
| SIDEWAYS_NEUTRAL | 48-52 | - | SIDEWAYS |
| SIDEWAYS_BEAR | <= 48 | < 15 | SIDEWAYS |
| BEAR_MODERATE | <= 48 | 15-20 | BEAR |
| BEAR_STRONG | <= 48 | >= 20 | BEAR |

### RegimeContext Output

```python
@dataclass
class RegimeContext:
    market_state: MarketState  # e.g., "BEAR_STRONG"
    regime: Regime             # "BULL", "SIDEWAYS", or "BEAR"
    mfi: float                 # Raw MFI value
    adx: float                 # Raw ADX value
```

### Strategy Activation by Regime

| Regime | Strategy |
|--------|----------|
| BULL | MLP_Direction |
| SIDEWAYS | Sideways_V2 |
| BEAR | Short_V1 |

---

## Backtesting Standards

From `CLAUDE.md`:

| Metric | Requirement |
|--------|-------------|
| Training Period | 2020-01-01 ~ 2024-12-31 |
| Validation Period | 2025-01-01 ~ present |
| OOS Return | >= 15% |
| Sharpe Ratio | >= 1.5 |
| Max Drawdown | <= 20% |

### Fee Calculation

```
Entry Fee:    0.05%
Exit Fee:     0.05%
Slippage:     0.04%
Total:        0.14% per trade
Min Target:   1.4% (10x fees)
```
