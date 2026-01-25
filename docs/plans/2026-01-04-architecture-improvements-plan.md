# Architecture Improvements Plan

**Date:** 2026-01-04
**Based on:** Architecture Review (docs/architecture-review.md)
**Status:** Pending Approval

---

## Overview

This plan addresses improvements identified in the architecture review, organized by the review criteria used for evaluation.

---

## Improvement Areas by Review Criteria

### Criteria 1: Error Handling (Current: B → Target: A)

#### Problem
Current error handling uses "log and continue" pattern without recovery mechanisms.

```python
# Current pattern throughout codebase
except Exception as e:
    logger.error(f"Failed: {e}")
```

#### Improvements

| ID | Improvement | Priority | Effort |
|----|-------------|----------|--------|
| E1 | Circuit breaker for Upbit adapter | High | 2h |
| E2 | Circuit breaker for Binance adapter | High | 2h |
| E3 | Retry with exponential backoff | Medium | 1h |
| E4 | Error classification (transient vs fatal) | Medium | 2h |

#### E1/E2: Circuit Breaker Implementation

**Files to create:**
- `trading/core/circuit_breaker.py`

**Files to modify:**
- `trading/adapters/upbit.py`
- `trading/adapters/binance.py`

**Design:**
```
States: CLOSED → OPEN → HALF_OPEN → CLOSED
        (normal)  (blocked)  (testing)  (recovered)

Triggers:
- 3 consecutive failures → OPEN
- 60 seconds in OPEN → HALF_OPEN
- 1 success in HALF_OPEN → CLOSED
- 1 failure in HALF_OPEN → OPEN
```

**Interface:**
```python
class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_timeout_sec: int = 60,
        half_open_max_calls: int = 1,
    ): ...

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""

    def is_open(self) -> bool: ...
    def get_state(self) -> str: ...
    def get_stats(self) -> Dict: ...
```

#### E3: Retry with Exponential Backoff

**Files to modify:**
- `trading/adapters/upbit.py` - `buy()`, `sell()` methods
- `trading/adapters/binance.py` - `open_short()`, `close_short()` methods

**Design:**
```python
@retry(max_attempts=3, base_delay=1.0, max_delay=10.0)
def buy(self, amount: float, price: float) -> Dict:
    ...
```

#### E4: Error Classification

**Files to create:**
- `trading/core/errors.py`

**Error types:**
```python
class TradingError(Exception):
    """Base trading error."""
    retryable: bool = False

class TransientError(TradingError):
    """Network timeout, rate limit - can retry."""
    retryable = True

class FatalError(TradingError):
    """Insufficient balance, invalid order - cannot retry."""
    retryable = False

class ExchangeDownError(TradingError):
    """Exchange maintenance - trigger circuit breaker."""
    retryable = False
```

---

### Criteria 2: State Persistence (Current: C → Target: A)

#### Problem
Position state exists only in memory. Restart loses awareness of open positions.

#### Improvements

| ID | Improvement | Priority | Effort |
|----|-------------|----------|--------|
| S1 | Alpha position state persistence | High | 3h |
| S2 | Hedge position state persistence (removed with Kimchi arbitrage) | - | - |
| S3 | State recovery on startup | High | 2h |
| S4 | State file integrity checks | Medium | 1h |

#### S1/S2: State Persistence

**Files to modify:**
- `trading/execution/multi_asset_alpha_manager.py`

**State file locations:**
```
logs/
├── alpha_state.json      # Upbit long positions
```

**Alpha state format:**
```json
{
  "version": 1,
  "saved_at": "2026-01-04T12:00:00Z",
  "states": {
    "BTC": {
      "active": true,
      "quantity": 0.5,
      "entry_price": 50000000,
      "strategy": "v35",
      "regime": "BULL"
    }
  }
}
```

**Persistence triggers:**
- After every trade execution (buy/sell)
- Every 5 minutes (heartbeat)
- On graceful shutdown

#### S3: State Recovery on Startup

**Startup flow:**
```
1. Load state file
2. Validate against exchange positions (if live mode)
3. Reconcile differences
4. Log any discrepancies
5. Resume trading loop
```

**Reconciliation logic:**
```python
def reconcile_state(self, saved: Dict, live: Dict) -> Dict:
    """
    Reconcile saved state with live exchange positions.

    Priority: Live exchange data > Saved state
    """
    for symbol in saved:
        if symbol not in live:
            logger.warning(f"{symbol}: saved position not found on exchange")
        elif abs(saved[symbol].qty - live[symbol].qty) > 0.0001:
            logger.warning(f"{symbol}: quantity mismatch, using exchange value")
    return live
```

---

### Criteria 3: Graceful Degradation (Current: C → Target: B+)

#### Problem
Single asset failure can impact evaluation of other assets.

#### Improvements

| ID | Improvement | Priority | Effort |
|----|-------------|----------|--------|
| G1 | Per-asset error isolation | Medium | 2h |
| G2 | Temporary asset disable mechanism | Medium | 2h |
| G3 | Auto-recovery attempts | Low | 2h |

#### G1/G2: Per-Asset Isolation

**Files to modify:**
- `trading/execution/multi_asset_alpha_manager.py`
- `trading/multi_asset_engine.py`

**Design:**
```python
@dataclass
class AssetHealth:
    symbol: str
    enabled: bool = True
    consecutive_failures: int = 0
    disabled_at: Optional[datetime] = None
    disable_reason: Optional[str] = None

    MAX_FAILURES = 5
    DISABLE_DURATION_SEC = 300  # 5 minutes

class AssetHealthTracker:
    def record_success(self, symbol: str): ...
    def record_failure(self, symbol: str, error: Exception): ...
    def is_healthy(self, symbol: str) -> bool: ...
    def check_recovery(self, symbol: str) -> bool: ...
```

**Evaluation flow:**
```python
async def evaluate_all(self):
    for symbol in self._symbols:
        if not self._health.is_healthy(symbol):
            if self._health.check_recovery(symbol):
                logger.info(f"{symbol}: attempting recovery")
            else:
                continue  # Skip unhealthy asset

        try:
            signal = await self._evaluate_asset(symbol)
            self._health.record_success(symbol)
        except Exception as e:
            self._health.record_failure(symbol, e)
```

---

### Criteria 4: Configuration Validation (Current: B+ → Target: A)

#### Problem
Configuration errors discovered only at runtime.

#### Improvements

| ID | Improvement | Priority | Effort |
|----|-------------|----------|--------|
| C1 | Startup config validation | Medium | 2h |
| C2 | Strategy config validation | Medium | 1h |
| C3 | Connection tests on startup | Medium | 1h |

#### C1: Startup Validation

**Files to create:**
- `trading/core/config_validator.py`

**Validation checks:**
```python
class ConfigValidator:
    def validate_allocation(self, config: Dict) -> List[str]:
        errors = []

        # Required fields
        if "assets" not in config:
            errors.append("Missing 'assets' section")

        for symbol, cfg in config.get("assets", {}).items():
            if cfg.get("enabled"):
                # Check required fields for enabled assets
                if not cfg.get("upbit_symbol"):
                    errors.append(f"{symbol}: missing upbit_symbol")
                if not cfg.get("db_path"):
                    errors.append(f"{symbol}: missing db_path")
                if not Path(cfg.get("db_path", "")).exists():
                    errors.append(f"{symbol}: db_path does not exist")

        return errors

    def validate_strategy_config(self, symbol: str, strategy: str) -> List[str]:
        errors = []
        config_path = Path(f"config/strategies/{strategy}.json")
        if not config_path.exists():
            errors.append(f"{symbol}: strategy config not found: {config_path}")
        return errors
```

#### C3: Connection Tests

**Startup sequence:**
```python
async def startup_checks(self):
    checks = [
        ("Upbit API", self._test_upbit_connection),
        ("Binance API", self._test_binance_connection),
        ("Redis", self._test_redis_connection),
        ("Telegram", self._test_telegram_connection),
    ]

    for name, check in checks:
        try:
            await check()
            logger.info(f"✓ {name} connected")
        except Exception as e:
            logger.error(f"✗ {name} failed: {e}")
            if name in ["Upbit API", "Binance API"]:
                raise StartupError(f"Critical: {name} connection failed")
```

---

### Criteria 5: Observability (Current: B → Target: A)

#### Problem
Limited visibility into system behavior in production.

#### Improvements

| ID | Improvement | Priority | Effort |
|----|-------------|----------|--------|
| O1 | Structured metrics collection | Low | 3h |
| O2 | Health endpoint for monitoring | Low | 2h |
| O3 | Trading activity dashboard data | Low | 2h |

#### O1: Metrics Collection

**Files to create:**
- `trading/core/metrics.py`

**Metrics to track:**
```python
@dataclass
class TradingMetrics:
    # Counters
    signals_generated: Dict[str, int]     # by strategy
    trades_executed: Dict[str, int]       # by symbol
    errors_by_type: Dict[str, int]

    # Gauges
    current_exposure_krw: float
    current_hedge_usd: float
    premium_pct: Dict[str, float]         # by symbol

    # Histograms
    execution_latency_ms: List[float]
    signal_to_trade_latency_ms: List[float]

    def to_dict(self) -> Dict: ...
    def reset_counters(self): ...
```

#### O2: Health Endpoint

**Files to modify:**
- `web/app.py`

**Endpoint:**
```python
@app.route("/health")
def health():
    return {
        "status": "healthy",
        "uptime_seconds": engine.uptime_seconds(),
        "components": {
            "upbit": engine.upbit_circuit_breaker.get_state(),
            "binance": engine.binance_circuit_breaker.get_state(),
            "data_cache": "ok" if engine.data_cache.is_healthy() else "degraded",
        },
        "assets": {
            symbol: health.is_healthy(symbol)
            for symbol in engine.symbols
        },
        "last_evaluation": engine.last_evaluation_time,
    }
```

---

## Implementation Phases

### Phase 1: Critical Safety (Week 1)

| Task | Effort | Dependencies |
|------|--------|--------------|
| E1: Upbit circuit breaker | 2h | None |
| E2: Binance circuit breaker | 2h | E1 (shared code) |
| S1: Alpha state persistence | 3h | None |
| S2: Hedge state persistence | 2h | S1 (shared pattern) |
| S3: State recovery | 2h | S1, S2 |

**Total:** ~11 hours

**Deliverables:**
- Circuit breakers protecting exchange calls
- Position state survives restarts
- State reconciliation on startup

### Phase 2: Resilience (Week 2)

| Task | Effort | Dependencies |
|------|--------|--------------|
| G1: Per-asset error isolation | 2h | None |
| G2: Temporary disable mechanism | 2h | G1 |
| E3: Retry with backoff | 1h | E1, E2 |
| E4: Error classification | 2h | None |
| C1: Config validation | 2h | None |

**Total:** ~9 hours

**Deliverables:**
- Single asset failure doesn't stop system
- Smarter retry logic
- Startup validation catches misconfigs

### Phase 3: Observability (Week 3)

| Task | Effort | Dependencies |
|------|--------|--------------|
| O1: Metrics collection | 3h | None |
| O2: Health endpoint | 2h | O1 |
| C2: Strategy config validation | 1h | C1 |
| C3: Connection tests | 1h | None |

**Total:** ~7 hours

**Deliverables:**
- Metrics for monitoring
- Health check endpoint
- Complete startup validation

---

## Success Criteria

### Phase 1 Complete When:
- [ ] Exchange failures trigger circuit breaker (verified in logs)
- [ ] `logs/alpha_state.json` created after trade
- [ ] Restart correctly loads previous positions
- [ ] State reconciliation logs any discrepancies

### Phase 2 Complete When:
- [ ] One asset failure doesn't stop other assets (test by blocking one DB)
- [ ] Disabled asset auto-recovers after timeout
- [ ] Transient errors retry with backoff
- [ ] Invalid config detected at startup (not runtime)

### Phase 3 Complete When:
- [ ] `/health` endpoint returns component status
- [ ] Metrics available for dashboard
- [ ] All startup checks pass before trading loop

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| State file corruption | S4: Integrity checks, backup before write |
| Circuit breaker too aggressive | Tune thresholds in paper mode first |
| Recovery logic bugs | Extensive testing with mock exchanges |
| Performance impact of persistence | Async writes, batched updates |

---

## Approval Checklist

- [ ] Plan reviewed by operator
- [ ] Priority order agreed
- [ ] Phase 1 scope confirmed
- [ ] Testing approach approved

**Awaiting approval to proceed with implementation.**
