# Kimchi Premium Hedge Strategy Design (Deprecated)

> Note: Kimchi premium arbitrage has been removed from the codebase. This design is historical.

**Date:** 2025-12-28
**Status:** Approved
**Author:** Claude + User

## Overview

Separate the Kimchi Premium hedge strategy from directional Alpha strategies (v35, va02). The hedge strategy maintains delta-neutral exposure to capture premium spread and funding rates, independent of market trend.

## Core Principles

1. **Delta Neutrality**: Match Upbit long with Binance short at 1:1 ratio
2. **Spread-Based Gating**: Entry/exit based on premium mean-reversion, NOT RegimeRouter
3. **Independent Allocation**: Separate capital pools for Alpha and Hedge
4. **Async Processing**: Redis/WebSocket price streams, in-memory DataFrame caching

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      DualPaperTradingEngine                         │
│                                                                     │
│  ┌─────────────────────────┐    ┌─────────────────────────────┐    │
│  │      AlphaManager       │    │       HedgeManager          │    │
│  │                         │    │                             │    │
│  │  • v35 (BULL)           │    │  • PremiumController        │    │
│  │  • va02 (BULL/SIDEWAYS) │    │  • Delta-neutral shorts     │    │
│  │  • sideways_v2          │    │  • Mean-reversion logic     │    │
│  │                         │    │                             │    │
│  │  Uses: RegimeRouter     │    │  Uses: Premium stats only   │    │
│  │  Capital: Upbit KRW     │    │  Capital: Binance USDT      │    │
│  │           (dedicated)   │    │           (dedicated pool)  │    │
│  └─────────────────────────┘    └─────────────────────────────┘    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      Shared Services                         │   │
│  │  • FeedHandler (async price streams)                        │   │
│  │  • DataCache (in-memory DataFrame)                          │   │
│  │  • TelegramNotifier                                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. PremiumController

**File:** `trading/risk/premium_controller.py`

Upgraded from PremiumTracker with execution decision authority.

```python
@dataclass
class HedgeSignal:
    action: Literal["open", "close", "hold"]
    reason: str
    target_btc_qty: float  # Must match Upbit long position
    premium_stats: PremiumStats
    timestamp: datetime

class PremiumController:
    DEFAULT_CONFIG = {
        "entry_threshold_pct": 1.5,      # Minimum premium to consider
        "entry_sigma": 2.0,              # Standard deviations above mean
        "exit_to_mean": True,            # Exit when premium reverts to mean
        "min_hold_minutes": 30,          # Prevent rapid flip-flopping
        "negative_funding_exit": -0.05,  # Exit if funding too negative
    }
```

**Entry Logic:**
- `current_premium > (mean_24h + 2 * std_24h)`
- AND `current_premium > 1.5%`
- AND `volatility_state != "high"`

**Exit Logic:**
- `current_premium <= mean_24h`
- OR `funding_rate < -0.05%`

**Delta-Neutral Quantity:**
```python
def calculate_hedge_qty(self, upbit_btc_balance: float) -> float:
    return upbit_btc_balance  # 1:1 matching
```

### 2. HedgeManager

**File:** `trading/execution/hedge_manager.py`

Manages delta-neutral hedge positions independently from Alpha strategies.

```python
class HedgeManager:
    def __init__(
        self,
        binance_account: BinanceAccount,  # Dedicated hedge capital
        premium_controller: PremiumController,
        capital_usdt: float = 5_000,      # Separate pool
    ):
        self.account = binance_account
        self.controller = premium_controller
        self.capital = capital_usdt
        self.hedge_position: Optional[HedgePosition] = None
        self.trades: List[HedgeTrade] = []

    async def evaluate(
        self,
        upbit_btc_balance: float,
        binance_price: float,
        premium_info: Dict,
    ) -> Optional[HedgeSignal]:
        signal = self.controller.generate_signal(
            premium_info=premium_info,
            upbit_btc_qty=upbit_btc_balance,
        )

        if signal.action == "open" and not self.hedge_position:
            await self._open_hedge(signal, binance_price)
        elif signal.action == "close" and self.hedge_position:
            await self._close_hedge(signal, binance_price)

        return signal
```

### 3. AlphaManager

**File:** `trading/execution/alpha_manager.py`

Manages directional Alpha strategies using RegimeRouter.

```python
class AlphaManager:
    def __init__(
        self,
        upbit_account: UpbitAccount,
        regime_router: RegimeRouter,
        strategies: Dict[str, BaseStrategy],
        allocation_config: Dict,
    ):
        self.account = upbit_account
        self.router = regime_router
        self.strategies = strategies
        self.positions: Dict[str, StrategyPosition] = {}

    def evaluate(
        self,
        current_price: float,
        df_day: pd.DataFrame,
    ) -> List[AlphaSignal]:
        decision = self.router.recommend(df_day)
        regime = decision.regime

        signals = []
        for name, strategy in self.strategies.items():
            if not self._is_allowed_in_regime(name, regime):
                continue
            signal = strategy.generate_signal(df_day, current_price)
            if signal and signal.action != "hold":
                signals.append(signal)

        return signals

    def get_total_btc_exposure(self) -> float:
        _, btc_balance = self.account.get_balance()
        return btc_balance
```

### 4. Engine Orchestration

**File:** `trading/engine.py` (modified)

```python
class DualPaperTradingEngine:
    def __init__(self, ...):
        # Shared services
        self.feed_handler = FeedHandler()
        self.data_cache = DataCache()
        self.telegram = TelegramNotifier()

        # Alpha: Upbit directional strategies
        self.alpha_manager = AlphaManager(...)

        # Hedge: Delta-neutral premium capture
        self.hedge_manager = HedgeManager(...)

        # SHORT_V1 remains separate (trend-based)
        self.short_v1_manager = ShortV1Manager(...)

    async def run_iteration(self):
        # 1. Get prices (async)
        prices = await self.feed_handler.get_prices()
        premium_info = self._calculate_premium(prices)

        # 2. Update data cache
        await self.data_cache.refresh_if_stale()

        # 3. Execute Alpha strategies (Upbit)
        df_day = self.data_cache.get_daily()
        alpha_signals = self.alpha_manager.evaluate(prices['upbit'], df_day)
        self.alpha_manager.execute(alpha_signals, prices['upbit'])

        # 4. Execute Hedge strategy (Binance - separate capital)
        upbit_btc = self.alpha_manager.get_total_btc_exposure()
        await self.hedge_manager.evaluate(
            upbit_btc_balance=upbit_btc,
            binance_price=prices['binance'],
            premium_info=premium_info,
        )

        # 5. Execute SHORT_V1 only when hedge inactive
        if not self.hedge_manager.hedge_position:
            decision = self.alpha_manager.router.recommend(df_day)
            if decision.binance_strategy == "short_v1":
                self.short_v1_manager.execute(prices['binance'], df_day)

        # 6. Write logs
        await self._write_logs(prices, premium_info)
```

### 5. Async FeedHandler & DataCache

**File:** `trading/streams/binance_feed.py` (current spot-only stream path)

```python
class FeedHandler:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis: Optional[aioredis.Redis] = None
        self._prices: Dict[str, float] = {"upbit": 0, "binance": 0}

    async def connect(self):
        self.redis = await aioredis.from_url(redis_url)
        asyncio.create_task(self._subscribe_loop())

    async def _subscribe_loop(self):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("prices:upbit", "prices:binance")
        async for message in pubsub.listen():
            # Update in-memory prices
            ...

    async def get_prices(self) -> Dict[str, float]:
        if self._is_stale():
            await self._fetch_rest_fallback()
        return self._prices.copy()
```

**File:** `trading/data/data_cache.py`

```python
class DataCache:
    def __init__(self, refresh_interval_minutes: int = 5):
        self._cache: Dict[str, pd.DataFrame] = {}
        self._refresh_interval = timedelta(minutes=refresh_interval_minutes)

    async def refresh_if_stale(self):
        for timeframe in ["day", "minute60"]:
            if self._needs_refresh(timeframe):
                await self._load_timeframe(timeframe)

    async def _load_timeframe(self, timeframe: str):
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: DataLoader().load_timeframe(timeframe, days=180)
        )
        self._cache[timeframe] = df
```

### 6. Risk Management

**File:** `trading/risk/premium_controller.py` (risk guards)

```python
def generate_signal(self, premium_info: Dict, upbit_btc_qty: float) -> HedgeSignal:
    stats = self.get_stats()

    # SLIPPAGE GUARD: Block entry in high volatility
    if stats.volatility_state == "high":
        return HedgeSignal(action="hold", reason="volatility_guard", ...)

    # ENTRY: Mean reversion + threshold
    entry_threshold = stats.mean_24h + (self.config["entry_sigma"] * stats.std_24h)
    if (stats.current > entry_threshold
        and stats.current > self.config["entry_threshold_pct"]):
        return HedgeSignal(action="open", ...)

    # EXIT: Mean reversion OR negative funding
    if self._has_position():
        if stats.current <= stats.mean_24h:
            return HedgeSignal(action="close", reason="mean_reversion", ...)

        funding_rate = self._get_current_funding_rate()
        if funding_rate < self.config["negative_funding_exit"]:
            return HedgeSignal(action="close", reason="negative_funding", ...)

    return HedgeSignal(action="hold", ...)
```

**File:** `trading/risk/hedge_risk.py`

```python
@dataclass
class HedgeRiskConfig:
    max_hedge_capital_pct: float = 0.8
    min_premium_for_entry: float = 1.5
    volatility_block_threshold: float = 2.0
    negative_funding_exit: float = -0.05
    min_hold_minutes: int = 30
```

### 7. Error Handling

```python
async def _open_hedge(self, signal: HedgeSignal, price: float):
    try:
        result = await self.account.open_short(qty, price)
        if not result.get("success"):
            raise ExecutionError(f"Short order failed: {result.get('error')}")

        self.hedge_position = HedgePosition(...)
        await self._notify_telegram(f"🔒 Hedge opened: {qty:.4f} BTC")

    except Exception as e:
        await self._notify_telegram(f"❌ Hedge open failed: {e}")
        raise

async def _close_hedge(self, signal: HedgeSignal, price: float):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = await self.account.close_short(qty)
            if result.get("success"):
                self.hedge_position = None
                return
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            await self._notify_telegram(f"🚨 CRITICAL: Hedge close failed!")
            raise

async def sync_position(self):
    """Reconcile local vs exchange state on startup."""
    exchange_pos = await self.account.get_position()
    # Sync logic...
```

### 8. Logging

**File:** `logs/v2_engine_combined.json`

```json
{
  "generated_at": "2025-12-28T12:00:00",
  "mode": "paper",
  "regime": "BULL",
  "market_state": "BULL_STRONG",
  "prices": {
    "upbit_krw": 140000000,
    "binance_usd": 95000
  },
  "kimchi_premium": {
    "current_pct": 3.5,
    "mean_24h": 2.1,
    "std_24h": 0.8,
    "volatility_state": "normal",
    "trend": "rising"
  },
  "hedge": {
    "active": true,
    "position_btc": 0.5,
    "entry_price": 94500,
    "entry_premium": 4.2,
    "unrealized_pnl": 250
  },
  "delta_exposure": {
    "long_btc": 0.5,
    "short_btc": 0.5,
    "net_btc": 0.0,
    "is_neutral": true
  },
  "hedge_statistics": {
    "total_trades": 5,
    "total_pnl_usdt": 1200,
    "total_funding_earned": 150,
    "total_fees_paid": 45
  }
}
```

## File Structure

```
trading/
├── engine.py                      # Modified: orchestrates Alpha + Hedge
├── execution/
│   ├── alpha_manager.py           # NEW: Upbit directional strategies
│   ├── hedge_manager.py           # NEW: Delta-neutral hedge execution
│   └── paper_account.py           # Existing
├── risk/
│   ├── premium_controller.py      # NEW: Upgraded from premium_tracker.py
│   ├── hedge_risk.py              # NEW: Hedge-specific risk guards
│   ├── premium_tracker.py         # DEPRECATED (kept for migration)
│   └── risk_controls.py           # Existing
├── data/
│   ├── feed_handler.py            # Modified: async price streams
│   └── data_cache.py              # NEW: in-memory DataFrame cache
├── strategy/
│   └── regime_router.py           # Unchanged (Alpha only)
└── adapters/
    └── binance.py                 # Minor: add hedge account support
```

## Configuration

**File:** `config/strategies/allocation.json`

```json
{
  "upbit": {
    "v35": {"ratio": 1.0, "enabled": true, "regimes": ["BULL"]},
    "va02": {"ratio": 0.0, "enabled": false, "regimes": ["BULL", "SIDEWAYS"]}
  },
  "hedge": {
    "enabled": true,
    "capital_usdt": 5000,
    "entry_threshold_pct": 1.5,
    "entry_sigma": 2.0,
    "volatility_block_threshold": 2.0,
    "negative_funding_exit": -0.05,
    "min_hold_minutes": 30
  }
}
```

## Implementation Order

1. **PremiumController** - Core signal logic
2. **HedgeManager** - Execution layer
3. **AlphaManager** - Extract from engine.py
4. **DataCache + FeedHandler** - Async performance
5. **engine.py refactor** - Orchestration
6. **Logging & dashboard** - Monitoring updates

## Success Criteria

- Alpha and Hedge P&L tracked separately
- Hedge achieves delta-neutral state (net_btc ≈ 0)
- No entry during high volatility periods
- Auto-exit on negative funding rates
- Position sync on startup
- < 5ms price fetch latency (from cache)
