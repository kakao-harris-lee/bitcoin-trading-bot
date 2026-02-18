"""Tests for RegimeLongV2 entry/exit components."""

from trading.strategies.components.models import (
    MarketData,
    Position,
    TradingContext,
    build_market_context,
)
from trading.strategies.components.regime_long_cooldown import (
    activate_cooldown,
    clear_cooldown,
    consume_cooldown,
)
from trading.strategies.components.regime_long_v2_entry import (
    RegimeLongV2EntryParams,
    RegimeLongV2EntryStrategy,
)
from trading.strategies.components.regime_long_v2_exit import (
    RegimeLongV2ExitParams,
    RegimeLongV2ExitStrategy,
)


def _ctx(
    *,
    ts: int,
    close: float = 100.0,
    high: float = 101.0,
    mfi: float = 60.0,
    adx: float = 25.0,
    rsi: float = 58.0,
    ema_20: float = 95.0,
    ema_120: float = 90.0,
) -> TradingContext:
    market = MarketData(
        symbol="BTC",
        open=close,
        close=close,
        high=high,
        low=close,
        mfi=mfi,
        adx=adx,
        rsi=rsi,
        ema_20=ema_20,
        ema_120=ema_120,
        timestamp=ts,
    )
    regime = build_market_context(
        mfi=mfi,
        adx=adx,
        atr=1.0,
        close=close,
    )
    return TradingContext(
        symbol="BTC",
        timestamp=ts,
        market=market,
        regime=regime,
        positions={},
    )


def _position(entry_price: float = 100.0) -> Position:
    return Position(
        symbol="BTC",
        entry_price=entry_price,
        quantity=1.0,
        strategy="regime_long_v2",
        market="spot",
        timestamp=1,
    )


def test_entry_blocks_when_cooldown_active():
    params = RegimeLongV2EntryParams(
        cooldown_tag="test_regime", min_ready_bars=1, entry_lookback_bars=4
    )
    strategy = RegimeLongV2EntryStrategy(params=params)
    activate_cooldown("BTC", "test_regime", 5)
    try:
        signal = strategy.check_entry(_ctx(ts=1000))
        assert signal is None
    finally:
        clear_cooldown("BTC", "test_regime")


def test_entry_emits_signal_after_quorum():
    params = RegimeLongV2EntryParams(
        cooldown_tag="test_regime",
        entry_lookback_bars=4,
        min_ready_bars=4,
        entry_quorum_ratio=0.75,
        risk_on_score_min=3,
    )
    strategy = RegimeLongV2EntryStrategy(params=params)

    signal = None
    for i in range(4):
        signal = strategy.check_entry(_ctx(ts=1000 + i, close=100 + i))

    assert signal is not None
    assert signal.side == "buy"
    assert "RegimeLongV2 entry" in signal.reason


def test_entry_blocks_in_bear_regime():
    params = RegimeLongV2EntryParams(
        cooldown_tag="test_regime",
        entry_lookback_bars=2,
        min_ready_bars=1,
    )
    strategy = RegimeLongV2EntryStrategy(params=params)
    signal = strategy.check_entry(_ctx(ts=1000, mfi=25.0, adx=35.0))
    assert signal is None


def test_exit_on_bear_regime_activates_cooldown():
    params = RegimeLongV2ExitParams(cooldown_tag="test_regime", cooldown_bars=3)
    strategy = RegimeLongV2ExitStrategy(params=params)
    pos = _position()
    signal = strategy.check_exit(
        _ctx(ts=2000, mfi=25.0, adx=35.0, close=95.0, high=100.0), pos
    )
    assert signal is not None
    assert "bear regime" in signal.reason
    assert consume_cooldown("BTC", "test_regime", 2001) > 0
    clear_cooldown("BTC", "test_regime")


def test_exit_on_peak_drawdown():
    params = RegimeLongV2ExitParams(
        peak_drawdown_exit_pct=0.05,
        exit_on_bear_regime=False,
        drop_1d_lookback_bars=99,
        drop_3d_lookback_bars=199,
    )
    strategy = RegimeLongV2ExitStrategy(params=params)
    pos = _position(entry_price=100.0)
    strategy.on_position_opened(pos)

    # Set a higher HWM first.
    assert strategy.check_exit(_ctx(ts=1, close=110.0, high=111.0), pos) is None
    signal = strategy.check_exit(_ctx(ts=2, close=104.0, high=104.0), pos)

    assert signal is not None
    assert "peak drawdown" in signal.reason


def test_exit_on_shock_return():
    params = RegimeLongV2ExitParams(
        exit_on_bear_regime=False,
        peak_drawdown_exit_pct=0.9,
        drop_1d_lookback_bars=1,
        drop_1d_threshold_pct=-0.01,
        drop_3d_lookback_bars=10,
    )
    strategy = RegimeLongV2ExitStrategy(params=params)
    pos = _position(entry_price=100.0)
    strategy.on_position_opened(pos)

    assert strategy.check_exit(_ctx(ts=1, close=100.0, high=101.0), pos) is None
    signal = strategy.check_exit(_ctx(ts=2, close=98.0, high=98.5), pos)

    assert signal is not None
    assert "1d shock" in signal.reason
