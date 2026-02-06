# Data Flow Architecture Analysis

## Overview
This document maps how trading decision information (market data, indicators, regime state, risk info) flows through the system to strategy components.

---

## 1. High-Level Data Flow

```
BinanceFeedTask (WebSocket)
    ↓ (price ticks)
Redis: market:prices stream
    ↓ (consumed by)
CompositeStrategyTask
    ├─ IndicatorService (shared across all strategies)
    │   ├─ Calculates: MFI, ADX, RSI, MACD, Stochastic, ATR, BB, etc.
    │   └─ Caches results (TTL-based) for CPU efficiency
    │
    ├─ _build_market_data()
    │   └─ MarketData (immutable DTO with all indicators)
    │
    ├─ _build_market_context()
    │   └─ MarketContext (pre-analyzed trend/volatility/regime)
    │
    ├─ Entry Component (IEntryStrategy)
    │   └─ Signal (or None) based on regime + indicators
    │
    ├─ Exit Component (IExitStrategy)
    │   └─ Signal (or None) based on position + market data
    │
    └─ Signal → Order Intent → Redis: orders stream → Executor
```

---

## 2. Key Data Structures

### 2.1 MarketData (Immutable DTO)
**File**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/models.py:37-76`

Received by entry/exit strategies. Contains all pre-calculated indicators:

```python
@dataclass(frozen=True)
class MarketData:
    # Core indicators
    symbol: str
    close: float
    mfi: float              # Money Flow Index (0-100)
    adx: float              # Average Directional Index
    rsi: float              # Relative Strength Index
    timestamp: int          # Unix timestamp in milliseconds
    
    # OHLCV data
    high: float
    low: float
    volume: float
    
    # MACD (momentum entry/exit)
    macd: float
    macd_signal: float
    
    # Stochastic (conservative entry)
    stoch_k: float = 50.0
    stoch_d: float = 50.0
    
    # Bollinger Bands
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_middle: float = 0.0
    
    # ATR (volatility)
    atr: float = 0.0
    
    # 20-period lookback (breakout/range detection)
    prev_high_20: float = 0.0
    prev_low_20: float = 0.0
    avg_volume_20: float = 0.0
    
    # Generic indicators map (flexible)
    indicators: dict[str, float] = None
```

**Pain Point 1**: `high_water_mark` field is defined twice (line 68 and 76). This is a duplicate field definition.

---

### 2.2 MarketContext (Pre-Analyzed Market State)
**File**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/models.py:97-125`

Provides simplified classification for early filtering:

```python
@dataclass(frozen=True)
class MarketContext:
    # Simplified 3-level trend
    trend: Literal["BULL", "BEAR", "NEUTRAL"]
    
    # Detailed 7-level regime
    regime: Regime  # BULL_STRONG, BULL_MODERATE, SIDEWAYS_UP, etc.
    
    # Volatility analysis
    volatility_score: float              # ATR / close (normalized)
    is_extreme_volatility: bool          # volatility_score > 3%
    
    # Trend strength
    adx: float
    
    # Volume analysis
    volume_ratio: float = 1.0            # current_volume / avg_volume_20
    is_high_volume: bool = False         # volume_ratio > 1.5
```

**Function**: `build_market_context()` - Creates MarketContext from raw indicators.

---

### 2.3 Signal (Trading Signal)
**File**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/models.py:79-94`

Immutable output from entry/exit components:

```python
@dataclass(frozen=True)
class Signal:
    symbol: str
    side: Literal["buy", "sell"]
    market: Literal["futures"]
    quantity: float
    reason: str
    trigger_price: float | None = None  # Optional for limit orders
```

---

### 2.4 Position (Current Open Position)
**File**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/models.py:288-303`

Input to exit strategies:

```python
@dataclass(frozen=True)
class Position:
    symbol: str
    entry_price: float
    quantity: float
    strategy: str
    market: Literal["futures"]
    timestamp: int
    side: str = "buy"
    leverage: int = 1
    liquidation_price: float = 0.0
```

---

## 3. Data Flow Through CompositeStrategyTask

**File**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/composite_task.py`

### 3.1 Initialization
**Method**: `__init__` (line 53-112)

```python
def __init__(
    self,
    name: str,
    symbols: list[str],
    redis: RedisStreams,
    entry_strategy: IEntryStrategy,      # Component injected here
    exit_strategy: IExitStrategy,        # Component injected here
    indicator_service: IndicatorService | None = None,  # CPU optimization
    ...
):
    self.entry_strategy = entry_strategy
    self.exit_strategy = exit_strategy
    self.indicator_service = indicator_service
    
    # Local caches (per-strategy, fallback if no indicator_service)
    self._market_data_cache: dict[str, MarketData] = {}
    self._context_cache: dict[str, MarketContext] = {}
```

**Injection Pattern**: Entry/Exit components are constructor-injected, not fetched.

---

### 3.2 Entry Evaluation Loop
**Method**: `evaluate()` (line 138-173)

**Data Flow**:

1. **Get Price Buffer** (from Redis streams)
   ```python
   buffer = self.price_buffer.get(symbol, [])
   ```

2. **Build MarketData** (step 3.3)
   ```python
   market_data = self._build_market_data(symbol)
   ```

3. **Build MarketContext** (pre-analyzes market state)
   ```python
   context = self._build_market_context(market_data)
   ```

4. **Delegate to Entry Component**
   ```python
   signal = self.entry_strategy.check_entry(market_data, context)
   ```

5. **Convert Signal to Order Intent**
   ```python
   if signal:
       return self._signal_to_dict(signal, quantity)
   ```

---

### 3.3 Market Data Construction

**Method**: `_build_market_data()` (line 268-392)

**Two Paths** (priority order):

#### Path A: Centralized IndicatorService (Preferred - 75% CPU reduction)
```python
if self.indicator_service:
    buffer = self.price_buffer.get(symbol, [])
    current_price = float(buffer[-1]["price"]) if buffer else None
    if buffer:
        self.indicator_service.add_price(symbol, buffer[-1])
    return self.indicator_service.get_market_data(symbol, current_price)
```

**Advantage**: All strategies share one indicator calculation per symbol.

#### Path B: Local Calculation (Fallback/Legacy)
```python
else:  # No indicator_service
    # Check cache (time-based throttling)
    if cached and not should_recalc:
        return replace(cached, close=current_price, timestamp=current_timestamp)
    
    # Recalculate indicators
    df = pd.DataFrame(history)
    df.at[idx, "close"] = current_price  # Update with current price
    df = add_all_indicators(df)  # Expensive operation
    last_row = df.iloc[-1]
    
    # Build MarketData
    market_data = MarketData(
        symbol=symbol,
        close=current_price,
        mfi=float(last_row.get("mfi", 50)),
        adx=float(last_row.get("adx", 20)),
        # ... all indicators
    )
    self._market_data_cache[symbol] = market_data
    return market_data
```

**Indicators Calculated**:
- Trend: MFI, ADX
- Momentum: MACD, MACD Signal, RSI
- Volatility: ATR, Stochastic (K/D)
- Breakout: prev_high_20, prev_low_20, volume ratios
- Bands: Bollinger Bands

---

### 3.4 Market Context Construction

**Method**: `_build_market_context()` (line 395-410)

```python
def _build_market_context(self, market_data: MarketData) -> MarketContext:
    return build_market_context(
        mfi=market_data.mfi,
        adx=market_data.adx,
        atr=market_data.atr,
        close=market_data.close,
        # Optional: volume, avg_volume for high_volume detection
    )
```

**Classification Logic** (in `build_market_context()`):

```python
# Trend (simple 3-level)
if mfi >= 52:
    trend = "BULL"
elif mfi <= 48:
    trend = "BEAR"
else:
    trend = "NEUTRAL"

# Regime (7-level classification)
regime = _classify_regime(mfi, adx)
# Returns: BULL_STRONG, BULL_MODERATE, SIDEWAYS_UP, SIDEWAYS_FLAT, 
#          SIDEWAYS_DOWN, BEAR_MODERATE, BEAR_STRONG

# Volatility
volatility_score = atr / close if close > 0 else 0.0
is_extreme_volatility = volatility_score > 0.03  # 3% threshold

# Volume
volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
is_high_volume = volume_ratio > 1.5
```

---

## 4. Entry/Exit Strategy Interfaces

### 4.1 IEntryStrategy Interface
**File**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/interfaces.py:12-34`

```python
class IEntryStrategy(Protocol):
    def check_entry(
        self,
        market_data: MarketData,      # All indicators
        context: MarketContext,       # Pre-analyzed market state
    ) -> Signal | None:
        """Analyze market conditions and return entry signal."""
        ...
```

**Data Received**: MarketData + MarketContext (no raw history, no Redis access)

---

### 4.2 IExitStrategy Interface
**File**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/interfaces.py:37-78`

```python
class IExitStrategy(Protocol):
    def check_exit(
        self,
        position: Position,           # Current open position
        market_data: MarketData,      # All indicators
    ) -> Signal | None:
        """Evaluate exit conditions for existing position."""
        ...
    
    def on_position_opened(self, position: Position) -> None:
        """Initialize state when position opens."""
        ...
    
    def on_position_closed(self, symbol: str) -> None:
        """Cleanup state when position closes."""
        ...
```

**Data Received**: Position + MarketData (stateless evaluation + optional state management)

---

## 5. IndicatorService (CPU Optimization)

**File**: `/home/deploy/project/bitcoin-trading-bot/trading/indicators/indicator_service.py`

### Architecture
```
Before:  4 strategies × 3 symbols = 12 independent calculations
After:   1 calculation per symbol, shared by all 4 strategies
Result:  ~75% CPU reduction
```

### Usage Pattern

**Initialization** (in Engine):
```python
indicator_service = IndicatorService(cache_ttl=60)
```

**Warmup** (in CompositeStrategyTask.run()):
```python
for symbol in self.symbols:
    candles = await self.fetch_initial_candles(symbol, ...)
    if self.indicator_service:
        self.indicator_service.update_history(symbol, candles)
```

**Real-time Updates**:
```python
# In price buffer handling
if self.indicator_service:
    self.indicator_service.add_price(symbol, buffer[-1])

# Get cached market data
market_data = self.indicator_service.get_market_data(
    symbol=symbol,
    current_price=current_price
)
```

### Cache Design
- **Key**: Symbol
- **Value**: (timestamp, MarketData)
- **TTL**: Configurable (default 60s)
- **Hit Rate**: ~80-90% in normal operation (indicator values cluster)

---

## 6. Data Flow in Engine.py

**File**: `/home/deploy/project/bitcoin-trading-bot/trading/engine.py:212-274`

### Step 1: Create Shared IndicatorService
```python
indicator_service = IndicatorService(cache_ttl=60)
```

### Step 2: For Each Strategy
```python
for name in strategy_names:
    # Create Entry/Exit components via Factory
    entry, exit_strat = factory.create_components(name, config)
    
    # Create CompositeTask with shared service
    task = await create_composite_task(
        name=name,
        symbols=symbols,
        redis=self.redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
        indicator_service=indicator_service,  # SHARED!
    )
    
    self.tasks.append(asyncio.create_task(task.run()))
```

**Key**: Same `indicator_service` instance passed to all strategies.

---

## 7. Current Data Flow Patterns

### Pattern 1: Component Injection
**Location**: CompositeStrategyTask receives entry/exit as constructor params
```python
def __init__(self, ..., entry_strategy: IEntryStrategy, exit_strategy: IExitStrategy):
```

**Benefit**: Testable, mockable, swappable without code changes
**Risk**: Constructor signatures can get cluttered

---

### Pattern 2: Immutable DTOs
**Location**: MarketData, MarketContext, Signal, Position all use @dataclass(frozen=True)

**Benefit**: Thread-safe, no accidental mutations
**Risk**: Creating new instances on each update (minor overhead)

---

### Pattern 3: Redis-Backed State
**Location**: Positions, risk, and state stored in Redis hashes/streams

**Example**:
```python
positions:{symbol}:futures  # Hash with entry_price, quantity, strategy
state:{strategy}:{symbol}   # Hash with strategy-specific state
risk                        # Hash with kill_switch, daily_pnl, etc.
```

**Benefit**: Persistent across restarts, shared across processes
**Risk**: Redis dependency, latency on state queries

---

### Pattern 4: Async/Await for I/O
**Location**: All strategy evaluation methods are async

```python
async def evaluate(self, symbol: str) -> dict | None:
async def evaluate_exit(self, symbol: str, position_dict: dict) -> dict | None:
async def on_position_opened(self, symbol: str, position_dict: dict) -> None:
```

**Benefit**: Non-blocking I/O, enables concurrent processing
**Risk**: Complexity in error handling

---

## 8. Identified Pain Points & Duplication

### Pain Point 1: Duplicate `high_water_mark` Field
**File**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/models.py:68, 76`

**Issue**: `high_water_mark` is defined twice in MarketData:
```python
high_water_mark: float | None = None  # Track HWM for trailing stops  [Line 68]
...
high_water_mark: float | None = None  # Optional for trailing stop calculations  [Line 76]
```

**Impact**: One will be ignored (Python takes last definition)
**Fix**: Remove one definition, keep clear documentation

---

### Pain Point 2: Indicator Calculation Duplication (Pre-IndicatorService)
**Location**: CompositeStrategyTask._build_market_data() (fallback path) duplicates IndicatorService logic

**Issue**: If IndicatorService unavailable or not passed, strategy recalculates independently
```python
if self.indicator_service:
    return self.indicator_service.get_market_data(...)
else:  # Fallback - duplicates all calculation logic
    df = add_all_indicators(df)
    ...
```

**Impact**: 
- Maintenance burden (two code paths)
- Inconsistent results if both are used
- Inefficient if many strategies without IndicatorService

**Fix**: Make IndicatorService mandatory, always pass from Engine

---

### Pain Point 3: Context Cache Never Used
**Location**: CompositeStrategyTask.__init__ (line 113)

```python
self._context_cache: dict[str, MarketContext] = {}
```

**Issue**: Cache initialized but never populated or retrieved
```python
# In _build_market_context() - always recalculates
context = self._build_market_context(market_data)  # No cache lookup
```

**Impact**: Wasted memory allocation, unnecessary overhead
**Fix**: Remove unused cache or implement proper caching

---

### Pain Point 4: Implicit Data Dependencies
**Location**: Entry/Exit components assume specific MarketData fields

**Issue**: No explicit contract of which indicators are needed
```python
# Entry strategy _momentum_entry() expects:
if market_data.macd <= market_data.macd_signal:
    return None

# But MarketData has no docstring saying which fields are required
# for which entry strategies
```

**Impact**: 
- Easy to accidentally add strategy that needs new indicators
- No validation that required fields exist
- Silent failures if indicators unavailable

**Fix**: Create specific dataclasses for each entry strategy's requirements

---

### Pain Point 5: Double Regime Classification
**Location**: Multiple places classify market regime

1. **In MarketContext.build_market_context()** → `regime: Regime`
2. **In CompositeStrategyTask._check_and_record_decision()** → calls `_classify_regime()` again
3. **EntryStrategy._should_enter()** → uses regime from context but logs independently

**Issue**: Same classification logic called multiple times per evaluation
```python
# In build_market_context()
regime = _classify_regime(mfi, adx)

# Later in _check_and_record_decision()
if hasattr(self.entry_strategy, '_classify_regime'):
    regime = self.entry_strategy._classify_regime(market_data.mfi, market_data.adx)
```

**Impact**: CPU overhead, inconsistent results, maintenance nightmare
**Fix**: Always use MarketContext.regime, remove alternative classifications

---

### Pain Point 6: No Type Validation in Component Interfaces
**Location**: IEntryStrategy, IExitStrategy are Protocols (structural typing)

**Issue**: No way to verify that components satisfy interface at instantiation
```python
class IEntryStrategy(Protocol):
    def check_entry(self, market_data: MarketData, context: MarketContext) -> Signal | None:
        ...
```

**Impact**: 
- Runtime errors if component missing methods
- No IDE support for finding implementations
- Difficult to refactor (no references list)

**Fix**: Add validation in Factory or explicit ABC inheritance

---

### Pain Point 7: Risk Data Not Passed to Components
**Location**: CompositeStrategyTask evaluates independently of risk state

**Issue**: Entry components can't see kill_switch or daily_pnl
```python
# Risk state exists in Redis
positions, risk_state = await asyncio.gather(
    self.redis._client.hgetall(position_key),
    self.redis._client.hgetall("risk")  # Not passed to strategies!
)

# But components can't access it
signal = self.entry_strategy.check_entry(market_data, context)
# Components don't know about risk constraints
```

**Impact**: 
- Strategies can generate signals when kill_switch is active
- No way to implement risk-aware entry logic
- Executor has to filter after-the-fact

**Fix**: Add optional RiskContext to entry strategy interface

---

## 9. Data Flow Summary Chart

```
┌─────────────────────────────────────────────────────────────┐
│ ENTRY POINT: BinanceFeedTask (price ticks)                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ Redis: market:prices       │
        │ (stream of price updates)  │
        └────────────┬───────────────┘
                     │
                     ▼
        ┌────────────────────────────────────┐
        │ CompositeStrategyTask.evaluate()   │
        ├────────────────────────────────────┤
        │ 1. Get price_buffer[symbol]        │
        │ 2. _build_market_data()            │
        │    ├─ Via IndicatorService (opt)  │
        │    └─ Via local calc (fallback)   │
        │ 3. _build_market_context()         │
        │    └─ Classify regime, volatility  │
        │ 4. Call entry_strategy.check_entry │
        │    (market_data, context)          │
        │ 5. If signal: _signal_to_dict()    │
        └────────┬──────────────────────────┘
                 │
                 ▼
        ┌────────────────────────────┐
        │ Redis: orders stream       │
        │ (entry/exit order intents) │
        └────────┬──────────────────┘
                 │
                 ▼
        ┌────────────────────────────────────┐
        │ Executor (Paper/Live)              │
        │ Places orders, manages positions   │
        └────────┬──────────────────────────┘
                 │
                 ▼
        ┌────────────────────────────┐
        │ Redis: trades stream       │
        │ (executed trade confirmations) │
        └────────────────────────────┘
```

---

## 10. Recommendations

### High Priority
1. **Remove duplicate `high_water_mark` field** in MarketData
2. **Make IndicatorService mandatory** - always pass from Engine, remove fallback path
3. **Remove unused `_context_cache`** - saves memory allocation
4. **Consolidate regime classification** - always use MarketContext.regime, remove redundant calls

### Medium Priority
5. **Add RiskContext parameter** to entry/exit interfaces so components can respect kill_switch
6. **Create specific data requirement specs** for each entry/exit strategy type
7. **Add validation in StrategyFactory** to check component interface compliance

### Low Priority
8. **Consider ABC inheritance** instead of just Protocols for better IDE support
9. **Cache MarketContext** once per evaluation cycle (not just MarketData)
10. **Document indicator requirements** for each strategy variant

---

## References

- **CompositeStrategyTask**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/composite_task.py`
- **Data Models**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/models.py`
- **IndicatorService**: `/home/deploy/project/bitcoin-trading-bot/trading/indicators/indicator_service.py`
- **Entry Strategy Example**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/short_entry.py`
- **Engine Orchestration**: `/home/deploy/project/bitcoin-trading-bot/trading/engine.py`
- **Interfaces**: `/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/interfaces.py`
