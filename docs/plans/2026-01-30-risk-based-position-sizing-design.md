# Risk-Based Position Sizing Refactoring

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


**Date**: 2026-01-30
**Status**: Draft
**Target Strategy**: tuned_v35_long_v2_core_overlay_v2

## Problem Statement

현재 tuned_v35_long_v2_core_overlay_v2 전략은 **포지션 크기(position_pct)** 기반으로 진입한다:
- `position_pct: 0.12` = 잔고의 12%를 한 트레이드에 사용
- RF 확신도에 따라 0.03~0.12 범위에서 조정

**문제점**:
1. 포지션을 키우면 MDD가 급증하고 수익률이 붕괴
2. 손절 거리(stop_distance)를 무시하고 고정 비율로 진입
3. 동시 포지션 리스크 합산 개념 없음
4. 상관관계 높은 자산들에 동시 노출 시 리스크 폭발

## Solution: Risk-Based Sizing

### 핵심 원칙

```
1% = 포지션 비중이 아니라 '최대 손실(Risk)'

qty = risk_budget / (stop_distance * entry_price)

where:
  risk_budget = equity * risk_per_trade (default 1%)
  stop_distance = ATR * multiplier (or fixed %)
```

### 예시

| Equity | Risk/Trade | Stop Distance | Entry Price | Quantity |
|--------|------------|---------------|-------------|----------|
| $10,000 | 1% ($100) | 3% | $100,000 | 0.033 BTC |
| $10,000 | 1% ($100) | 5% | $100,000 | 0.02 BTC |
| $10,000 | 1% ($100) | 2% | $3,000 | 1.67 ETH |

손절 거리가 클수록 포지션이 작아지고, 작을수록 커진다.
**결과: 모든 트레이드의 예상 최대 손실이 equity의 1%로 고정**

---

## Architecture Changes

### 1. New Module: PositionSizer

**File**: `trading/risk/position_sizer.py`

```python
@dataclass
class SizingResult:
    quantity: float        # 계산된 수량
    risk_amount: float     # 리스크 금액 (USDT)
    stop_distance_pct: float
    leverage_adjusted: bool

def calculate_quantity(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = 0.01,       # 1% default
    leverage: int = 1,
    min_qty: float = 0.0,
    qty_step: float = 0.001,
    fee_pct: float = 0.001,       # 0.1% fee buffer
) -> SizingResult:
    """Risk-based position sizing."""

    risk_budget = equity * risk_pct
    stop_distance = abs(entry_price - stop_price) / entry_price

    # Stop distance must be > 0
    if stop_distance < 0.001:
        raise ValueError("Stop distance too small (<0.1%)")

    # Adjust for fees (entry + exit)
    effective_stop = stop_distance + fee_pct * 2

    # Calculate raw quantity
    raw_qty = risk_budget / (effective_stop * entry_price)

    # Apply leverage (increases qty but also risk)
    # Note: leverage does NOT change risk_budget, only amplifies P&L
    # If using leverage, stop_distance is leveraged too
    leveraged_stop = stop_distance * leverage
    raw_qty = risk_budget / (leveraged_stop * entry_price / leverage)

    # Simplified: qty = risk / (stop_pct * price) regardless of leverage
    # because leverage affects both qty and stop in opposite directions
    raw_qty = risk_budget / (stop_distance * entry_price)

    # Round to exchange step
    quantity = round_to_step(raw_qty, qty_step)

    # Enforce minimum
    if quantity < min_qty:
        return SizingResult(0, 0, stop_distance, False)

    actual_risk = quantity * entry_price * stop_distance

    return SizingResult(
        quantity=quantity,
        risk_amount=actual_risk,
        stop_distance_pct=stop_distance * 100,
        leverage_adjusted=leverage > 1,
    )
```

### 2. New Module: PortfolioRiskManager

**File**: `trading/risk/portfolio_risk_manager.py`

```python
@dataclass
class RiskCapConfig:
    max_total_risk_pct: float = 0.05    # 5% max total risk
    max_open_positions: int = 5
    risk_per_trade_pct: float = 0.01    # 1% per trade
    corr_threshold: float = 0.75        # Block if corr > 0.75
    corr_lookback: int = 240            # 4 hours of 1-min data

@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str
    adjusted_risk_pct: float | None = None  # 상관 필터 시 축소된 리스크

class PortfolioRiskManager:
    """포트폴리오 레벨 리스크 관리"""

    def __init__(self, config: RiskCapConfig, redis: RedisStreams):
        self.config = config
        self.redis = redis
        self._return_cache: Dict[str, pd.Series] = {}

    async def can_open_trade(
        self,
        symbol: str,
        proposed_risk: float,  # USDT
        equity: float,
    ) -> RiskCheckResult:
        """신규 진입 가능 여부 확인"""

        # 1. Get current open positions and their risks
        open_risks = await self._get_open_position_risks()

        # 2. Check position count
        if len(open_risks) >= self.config.max_open_positions:
            return RiskCheckResult(False, "MAX_POSITIONS_REACHED")

        # 3. Check total risk cap
        current_total_risk = sum(open_risks.values())
        max_total_risk = equity * self.config.max_total_risk_pct

        if current_total_risk + proposed_risk > max_total_risk:
            return RiskCheckResult(
                False,
                f"TOTAL_RISK_CAP_EXCEEDED:{current_total_risk + proposed_risk:.0f}>{max_total_risk:.0f}"
            )

        # 4. Correlation filter
        if open_risks:
            corr_result = await self._check_correlation(symbol, list(open_risks.keys()))
            if not corr_result.allowed:
                return corr_result

        return RiskCheckResult(True, "OK")

    async def _get_open_position_risks(self) -> Dict[str, float]:
        """각 포지션의 예상 손실 금액 계산"""
        positions = {}
        for symbol in ["BTC", "ETH", "SOL"]:
            pos = await self.redis.get_position(symbol, "futures")
            if pos and float(pos.get("quantity", 0)) > 0:
                entry = float(pos.get("entry_price", 0))
                qty = float(pos.get("quantity", 0))
                # Stop distance from strategy config or default 3%
                stop_pct = float(pos.get("stop_pct", 0.03))
                risk = qty * entry * stop_pct
                positions[symbol] = risk
        return positions

    async def _check_correlation(
        self,
        new_symbol: str,
        existing_symbols: List[str],
    ) -> RiskCheckResult:
        """상관관계 필터"""
        for existing in existing_symbols:
            corr = await self._calculate_correlation(new_symbol, existing)
            if corr > self.config.corr_threshold:
                return RiskCheckResult(
                    False,
                    f"HIGH_CORRELATION:{new_symbol}-{existing}={corr:.2f}"
                )
        return RiskCheckResult(True, "CORR_OK")
```

### 3. New Module: CorrelationFilter

**File**: `trading/risk/correlation_filter.py`

```python
class CorrelationFilter:
    """실시간 상관계수 계산 및 필터링"""

    def __init__(
        self,
        redis: RedisStreams,
        lookback: int = 240,      # 4 hours of 1-min data
        threshold: float = 0.75,
        cache_ttl: int = 300,     # 5 min cache
    ):
        self.redis = redis
        self.lookback = lookback
        self.threshold = threshold
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Tuple[float, float]] = {}  # (corr, timestamp)

    async def get_returns(self, symbol: str) -> pd.Series:
        """Redis에서 최근 수익률 시계열 가져오기"""
        key = f"prices:{symbol}:minute"
        data = await self.redis.lrange(key, 0, self.lookback)
        prices = pd.Series([float(d['close']) for d in data])
        returns = prices.pct_change().dropna()
        return returns

    async def calculate_correlation(
        self,
        symbol_a: str,
        symbol_b: str,
    ) -> float:
        """두 심볼 간 상관계수 계산"""
        cache_key = f"{min(symbol_a, symbol_b)}_{max(symbol_a, symbol_b)}"

        # Check cache
        if cache_key in self._cache:
            corr, ts = self._cache[cache_key]
            if time.time() - ts < self.cache_ttl:
                return corr

        # Calculate
        returns_a = await self.get_returns(symbol_a)
        returns_b = await self.get_returns(symbol_b)

        # Align indices
        combined = pd.concat([returns_a, returns_b], axis=1).dropna()
        if len(combined) < 30:  # Min data points
            return 0.0

        corr = combined.iloc[:, 0].corr(combined.iloc[:, 1])

        # Cache
        self._cache[cache_key] = (corr, time.time())

        return corr

    async def should_block(
        self,
        new_symbol: str,
        existing_symbols: List[str],
    ) -> Tuple[bool, str]:
        """신규 심볼이 기존 포지션과 높은 상관관계인지 확인"""
        for existing in existing_symbols:
            corr = await self.calculate_correlation(new_symbol, existing)
            if corr > self.threshold:
                return True, f"{new_symbol}-{existing} corr={corr:.2f}"
        return False, "OK"
```

---

## Integration Points

### 1. CompositeStrategyTask 수정

**File**: `trading/strategies/components/composite_task.py`

Entry signal 생성 후, 주문 발행 전에 리스크 체크 삽입:

```python
# In CompositeStrategyTask._handle_entry()

# 1. Entry signal from strategy component
signal = self.entry_strategy.check_entry(ctx)
if not signal:
    return

# 2. Calculate stop price (from exit strategy params)
stop_price = self._calculate_stop_price(ctx.market.close)

# 3. Risk-based sizing
sizing = self.position_sizer.calculate_quantity(
    equity=ctx.equity,
    entry_price=ctx.market.close,
    stop_price=stop_price,
    risk_pct=self.config.get("risk_per_trade_pct", 0.01),
    leverage=self.config.get("leverage", 1),
)

if sizing.quantity == 0:
    logger.info(f"Sizing too small, skipping entry")
    return

# 4. Portfolio risk check
risk_check = await self.portfolio_risk_mgr.can_open_trade(
    symbol=ctx.market.symbol,
    proposed_risk=sizing.risk_amount,
    equity=ctx.equity,
)

if not risk_check.allowed:
    logger.info(f"Entry blocked: {risk_check.reason}")
    return

# 5. Publish order with calculated quantity
order = Order(
    symbol=signal.symbol,
    side=signal.side,
    quantity=sizing.quantity,
    ...
)
```

### 2. allocation.json 확장

```json
{
  "strategies": {
    "tuned_v35_long_v2_core_overlay_v2": {
      // ... existing config ...

      // NEW: Risk-based sizing
      "risk_based_sizing": true,
      "risk_per_trade_pct": 0.01,      // 1% risk per trade
      "max_total_risk_pct": 0.05,      // 5% max total risk
      "max_open_positions": 5,

      // NEW: Correlation filter
      "correlation_filter": true,
      "corr_threshold": 0.75,
      "corr_lookback_bars": 240,
      "corr_action": "block"           // "block" | "reduce" | "group_cap"
    }
  }
}
```

### 3. Redis Position Schema 확장

현재:
```
positions:{symbol}:futures → {quantity, entry_price, strategy, side, leverage}
```

추가:
```
positions:{symbol}:futures → {
    ...,
    stop_price: str,      # 손절가
    risk_amount: str,     # 예상 손실 (USDT)
    risk_pct: str,        # 리스크 비율
}
```

---

## Edge Cases

### 1. 부분 체결 (Partial Fill)

```python
def handle_partial_fill(order, fill):
    """부분 체결 시 리스크 재계산"""
    filled_qty = fill.quantity
    remaining_qty = order.quantity - filled_qty

    # 체결된 부분의 리스크
    filled_risk = filled_qty * order.entry_price * order.stop_pct

    # Redis에 저장
    update_position_risk(order.symbol, filled_risk)

    # 남은 수량은 다음 체결까지 대기
    # 총 리스크 캡 업데이트
```

### 2. 최소 주문 수량/스텝

```python
# Exchange-specific minimums
EXCHANGE_LIMITS = {
    "BTC": {"min_qty": 0.001, "qty_step": 0.001, "min_notional": 10},
    "ETH": {"min_qty": 0.01, "qty_step": 0.01, "min_notional": 10},
    "SOL": {"min_qty": 0.1, "qty_step": 0.1, "min_notional": 10},
}

def round_to_step(qty: float, step: float) -> float:
    return round(qty / step) * step

def enforce_minimums(qty: float, symbol: str, price: float) -> float:
    limits = EXCHANGE_LIMITS[symbol]

    # Round to step
    qty = round_to_step(qty, limits["qty_step"])

    # Check minimum quantity
    if qty < limits["min_qty"]:
        return 0  # Too small to trade

    # Check minimum notional
    if qty * price < limits["min_notional"]:
        return 0

    return qty
```

### 3. 레버리지와 마진

```python
def check_margin_sufficiency(
    equity: float,
    position_value: float,
    leverage: int,
    existing_margin_used: float,
) -> bool:
    """마진 충분 여부 확인"""
    required_margin = position_value / leverage
    available_margin = equity - existing_margin_used

    # 20% 버퍼
    return available_margin * 0.8 >= required_margin
```

### 4. 펀딩비/수수료 반영

```python
def calculate_breakeven(
    entry_price: float,
    stop_pct: float,
    fee_pct: float = 0.001,      # 0.1% trading fee
    funding_rate: float = 0.0,   # 펀딩비 (보통 8시간마다)
    hold_hours: int = 24,
) -> float:
    """손익분기점 계산 (수수료, 펀딩비 포함)"""

    # Entry + Exit fees
    total_fees = fee_pct * 2

    # Estimated funding cost
    funding_periods = hold_hours / 8
    total_funding = abs(funding_rate) * funding_periods

    # Breakeven = fees + funding
    breakeven_pct = total_fees + total_funding

    return breakeven_pct
```

---

## Testing Plan

### 1. Unit Tests: PositionSizer

```python
def test_basic_sizing():
    """기본 리스크 기반 사이징"""
    result = calculate_quantity(
        equity=10000,
        entry_price=100000,  # BTC
        stop_price=97000,    # 3% stop
        risk_pct=0.01,       # 1% risk
    )
    # risk = $100, stop = 3%, qty = 100 / (0.03 * 100000) = 0.033
    assert abs(result.quantity - 0.033) < 0.001
    assert abs(result.risk_amount - 100) < 1

def test_minimum_qty():
    """최소 수량 미달 시 0 반환"""
    result = calculate_quantity(
        equity=100,           # Small account
        entry_price=100000,
        stop_price=97000,
        risk_pct=0.01,
        min_qty=0.001,
    )
    # risk = $1, qty = 0.00033 < min_qty
    assert result.quantity == 0

def test_leverage_sizing():
    """레버리지 사용 시 사이징"""
    result = calculate_quantity(
        equity=10000,
        entry_price=100000,
        stop_price=97000,
        risk_pct=0.01,
        leverage=3,
    )
    # Leverage doesn't change risk budget
    # qty is same but position value is 3x
    assert abs(result.quantity - 0.033) < 0.001
```

### 2. Unit Tests: PortfolioRiskManager

```python
@pytest.mark.asyncio
async def test_total_risk_cap():
    """총 리스크 캡 동작"""
    mgr = PortfolioRiskManager(RiskCapConfig(max_total_risk_pct=0.05))

    # Mock existing positions with $400 risk (4%)
    mock_positions = {"BTC": 200, "ETH": 200}

    # Try to add $200 more (2%) - should fail (4% + 2% > 5%)
    result = await mgr.can_open_trade("SOL", 200, equity=10000)
    assert result.allowed == False
    assert "TOTAL_RISK_CAP" in result.reason

@pytest.mark.asyncio
async def test_position_count_cap():
    """포지션 수 하드 캡"""
    mgr = PortfolioRiskManager(RiskCapConfig(max_open_positions=3))

    # Mock 3 existing positions
    # Try to add 4th - should fail
    ...
```

### 3. Unit Tests: CorrelationFilter

```python
@pytest.mark.asyncio
async def test_correlation_block():
    """높은 상관관계 시 진입 차단"""
    filter = CorrelationFilter(threshold=0.75)

    # Mock BTC-ETH correlation = 0.85
    blocked, reason = await filter.should_block("ETH", ["BTC"])
    assert blocked == True
    assert "corr=0.85" in reason

@pytest.mark.asyncio
async def test_low_correlation_pass():
    """낮은 상관관계 시 통과"""
    filter = CorrelationFilter(threshold=0.75)

    # Mock BTC-SOL correlation = 0.45
    blocked, reason = await filter.should_block("SOL", ["BTC"])
    assert blocked == False
```

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `trading/risk/position_sizer.py` | **CREATE** | Risk-based qty calculation |
| `trading/risk/portfolio_risk_manager.py` | **CREATE** | Total risk cap + position limits |
| `trading/risk/correlation_filter.py` | **CREATE** | Symbol correlation filtering |
| `trading/strategies/components/composite_task.py` | MODIFY | Integrate sizing + risk checks |
| `config/strategies/allocation.json` | MODIFY | Add risk parameters |
| `trading/executor/async_executor.py` | MODIFY | Pass stop_price in position |
| `tests/test_position_sizer.py` | **CREATE** | Unit tests |
| `tests/test_portfolio_risk.py` | **CREATE** | Integration tests |

---

## Migration Path

1. **Phase 1**: Implement modules with feature flag `risk_based_sizing: false`
2. **Phase 2**: Enable on paper trading, monitor sizing decisions
3. **Phase 3**: Backtest comparison (old vs new sizing)
4. **Phase 4**: Enable on live with small risk_pct (0.5%)
5. **Phase 5**: Tune risk_pct based on performance

---

## Success Metrics

| Metric | Before | Target |
|--------|--------|--------|
| Max single-trade loss | 5-10% | 1-2% |
| Max total exposure | Unlimited | 5% |
| MDD during position scaling | 30%+ | <15% |
| Correlation diversification | None | Enforced |

---

## Implementation: CompositeStrategyTask Integration

### Step 1: Add Imports and Instance Variables

In `trading/strategies/components/composite_task.py`, add:

```python
# Add at top of file
from trading.risk.position_sizer import PositionSizer, RiskSizingConfig
from trading.risk.portfolio_risk_manager import PortfolioRiskManager, RiskCapConfig
from trading.risk.correlation_filter import CorrelationFilter, CorrelationConfig

# Add in __init__:
class CompositeStrategyTask(BaseStrategyTask):
    def __init__(self, ...):
        # ... existing code ...

        # Risk-based sizing (new)
        self._risk_based_sizing = self.config.get("risk_based_sizing", False)
        if self._risk_based_sizing:
            sizing_config = RiskSizingConfig.from_dict(self.config)
            self._position_sizer = PositionSizer(sizing_config)

            # Portfolio risk manager
            risk_cap_config = RiskCapConfig.from_dict(self.config)

            # Correlation filter (optional)
            corr_filter = None
            if self.config.get("correlation_filter", True):
                corr_config = CorrelationConfig.from_dict(self.config)
                corr_filter = CorrelationFilter(corr_config, redis)

            self._portfolio_risk_mgr = PortfolioRiskManager(
                risk_cap_config, redis, corr_filter
            )
        else:
            self._position_sizer = None
            self._portfolio_risk_mgr = None
```

### Step 2: Replace `_get_quantity()` Method

Replace the existing `_get_quantity()` method (lines 1038-1070):

```python
async def _get_quantity(
    self,
    symbol: str,
    price: float,
    default_quantity: float,
    context: MarketContext | None = None,
    market_data: MarketData | None = None,
) -> tuple[float, float | None]:
    """Get position quantity using risk-based sizing if enabled.

    Returns:
        Tuple of (quantity, stop_price). stop_price is None if using legacy sizing.
    """
    # === NEW: Risk-based sizing ===
    if self._risk_based_sizing and self._position_sizer and market_data:
        # Get equity from Redis
        equity = await self._get_account_equity()
        if equity <= 0:
            return (0.0, None)

        # Calculate stop price from ATR
        atr = market_data.atr
        if atr <= 0:
            atr = price * 0.02  # Fallback: 2% of price

        leverage = int(self.config.get("leverage", 1))

        # Size position based on risk
        result = self._position_sizer.size_position(
            equity=equity,
            entry_price=price,
            atr=atr,
            symbol=symbol,
            leverage=leverage,
            direction="long",
        )

        if result.quantity == 0:
            logger.info(
                f"{symbol}: Risk sizing rejected - {result.rejection_reason}"
            )
            return (0.0, None)

        # Calculate stop price for position tracking
        stop_price = price * (1 - result.stop_distance_pct / 100)

        logger.info(
            f"{symbol}: Risk-sized qty={result.quantity:.6f}, "
            f"risk=${result.risk_amount:.2f}, stop={result.stop_distance_pct:.1f}%"
        )

        return (result.quantity, stop_price)

    # === Legacy: Percentage-based sizing ===
    use_dynamic = self.config.get("dynamic_sizing", False)
    position_pct = float(self.config.get("position_pct", 0.02))

    if self._dynamic_position_sizing and use_dynamic and context is not None:
        rf_conf = context.rf_confidence if context.rf_confidence > 0 else 0.0
        if rf_conf >= self._position_conf_high:
            position_pct = self._position_size_high
        elif rf_conf >= self._position_conf_low:
            position_pct = self._position_size_mid
        else:
            position_pct = self._position_size_low

    if use_dynamic:
        qty = await self.get_dynamic_position_size(symbol, price, position_pct)
        return (qty, None)

    return (self.config.get("position_size", default_quantity), None)

async def _get_account_equity(self) -> float:
    """Get current account equity from Redis."""
    try:
        data = await self.redis._client.hgetall("account:live")
        return float(data.get("futures_balance", 0))
    except Exception:
        return 0.0
```

### Step 3: Add Portfolio Risk Check in `evaluate()`

In the `evaluate()` method, add portfolio risk check after entry signal:

```python
async def evaluate(self, symbol: str) -> dict[str, Any] | None:
    # ... existing code up to line 355 ...

    signal = self.entry_strategy.check_entry(ctx)

    # Emit entry evaluation event for observability
    await self._emit_entry_evaluation(market_data, context, signal)

    if signal:
        # Get quantity with risk-based sizing
        quantity, stop_price = await self._get_quantity(
            symbol, market_data.close, signal.quantity, context, market_data
        )

        if quantity == 0:
            return None

        # === NEW: Portfolio risk check ===
        if self._portfolio_risk_mgr:
            equity = await self._get_account_equity()

            # Calculate proposed risk
            if stop_price:
                stop_pct = abs(market_data.close - stop_price) / market_data.close
            else:
                stop_pct = 0.03  # Default 3%

            proposed_risk = quantity * market_data.close * stop_pct

            risk_check = await self._portfolio_risk_mgr.can_open_trade(
                symbol=symbol,
                proposed_risk=proposed_risk,
                equity=equity,
            )

            if not risk_check.allowed:
                logger.info(
                    f"{symbol}: Entry blocked by portfolio risk - {risk_check.reason}"
                )
                return None

            # If correlation filter suggests reduced risk, recalculate quantity
            if risk_check.adjusted_risk_pct:
                # Recalculate with reduced risk budget
                result = self._position_sizer.size_position_with_stop(
                    equity=equity,
                    entry_price=market_data.close,
                    stop_price=stop_price,
                    symbol=symbol,
                )
                # Apply reduction
                quantity = result.quantity * risk_check.adjusted_risk_pct / self.config.get("risk_per_trade_pct", 0.01)

        # Create order with stop_price for position tracking
        order = self._signal_to_dict(signal, quantity, leverage=leverage)

        # Include stop price for position tracking
        if stop_price:
            order["stop_price"] = stop_price

        return order

    return None
```

### Step 4: Update allocation.json

Add risk-based sizing parameters to tuned_v35_long_v2_core_overlay_v2:

```json
{
  "strategies": {
    "tuned_v35_long_v2_core_overlay_v2": {
      // ... existing config ...

      // Risk-based sizing (NEW)
      "risk_based_sizing": true,
      "risk_per_trade_pct": 0.01,
      "max_total_risk_pct": 0.05,
      "max_open_positions": 5,

      // ATR-based stops
      "atr_stop_multiplier": 3.5,
      "atr_stop_min_pct": 3.0,
      "atr_stop_max_pct": 5.0,

      // Correlation filter
      "correlation_filter": true,
      "corr_threshold": 0.75,
      "corr_lookback_bars": 240,
      "corr_action": "block"
    }
  }
}
```

### Step 5: Update Position Schema in Redis

When storing positions, include stop_price and risk_amount:

```python
# In async_executor.py _update_position():
await self.redis.set_position(order["symbol"], order["market"], {
    "quantity": str(fill["filled_qty"]),
    "entry_price": str(fill["filled_price"]),
    "strategy": order["strategy"],
    "entry_time": str(int(time.time() * 1000)),
    "side": order["side"],
    "leverage": str(leverage),
    "liquidation_price": str(liq_price),
    # NEW: Risk tracking fields
    "stop_price": str(order.get("stop_price", 0)),
    "risk_amount": str(order.get("risk_amount", 0)),
})
```

---

## Activation Sequence

1. **Merge code** with `risk_based_sizing: false` (feature flag off)
2. **Run tests**: `pytest tests/test_position_sizer.py tests/test_portfolio_risk.py`
3. **Enable on paper**: Set `risk_based_sizing: true` in allocation.json
4. **Monitor sizing decisions** in logs for 24-48 hours
5. **Backtest comparison**: Run same period with old vs new sizing
6. **Enable on live**: Start with `risk_per_trade_pct: 0.005` (0.5%)
7. **Tune**: Increase to 1% after validating MDD behavior
