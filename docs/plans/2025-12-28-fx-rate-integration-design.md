# FX Rate Integration Design

**Date:** 2025-12-28
**Status:** Approved
**Scope:** Integrate live USD/KRW exchange rate into Kimchi Premium calculation

## Problem

Premium calculation uses hardcoded `usd_krw_rate = 1450`, causing:
- Incorrect premium calculation during FX volatility
- Missed profitable entries or bad trade entries
- Every hedge trade starts with incorrect P&L assumptions

Example error impact:
```
Upbit 100M KRW, Binance $68,000

With fixed 1450:  Premium = 1.4% (no entry signal)
With real  1380:  Premium = 6.6% (strong entry!)
```

## Solution

Integrate existing `FXRateCache` (`trading/core/fx_cache.py`) into engine.

## Architecture

```
engine.py.__init__()
    └─ self.fx_cache = FXRateCache(default_rate=1450, refresh_interval=300)
    └─ self._start_fx_cache()  # Background refresh task

engine.py:calculate_kimchi_premium()
    └─ usd_krw_rate = self.fx_cache.rate  # Live rate with fallback
```

## Changes

### 1. Engine Initialization (`engine.py:_init_hedge_infrastructure`)

```python
from trading.core.fx_cache import FXRateCache

def _init_hedge_infrastructure(self, hedge_config: Dict[str, Any]) -> None:
    # ... existing code ...

    # FX Rate Cache
    default_fx_rate = self._allocation_config.get("premium_tracking", {}).get("usd_krw_rate", 1450)
    self.fx_cache = FXRateCache(
        default_rate=default_fx_rate,
        refresh_interval=300,
        on_rate_change=self._on_fx_rate_change,
    )
    self._start_fx_cache()
```

### 2. FX Cache Startup (new method)

```python
def _start_fx_cache(self) -> None:
    """Start FX rate cache with sync-compatible initialization."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(self.fx_cache.start())
    logger.info(f"FX cache started: USD/KRW = {self.fx_cache.rate}")

def _on_fx_rate_change(self, new_rate: float) -> None:
    """Callback when FX rate updates."""
    logger.info(f"FX rate updated: USD/KRW = {new_rate}")
```

### 3. Use Live Rate (`engine.py:calculate_kimchi_premium`)

```python
def calculate_kimchi_premium(self, prices: Dict[str, float]) -> Dict[str, Any]:
    premium_config = self._allocation_config.get("premium_tracking", {})

    # Live rate with fallback
    if hasattr(self, 'fx_cache') and self.fx_cache:
        usd_krw_rate = self.fx_cache.rate
        if self.fx_cache.is_stale():
            logger.warning(f"FX rate may be stale: {usd_krw_rate}")
    else:
        usd_krw_rate = premium_config.get("usd_krw_rate", 1450)

    # Sanity check (1100-1600 range)
    if not (1100 <= usd_krw_rate <= 1600):
        logger.error(f"FX rate out of bounds: {usd_krw_rate}, using fallback")
        usd_krw_rate = premium_config.get("usd_krw_rate", 1450)

    # ... rest unchanged ...
```

### 4. Shutdown Handling (`engine.py:stop`)

```python
async def stop(self) -> None:
    # ... existing cleanup ...
    if hasattr(self, 'fx_cache') and self.fx_cache:
        await self.fx_cache.stop()
        logger.info("FX cache stopped")
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| API timeout at startup | Use config default, retry in background |
| API returns invalid data | Keep last known rate |
| All APIs fail >10 min | Continue with stale rate + warning |
| Rate out of bounds | Use config fallback |

## Testing

1. **Unit tests:** Verify live rate usage, fallback behavior, sanity bounds
2. **Integration:** Premium calculation accuracy with live rate
3. **Manual:** Paper trading verification via logs

## Files Modified

- `trading/engine.py` - Initialize and use FXRateCache
- `tests/test_fx_integration.py` - New test file

## Rollback

Remove FXRateCache initialization; `calculate_kimchi_premium` will use config default automatically.
