"""Tests for SidewaysExitStrategy."""

from types import MappingProxyType

from trading.strategies.components.models import (
    MarketContext,
    MarketData,
    Position,
    TradingContext,
)
from trading.strategies.components.sideways_exit import (
    SidewaysExitParams,
    SidewaysExitStrategy,
)


def _make_context(close: float = 100000.0, rsi: float = 40.0) -> TradingContext:
    market = MarketData(
        symbol="BTC",
        close=close,
        mfi=45.0,
        adx=18.0,
        rsi=rsi,
        timestamp=1000,
        atr=1000.0,
        volume=90.0,
        avg_volume_20=100.0,
    )
    regime = MarketContext(
        trend="NEUTRAL",
        regime="SIDEWAYS_FLAT",
        volatility_score=0.01,
        is_extreme_volatility=False,
        adx=18.0,
    )
    return TradingContext(
        symbol="BTC",
        timestamp=1000,
        market=market,
        regime=regime,
        positions=MappingProxyType({}),
    )


def _make_position(entry_price: float = 100000.0, quantity: float = 0.01) -> Position:
    return Position(
        symbol="BTC",
        entry_price=entry_price,
        quantity=quantity,
        strategy="sideways_v2",
        market="futures",
        timestamp=1000,
        side="buy",
    )


def test_take_profit_exit():
    strategy = SidewaysExitStrategy(SidewaysExitParams(take_profit_pct=1.5))
    position = _make_position()
    ctx = _make_context(close=102000.0)  # +2.0%

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert signal.side == "sell"
    assert "Take profit" in signal.reason


def test_take_profit_exit_at_exact_threshold():
    strategy = SidewaysExitStrategy(SidewaysExitParams(take_profit_pct=1.5, stop_loss_pct=10.0))
    position = _make_position()
    ctx = _make_context(close=101500.0)  # exactly +1.5%

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert "Take profit" in signal.reason


def test_stop_loss_exit():
    strategy = SidewaysExitStrategy(SidewaysExitParams(stop_loss_pct=1.0))
    position = _make_position()
    ctx = _make_context(close=98500.0)  # -1.5%

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert signal.side == "sell"
    assert "Stop loss" in signal.reason


def test_stop_loss_exit_at_exact_threshold():
    strategy = SidewaysExitStrategy(SidewaysExitParams(stop_loss_pct=1.0, take_profit_pct=10.0))
    position = _make_position()
    ctx = _make_context(close=99000.0)  # exactly -1.0%

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert "Stop loss" in signal.reason


def test_rsi_mean_reversion_exit():
    params = SidewaysExitParams(take_profit_pct=10.0, stop_loss_pct=10.0, rsi_mean=50.0)
    strategy = SidewaysExitStrategy(params)
    position = _make_position()
    ctx = _make_context(close=100300.0, rsi=55.0)  # small pnl, RSI trigger only

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert signal.side == "sell"
    assert "mean reversion" in signal.reason


def test_rsi_mean_reversion_exit_at_exact_threshold():
    params = SidewaysExitParams(take_profit_pct=10.0, stop_loss_pct=10.0, rsi_mean=50.0)
    strategy = SidewaysExitStrategy(params)
    position = _make_position()
    ctx = _make_context(close=100200.0, rsi=50.0)

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert "mean reversion" in signal.reason


def test_take_profit_has_priority_over_rsi_exit():
    params = SidewaysExitParams(take_profit_pct=1.0, stop_loss_pct=10.0, rsi_mean=50.0)
    strategy = SidewaysExitStrategy(params)
    position = _make_position()
    ctx = _make_context(close=101200.0, rsi=60.0)  # both TP and RSI are true

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert "Take profit" in signal.reason


def test_none_when_no_exit_conditions_met():
    params = SidewaysExitParams(take_profit_pct=3.0, stop_loss_pct=3.0, rsi_mean=60.0)
    strategy = SidewaysExitStrategy(params)
    position = _make_position()
    ctx = _make_context(close=100500.0, rsi=50.0)

    assert strategy.check_exit(ctx, position) is None


def test_none_for_invalid_position_values():
    strategy = SidewaysExitStrategy()
    ctx = _make_context()

    assert strategy.check_exit(ctx, _make_position(entry_price=0.0)) is None
    assert strategy.check_exit(ctx, _make_position(quantity=0.0)) is None


def test_exit_signal_uses_fraction_quantity_convention():
    strategy = SidewaysExitStrategy(SidewaysExitParams(take_profit_pct=1.0))
    position = _make_position(quantity=0.7363)
    ctx = _make_context(close=101500.0)  # +1.5%

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert signal.quantity == 1.0
