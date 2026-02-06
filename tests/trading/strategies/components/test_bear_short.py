"""Tests for Bear Short entry and exit strategy components.

Tests the conservative futures short strategy that activates during
confirmed BEAR_STRONG regimes with MACD momentum + volume confirmation.
"""

import pytest
from types import MappingProxyType

from trading.strategies.components.bear_short_entry import (
    BearShortEntryStrategy,
    BearShortEntryParams,
)
from trading.strategies.components.bear_short_exit import (
    BearShortExitStrategy,
    BearShortExitParams,
)
from trading.strategies.components.models import (
    MarketData,
    MarketContext,
    Position,
    Signal,
    TradingContext,
    build_market_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_market_data(
    symbol: str = "BTC",
    close: float = 50000.0,
    macd: float = -100.0,
    macd_signal: float = -50.0,
    mfi: float = 30.0,
    adx: float = 30.0,
    rsi: float = 45.0,
    volume: float = 200.0,
    avg_volume_20: float = 100.0,
) -> MarketData:
    return MarketData(
        symbol=symbol,
        close=close,
        mfi=mfi,
        adx=adx,
        rsi=rsi,
        timestamp=1000,
        atr=1500.0,
        volume=volume,
        avg_volume_20=avg_volume_20,
        macd=macd,
        macd_signal=macd_signal,
    )


def _make_context(
    symbol: str = "BTC",
    close: float = 50000.0,
    macd: float = -100.0,
    macd_signal: float = -50.0,
    mfi: float = 30.0,
    adx: float = 30.0,
    rsi: float = 45.0,
    volume: float = 200.0,
    avg_volume: float = 100.0,
    regime_override: str | None = None,
) -> TradingContext:
    """Build a full TradingContext for testing."""
    market = _make_market_data(
        symbol=symbol,
        close=close,
        macd=macd,
        macd_signal=macd_signal,
        mfi=mfi,
        adx=adx,
        rsi=rsi,
        volume=volume,
        avg_volume_20=avg_volume,
    )
    regime = build_market_context(
        mfi=mfi,
        adx=adx,
        atr=1500.0,
        close=close,
        volume=volume,
        avg_volume=avg_volume,
    )
    # Allow overriding regime for test control
    if regime_override:
        regime = MarketContext(
            trend=regime.trend,
            regime=regime_override,
            volatility_score=regime.volatility_score,
            is_extreme_volatility=regime.is_extreme_volatility,
            adx=adx,
            volume_ratio=regime.volume_ratio,
            is_high_volume=regime.is_high_volume,
        )
    return TradingContext(
        symbol=symbol,
        timestamp=1000,
        market=market,
        regime=regime,
        positions=MappingProxyType({}),
    )


def _make_position(
    symbol: str = "BTC",
    entry_price: float = 50000.0,
    quantity: float = 0.01,
) -> Position:
    return Position(
        symbol=symbol,
        entry_price=entry_price,
        quantity=quantity,
        strategy="bear_short",
        market="futures",
        timestamp=1000,
        side="sell",
        leverage=3,
    )


# ===========================================================================
# Entry Tests
# ===========================================================================

class TestBearShortEntryParams:
    """Test BearShortEntryParams defaults and overrides."""

    def test_default_values(self):
        params = BearShortEntryParams()
        assert params.volume_ratio_threshold == 1.5
        assert params.position_size == 0.01
        assert params.market == "futures"

    def test_custom_values(self):
        params = BearShortEntryParams(
            volume_ratio_threshold=2.0,
            position_size=0.05,
        )
        assert params.volume_ratio_threshold == 2.0
        assert params.position_size == 0.05


class TestBearShortEntry:
    """Test BearShortEntryStrategy check_entry logic."""

    def test_entry_all_conditions_met(self):
        """BEAR_STRONG + MACD bearish + high volume -> signal."""
        strategy = BearShortEntryStrategy()
        # mfi=30, adx=30 -> BEAR_STRONG; macd < signal; volume=200/100=2.0
        ctx = _make_context(
            mfi=30.0, adx=30.0,
            macd=-100.0, macd_signal=-50.0,
            volume=200.0, avg_volume=100.0,
        )
        signal = strategy.check_entry(ctx)
        assert signal is not None
        assert signal.side == "sell"
        assert signal.market == "futures"
        assert "BearShort entry" in signal.reason

    def test_entry_blocked_by_bull_regime(self):
        """BULL regime -> no signal."""
        strategy = BearShortEntryStrategy()
        ctx = _make_context(
            mfi=60.0, adx=30.0,  # BULL
            macd=-100.0, macd_signal=-50.0,
            volume=200.0, avg_volume=100.0,
        )
        assert strategy.check_entry(ctx) is None

    def test_entry_blocked_by_bear_moderate(self):
        """BEAR_MODERATE -> no signal (strict BEAR_STRONG only)."""
        strategy = BearShortEntryStrategy()
        # mfi=30, adx=15 -> BEAR_MODERATE (ADX too low for BEAR_STRONG)
        ctx = _make_context(
            mfi=30.0, adx=15.0,
            macd=-100.0, macd_signal=-50.0,
            volume=200.0, avg_volume=100.0,
        )
        assert strategy.check_entry(ctx) is None

    def test_entry_blocked_by_sideways(self):
        """SIDEWAYS regimes -> no signal."""
        strategy = BearShortEntryStrategy()
        ctx = _make_context(
            mfi=45.0, adx=15.0,  # SIDEWAYS_FLAT
            macd=-100.0, macd_signal=-50.0,
            volume=200.0, avg_volume=100.0,
        )
        assert strategy.check_entry(ctx) is None

    def test_entry_blocked_by_macd_bullish(self):
        """MACD >= Signal (bullish) -> no signal."""
        strategy = BearShortEntryStrategy()
        ctx = _make_context(
            mfi=30.0, adx=30.0,  # BEAR_STRONG
            macd=50.0, macd_signal=-50.0,  # MACD > Signal = bullish
            volume=200.0, avg_volume=100.0,
        )
        assert strategy.check_entry(ctx) is None

    def test_entry_blocked_by_macd_equal(self):
        """MACD == Signal (no momentum) -> no signal."""
        strategy = BearShortEntryStrategy()
        ctx = _make_context(
            mfi=30.0, adx=30.0,
            macd=-50.0, macd_signal=-50.0,  # Equal
            volume=200.0, avg_volume=100.0,
        )
        assert strategy.check_entry(ctx) is None

    def test_entry_blocked_by_low_volume(self):
        """Volume ratio below threshold -> no signal."""
        strategy = BearShortEntryStrategy()
        ctx = _make_context(
            mfi=30.0, adx=30.0,
            macd=-100.0, macd_signal=-50.0,
            volume=100.0, avg_volume=100.0,  # ratio=1.0 < 1.5
        )
        assert strategy.check_entry(ctx) is None

    def test_entry_with_custom_volume_threshold(self):
        """Custom volume threshold should be respected."""
        params = BearShortEntryParams(volume_ratio_threshold=1.2)
        strategy = BearShortEntryStrategy(params=params)
        ctx = _make_context(
            mfi=30.0, adx=30.0,
            macd=-100.0, macd_signal=-50.0,
            volume=130.0, avg_volume=100.0,  # ratio=1.3 >= 1.2
        )
        signal = strategy.check_entry(ctx)
        assert signal is not None

    def test_entry_signal_quantity_from_params(self):
        """Signal quantity should match params.position_size."""
        params = BearShortEntryParams(position_size=0.05)
        strategy = BearShortEntryStrategy(params=params)
        ctx = _make_context(
            mfi=30.0, adx=30.0,
            macd=-100.0, macd_signal=-50.0,
            volume=200.0, avg_volume=100.0,
        )
        signal = strategy.check_entry(ctx)
        assert signal is not None
        assert signal.quantity == 0.05

    def test_entry_uses_regime_override(self):
        """Explicitly override regime to verify gate logic."""
        strategy = BearShortEntryStrategy()
        # Use high MFI (would normally be BULL) but override to BEAR_STRONG
        ctx = _make_context(
            mfi=60.0, adx=30.0,
            macd=-100.0, macd_signal=-50.0,
            volume=200.0, avg_volume=100.0,
            regime_override="BEAR_STRONG",
        )
        signal = strategy.check_entry(ctx)
        assert signal is not None


# ===========================================================================
# Exit Tests
# ===========================================================================

class TestBearShortExitParams:
    """Test BearShortExitParams defaults and overrides."""

    def test_default_values(self):
        params = BearShortExitParams()
        assert params.stop_loss_pct == 3.0
        assert params.take_profit_pct == 5.0
        assert params.market == "futures"

    def test_custom_values(self):
        params = BearShortExitParams(stop_loss_pct=4.0, take_profit_pct=8.0)
        assert params.stop_loss_pct == 4.0
        assert params.take_profit_pct == 8.0


class TestBearShortExit:
    """Test BearShortExitStrategy check_exit logic."""

    def test_stop_loss_triggered(self):
        """Price rose 3% -> stop loss exit."""
        strategy = BearShortExitStrategy()
        # Entry at 50000, current at 51500 -> pnl = (50000-51500)/50000*100 = -3.0%
        ctx = _make_context(close=51500.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None
        assert signal.side == "buy"
        assert "Stop loss" in signal.reason

    def test_stop_loss_exact_boundary(self):
        """Exactly at stop loss boundary -> should trigger."""
        strategy = BearShortExitStrategy()
        # pnl = (50000-51500)/50000*100 = -3.0% exactly
        ctx = _make_context(close=51500.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None

    def test_take_profit_triggered(self):
        """Price dropped 5% -> take profit exit."""
        strategy = BearShortExitStrategy()
        # Entry at 50000, current at 47500 -> pnl = (50000-47500)/50000*100 = 5.0%
        ctx = _make_context(close=47500.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None
        assert signal.side == "buy"
        assert "Take profit" in signal.reason

    def test_take_profit_exact_boundary(self):
        """Exactly at take profit boundary -> should trigger."""
        strategy = BearShortExitStrategy()
        ctx = _make_context(close=47500.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None

    def test_regime_change_to_sideways_exits(self):
        """Regime changes to SIDEWAYS -> exit."""
        strategy = BearShortExitStrategy()
        ctx = _make_context(close=49000.0, regime_override="SIDEWAYS_FLAT")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None
        assert "Regime change" in signal.reason

    def test_regime_change_to_bull_exits(self):
        """Regime changes to BULL -> exit."""
        strategy = BearShortExitStrategy()
        ctx = _make_context(close=49000.0, regime_override="BULL_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None
        assert "Regime change" in signal.reason

    def test_bear_moderate_holds(self):
        """BEAR_MODERATE -> hold (still in BEAR zone)."""
        strategy = BearShortExitStrategy()
        ctx = _make_context(close=49000.0, regime_override="BEAR_MODERATE")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is None

    def test_bear_strong_holds(self):
        """BEAR_STRONG with moderate P&L -> hold."""
        strategy = BearShortExitStrategy()
        # pnl = (50000-49000)/50000*100 = 2.0% (below TP)
        ctx = _make_context(close=49000.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is None

    def test_no_exit_with_invalid_position(self):
        """Zero entry price -> no signal."""
        strategy = BearShortExitStrategy()
        ctx = _make_context(close=49000.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=0.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is None

    def test_no_exit_with_zero_quantity(self):
        """Zero quantity -> no signal."""
        strategy = BearShortExitStrategy()
        ctx = _make_context(close=49000.0, regime_override="BEAR_STRONG")
        pos = _make_position(quantity=0.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is None

    def test_exit_signal_covers_full_quantity(self):
        """Exit signal should cover the full position quantity."""
        strategy = BearShortExitStrategy()
        ctx = _make_context(close=51500.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=50000.0, quantity=0.05)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None
        assert signal.quantity == 0.05

    def test_custom_stop_loss(self):
        """Custom stop loss threshold should be respected."""
        params = BearShortExitParams(stop_loss_pct=5.0)
        strategy = BearShortExitStrategy(params=params)
        # 3% loss - should NOT trigger with 5% SL
        ctx = _make_context(close=51500.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is None

    def test_custom_take_profit(self):
        """Custom take profit threshold should be respected."""
        params = BearShortExitParams(take_profit_pct=3.0)
        strategy = BearShortExitStrategy(params=params)
        # 4% profit with 3% TP -> should trigger
        ctx = _make_context(close=48000.0, regime_override="BEAR_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None
        assert "Take profit" in signal.reason

    def test_on_position_opened_no_error(self):
        """on_position_opened should not raise."""
        strategy = BearShortExitStrategy()
        pos = _make_position()
        strategy.on_position_opened(pos)  # Should not raise

    def test_on_position_closed_no_error(self):
        """on_position_closed should not raise."""
        strategy = BearShortExitStrategy()
        strategy.on_position_closed("BTC")  # Should not raise

    def test_stop_loss_priority_over_regime_change(self):
        """Stop loss should trigger even when regime also changed."""
        strategy = BearShortExitStrategy()
        # Price rose 4% AND regime is BULL
        ctx = _make_context(close=52000.0, regime_override="BULL_STRONG")
        pos = _make_position(entry_price=50000.0)
        signal = strategy.check_exit(ctx, pos)
        assert signal is not None
        # Stop loss checked first
        assert "Stop loss" in signal.reason


# ===========================================================================
# Registration Tests
# ===========================================================================

class TestBearShortRegistration:
    """Test that strategies are properly registered via decorators."""

    def test_entry_registered(self):
        from trading.strategies.components.registry import is_entry_registered
        assert is_entry_registered("BearShortEntryStrategy")

    def test_exit_registered(self):
        from trading.strategies.components.registry import is_exit_registered
        assert is_exit_registered("BearShortExitStrategy")

    def test_factory_creates_entry(self):
        from trading.strategies.components.strategy_factory import StrategyFactory
        factory = StrategyFactory()
        config = {
            "market": "futures",
            "entry": {
                "class": "BearShortEntryStrategy",
                "params": {"volume_ratio_threshold": 1.5},
            },
            "exit": {
                "class": "BearShortExitStrategy",
                "params": {"stop_loss_pct": 3.0},
            },
        }
        entry = factory.create_entry("bear_short", config)
        assert isinstance(entry, BearShortEntryStrategy)
        assert entry.params.volume_ratio_threshold == 1.5

    def test_factory_creates_exit(self):
        from trading.strategies.components.strategy_factory import StrategyFactory
        factory = StrategyFactory()
        config = {
            "market": "futures",
            "entry": {
                "class": "BearShortEntryStrategy",
                "params": {},
            },
            "exit": {
                "class": "BearShortExitStrategy",
                "params": {"stop_loss_pct": 4.0, "take_profit_pct": 8.0},
            },
        }
        exit_strat = factory.create_exit("bear_short", config)
        assert isinstance(exit_strat, BearShortExitStrategy)
        assert exit_strat.params.stop_loss_pct == 4.0
        assert exit_strat.params.take_profit_pct == 8.0
