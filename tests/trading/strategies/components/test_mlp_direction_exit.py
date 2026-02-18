"""Tests for MLPDirectionExitStrategy.

Tests the MLP Direction exit strategy component based on
Parente & Rizzuti (2025) methodology.
"""

from unittest.mock import MagicMock

from trading.strategies.components.mlp_direction_exit import (
    MLPDirectionExitStrategy,
    MLPDirectionExitParams,
)
from trading.strategies.components.models import (
    MLP_LABEL_SELL,
    MarketData,
    Position,
    TradingContext,
    build_market_context,
)


def _make_context(
    mfi: float = 55.0,
    adx: float = 25.0,
    close: float = 100000.0,
    high: float = 101000.0,
    atr: float = 1000.0,
    timestamp: int = 1000,
    mlp_prediction: int | None = None,
    mlp_confidence: float | None = None,
    ema_200: float = 0.0,
    ema_5: float = 0.0,
    ema_10: float = 0.0,
    ema_20: float = 0.0,
    trix: float = 0.0,
    trix_signal: float = 0.0,
) -> TradingContext:
    """Helper to create TradingContext for tests."""
    market = MarketData(
        symbol="BTC",
        close=close,
        high=high,
        mfi=mfi,
        adx=adx,
        rsi=50.0,
        timestamp=timestamp,
        atr=atr,
        volume=100.0,
        avg_volume_20=80.0,
        ema_200=ema_200,
        ema_5=ema_5,
        ema_10=ema_10,
        ema_20=ema_20,
        trix=trix,
        trix_signal=trix_signal,
    )
    regime = build_market_context(mfi=mfi, adx=adx, atr=atr, close=close)
    return TradingContext(
        symbol="BTC",
        timestamp=timestamp,
        market=market,
        regime=regime,
        positions={},
        mlp_prediction=mlp_prediction,
        mlp_confidence=mlp_confidence,
    )


def _make_position(
    entry_price: float = 100000.0,
    quantity: float = 0.1,
    symbol: str = "BTC",
    strategy: str = "mlp_direction",
) -> Position:
    """Helper to create Position for tests."""
    return Position(
        symbol=symbol,
        entry_price=entry_price,
        quantity=quantity,
        strategy=strategy,
        market="futures",
        timestamp=1000,
        side="buy",
    )


class TestMLPDirectionExitParams:
    """Test MLPDirectionExitParams dataclass."""

    def test_default_values(self):
        """Test default parameter values match paper (10% stop loss, FWin exit)."""
        params = MLPDirectionExitParams()

        assert params.stop_loss_pct == 10.0
        assert params.fwin_exit_enabled is True  # Paper methodology
        assert params.fwin_periods == 2  # Exit after 2 candles (8H for 4H timeframe)
        assert params.atr_stop_enabled is False
        assert params.trailing_enabled is False
        assert params.use_mlp_sell_exit is False
        assert params.min_hold_bars_for_sell_exit == 0
        assert params.bull_regime_sell_guard is False
        assert params.take_profit_enabled is False
        assert params.market == "spot"

    def test_custom_values(self):
        """Test custom parameter values."""
        params = MLPDirectionExitParams(
            stop_loss_pct=5.0,
            trailing_enabled=True,
            trailing_activation=3.0,
            trailing_distance=2.0,
        )

        assert params.stop_loss_pct == 5.0
        assert params.trailing_enabled is True
        assert params.trailing_activation == 3.0
        assert params.trailing_distance == 2.0


class TestMLPDirectionExitStrategy:
    """Test MLPDirectionExitStrategy."""

    def test_initialization(self):
        """Test strategy initialization."""
        strategy = MLPDirectionExitStrategy()

        assert strategy.params is not None
        assert strategy.params.stop_loss_pct == 10.0

    def test_initialization_with_params(self):
        """Test strategy initialization with custom params."""
        params = MLPDirectionExitParams(stop_loss_pct=5.0)
        strategy = MLPDirectionExitStrategy(params=params)

        assert strategy.params.stop_loss_pct == 5.0

    def test_stop_loss_triggered(self):
        """Exit triggers when loss exceeds stop loss threshold."""
        strategy = MLPDirectionExitStrategy()
        position = _make_position(entry_price=100000.0)
        ctx = _make_context(close=89000.0)  # -11% loss (exceeds 10% stop loss)

        signal = strategy.check_exit(ctx, position)

        assert signal is not None
        assert "Stop loss" in signal.reason

    def test_stop_loss_not_triggered(self):
        """Exit does not trigger when loss is within threshold."""
        strategy = MLPDirectionExitStrategy()
        position = _make_position(entry_price=100000.0)
        ctx = _make_context(close=95000.0)  # -5% loss (within 10% stop loss)

        signal = strategy.check_exit(ctx, position)

        assert signal is None

    def test_custom_stop_loss_threshold(self):
        """Exit respects custom stop loss threshold."""
        params = MLPDirectionExitParams(stop_loss_pct=5.0)
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)
        ctx = _make_context(close=94000.0)  # -6% loss

        signal = strategy.check_exit(ctx, position)

        assert signal is not None
        assert "Stop loss" in signal.reason

    def test_take_profit_triggered(self):
        """Exit triggers at take profit when enabled."""
        params = MLPDirectionExitParams(
            take_profit_enabled=True,
            take_profit_pct=20.0,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)
        ctx = _make_context(close=121000.0)  # +21% profit

        signal = strategy.check_exit(ctx, position)

        assert signal is not None
        assert "Take profit" in signal.reason

    def test_take_profit_not_triggered(self):
        """Exit does not trigger when profit is below threshold."""
        params = MLPDirectionExitParams(
            take_profit_enabled=True,
            take_profit_pct=20.0,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)
        ctx = _make_context(close=115000.0)  # +15% profit

        signal = strategy.check_exit(ctx, position)

        assert signal is None

    def test_trix_protective_exit_triggered(self):
        """Exit triggers when TRIX falls below signal and below EMA200."""
        params = MLPDirectionExitParams(
            stop_loss_pct=50.0,
            fwin_exit_enabled=False,
            trix_protective_exit_enabled=True,
            trix_exit_requires_below_ema200=True,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)
        ctx = _make_context(
            close=98000.0,
            ema_200=100000.0,
            trix=-0.02,
            trix_signal=0.01,
        )

        signal = strategy.check_exit(ctx, position)

        assert signal is not None
        assert "TRIX protective exit" in signal.reason

    def test_trix_protective_exit_respects_ema200_guard(self):
        """TRIX protective exit can be guarded by EMA200 condition."""
        params = MLPDirectionExitParams(
            stop_loss_pct=50.0,
            fwin_exit_enabled=False,
            trix_protective_exit_enabled=True,
            trix_exit_requires_below_ema200=True,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)
        ctx = _make_context(
            close=102000.0,
            ema_200=100000.0,
            trix=-0.02,
            trix_signal=0.01,
        )

        signal = strategy.check_exit(ctx, position)

        assert signal is None

    def test_ema_deadcross_exit_triggered_after_consecutive_bars(self):
        """EMA deadcross exit should trigger only after required streak."""
        params = MLPDirectionExitParams(
            stop_loss_pct=50.0,
            fwin_exit_enabled=False,
            ema_deadcross_exit_enabled=True,
            ema_deadcross_consecutive_bars=2,
            ema_deadcross_require_below_ema20=True,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)

        # 1st bar: deadcross condition true but streak=1 -> no exit
        ctx1 = _make_context(
            close=98000.0,
            ema_5=97500.0,
            ema_10=98500.0,
            ema_20=99500.0,
        )
        signal1 = strategy.check_exit(ctx1, position)
        assert signal1 is None

        # 2nd consecutive bar: should exit
        ctx2 = _make_context(
            close=97500.0,
            ema_5=97000.0,
            ema_10=98000.0,
            ema_20=99000.0,
        )
        signal2 = strategy.check_exit(ctx2, position)
        assert signal2 is not None
        assert "EMA deadcross" in signal2.reason

    def test_ema_deadcross_requires_price_below_ema20(self):
        """EMA deadcross guard should not trigger if close is above EMA20."""
        params = MLPDirectionExitParams(
            stop_loss_pct=50.0,
            fwin_exit_enabled=False,
            ema_deadcross_exit_enabled=True,
            ema_deadcross_consecutive_bars=1,
            ema_deadcross_require_below_ema20=True,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)
        ctx = _make_context(
            close=100500.0,  # above ema20
            ema_5=99500.0,
            ema_10=100000.0,
            ema_20=100200.0,
        )

        signal = strategy.check_exit(ctx, position)
        assert signal is None


class TestMLPDirectionExitTrailingStop:
    """Test trailing stop functionality."""

    def test_trailing_stop_not_active_before_threshold(self):
        """Trailing stop does not trigger before activation threshold."""
        params = MLPDirectionExitParams(
            trailing_enabled=True,
            trailing_activation=5.0,  # Activate at +5%
            trailing_distance=3.0,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)

        # Initialize position state
        strategy.on_position_opened(position)

        # Price at +3% (below 5% activation)
        ctx = _make_context(close=103000.0, high=103000.0)
        signal = strategy.check_exit(ctx, position)

        assert signal is None

    def test_trailing_stop_triggered_after_activation(self):
        """Trailing stop triggers after activation and price drop."""
        params = MLPDirectionExitParams(
            trailing_enabled=True,
            trailing_activation=5.0,  # Activate at +5%
            trailing_distance=3.0,    # Trail by 3%
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)

        # Initialize position state
        strategy.on_position_opened(position)

        # First, price rises to +10% (activates trailing)
        ctx1 = _make_context(close=110000.0, high=110000.0)
        signal1 = strategy.check_exit(ctx1, position)
        assert signal1 is None  # Still profitable, no exit

        # Then price drops 4% from high (exceeds 3% trail distance)
        ctx2 = _make_context(close=105000.0, high=110000.0)  # HWM still at 110k
        signal2 = strategy.check_exit(ctx2, position)

        assert signal2 is not None
        assert "Trailing stop" in signal2.reason


class TestMLPDirectionExitStateManagement:
    """Test state management methods."""

    def test_on_position_opened_initializes_state(self):
        """on_position_opened initializes tracking state."""
        strategy = MLPDirectionExitStrategy()
        position = _make_position(entry_price=100000.0)

        strategy.on_position_opened(position)

        key = f"{position.symbol}:{position.strategy}"
        assert key in strategy._high_water_marks
        assert strategy._high_water_marks[key] == position.entry_price

    def test_on_position_closed_clears_state(self):
        """on_position_closed clears tracking state."""
        strategy = MLPDirectionExitStrategy()
        position = _make_position(entry_price=100000.0)

        strategy.on_position_opened(position)
        strategy.on_position_closed(position.symbol)

        key = f"{position.symbol}:{position.strategy}"
        assert key not in strategy._high_water_marks

    def test_high_water_mark_property(self):
        """high_water_mark property returns copy of internal dict."""
        strategy = MLPDirectionExitStrategy()
        position = _make_position(entry_price=100000.0)

        strategy.on_position_opened(position)
        hwm = strategy.high_water_mark

        # Should be a copy, not the same object
        assert hwm is not strategy._high_water_marks

        key = f"{position.symbol}:{position.strategy}"
        assert key in hwm


class TestMLPDirectionExitATRStop:
    """Test ATR-based dynamic stop loss."""

    def test_atr_stop_adjusts_threshold(self):
        """ATR-based stop loss adjusts threshold based on volatility."""
        params = MLPDirectionExitParams(
            atr_stop_enabled=True,
            atr_stop_multiplier=2.0,
            atr_stop_min_pct=3.0,
            atr_stop_max_pct=15.0,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)

        # High ATR = 5000 (5% of price) -> dynamic stop = 10%
        ctx = _make_context(close=91000.0, atr=5000.0)  # -9% loss

        signal = strategy.check_exit(ctx, position)

        assert signal is None  # Within 10% dynamic stop

        # Lower price to exceed 10%
        ctx2 = _make_context(close=89000.0, atr=5000.0)  # -11% loss
        signal2 = strategy.check_exit(ctx2, position)

        assert signal2 is not None
        assert "Stop loss" in signal2.reason

    def test_atr_stop_respects_min_bound(self):
        """ATR-based stop loss respects minimum bound."""
        params = MLPDirectionExitParams(
            atr_stop_enabled=True,
            atr_stop_multiplier=2.0,
            atr_stop_min_pct=5.0,  # Minimum 5%
            atr_stop_max_pct=15.0,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)

        # Very low ATR (100) -> computed stop = 2 * (100/100000) * 100 = 0.2%
        # Should clamp to min (5%)
        ctx = _make_context(close=94000.0, atr=100.0)  # -6% loss > 5% min
        signal = strategy.check_exit(ctx, position)

        assert signal is not None
        assert "Stop loss" in signal.reason

    def test_atr_stop_respects_max_bound(self):
        """ATR-based stop loss respects maximum bound."""
        params = MLPDirectionExitParams(
            atr_stop_enabled=True,
            atr_stop_multiplier=2.0,
            atr_stop_min_pct=5.0,
            atr_stop_max_pct=8.0,  # Maximum 8%
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)

        # Very high ATR (10000) -> computed stop = 2 * (10000/100000) * 100 = 20%
        # Should clamp to max (8%)
        ctx = _make_context(close=91000.0, atr=10000.0)  # -9% loss > 8% max
        signal = strategy.check_exit(ctx, position)

        assert signal is not None
        assert "Stop loss" in signal.reason


class TestMLPDirectionExitFWin:
    """Test Forward Window (FWin) exit - paper methodology."""

    def test_fwin_exit_after_periods_elapsed(self):
        """Exit triggers after FWin periods have elapsed."""
        params = MLPDirectionExitParams(
            fwin_exit_enabled=True,
            fwin_periods=2,
        )
        strategy = MLPDirectionExitStrategy(params=params)

        # Entry at t=1000000ms
        entry_ts = 1000000
        position = Position(
            symbol="BTC",
            entry_price=100000.0,
            quantity=0.1,
            strategy="mlp_direction",
            market="futures",
            timestamp=1000,
            side="buy",
            entry_time=entry_ts,  # Set entry_time in Position
        )

        strategy.on_position_opened(position)

        # 4H candle = 4 * 60 * 60 * 1000 = 14400000 ms
        # After 2 candles = 28800000 ms later
        candle_ms = 4 * 60 * 60 * 1000
        elapsed_ts = entry_ts + (2 * candle_ms)  # 2 candles elapsed

        market = MarketData(
            symbol="BTC",
            close=100500.0,  # Small profit
            high=101000.0,
            mfi=55.0,
            adx=25.0,
            rsi=50.0,
            timestamp=elapsed_ts,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )
        regime = build_market_context(mfi=55.0, adx=25.0, atr=1000.0, close=100500.0)
        ctx = TradingContext(symbol="BTC", timestamp=elapsed_ts, market=market, regime=regime, positions={})

        signal = strategy.check_exit(ctx, position)

        assert signal is not None
        assert "FWin exit" in signal.reason

    def test_fwin_exit_not_triggered_before_periods(self):
        """Exit does not trigger before FWin periods have elapsed."""
        params = MLPDirectionExitParams(
            fwin_exit_enabled=True,
            fwin_periods=2,
        )
        strategy = MLPDirectionExitStrategy(params=params)

        # Entry at t=1000000ms
        entry_ts = 1000000
        position = Position(
            symbol="BTC",
            entry_price=100000.0,
            quantity=0.1,
            strategy="mlp_direction",
            market="futures",
            timestamp=1000,
            side="buy",
            entry_time=entry_ts,
        )

        strategy.on_position_opened(position)

        # Only 1 candle elapsed (not 2)
        candle_ms = 4 * 60 * 60 * 1000
        elapsed_ts = entry_ts + (1 * candle_ms)

        market = MarketData(
            symbol="BTC",
            close=100500.0,
            high=101000.0,
            mfi=55.0,
            adx=25.0,
            rsi=50.0,
            timestamp=elapsed_ts,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )
        regime = build_market_context(mfi=55.0, adx=25.0, atr=1000.0, close=100500.0)
        ctx = TradingContext(symbol="BTC", timestamp=elapsed_ts, market=market, regime=regime, positions={})

        signal = strategy.check_exit(ctx, position)

        assert signal is None  # Not yet time to exit

    def test_fwin_disabled_no_exit(self):
        """FWin exit does not trigger when disabled."""
        params = MLPDirectionExitParams(
            fwin_exit_enabled=False,
            fwin_periods=2,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)

        entry_ts = 1000000
        strategy.on_position_opened(position, entry_timestamp=entry_ts)

        # 10 candles elapsed (way past FWin)
        candle_ms = 4 * 60 * 60 * 1000
        elapsed_ts = entry_ts + (10 * candle_ms)

        market = MarketData(
            symbol="BTC",
            close=100500.0,
            high=101000.0,
            mfi=55.0,
            adx=25.0,
            rsi=50.0,
            timestamp=elapsed_ts,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )
        regime = build_market_context(mfi=55.0, adx=25.0, atr=1000.0, close=100500.0)
        ctx = TradingContext(symbol="BTC", timestamp=elapsed_ts, market=market, regime=regime, positions={})

        signal = strategy.check_exit(ctx, position)

        assert signal is None  # FWin disabled

    def test_stop_loss_takes_priority_over_fwin(self):
        """Stop loss triggers before FWin if loss exceeds threshold."""
        params = MLPDirectionExitParams(
            fwin_exit_enabled=True,
            fwin_periods=2,
            stop_loss_pct=10.0,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        position = _make_position(entry_price=100000.0)

        entry_ts = 1000000
        strategy.on_position_opened(position, entry_timestamp=entry_ts)

        # Only 1 candle elapsed, but price dropped 11%
        candle_ms = 4 * 60 * 60 * 1000
        elapsed_ts = entry_ts + (1 * candle_ms)

        market = MarketData(
            symbol="BTC",
            close=89000.0,  # -11% loss
            high=90000.0,
            mfi=55.0,
            adx=25.0,
            rsi=50.0,
            timestamp=elapsed_ts,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )
        regime = build_market_context(mfi=55.0, adx=25.0, atr=1000.0, close=89000.0)
        ctx = TradingContext(symbol="BTC", timestamp=elapsed_ts, market=market, regime=regime, positions={})

        signal = strategy.check_exit(ctx, position)

        assert signal is not None
        assert "Stop loss" in signal.reason  # Stop loss, not FWin

    def test_entry_timestamp_cleared_on_position_close(self):
        """Entry timestamp is now stored in Position.entry_time, not in-memory dict."""
        # This test is obsolete - entry_time is in Position object now
        # Test that the strategy doesn't crash when closing a position
        strategy = MLPDirectionExitStrategy()

        # Position with entry_time
        position = Position(
            symbol="BTC",
            entry_price=100000.0,
            quantity=0.1,
            strategy="mlp_direction",
            market="futures",
            timestamp=1000,
            side="buy",
            entry_time=1000000,
        )

        strategy.on_position_opened(position)
        strategy.on_position_closed(position.symbol)

        # No crash = success (no more _entry_timestamps dict to check)


class TestMLPDirectionExitIntegration:
    """Integration tests for MLPDirectionExitStrategy."""

    def test_strategy_is_registered(self):
        """Test that strategy is properly registered."""
        from trading.strategies.components.registry import is_exit_registered

        assert is_exit_registered("MLPDirectionExitStrategy")

    def test_can_be_created_from_factory(self):
        """Test that strategy can be created via StrategyFactory."""
        from trading.strategies.components.strategy_factory import STRATEGY_REGISTRY

        assert "mlp_direction" in STRATEGY_REGISTRY

        spec = STRATEGY_REGISTRY["mlp_direction"]
        assert spec.exit_class == MLPDirectionExitStrategy
        assert spec.exit_params_class == MLPDirectionExitParams


class TestMLPDirectionExitSellGuards:
    """Test MLP SELL exit guardrails for uptrend retention."""

    def test_min_hold_bars_blocks_early_sell_exit(self):
        params = MLPDirectionExitParams(
            fwin_exit_enabled=False,
            use_mlp_sell_exit=True,
            sell_confidence_threshold=0.6,
            min_hold_bars_for_sell_exit=3,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        strategy._ensure_model = MagicMock(return_value=True)
        position = _make_position(entry_price=100000.0)
        strategy.on_position_opened(position)

        ctx = _make_context(
            close=101000.0,
            mlp_prediction=MLP_LABEL_SELL,
            mlp_confidence=0.9,
        )

        # 1st/2nd bar: blocked by hold guard
        assert strategy.check_exit(ctx, position) is None
        assert strategy.check_exit(ctx, position) is None

        # 3rd bar: guard satisfied, SELL exit allowed
        signal = strategy.check_exit(ctx, position)
        assert signal is not None
        assert "SELL prediction" in signal.reason

    def test_bull_regime_guard_requires_higher_sell_confidence(self):
        params = MLPDirectionExitParams(
            fwin_exit_enabled=False,
            use_mlp_sell_exit=True,
            sell_confidence_threshold=0.6,
            bull_regime_sell_guard=True,
        )
        strategy = MLPDirectionExitStrategy(params=params)
        strategy._ensure_model = MagicMock(return_value=True)
        position = _make_position(entry_price=100000.0)
        strategy.on_position_opened(position)

        # Bull regime + low SELL confidence: blocked by guard floor (0.75 by default)
        bull_ctx_low_conf = _make_context(
            mfi=56.0,
            adx=25.0,
            close=101000.0,
            mlp_prediction=MLP_LABEL_SELL,
            mlp_confidence=0.65,
        )
        assert strategy.check_exit(bull_ctx_low_conf, position) is None

        # Bull regime + high SELL confidence: exit allowed
        bull_ctx_high_conf = _make_context(
            mfi=56.0,
            adx=25.0,
            close=101000.0,
            mlp_prediction=MLP_LABEL_SELL,
            mlp_confidence=0.8,
        )
        signal = strategy.check_exit(bull_ctx_high_conf, position)
        assert signal is not None
        assert "SELL prediction" in signal.reason
