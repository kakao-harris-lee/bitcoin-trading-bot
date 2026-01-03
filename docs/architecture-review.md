# Architecture Review: Bitcoin Trading Bot

**Date:** 2026-01-04
**Reviewer:** Claude (Architecture Expert)
**Version:** 1.0

---

## Executive Summary

This document provides an architecture review of the Bitcoin Trading Bot project. The system demonstrates **solid design fundamentals** with proper separation of concerns between market classification, strategy execution, and premium arbitrage trading.

**Overall Rating: A-** (Production-ready with solid design fundamentals)

---

## System Overview

The trading bot consists of three independent systems coordinated by `MultiAssetTradingEngine`:

1. **RegimeRouter** - Market state oracle (read-only reference)
2. **Trend Strategies** - Independent entry/exit decision makers (Upbit/Binance)
3. **Kimchi Premium System** - Separate arbitrage trading system

---

## Architecture Diagram

```
                          ┌─────────────────────┐
                          │    RegimeRouter     │
                          │  (Market Oracle)    │
                          │ ┌─────┐  ┌─────┐   │
                          │ │ MFI │  │ ADX │   │
                          │ └─────┘  └─────┘   │
                          └──────────┬──────────┘
                                     │
                    publishes regime │ (BULL/SIDEWAYS/BEAR)
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
              ▼                      ▼                      ▼
   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │  V35LongStrategy │   │ SidewaysV2       │   │ ShortV1Strategy  │
   │  (Upbit Long)    │   │ (Upbit)          │   │ (Binance Short)  │
   ├──────────────────┤   ├──────────────────┤   ├──────────────────┤
   │ • Market classify│   │ • RSI Bollinger  │   │ • EMA cross      │
   │ • Momentum entry │   │ • Volume breakout│   │ • ADX confirm    │
   │ • Dynamic exit   │   │ • Trailing stop  │   │ • Death cross    │
   │                  │   │                  │   │                  │
   │ INDEPENDENT      │   │ INDEPENDENT      │   │ INDEPENDENT      │
   │ entry/exit logic │   │ entry/exit logic │   │ entry/exit logic │
   └──────────────────┘   └──────────────────┘   └──────────────────┘
              │                      │                      │
              └──────────────────────┼──────────────────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ MultiAssetAlphaManager│
                          │   (Execution)         │
                          └──────────────────────┘


   ═══════════════════════════════════════════════════════════════════
                        COMPLETELY SEPARATE SYSTEM
   ═══════════════════════════════════════════════════════════════════


   ┌──────────────────────────────────────────────────────────────────┐
   │                    KIMCHI PREMIUM SYSTEM                        │
   │                                                                  │
   │   Upbit Price ─────┐                                             │
   │                    ├──► Premium = (Upbit - Binance*FX) / Binance │
   │   Binance Price ───┘                                             │
   │                                                                  │
   │   ┌──────────────────┐    ┌─────────────────────────┐           │
   │   │ PremiumStrategy  │    │ MultiAssetHedgeManager  │           │
   │   │ (Signal Gen)     │───►│ (Position Management)   │           │
   │   └──────────────────┘    └─────────────────────────┘           │
   │                                                                  │
   │   Entry: Premium > threshold                                     │
   │   Exit: Premium converges or funding rate adverse               │
   └──────────────────────────────────────────────────────────────────┘
```

---

## Component Analysis

### 1. RegimeRouter (Market State Oracle)

**Location:** `trading/strategy/regime_router.py`

**Role:** Classifies market state using MFI and ADX indicators. Provides read-only reference information to strategies.

**Key Characteristics:**
- Publishes market state: `BULL_STRONG`, `BULL_MODERATE`, `SIDEWAYS_*`, `BEAR_*`
- Coarse regime: `BULL`, `SIDEWAYS`, `BEAR`
- Does NOT control strategy execution
- Strategies reference this information but make independent decisions

**Output:**
```python
@dataclass(frozen=True)
class RegimeDecision:
    market_state: MarketState  # 7 granular states
    regime: Regime             # BULL / SIDEWAYS / BEAR
    upbit_strategy: str | None # recommended strategy
    binance_strategy: str | None
```

**Design Rating: A**
- Correctly positioned as an oracle, not a controller
- Clean separation from execution logic

---

### 2. Trend Strategies

**Locations:**
- `trading/strategy/v35_long.py` - Bull market momentum strategy
- `trading/strategy/sideways_v2.py` - Range-bound trading
- `trading/strategy/short_v1.py` - Binance short strategy

**Role:** Each strategy independently determines entry/exit points based on its own indicators and logic.

**Key Characteristics:**
- Strategies reference RegimeRouter information as context
- Entry/exit decisions are fully autonomous
- Each strategy has its own indicator set and thresholds

**Independence Pattern:**
```python
# From multi_asset_alpha_manager.py
# Regime is passed as context, not control
regime = decision.regime  # reference only
signal = strategy.generate_signal(df, current_price)  # strategy decides
```

**Design Rating: A**
- Each strategy is self-contained
- Clean interface via `BaseStrategy` abstraction
- Configuration-driven parameters

---

### 3. Kimchi Premium System

**Locations:**
- `trading/strategies/premium.py` - Signal generation
- `trading/execution/multi_asset_hedge_manager.py` - Position management

**Role:** Completely independent arbitrage system exploiting KRW-USD price spreads.

**Key Characteristics:**
- Subscribes to BOTH Upbit and Binance price streams
- Calculates premium: `(Upbit - Binance * FX) / Binance`
- Entry based on premium threshold
- Exit based on premium convergence or adverse funding

**Independence:**
```python
@property
def subscribed_streams(self) -> List[str]:
    return ["market:upbit:prices", "market:binance:prices"]
```

**Design Rating: A**
- Completely separate from trend strategies
- Different exchange focus (Binance shorts)
- Independent trigger conditions

---

### 4. MultiAssetTradingEngine

**Location:** `trading/multi_asset_engine.py`

**Role:** Orchestrates all components without controlling their internal logic.

**Components Managed:**
| Component | Purpose |
|-----------|---------|
| `MultiAssetPriceHub` | Per-symbol price tracking |
| `MultiAssetDataCache` | Per-symbol OHLCV data |
| `MultiAssetAlphaManager` | Strategy evaluation & execution |
| `MultiAssetHedgeManager` | Hedge position management |
| `MultiAssetDeltaRebalancer` | Delta tracking |
| `PortfolioManager` | Capital allocation |

**Design Rating: B+**
- Acceptable complexity for coordinator role
- Clear initialization flow
- Could benefit from sub-coordinators for large-scale growth

---

## Strengths

### 1. Clean Separation of Concerns

| Component | Role | Independence |
|-----------|------|--------------|
| **RegimeRouter** | Market state oracle | Read-only reference |
| **Trend Strategies** | Entry/exit decisions | Fully autonomous |
| **Premium System** | Arbitrage execution | Completely separate |

### 2. Strategy Autonomy

Each strategy owns:
- Its own entry conditions
- Its own exit conditions
- Its own indicators
- Configuration via JSON files

### 3. Configuration-Driven Design

- Strategy parameters in `config/strategies/*.json`
- Asset allocation in `config/strategies/allocation.json`
- Tuned parameters in `config/tuned/selected_candidate.json`

### 4. Multi-Asset Support

- Per-symbol data caching
- Per-symbol regime routing
- Per-symbol capital allocation
- Concurrent evaluation via `asyncio.gather`

### 5. Risk Controls

- File-based kill switch
- Telegram command integration (`/kill_on`, `/kill_off`)
- Daily loss limits
- Position size limits

---

## Areas for Improvement

### 1. Error Recovery (Medium Priority)

**Current:** Log and continue pattern
```python
except Exception as e:
    logger.error(f"Failed: {e}")
```

**Recommendation:** Add circuit breakers per exchange adapter
```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int, reset_timeout: int):
        ...
    def call(self, func): ...
    def is_open(self) -> bool: ...
```

### 2. Configuration Validation (Low Priority)

**Current:** Configuration spread across multiple files

**Recommendation:** Add startup validation
```python
class ConfigValidator:
    def validate_allocation(self, config: Dict) -> List[str]:
        """Returns list of validation errors."""
        ...
```

### 3. Observability (Low Priority)

**Recommendation:** Add structured metrics
- Strategy signal counts
- Execution latencies
- Premium calculations
- Regime transitions

---

## Component Ratings

| Component | Rating | Notes |
|-----------|--------|-------|
| RegimeRouter | A | Correctly positioned as oracle |
| Trend Strategies | A | Autonomous, well-structured |
| Premium System | A | Properly isolated |
| MultiAssetEngine | B+ | Acceptable coordinator complexity |
| Risk Controls | A | Comprehensive coverage |
| Configuration | B+ | Could use validation layer |
| Error Handling | B | Needs circuit breakers |
| Testability | B | Good structure, could expand |

---

## Key Design Decisions (Validated)

1. **RegimeRouter as Oracle** - Correct. Market classification should be separate from execution.

2. **Strategy Independence** - Correct. Strategies reference regime but decide autonomously.

3. **Premium as Separate System** - Correct. Different exchange, different logic, different purpose.

4. **Async Coordination** - Correct. `asyncio.gather` for concurrent multi-asset evaluation.

5. **Paper/Live Mode Toggle** - Correct. Same code paths with execution mode flag.

---

## Conclusion

The Bitcoin Trading Bot architecture demonstrates mature design patterns for a multi-asset trading system. The separation between market classification (RegimeRouter), strategy execution (V35/Sideways/Short), and premium arbitrage (HedgeManager) is properly implemented.

The system is **production-ready** with the current design. Future improvements should focus on error recovery mechanisms and observability enhancements.

---

## Appendix: Key File Locations

| Purpose | File |
|---------|------|
| Entry Point | `run.py` |
| Engine | `trading/multi_asset_engine.py` |
| Regime Router | `trading/strategy/regime_router.py` |
| V35 Strategy | `trading/strategy/v35_long.py` |
| Sideways Strategy | `trading/strategy/sideways_v2.py` |
| Short Strategy | `trading/strategy/short_v1.py` |
| Alpha Manager | `trading/execution/multi_asset_alpha_manager.py` |
| Hedge Manager | `trading/execution/multi_asset_hedge_manager.py` |
| Premium Strategy | `trading/strategies/premium.py` |
| Risk Controls | `trading/risk/risk_controls.py` |
| Allocation Config | `config/strategies/allocation.json` |
