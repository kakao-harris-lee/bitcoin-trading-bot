# Trading Strategies Reference

This document describes all trading strategies, their data sources, indicators, and entry/exit conditions.

## Quick Reference

| Strategy | Exchange | Direction | Timeframe | Primary Indicators | Entry Method |
|----------|----------|-----------|-----------|-------------------|--------------|
| V35_Long | Upbit | LONG | Daily | RSI, MACD, MFI, ADX | Momentum/Breakout/Range |
| Short_V1 | Binance | SHORT | 4H | EMA, ADX, DI, ATR | EMA Death Cross + ADX |
| Short_V2 | Binance | SHORT | 4H | EMA, ADX, DI | Hedge (regime-based) |
| Sideways_V2 | Upbit | LONG | Daily | RSI, BB, Stoch, OBV | Multi-method (3 entries) |
| H4_Conservative | Upbit | LONG | 4H | RSI, BB, EMA, Volume | Oversold pullback |
| H4_Short | Binance | SHORT | 4H | RSI, BB, EMA, Volume | Overbought bounce |

---

## 1. V35_Long Strategy

**File:** `trading/strategy/v35_long.py`
**Config:** `config/strategies/v35_long.json`

### Overview
- **Exchange:** Upbit (KRW-BTC)
- **Direction:** LONG
- **Timeframe:** Daily

### Data Sources
| Source | Description |
|--------|-------------|
| OHLCV | Daily candles from Upbit |
| Volume | Daily trading volume |

### Indicators

| Indicator | Period | Purpose |
|-----------|--------|---------|
| RSI | 14 | Momentum / Oversold detection |
| MACD | 12, 26, 9 | Trend confirmation (golden/dead cross) |
| MFI | 14 | Buying/selling pressure (0-100) |
| ADX | 14 | Trend strength (0-100) |
| Bollinger Bands | 20, 2σ | Volatility bands |
| Stochastic | 14K, 3D | Overbought/oversold |

### Market Classification (7 States)

| State | MFI Condition | ADX Condition |
|-------|---------------|---------------|
| BULL_STRONG | >= 54 | >= 25 |
| BULL_MODERATE | >= 54 | >= 18 |
| SIDEWAYS_UP | >= 49 | - |
| SIDEWAYS_FLAT | >= 41 | - |
| SIDEWAYS_DOWN | >= 34 | - |
| BEAR_MODERATE | < 34 | < 18 |
| BEAR_STRONG | < 34 | >= 25 |

### Entry Conditions

**BULL_STRONG (Momentum Entry):**
- MACD > MACD_signal (golden cross)
- RSI > 52
- Confidence: 0.85

**BULL_MODERATE (Momentum Entry):**
- MACD > MACD_signal
- RSI > 55
- Confidence: 0.75

**SIDEWAYS_UP (Breakout Entry):**
- Close > 20-period high × 1.0071
- Volume > 20-period avg × 1.23
- Confidence: 0.70

**SIDEWAYS_FLAT/DOWN (Range Support Entry):**
- Close < Support + (Range × 15.93%)
- RSI < 38
- Confidence: 0.65

**BEAR (Conservative Entry):**
- RSI < 30
- Stoch_K < 20
- Close < Support + (Range × 10%)
- Position size: 50%

### Exit Conditions

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| Stop Loss | Profit <= -2.10% | Sell 100% |
| TP1 (BULL_STRONG) | +5.3% | Sell 35.1% |
| TP2 (BULL_STRONG) | +10.7% | Sell 37.7% |
| TP3 (BULL_STRONG) | +20.1% | Sell remaining |
| Trailing Stop | Activation: +3.0%, Trail: 2.0% | Sell 100% |
| MACD Dead Cross | MACD < Signal, Profit > 0 | Sell 100% |

---

## 2. Short_V1 Strategy

**File:** `trading/strategy/short_v1.py`
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

**File:** `trading/strategy/sideways_v2.py`
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

| Regime | Upbit Strategy | Binance Strategy |
|--------|----------------|------------------|
| BULL | V35_Long | - |
| SIDEWAYS | Sideways_V2 | - |
| BEAR_STRONG | - | Short_V1 |

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
