from unittest.mock import AsyncMock, MagicMock

import pytest

from trading.strategies.components.composite_task import CompositeStrategyTask
from trading.strategies.components.models import MarketData, Signal


class RejectingEntry:
    def __init__(self, reason: str):
        self.reason = reason
        self.params = MagicMock()
        self.params.mfi_bull = 52.0
        self.params.mfi_bear = 48.0
        self.params.adx_trend = 20.0

    def check_entry(self, ctx):
        _ = ctx
        return None

    def get_last_rejection_reason(self, symbol: str):
        _ = symbol
        return self.reason


class AcceptingFallbackEntry:
    def __init__(self):
        self.params = MagicMock()

    def check_entry(self, ctx):
        return Signal(
            symbol=ctx.symbol,
            side="buy",
            market="spot",
            quantity=0.25,
            reason="RegimeLongV2 entry: regime=BULL_STRONG, risk_on_hits=1/1 (need>=1), score=5",
        )

    def get_last_rejection_reason(self, symbol: str):
        _ = symbol
        return None


@pytest.mark.asyncio
async def test_provider_error_uses_fallback_signal():
    redis = MagicMock()
    redis.publish = AsyncMock(return_value=1)
    redis.publish_event = AsyncMock(return_value="1-0")
    redis.get_position = AsyncMock(return_value={})
    redis._client = MagicMock()
    redis._client.hgetall = AsyncMock(return_value={"mode": "paper"})
    redis._client.xadd = AsyncMock(return_value="1-0")

    task = CompositeStrategyTask(
        name="llm_direction_btc",
        symbols=["BTC"],
        redis=redis,
        entry_strategy=RejectingEntry(
            "LLM predicted HOLD (conf=0.00): LLM provider error: Ollama decision request failed",
        ),
        exit_strategy=MagicMock(),
        config={
            "market": "spot",
            "timeframe": "minute240",
            "entry_fallback": {
                "enabled": True,
                "class": "RegimeLongV2EntryStrategy",
                "on_provider_error": True,
                "params": {
                    "market": "spot",
                    "position_size": 0.25,
                    "entry_lookback_bars": 1,
                    "entry_quorum_ratio": 1.0,
                    "min_ready_bars": 1,
                    "risk_on_score_min": 4,
                    "adx_trend_threshold": 10.0,
                    "require_close_above_ema20": True,
                    "require_close_above_ema120": False,
                    "require_ema20_above_ema120": True,
                    "require_rsi_above_50": True,
                    "require_mfi_above_50": True,
                    "require_adx_trend": True,
                },
            },
            "use_signal_quantity": True,
        },
    )
    task._fallback_entry_strategy = AcceptingFallbackEntry()
    task.price_buffer["BTC"] = [{"price": "80000", "timestamp": 1234567890}]
    task.history["BTC"] = [
        {"open": 79000, "high": 80500, "low": 78800, "close": 80000, "volume": 1000}
        for _ in range(200)
    ]
    task._build_market_data = MagicMock(
        return_value=MarketData(
            symbol="BTC",
            close=80000.0,
            open=79800.0,
            high=80500.0,
            low=79700.0,
            volume=1200.0,
            avg_volume_20=1000.0,
            mfi=68.0,
            adx=28.0,
            rsi=61.0,
            atr=900.0,
            ema_20=79500.0,
            ema_120=78000.0,
            ema_200=77000.0,
            prev_high_20=80200.0,
            timestamp=1234567890,
        )
    )
    task._build_entry_order = AsyncMock(
        return_value={
            "symbol": "BTC",
            "side": "buy",
            "market": "spot",
            "quantity": "0.25",
            "reason": "HybridLong[regime_fallback] primary=provider error; RegimeLongV2 entry",
        }
    )

    order = await task.evaluate("BTC")

    assert order is not None
    assert order["symbol"] == "BTC"
    assert order["side"] == "buy"
    assert "HybridLong[regime_fallback]" in order["reason"]


def test_non_buy_fallback_respects_confidence_ceiling():
    task = CompositeStrategyTask(
        name="llm_direction_btc",
        symbols=["BTC"],
        redis=MagicMock(),
        entry_strategy=MagicMock(),
        exit_strategy=MagicMock(),
        config={
            "entry_fallback": {
                "enabled": True,
                "on_non_buy": True,
                "max_hold_confidence": 0.55,
            }
        },
    )

    assert (
        task._should_apply_entry_fallback(
            "LLM predicted HOLD (conf=0.50): mixed signals"
        )
        is True
    )
    assert (
        task._should_apply_entry_fallback(
            "LLM predicted HOLD (conf=0.70): mixed signals"
        )
        is False
    )
