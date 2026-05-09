"""Tests for CompositeStrategyTask exit quantity resolution."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from trading.strategies.components.composite_task import CompositeStrategyTask
from trading.strategies.components.models import MarketContext, MarketData, Position, Signal
from trading.utils.precision import SymbolInfo


def _make_task(market: str = "spot", config: dict | None = None) -> CompositeStrategyTask:
    redis = MagicMock()
    redis.publish_event = AsyncMock(return_value="1-0")
    redis.get_position = AsyncMock(return_value={})
    redis._client = MagicMock()
    redis._client.hgetall = AsyncMock(return_value={})

    entry = MagicMock()
    entry.check_entry = MagicMock(return_value=None)
    entry.params = MagicMock()
    entry.params.mfi_bull = 52.0
    entry.params.mfi_bear = 48.0
    entry.params.adx_trend = 20.0

    exit_strategy = MagicMock()
    exit_strategy.check_exit = MagicMock(return_value=None)
    exit_strategy.on_position_opened = MagicMock()
    exit_strategy.on_position_closed = MagicMock()
    exit_strategy.params = MagicMock()
    exit_strategy.params.stop_loss_pct = 2.0
    exit_strategy.params.take_profit_pct = 5.0

    return CompositeStrategyTask(
        name="llm_direction_btc",
        symbols=["BCH"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strategy,
        market=market,
        config=config,
    )


def test_resolve_exit_quantity_full_fraction_uses_position_size():
    task = _make_task(market="spot")
    position = Position(
        symbol="BTC",
        entry_price=577.68,
        quantity=0.7363438363899231,
        strategy="llm_direction_btc",
        market="spot",
        timestamp=1,
    )
    signal = Signal(
        symbol="BTC",
        side="sell",
        market="spot",
        quantity=1.0,
        reason="stop",
    )

    resolved = task._resolve_exit_order_quantity(position=position, signal=signal)
    assert resolved == pytest.approx(position.quantity, rel=1e-12)

    order = task._signal_to_dict(signal, resolved)
    # Spot order should be rounded by exchange step size (BTC step 0.00001).
    assert float(order["quantity"]) == pytest.approx(0.73634, rel=1e-12)


def test_resolve_exit_quantity_partial_fraction_scales_position():
    task = _make_task(market="spot")
    position = Position(
        symbol="BTC",
        entry_price=100000.0,
        quantity=4.0,
        strategy="llm_direction",
        market="spot",
        timestamp=1,
    )
    signal = Signal(
        symbol="BTC",
        side="sell",
        market="spot",
        quantity=0.5,
        reason="tp1",
    )

    resolved = task._resolve_exit_order_quantity(position=position, signal=signal)
    assert resolved == pytest.approx(2.0, rel=1e-12)


def test_resolve_exit_quantity_clamps_oversized_absolute_signal():
    task = _make_task(market="spot")
    position = Position(
        symbol="BTC",
        entry_price=100000.0,
        quantity=0.7363,
        strategy="llm_direction",
        market="spot",
        timestamp=1,
    )
    signal = Signal(
        symbol="BTC",
        side="sell",
        market="spot",
        quantity=2.0,
        reason="stop",
    )

    resolved = task._resolve_exit_order_quantity(position=position, signal=signal)
    assert resolved == pytest.approx(position.quantity, rel=1e-12)


def test_spot_adjusted_qty_respects_min_trade_unit(monkeypatch):
    task = _make_task(market="spot")

    def _mock_symbol_info(_symbol: str) -> SymbolInfo:
        return SymbolInfo(
            symbol="BCHUSDT",
            price_precision=2,
            qty_precision=3,
            min_qty="0.001",
            step_size="0.001",
            tick_size="0.01",
            min_notional="10",
        )

    monkeypatch.setattr(
        "trading.strategies.components.composite_task.get_symbol_info",
        _mock_symbol_info,
    )

    assert task._spot_adjusted_qty("BCH", 0.0013) == pytest.approx(0.001, rel=1e-12)
    assert task._spot_adjusted_qty("BCH", 0.0009) == 0.0


def test_bear_moderate_exit_uses_single_partial_de_risk():
    task = _make_task(
        config={
            "exit_on_bear_regime": True,
            "protective_partial_exit_enabled": True,
            "protective_partial_exit_fraction": 0.5,
            "protective_partial_regimes": ["BEAR_MODERATE"],
        }
    )
    position = Position(
        symbol="BTC",
        entry_price=100000.0,
        quantity=0.2,
        strategy="llm_direction_btc",
        market="spot",
        timestamp=1,
    )
    context = MarketContext(
        trend="BEAR",
        regime="BEAR_MODERATE",
        volatility_score=0.01,
        is_extreme_volatility=False,
        adx=20.0,
    )

    first = task._check_bear_regime_exit("BTC", position, context)
    second = task._check_bear_regime_exit("BTC", position, context)

    assert first is not None
    assert float(first["quantity"]) == pytest.approx(0.1, rel=1e-12)
    assert "PROTECTIVE_PARTIAL_DE_RISK" in first["reason"]
    assert second is None


def test_bear_strong_exit_remains_full_exit_after_partial_de_risk():
    task = _make_task(
        config={
            "exit_on_bear_regime": True,
            "protective_partial_exit_enabled": True,
            "protective_partial_exit_fraction": 0.5,
            "protective_partial_regimes": ["BEAR_MODERATE"],
        }
    )
    position = Position(
        symbol="BTC",
        entry_price=100000.0,
        quantity=0.2,
        strategy="llm_direction_btc",
        market="spot",
        timestamp=1,
    )
    context = MarketContext(
        trend="BEAR",
        regime="BEAR_STRONG",
        volatility_score=0.01,
        is_extreme_volatility=False,
        adx=30.0,
    )

    order = task._check_bear_regime_exit("BTC", position, context)

    assert order is not None
    assert float(order["quantity"]) == pytest.approx(0.2, rel=1e-12)
    assert order["reason"] == "bear_regime_exit:BEAR_STRONG"


def test_trend_hold_guard_suppresses_live_bear_moderate_exit_above_ema200():
    task = _make_task(
        config={
            "exit_on_bear_regime": True,
            "trend_hold_exit_guard_enabled": True,
            "trend_hold_guard_require_above_ema200": True,
        }
    )
    position = Position(
        symbol="BTC",
        entry_price=100000.0,
        quantity=0.2,
        strategy="llm_direction_btc",
        market="spot",
        timestamp=1,
    )
    context = MarketContext(
        trend="BEAR",
        regime="BEAR_MODERATE",
        volatility_score=0.01,
        is_extreme_volatility=False,
        adx=20.0,
    )
    market_data = MarketData(
        symbol="BTC",
        close=105000.0,
        timestamp=1,
        mfi=35.0,
        adx=20.0,
        rsi=45.0,
        ema_200=100000.0,
    )

    order = task._check_bear_regime_exit("BTC", position, context, market_data)

    assert order is None


def test_trend_hold_guard_does_not_suppress_live_bear_strong_exit():
    task = _make_task(
        config={
            "exit_on_bear_regime": True,
            "trend_hold_exit_guard_enabled": True,
            "trend_hold_guard_require_above_ema200": True,
        }
    )
    position = Position(
        symbol="BTC",
        entry_price=100000.0,
        quantity=0.2,
        strategy="llm_direction_btc",
        market="spot",
        timestamp=1,
    )
    context = MarketContext(
        trend="BEAR",
        regime="BEAR_STRONG",
        volatility_score=0.01,
        is_extreme_volatility=False,
        adx=30.0,
    )
    market_data = MarketData(
        symbol="BTC",
        close=105000.0,
        timestamp=1,
        mfi=30.0,
        adx=30.0,
        rsi=40.0,
        ema_200=100000.0,
    )

    order = task._check_bear_regime_exit("BTC", position, context, market_data)

    assert order is not None
    assert float(order["quantity"]) == pytest.approx(0.2, rel=1e-12)
