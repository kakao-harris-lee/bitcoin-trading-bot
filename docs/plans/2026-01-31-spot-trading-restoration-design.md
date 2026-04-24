# Spot Trading Restoration Design

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


**Date**: 2026-01-31
**Status**: Approved

## Background

V35 전략의 백테스트 분석 결과:
- 1% 포지션에서만 효과적, 10%+ 투입 시 효과 급감
- 레버리지를 활용한 스케일링이 불가능
- 펀딩 비용 + 수수료로 리스크만 증가
- 선물 거래의 복잡성 대비 이점 없음

**결론**: V35 전략은 단순한 현물 거래가 더 적합

## Decision Summary

| 시장 | 전략 | 용도 |
|------|------|------|
| **현물 (Spot)** | V35 전략 전체 (6개) | 장기 보유, 저비용 |
| **선물 (Futures)** | Short, Sideways | 숏 포지션, 헷지 |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Engine                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   BinanceFeedTask                         │   │
│  │              (가격 스트림 - 공통)                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              ▼                               ▼                   │
│  ┌─────────────────────┐       ┌─────────────────────┐          │
│  │   Spot Strategies   │       │  Futures Strategies │          │
│  │  (V35 전략 6개)     │       │  (Short, Sideways)  │          │
│  │  market: "spot"     │       │  market: "futures"  │          │
│  └──────────┬──────────┘       └──────────┬──────────┘          │
│             │                              │                     │
│             ▼                              ▼                     │
│  ┌─────────────────────┐       ┌─────────────────────┐          │
│  │   SpotExecutor      │       │  FuturesExecutor    │          │
│  │  (레버리지 없음)    │       │  (레버리지, 청산)   │          │
│  └──────────┬──────────┘       └──────────┬──────────┘          │
│             │                              │                     │
│             └───────────────┬──────────────┘                     │
│                             ▼                                    │
│                   ┌─────────────────────┐                        │
│                   │   BinanceClient     │                        │
│                   │  (통합 API 클라이언트)│                       │
│                   └─────────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

## Component Changes

### 1. BinanceClient

Restore spot trading methods from commit `cb172607^`:

```python
class BinanceClient:
    # === Spot Trading (Restore) ===
    async def place_spot_order(self, symbol: str, side: str, quantity: float, order_type: str = "MARKET") -> Fill
    async def get_spot_balance(self, asset: str = "USDT") -> float
    async def get_spot_positions(self) -> dict[str, Position]

    # === Futures Trading (Keep) ===
    async def place_futures_order(...) -> Fill
    async def get_futures_balance(...) -> float
    async def get_futures_positions(...) -> dict[str, Position]

    # === Unified Methods ===
    async def get_all_balances(self) -> Balance
    async def get_all_positions(self) -> dict[str, Position]
```

### 2. Executor Changes

```python
class AsyncExecutor:
    async def execute_order(self, order: Order) -> Fill:
        market = order.market  # "spot" or "futures"

        if market == "spot":
            return await self._execute_spot_order(order)
        else:
            return await self._execute_futures_order(order)
```

### 3. Redis Key Schema

```
# Spot positions (new)
positions:{symbol}:spot     → {qty, entry_price, strategy, ...}

# Futures positions (existing)
positions:{symbol}:futures  → {qty, entry_price, leverage, liquidation_price, ...}

# Balance
balance:spot:usdt           → 10000.0
balance:futures:usdt        → 5000.0
```

### 4. Strategy Configuration

```json
{
  "strategies": {
    "v35_classic_wide": {
      "market": "spot",
      ...
    },
    "short_v1": {
      "market": "futures",
      "leverage": 3,
      ...
    }
  },
  "spot": {
    "enabled": true,
    "fee_rate": 0.001
  },
  "futures": {
    "enabled": true,
    "default_leverage": 3
  }
}
```

## Dashboard Design

### Hybrid View Structure

**Main Dashboard (Combined Summary)**:
- Total Equity across spot + futures
- Spot/Futures balance cards
- All active positions in unified list

**Detail Pages (Tab Separation)**:
- Spot tab: Holdings, balance, spot trades
- Futures tab: Positions, leverage, liquidation info

### API Endpoints

```
GET /api/summary           → Combined equity summary
GET /api/spot/positions    → Spot holdings
GET /api/spot/balance      → Spot USDT balance
GET /api/futures/positions → Futures positions
GET /api/futures/balance   → Futures balance
```

## Backtesting Design

### Spot vs Futures Differences

| Feature | Spot | Futures |
|---------|------|---------|
| Leverage | 1x (fixed) | 1-3x |
| Margin/Liquidation | None | Yes |
| Funding Cost | None | 8-hourly |
| Fee Rate | 0.1% | 0.02-0.05% |

### Enhanced Result Charts

**4-Panel Layout**:
1. Equity Curve vs Benchmark (with invested periods shaded)
2. Drawdown Analysis (strategy vs B&H comparison)
3. Trade Distribution (win/loss histogram, profit factor)
4. Monthly Returns Heatmap

**Judgment Metrics**:
- CAGR, Sharpe, Sortino, Calmar ratios
- Risk comparison (MDD, volatility)
- Cost analysis (fees, funding)
- Time in market, holding period

## Implementation Plan

### Phases

| Phase | Description | Files |
|-------|-------------|-------|
| 1 | BinanceClient spot restoration | 1 |
| 2 | Executor market branching | 3 |
| 3 | Redis schema & models | 2 |
| 4 | Strategy config migration | 4 |
| 5 | Backtester spot support | 4 |
| 6 | Dashboard hybrid view | 3 |
| 7 | Tests & verification | 4 |

**Total**: ~21 files

### File Changes

**Phase 1: BinanceClient**
- `trading/executor/binance_client.py` - Restore spot methods

**Phase 2: Executor**
- `trading/executor/async_executor.py` - Market branching
- `trading/executor/paper_executor.py` - Spot simulation
- `trading/executor/smart_executor.py` - Spot support

**Phase 3: Models/Redis**
- `trading/strategies/components/models.py` - Position.market usage
- `trading/streams/base_strategy.py` - Redis key schema

**Phase 4: Strategy Config**
- `config/strategies/allocation.json` - V35 to spot
- `trading/strategies/components/strategy_factory.py` - Market selection
- `trading/strategies/components/v35_entry.py` - Spot mode
- `trading/strategies/components/v35_trailing_exit.py` - No leverage

**Phase 5: Backtester**
- `core/backtester.py` - Spot/futures branching
- `core/component_adapter.py` - Market type passing
- `scripts/backtest_risk_based_sizing.py` - Spot backtest + charts
- `core/metrics.py` - Judgment metrics

**Phase 6: Dashboard**
- `web/app.py` - API endpoints
- `web/templates/dashboard.html` - Hybrid view UI
- `web/static/js/dashboard.js` - Tab switching

**Phase 7: Tests**
- `tests/trading/executor/test_binance_client.py` - Spot tests
- `tests/trading/executor/test_async_executor.py` - Market branching
- `tests/trading/executor/test_paper_executor.py` - Spot simulation
- `tests/core/test_backtester.py` - Spot backtest

## Implementation Approach

**Hybrid**: Restore from git history (`cb172607^`) + refactor for current architecture

Reference commit for spot code: `cb172607` (Refactor: Remove spot trading - futures only)
