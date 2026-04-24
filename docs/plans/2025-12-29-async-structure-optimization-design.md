# Async Structure Optimization Design

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


**Date**: 2025-12-29
**Status**: Approved
**Author**: Claude Code

## Problem Statement

Order status polling in exchange adapters uses fixed `time.sleep(1)` intervals, causing inefficient thread usage. While this runs in a thread pool and doesn't block the event loop, it wastes resources and delays order confirmation for quick fills.

### Current Behavior

```python
# trading/adapters/upbit.py:110, binance.py:186,259
for i in range(30):
    time.sleep(1)  # Fixed 1s delay
    order_status = self.upbit.get_order(uuid)
    if order_status['state'] == 'done':
        break
```

- Fixed 1-second delay between checks
- Maximum 30 seconds per order
- Quick fills still wait 1 second minimum

## Solution: Exponential Backoff

Replace fixed polling with exponential backoff:
- Start at 0.1s, double each time
- Cap at 2s per check
- Maximum 30s total wait time

### Implementation

```python
def _wait_for_order_fill(self, uuid: str, max_wait: float = 30.0) -> dict:
    """Wait for order fill with exponential backoff."""
    delay = 0.1  # Start at 100ms
    elapsed = 0.0

    while elapsed < max_wait:
        order_status = self.upbit.get_order(uuid)
        if order_status['state'] == 'done':
            return order_status

        time.sleep(delay)
        elapsed += delay
        delay = min(delay * 2, 2.0)  # Double, cap at 2s

    # Timeout - return last status with warning
    logger.warning(f"Order {uuid} not filled after {max_wait}s, state: {order_status['state']}")
    return order_status
```

### Timing Comparison

| Scenario | Old (fixed 1s) | New (exponential) |
|----------|---------------|-------------------|
| Instant fill | 1s | 0.1s |
| Fill at 2s | 2s | 0.3s (0.1+0.2) |
| Fill at 5s | 5s | 1.5s (0.1+0.2+0.4+0.8) |
| Fill at 15s | 15s | ~10s |
| Timeout (30s) | 30s | 30s |

## Files to Modify

| File | Method | Change |
|------|--------|--------|
| `trading/adapters/upbit.py` | `buy_market_order()` | Replace fixed loop with `_wait_for_order_fill()` |
| `trading/adapters/binance.py` | `open_short()` | Replace fixed loop with `_wait_for_order_fill()` |
| `trading/adapters/binance.py` | `close_short()` | Replace fixed loop with `_wait_for_order_fill()` |

## Error Handling

- If max_wait exceeded, return last order status (may be 'pending')
- Log warning when order doesn't fill within expected time
- Caller (AsyncExecutor) handles partial/unfilled orders appropriately

## Testing Strategy

### Unit Tests

1. `test_exponential_backoff_quick_fill` - Order fills on first check
2. `test_exponential_backoff_slow_fill` - Order fills after several checks
3. `test_exponential_backoff_timeout` - Order never fills, returns after 30s

### Mock Pattern

```python
mock_upbit.get_order.side_effect = [
    {'state': 'wait'},   # Check 1: 0.1s
    {'state': 'wait'},   # Check 2: 0.2s
    {'state': 'done'},   # Check 3: fills
]
# Total time: ~0.3s instead of 3s with fixed polling
```

## Future Work: Engine Migration

After polling optimization, migrate DualPaperTradingEngine features to AsyncTradingEngine:

### Features to Migrate
- Hedge infrastructure (PremiumController, HedgeManager, DeltaRebalancer)
- AlphaManager with DataCache integration
- FXRateCache integration for live premium calculation

### Not Migrating
- Legacy position tracking (async engine has its own)
- Sync API calls (already replaced with WebSocket)

This will be implemented as a separate PR.

## Benefits

1. **Faster order confirmation**: Quick fills detected in <0.2s instead of 1s
2. **Efficient resource usage**: Less time spent in thread pool workers
3. **Same reliability**: 30s max wait maintained for slow fills
4. **Better logging**: Warnings when orders timeout
