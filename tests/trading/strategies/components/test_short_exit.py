"""Tests for ShortExitStrategy."""

from types import MappingProxyType

from trading.strategies.components.models import (
    MarketContext,
    MarketData,
    Position,
    Regime,
    TradingContext,
)
from trading.strategies.components.short_exit import (
    ShortExitParams,
    ShortExitStrategy,
)


def _make_context(
    close: float = 100000.0,
    rsi: float = 50.0,
    regime: Regime = "SIDEWAYS_FLAT",
) -> TradingContext:
    market = MarketData(
        symbol="BTC",
        close=close,
        mfi=45.0,
        adx=20.0,
        rsi=rsi,
        timestamp=1000,
        atr=1200.0,
        volume=100.0,
        avg_volume_20=90.0,
    )
    market_context = MarketContext(
        trend="NEUTRAL",
        regime=regime,
        volatility_score=0.01,
        is_extreme_volatility=False,
        adx=20.0,
    )
    return TradingContext(
        symbol="BTC",
        timestamp=1000,
        market=market,
        regime=market_context,
        positions=MappingProxyType({}),
    )


def _make_position(entry_price: float = 100000.0, quantity: float = 0.01) -> Position:
    return Position(
        symbol="BTC",
        entry_price=entry_price,
        quantity=quantity,
        strategy="short_v1",
        market="futures",
        timestamp=1000,
        side="sell",
    )


def test_exit_none_for_invalid_position_values():
    strategy = ShortExitStrategy()
    ctx = _make_context()

    assert strategy.check_exit(ctx, _make_position(entry_price=0.0)) is None
    assert strategy.check_exit(ctx, _make_position(quantity=0.0)) is None


def test_stop_loss_triggered_when_short_loses():
    strategy = ShortExitStrategy(ShortExitParams(stop_loss_pct=2.0))
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=103000.0)  # -3% for short

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert signal.side == "buy"
    assert "Stop loss" in signal.reason


def test_stop_loss_triggered_at_exact_threshold():
    strategy = ShortExitStrategy(ShortExitParams(stop_loss_pct=2.0, take_profit_pct=10.0))
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=102000.0)  # exactly -2% for short

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert "Stop loss" in signal.reason


def test_take_profit_triggered_when_short_wins():
    strategy = ShortExitStrategy(ShortExitParams(take_profit_pct=3.0))
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=96000.0)  # +4% for short

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert signal.side == "buy"
    assert "Take profit" in signal.reason


def test_take_profit_triggered_at_exact_threshold():
    strategy = ShortExitStrategy(ShortExitParams(take_profit_pct=3.0, stop_loss_pct=10.0))
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=97000.0)  # exactly +3% for short

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert "Take profit" in signal.reason


def test_rsi_oversold_exit_triggered():
    params = ShortExitParams(stop_loss_pct=10.0, take_profit_pct=10.0, rsi_oversold=30.0)
    strategy = ShortExitStrategy(params)
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=99500.0, rsi=25.0)  # small pnl, RSI trigger only

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert signal.side == "buy"
    assert "oversold" in signal.reason


def test_rsi_oversold_triggered_at_exact_threshold():
    params = ShortExitParams(stop_loss_pct=10.0, take_profit_pct=10.0, rsi_oversold=30.0)
    strategy = ShortExitStrategy(params)
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=99900.0, rsi=30.0)

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert "oversold" in signal.reason


def test_bull_regime_profit_exit_triggered():
    params = ShortExitParams(stop_loss_pct=10.0, take_profit_pct=10.0, rsi_oversold=10.0)
    strategy = ShortExitStrategy(params)
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=99000.0, rsi=50.0, regime="BULL_MODERATE")

    signal = strategy.check_exit(ctx, position)
    assert signal is not None
    assert signal.side == "buy"
    assert "Regime change" in signal.reason


def test_bull_regime_does_not_exit_when_not_profitable():
    params = ShortExitParams(stop_loss_pct=10.0, take_profit_pct=10.0, rsi_oversold=10.0)
    strategy = ShortExitStrategy(params)
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=100500.0, rsi=50.0, regime="BULL_STRONG")

    assert strategy.check_exit(ctx, position) is None


def test_bull_regime_does_not_exit_at_zero_pnl():
    params = ShortExitParams(stop_loss_pct=10.0, take_profit_pct=10.0, rsi_oversold=10.0)
    strategy = ShortExitStrategy(params)
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=100000.0, rsi=50.0, regime="BULL_MODERATE")

    assert strategy.check_exit(ctx, position) is None
