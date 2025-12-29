# Multi-Asset Portfolio Expansion Design

**Version**: v0.0.6
**Date**: 2025-12-29
**Status**: Approved

## Objective

Transition the current Bitcoin-centric system into a Multi-Asset Trading Platform. Leverage the AsyncTradingEngine architecture to trade multiple high-liquidity assets (BTC, ETH, SOL) simultaneously, diversifying risk and capturing asset-specific Kimchi Premium spreads.

## Goals

1. **Diversification** - Spread risk across multiple uncorrelated assets
2. **Arbitrage opportunities** - Capture different Kimchi premiums per coin
3. **Capital efficiency** - Deploy idle capital when BTC has no signal

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Asset selection | Configurable, start with BTC + ETH + SOL | Flexibility without code changes |
| Hedging approach | Hybrid (per-asset where available) | BTC/ETH hedge, SOL alpha-only |
| Capital allocation | Fixed ratios in config | Simplicity; dynamic rebalancing deferred to v0.0.7 |
| Strategy assignment | Shared strategies with per-asset params | Reuse v35/va02, tune via config |
| Data storage | Separate DB per asset | Maintains current structure, enables backtesting |

## Configuration Schema

```json
{
  "assets": {
    "BTC": {
      "enabled": true,
      "alpha_ratio": 0.6,
      "hedge_enabled": true,
      "upbit_symbol": "KRW-BTC",
      "binance_symbol": "BTCUSDT",
      "strategies": {
        "BULL": "v35",
        "SIDEWAYS": "sideways_v2",
        "BEAR": null
      },
      "params_override": {}
    },
    "ETH": {
      "enabled": true,
      "alpha_ratio": 0.3,
      "hedge_enabled": true,
      "upbit_symbol": "KRW-ETH",
      "binance_symbol": "ETHUSDT",
      "strategies": {
        "BULL": "v35",
        "SIDEWAYS": "sideways_v2",
        "BEAR": null
      },
      "params_override": {
        "entry_threshold_pct": 2.0
      }
    },
    "SOL": {
      "enabled": true,
      "alpha_ratio": 0.1,
      "hedge_enabled": false,
      "upbit_symbol": "KRW-SOL",
      "binance_symbol": "SOLUSDT",
      "strategies": {
        "BULL": "v35",
        "SIDEWAYS": null,
        "BEAR": null
      },
      "params_override": {
        "entry_threshold_pct": 2.5
      }
    }
  },
  "hedge": {
    "capital_usdt": 5000,
    "entry_threshold_pct": 1.5,
    "max_capital_usage_pct": 0.8
  },
  "future_v007": {
    "dynamic_rebalancing": "deferred"
  }
}
```

### Config Notes

- `alpha_ratio` values must sum to 1.0
- `hedge_enabled` controls per-asset hedging (requires Binance futures liquidity)
- `params_override` allows per-asset strategy parameter tuning
- `future_v007` documents deferred features

## Architecture Changes

### Data Layer

#### PriceHub (Multi-Symbol)

```python
class PriceHub:
    def __init__(self, symbols: list[str]):
        # Per-symbol price storage
        self._prices: dict[str, SymbolPrices] = {
            sym: SymbolPrices() for sym in symbols
        }
        # Per-symbol subscribers
        self._subscribers: dict[str, list[asyncio.Queue]] = {
            sym: [] for sym in symbols
        }

    def update_price(self, symbol: str, exchange: str, price: float):
        """Update price for specific symbol and exchange."""
        self._prices[symbol].update(exchange, price, self._fx_rate)
        if self._prices[symbol].should_notify():
            self._notify_subscribers(symbol)

    def get_premium(self, symbol: str) -> PremiumInfo:
        """Get premium for specific symbol."""
        return self._prices[symbol].premium_info

    def subscribe(self, symbol: str) -> asyncio.Queue:
        """Subscribe to price events for a symbol."""
        queue = asyncio.Queue()
        self._subscribers[symbol].append(queue)
        return queue
```

#### SimpleFeedHandler (Multi-Symbol)

```python
class SimpleFeedHandler:
    def __init__(self, symbols: list[str]):
        self._symbols = symbols
        # Upbit: ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
        # Binance: ["btcusdt", "ethusdt", "solusdt"]

    async def _connect_upbit(self):
        # Single WebSocket, multiple symbol subscription
        subscribe_msg = [
            {"ticket": "..."},
            {"type": "ticker", "codes": self._upbit_symbols}
        ]
```

#### DataCache (Partitioned)

```python
class DataCache:
    def __init__(self, symbols: list[str]):
        # Nested structure: symbol -> timeframe -> DataFrame
        self._cache: dict[str, dict[str, pd.DataFrame]] = {
            sym: {"minute60": pd.DataFrame(), "day": pd.DataFrame()}
            for sym in symbols
        }

    def get_df(self, symbol: str, timeframe: str) -> pd.DataFrame:
        return self._cache[symbol][timeframe]
```

### Execution Layer

#### PortfolioManager (New Component)

```python
# trading/execution/portfolio_manager.py

class PortfolioManager:
    """Manages capital allocation across multiple assets."""

    def __init__(self, total_capital_krw: float, config: dict):
        self._total_capital = total_capital_krw
        self._allocations = self._load_allocations(config)
        self._positions: dict[str, AssetPosition] = {}

    def get_capital_for_asset(self, symbol: str) -> float:
        """Returns allocated capital for a specific asset."""
        ratio = self._allocations[symbol].alpha_ratio
        return self._total_capital * ratio

    def get_portfolio_state(self) -> PortfolioState:
        """Aggregate view: total exposure, per-asset breakdown."""
        return PortfolioState(
            total_value_krw=self._calculate_total_value(),
            positions=self._positions,
            exposure_pct=self._calculate_exposure()
        )
```

#### AlphaManager (Multi-Asset)

```python
class AlphaManager:
    def __init__(self, symbols: list[str], portfolio: PortfolioManager):
        self._symbols = symbols
        self._portfolio = portfolio
        # Per-asset strategy runners
        self._runners: dict[str, StrategyRunner] = {
            sym: StrategyRunner(sym, config) for sym in symbols
        }

    async def evaluate_all(self, regime: MarketRegime) -> list[AlphaSignal]:
        """Evaluate all assets concurrently."""
        tasks = [
            self._evaluate_asset(sym, regime)
            for sym in self._symbols
        ]
        # Parallel evaluation - keeps latency low
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def _evaluate_asset(self, symbol: str, regime: MarketRegime):
        capital = self._portfolio.get_capital_for_asset(symbol)
        signal = await self._runners[symbol].evaluate(regime, capital)
        if signal and signal.action != "hold":
            self._delta_rebalancer.on_alpha_trade(symbol, signal)
        return signal
```

### Hedging Layer

#### DeltaRebalancer (Multi-Asset)

```python
class DeltaRebalancer:
    def __init__(self, symbols: list[str], hedge_config: dict):
        # Per-asset delta tracking
        self._deltas: dict[str, DeltaState] = {
            sym: DeltaState() for sym in symbols
        }
        # Only track hedgeable assets
        self._hedgeable = [s for s in symbols if hedge_config[s]["hedge_enabled"]]

    def on_alpha_trade(self, symbol: str, signal: AlphaSignal):
        """Accumulate pending delta for specific asset."""
        if symbol not in self._hedgeable:
            return  # Skip non-hedged assets (e.g., SOL)
        self._deltas[symbol].pending += signal.qty

    async def flush_rebalance(self, prices: dict[str, float]):
        """Rebalance each hedgeable asset independently."""
        for symbol in self._hedgeable:
            state = self._deltas[symbol]
            if self._needs_rebalance(state):
                await self._hedge_manager.adjust_position(
                    symbol, state.target_qty, prices[symbol]
                )
```

#### HedgeManager (Multi-Asset)

```python
class HedgeManager:
    def __init__(self, symbols: list[str], capital_usdt: float):
        # Per-asset hedge positions
        self._positions: dict[str, HedgePosition] = {}
        # Capital split across hedgeable assets (proportional)
        self._capital_per_asset = self._allocate_hedge_capital(symbols)

    async def adjust_position(self, symbol: str, target_qty: float, price: float):
        """Adjust short position for specific asset."""
        current = self._positions.get(symbol, HedgePosition())
        diff = target_qty - current.qty

        if abs(diff) < self._min_order_size[symbol]:
            return

        binance_symbol = self._symbol_map[symbol]  # BTC -> BTCUSDT
        if diff > 0:
            await self._open_short(binance_symbol, diff, price)
        else:
            await self._close_short(binance_symbol, abs(diff), price)

    def get_total_hedge_exposure(self) -> dict[str, float]:
        """Returns hedge exposure per asset in USD."""
        return {
            sym: pos.qty * pos.current_price
            for sym, pos in self._positions.items()
        }
```

### Engine Orchestration

#### AsyncTradingEngine (Multi-Asset)

```python
class AsyncTradingEngine:
    def __init__(self, config: dict):
        # Load enabled symbols from config
        self._symbols = [s for s, c in config["assets"].items() if c["enabled"]]

        # Initialize multi-asset components
        self._price_hub = PriceHub(self._symbols)
        self._data_cache = DataCache(self._symbols)
        self._feed_handler = SimpleFeedHandler(self._symbols)
        self._portfolio = PortfolioManager(self._total_capital, config)
        self._alpha_manager = AlphaManager(self._symbols, self._portfolio)
        self._hedge_manager = HedgeManager(
            [s for s in self._symbols if config["assets"][s]["hedge_enabled"]],
            config["hedge"]["capital_usdt"]
        )
        self._delta_rebalancer = DeltaRebalancer(self._symbols, config["assets"])

    async def _main_loop(self):
        """Process price events for all symbols."""
        while self._running:
            # Wait for any symbol's price change
            events = await self._wait_for_price_events()

            for event in events:
                symbol = event.symbol
                self._data_cache.update_from_tick(symbol, event)

                if event.change_pct > 0.1:
                    await self._evaluate_symbol(symbol)

            # Flush delta rebalancing after all evaluations
            await self._delta_rebalancer.flush_rebalance(
                self._get_current_prices()
            )

    async def _evaluate_symbol(self, symbol: str):
        """Evaluate and execute for a single symbol."""
        regime = self._regime_router.get_regime(symbol)
        signal = await self._alpha_manager.evaluate_asset(symbol, regime)

        if signal and signal.action != "hold":
            await self._executor.submit(signal)
```

### Status Logging (Multi-Asset)

```json
{
  "timestamp": "2025-01-15T10:30:00",
  "assets": {
    "BTC": {"price_krw": 145000000, "premium_pct": 1.8, "delta": 0.02},
    "ETH": {"price_krw": 5200000, "premium_pct": 2.1, "delta": 0.01},
    "SOL": {"price_krw": 320000, "premium_pct": 2.5, "delta": null}
  },
  "portfolio": {
    "total_value_krw": 50000000,
    "exposure_pct": 65
  }
}
```

## Data Collection

### Collector Updates

```bash
# upbit-collector multi-symbol support
./upbit-collector --symbols BTC,ETH,SOL

# Creates separate DBs:
# data/upbit_bitcoin.db   (existing)
# data/upbit_ethereum.db  (new)
# data/upbit_solana.db    (new)
```

## Implementation Order

### Phase 1: Config & Types (Foundation)
- Update `allocation.json` schema
- Add `AssetConfig`, `PortfolioState` types to `core/types.py`

### Phase 2: Data Layer (Bottom-Up)
- `SimpleFeedHandler` multi-symbol WebSocket
- `PriceHub` multi-symbol tracking
- `DataCache` partitioned storage
- `upbit-collector` multi-symbol support

### Phase 3: Execution Layer (Middle)
- New `PortfolioManager` component
- `AlphaManager` multi-asset iteration
- `StrategyRunner` per-asset instantiation

### Phase 4: Hedging Layer (Top)
- `DeltaRebalancer` per-asset tracking
- `HedgeManager` per-asset positions

### Phase 5: Engine Integration (Orchestration)
- `AsyncTradingEngine` wiring
- Status logging updates

### Phase 6: Testing & Validation
- Unit tests per component
- Integration test with paper trading
- Backtest validation per asset

## Deferred to v0.0.7

- **Dynamic capital rebalancing** - Adjust weights based on volatility/performance
- **Asset-specific strategies** - eth_momentum, sol_breakout
- **Cross-asset correlation monitoring** - Reduce exposure when assets correlate

## Files to Create/Modify

### New Files
- `trading/execution/portfolio_manager.py`
- `config/strategies/allocation.json` (update schema)

### Modified Files
- `trading/core/price_hub.py`
- `trading/core/data_cache.py`
- `trading/core/types.py`
- `trading/data/simple_feed_handler.py`
- `trading/execution/alpha_manager.py`
- `trading/execution/hedge_manager.py`
- `trading/execution/delta_rebalancer.py`
- `trading/async_engine.py`
- `upbit_history_db/` (collector updates)

## Performance Targets

- Maintain <50ms per evaluation cycle
- Parallel evaluation via `asyncio.gather`
- Single WebSocket per exchange (multi-symbol subscription)
- No additional DB queries per cycle
