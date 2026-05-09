from unittest.mock import MagicMock

from trading.strategies.components.composite_task import CompositeStrategyTask
from trading.strategies.components.models import (
    MarketContext,
    MarketData,
    Position,
    TradingContext,
)


def _make_task(**extra_config):
    config = {"allow_scale_in_entries": True, **extra_config}
    return CompositeStrategyTask(
        name="llm_direction_btc",
        symbols=["BTC"],
        redis=MagicMock(),
        entry_strategy=MagicMock(),
        exit_strategy=MagicMock(),
        config=config,
    )


def test_context_position_cap_allows_scale_in_for_same_strategy():
    task = _make_task(context_max_symbol_positions=1)
    existing = [
        Position(
            symbol="BTC",
            entry_price=100000.0,
            quantity=0.01,
            strategy="llm_direction_btc",
            market="spot",
            timestamp=1,
        )
    ]

    allowed, reason = task._passes_context_position_count_caps(
        symbol="BTC",
        open_symbols=["BTC"],
        symbol_positions=existing,
    )

    assert allowed is True
    assert reason == "OK_SCALE_IN"


def test_build_decision_snapshot_reports_buy_when_scale_in_hint_exists():
    task = _make_task()
    task._update_entry_decision_hint(
        "BTC",
        should_enter=True,
        reason="Scale-in signal: BULL_STRONG momentum follow-through",
    )
    market_data = MarketData(
        symbol="BTC",
        close=101000.0,
        open=100500.0,
        high=101500.0,
        low=100000.0,
        volume=1000.0,
        avg_volume_20=900.0,
        mfi=65.0,
        adx=28.0,
        rsi=60.0,
        atr=1200.0,
        ema_20=100200.0,
        ema_120=98000.0,
        ema_200=96000.0,
        prev_high_20=101200.0,
        timestamp=1,
    )
    position = {"quantity": "0.01", "entry_price": "99000"}

    decision, reason, position_data = task._build_decision_snapshot(
        market_data=market_data,
        regime="BULL_STRONG",
        position=position,
        mfi_bull=52.0,
        mfi_bear=48.0,
        adx_trend=20.0,
    )

    assert decision == "BUY"
    assert "Scale-in signal" in reason
    assert position_data["active"] is True


def test_trend_floor_signal_generates_buy_in_bullish_context():
    task = _make_task(
        trend_floor_entry_enabled=True,
        trend_floor_position_size=0.08,
        trend_floor_min_adx=12.0,
        trend_floor_min_mfi=45.0,
    )
    ctx = TradingContext(
        symbol="BTC",
        timestamp=1,
        market=MarketData(
            symbol="BTC",
            close=105.0,
            mfi=55.0,
            adx=20.0,
            rsi=55.0,
            timestamp=1,
            ema_20=100.0,
            ema_120=95.0,
        ),
        regime=MarketContext(
            trend="BULL",
            regime="SIDEWAYS_UP",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=20.0,
        ),
        positions={},
    )

    signal = task._maybe_build_trend_floor_signal("BTC", ctx, "LLM predicted HOLD")

    assert signal is not None
    assert signal.side == "buy"
    assert signal.quantity == 0.08
    assert signal.reason.startswith("TrendFloor entry")


def test_trend_floor_signal_blocks_when_required_ema_is_not_ready():
    task = _make_task(
        trend_floor_entry_enabled=True,
        trend_floor_position_size=0.08,
        trend_floor_min_adx=12.0,
        trend_floor_min_mfi=45.0,
        trend_floor_require_ema120_ready=True,
    )
    ctx = TradingContext(
        symbol="BTC",
        timestamp=1,
        market=MarketData(
            symbol="BTC",
            close=105.0,
            mfi=55.0,
            adx=20.0,
            rsi=55.0,
            timestamp=1,
            ema_20=100.0,
            ema_120=float("nan"),
        ),
        regime=MarketContext(
            trend="BULL",
            regime="SIDEWAYS_UP",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=20.0,
        ),
        positions={},
    )

    signal = task._maybe_build_trend_floor_signal("BTC", ctx, "LLM predicted HOLD")

    assert signal is None
