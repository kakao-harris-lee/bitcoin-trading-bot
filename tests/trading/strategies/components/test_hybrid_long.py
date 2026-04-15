"""Tests for HybridLong entry/exit routing."""

from unittest.mock import Mock

from trading.strategies.components.hybrid_long_entry import (
    HybridLongEntryParams,
    HybridLongEntryStrategy,
)
from trading.strategies.components.hybrid_long_exit import (
    HybridLongExitParams,
    HybridLongExitStrategy,
)
from trading.strategies.components.models import (
    MarketData,
    Position,
    Signal,
    TradingContext,
    build_market_context,
)


def _ctx(*, ts: int, regime_mfi: float, regime_adx: float = 25.0) -> TradingContext:
    market = MarketData(
        symbol="BTC",
        open=100.0,
        close=100.0,
        high=101.0,
        low=99.0,
        mfi=regime_mfi,
        adx=regime_adx,
        rsi=55.0,
        ema_20=95.0,
        ema_120=90.0,
        timestamp=ts,
    )
    regime = build_market_context(mfi=regime_mfi, adx=regime_adx, atr=1.0, close=100.0)
    return TradingContext(
        symbol="BTC",
        timestamp=ts,
        market=market,
        regime=regime,
        positions={},
    )


def _buy_signal(reason: str) -> Signal:
    return Signal(
        symbol="BTC",
        side="buy",
        market="spot",
        quantity=0.5,
        reason=reason,
    )


def _sell_signal(reason: str) -> Signal:
    return Signal(
        symbol="BTC",
        side="sell",
        market="spot",
        quantity=1.0,
        reason=reason,
    )


def _position() -> Position:
    return Position(
        symbol="BTC",
        entry_price=100.0,
        quantity=1.0,
        strategy="mlp_direction_btc",
        market="spot",
        timestamp=1,
    )


def test_hybrid_entry_mlp_primary_with_regime_fallback():
    params = HybridLongEntryParams(
        mlp_route_regimes=["BULL_STRONG", "BULL_MODERATE"],
        fallback_to_regime_when_mlp_none=True,
    )
    strategy = HybridLongEntryStrategy(params=params)
    strategy._mlp.check_entry = Mock(return_value=None)
    strategy._mlp.get_last_rejection_reason = Mock(return_value="MLP warmup (10/120 bars)")
    strategy._regime.check_entry = Mock(return_value=_buy_signal("regime entry"))

    signal = strategy.check_entry(_ctx(ts=1, regime_mfi=70.0, regime_adx=30.0))

    assert signal is not None
    assert "HybridLong[regime_fallback]" in signal.reason
    strategy._mlp.check_entry.assert_called_once()
    strategy._regime.check_entry.assert_called_once()


def test_hybrid_entry_regime_primary_with_mlp_fallback():
    params = HybridLongEntryParams(
        mlp_route_regimes=["BULL_STRONG"],
        fallback_to_mlp_when_regime_none=True,
    )
    strategy = HybridLongEntryStrategy(params=params)
    strategy._regime.check_entry = Mock(return_value=None)
    strategy._mlp.check_entry = Mock(return_value=_buy_signal("mlp entry"))

    # SIDEWAYS_DOWN => regime primary (not in mlp route list)
    signal = strategy.check_entry(_ctx(ts=1, regime_mfi=40.0, regime_adx=15.0))

    assert signal is not None
    assert "HybridLong[mlp_fallback]" in signal.reason
    strategy._regime.check_entry.assert_called_once()
    strategy._mlp.check_entry.assert_called_once()


def test_hybrid_entry_rejection_reason_tracks_primary_and_fallback():
    params = HybridLongEntryParams(
        mlp_route_regimes=["BULL_STRONG", "BULL_MODERATE"],
        fallback_to_regime_when_mlp_none=True,
        fallback_on_mlp_non_buy=True,
    )
    strategy = HybridLongEntryStrategy(params=params)
    strategy._mlp.check_entry = Mock(return_value=None)
    strategy._regime.check_entry = Mock(return_value=None)
    strategy._mlp.get_last_rejection_reason = Mock(return_value="MLP predicted HOLD (not BUY)")
    strategy._regime.get_last_rejection_reason = Mock(return_value="RegimeLongV2 quorum miss (2/3 < 3)")

    signal = strategy.check_entry(_ctx(ts=1, regime_mfi=70.0, regime_adx=30.0))

    assert signal is None
    reason = strategy.get_last_rejection_reason("BTC")
    assert reason is not None
    assert "HybridLong[mlp] blocked" in reason
    assert "MLP predicted HOLD" in reason
    assert "fallback[regime] blocked" in reason


def test_hybrid_entry_skips_regime_fallback_for_non_buy_by_default():
    params = HybridLongEntryParams(
        mlp_route_regimes=["BULL_STRONG", "BULL_MODERATE"],
        fallback_to_regime_when_mlp_none=True,
    )
    strategy = HybridLongEntryStrategy(params=params)
    strategy._mlp.check_entry = Mock(return_value=None)
    strategy._mlp.get_last_rejection_reason = Mock(return_value="MLP predicted HOLD (not BUY)")
    strategy._regime.check_entry = Mock(return_value=_buy_signal("regime entry"))

    signal = strategy.check_entry(_ctx(ts=1, regime_mfi=70.0, regime_adx=30.0))

    assert signal is None
    strategy._regime.check_entry.assert_not_called()
    reason = strategy.get_last_rejection_reason("BTC")
    assert reason is not None
    assert "skipped by policy" in reason


def test_hybrid_entry_rejection_reason_cleared_on_signal():
    params = HybridLongEntryParams(
        mlp_route_regimes=["BULL_STRONG", "BULL_MODERATE"],
        fallback_to_regime_when_mlp_none=True,
    )
    strategy = HybridLongEntryStrategy(params=params)
    strategy._mlp.check_entry = Mock(return_value=None)
    strategy._regime.check_entry = Mock(return_value=None)
    strategy._mlp.get_last_rejection_reason = Mock(return_value="MLP warmup (10/120 bars)")
    strategy._regime.get_last_rejection_reason = Mock(return_value="RegimeLongV2 waiting")

    assert strategy.check_entry(_ctx(ts=1, regime_mfi=70.0, regime_adx=30.0)) is None
    assert strategy.get_last_rejection_reason("BTC") is not None

    strategy._mlp.check_entry = Mock(return_value=_buy_signal("mlp entry"))
    signal = strategy.check_entry(_ctx(ts=2, regime_mfi=70.0, regime_adx=30.0))

    assert signal is not None
    assert strategy.get_last_rejection_reason("BTC") is None


def test_hybrid_entry_non_buy_fallback_can_be_restricted_to_quality_allowlist():
    params = HybridLongEntryParams(
        mlp_route_regimes=["BULL_STRONG", "BULL_MODERATE"],
        fallback_to_regime_when_mlp_none=True,
        fallback_on_mlp_non_buy=True,
        fallback_quality_allowlist_symbols=["ETH"],
    )
    strategy = HybridLongEntryStrategy(params=params)
    strategy._mlp.check_entry = Mock(return_value=None)
    strategy._mlp.get_last_rejection_reason = Mock(return_value="MLP predicted HOLD (not BUY)")
    strategy._regime.check_entry = Mock(return_value=_buy_signal("regime entry"))

    signal = strategy.check_entry(_ctx(ts=1, regime_mfi=70.0, regime_adx=30.0))

    assert signal is None
    strategy._regime.check_entry.assert_not_called()


def test_hybrid_entry_blocked_symbol_skips_even_unavailable_fallback():
    params = HybridLongEntryParams(
        mlp_route_regimes=["BULL_STRONG", "BULL_MODERATE"],
        fallback_to_regime_when_mlp_none=True,
        fallback_on_mlp_unavailable=True,
        fallback_blocked_symbols=["BTC"],
    )
    strategy = HybridLongEntryStrategy(params=params)
    strategy._mlp.check_entry = Mock(return_value=None)
    strategy._mlp.get_last_rejection_reason = Mock(return_value="MLP warmup (10/120 bars)")
    strategy._regime.check_entry = Mock(return_value=_buy_signal("regime entry"))

    signal = strategy.check_entry(_ctx(ts=1, regime_mfi=70.0, regime_adx=30.0))

    assert signal is None
    strategy._regime.check_entry.assert_not_called()


def test_hybrid_exit_regime_protection_preempts_mlp():
    params = HybridLongExitParams(
        mlp_route_regimes=["BULL_STRONG", "BULL_MODERATE"],
        always_apply_regime_protection=True,
    )
    strategy = HybridLongExitStrategy(params=params)
    strategy._regime.check_exit = Mock(return_value=_sell_signal("regime protect exit"))
    strategy._mlp.check_exit = Mock(return_value=_sell_signal("mlp exit"))

    signal = strategy.check_exit(
        _ctx(ts=1, regime_mfi=70.0, regime_adx=30.0), _position()
    )

    assert signal is not None
    assert "HybridLong[regime_protect]" in signal.reason
    strategy._regime.check_exit.assert_called_once()
    strategy._mlp.check_exit.assert_not_called()


def test_hybrid_exit_mlp_primary_when_no_regime_protect_signal():
    params = HybridLongExitParams(
        mlp_route_regimes=["BULL_STRONG", "BULL_MODERATE"],
        always_apply_regime_protection=True,
    )
    strategy = HybridLongExitStrategy(params=params)
    strategy._regime.check_exit = Mock(return_value=None)
    strategy._mlp.check_exit = Mock(return_value=_sell_signal("mlp exit"))

    signal = strategy.check_exit(
        _ctx(ts=1, regime_mfi=70.0, regime_adx=30.0), _position()
    )

    assert signal is not None
    assert "HybridLong[mlp]" in signal.reason
    strategy._regime.check_exit.assert_called_once()
    strategy._mlp.check_exit.assert_called_once()


def test_hybrid_exit_regime_primary_with_mlp_fallback():
    params = HybridLongExitParams(
        mlp_route_regimes=["BULL_STRONG"],
        fallback_to_mlp_when_regime_none=True,
        always_apply_regime_protection=False,
    )
    strategy = HybridLongExitStrategy(params=params)
    strategy._regime.check_exit = Mock(return_value=None)
    strategy._mlp.check_exit = Mock(return_value=_sell_signal("mlp fallback exit"))

    signal = strategy.check_exit(
        _ctx(ts=1, regime_mfi=40.0, regime_adx=15.0), _position()
    )

    assert signal is not None
    assert "HybridLong[mlp_fallback]" in signal.reason
    strategy._regime.check_exit.assert_called_once()
    strategy._mlp.check_exit.assert_called_once()
