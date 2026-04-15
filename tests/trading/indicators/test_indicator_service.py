from __future__ import annotations

import time
from collections import deque

from trading.indicators.indicator_service import IndicatorService
from trading.strategies.components.models import MarketData


def test_indicator_service_cache_hit_uses_latest_price_timestamp() -> None:
    service = IndicatorService(cache_ttl=60.0)
    cached = MarketData(
        symbol="BTC",
        open=100.0,
        close=100.0,
        high=101.0,
        low=99.0,
        mfi=55.0,
        adx=25.0,
        rsi=50.0,
        timestamp=1_000,
    )
    service._cache["BTC"] = (time.time(), cached)
    service._price_buffers["BTC"] = deque(
        [{"price": 101.0, "timestamp": 2_000}],
        maxlen=100,
    )

    updated = service.get_market_data("BTC", current_price=101.0)

    assert updated is not None
    assert updated.timestamp == 2_000
    assert updated.close == 101.0
