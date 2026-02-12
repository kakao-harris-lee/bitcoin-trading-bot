from __future__ import annotations

from unittest.mock import MagicMock

from trading.regime.runtime import RuntimeRegimePrediction
from trading.strategies.components.models import MarketContext, MarketData


class _DummyOverlay:
    def __init__(self, prediction: RuntimeRegimePrediction | None, *, apply_v2_filters: bool):
        self._prediction = prediction
        self.apply_v2_filters = apply_v2_filters

    def is_enabled_for(self, symbol: str) -> bool:
        return True

    def predict(self, *, symbol: str, market_data, history_df):
        return self._prediction


def _make_task(config: dict | None = None):
    from trading.strategies.components.composite_task import CompositeStrategyTask

    redis = MagicMock()
    redis.publish_event = MagicMock()
    redis._client = MagicMock()

    entry = MagicMock()
    entry.params = MagicMock()
    entry.params.mfi_bull = 52.0
    entry.params.mfi_bear = 48.0
    entry.params.adx_trend = 20.0

    exit_strat = MagicMock()
    exit_strat.params = MagicMock()

    return CompositeStrategyTask(
        name="test_runtime_overlay",
        symbols=["BTC"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
        market="spot",
        config=config or {},
    )


def _market_data() -> MarketData:
    return MarketData(
        symbol="BTC",
        close=45000.0,
        mfi=55.0,
        adx=30.0,
        rsi=50.0,
        timestamp=1700000000000,
        atr=900.0,
        volume=1000.0,
        avg_volume_20=950.0,
        high_30d=52000.0,
        prev_high_20=51000.0,
        bb_upper=46000.0,
        bb_lower=44000.0,
        bb_middle=45000.0,
    )


def test_build_market_context_uses_runtime_overlay_without_v2() -> None:
    task = _make_task({"regime_runtime_overlay": {"enabled": True}})

    prediction = RuntimeRegimePrediction(
        symbol="BTC",
        model="rf_calibrated",
        regime_3="BEAR",
        regime_7="BEAR_STRONG",
        confidence=0.77,
        rf_confidence=0.72,
        rf_signal="SELL",
    )
    task._runtime_regime_overlay = _DummyOverlay(prediction, apply_v2_filters=False)

    ctx = task._build_market_context(_market_data())

    assert ctx.regime == "BEAR_STRONG"
    assert ctx.trend == "BEAR"
    assert ctx.rf_confidence == 0.72
    assert ctx.rf_direction == "BEAR"
    assert ctx.rf_signal == "SELL"


def test_build_market_context_applies_v2_after_runtime_overlay_when_enabled() -> None:
    task = _make_task({"regime_runtime_overlay": {"enabled": True}})

    prediction = RuntimeRegimePrediction(
        symbol="BTC",
        model="rf_calibrated",
        regime_3="BULL",
        regime_7="BULL_MODERATE",
        confidence=0.61,
        rf_confidence=0.61,
        rf_signal="BUY",
    )
    task._runtime_regime_overlay = _DummyOverlay(prediction, apply_v2_filters=True)

    v2_ctx = MarketContext(
        trend="BULL",
        regime="BULL_STRONG",
        volatility_score=0.01,
        is_extreme_volatility=False,
        adx=30.0,
    )
    task._apply_v2_regime_context = MagicMock(return_value=v2_ctx)

    ctx = task._build_market_context(_market_data())

    assert ctx.regime == "BULL_STRONG"
    task._apply_v2_regime_context.assert_called_once()
