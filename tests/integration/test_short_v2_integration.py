"""Integration test for SHORT_V2 hedge strategy."""
import pandas as pd
import numpy as np
import pytest

from trading.strategy.short_v2 import ShortV2Strategy
from trading.strategy.regime_router import RegimeRouter


def _make_bear_market_df(n: int = 200) -> pd.DataFrame:
    """Create DataFrame simulating bear market conditions.

    Generates data with:
    - Strong downtrend (price declining from 50000 to 35000)
    - EMA30 < EMA100 (bearish crossover)
    - ADX >= 20 (trending market)
    - -DI > +DI (downward momentum)
    """
    rng = np.random.default_rng(123)

    # Strong downtrend
    close = np.linspace(50000, 35000, n) + rng.normal(0, 200, n)
    high = close + rng.uniform(100, 500, n)
    low = close - rng.uniform(100, 500, n)
    open_ = close + rng.normal(0, 100, n)
    volume = rng.integers(1000, 5000, n).astype(float)

    return pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=n, freq="4h"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


class TestShortV2Integration:
    """Integration tests for SHORT_V2 with RegimeRouter."""

    def test_full_hedge_cycle(self):
        """Test complete hedge cycle: entry -> hold -> exit."""
        df = _make_bear_market_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # Simulate BEAR_STRONG regime with long exposure
        long_exposure = 10_000_000  # 10M KRW

        # Find entry point
        entry_signal = None
        entry_idx = None
        for i in range(120, len(df)):
            signal = strategy.generate_signal(
                df, i,
                regime="BEAR_STRONG",
                long_exposure_krw=long_exposure,
            )
            if signal and signal.get("action") == "open_short":
                entry_signal = signal
                entry_idx = i
                break

        assert entry_signal is not None, "Should find entry point in bear market"
        assert entry_signal["metadata"]["long_exposure_krw"] == long_exposure
        assert "HEDGE" in entry_signal["reason"]

        # Simulate regime change exit
        exit_signal = strategy.generate_signal(
            df, len(df) - 1,
            regime="SIDEWAYS_NEUTRAL",
            long_exposure_krw=long_exposure,
        )

        assert exit_signal is not None
        assert exit_signal["action"] == "close_short"
        assert "REGIME_CHANGE" in exit_signal["reason"]

    def test_no_hedge_without_long_exposure(self):
        """Test that hedge doesn't open without long position."""
        df = _make_bear_market_df()
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        # No long exposure
        for i in range(120, len(df)):
            signal = strategy.generate_signal(
                df, i,
                regime="BEAR_STRONG",
                long_exposure_krw=0,  # No long position
            )
            if signal and signal.get("action") == "open_short":
                pytest.fail("Should not enter hedge without long exposure")

    def test_router_integration(self):
        """Test RegimeRouter correctly routes to short_v2."""
        router = RegimeRouter(
            binance_gate_mode="bear_strong_only",
            binance_policy="short_v2",
        )

        # BEAR_STRONG should activate short_v2
        decision = router.decide_from_market_state("BEAR_STRONG")
        assert decision.binance_strategy == "short_v2"

        # BEAR_MODERATE should NOT activate
        decision = router.decide_from_market_state("BEAR_MODERATE")
        assert decision.binance_strategy is None

        # BULL should NOT activate
        decision = router.decide_from_market_state("BULL_STRONG")
        assert decision.binance_strategy is None

    def test_stop_loss_prevents_reentry(self):
        """Test that stop-loss in same regime prevents re-entry."""
        df = _make_bear_market_df(300)
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        long_exposure = 10_000_000

        # Find and simulate entry
        for i in range(120, len(df)):
            signal = strategy.generate_signal(
                df, i,
                regime="BEAR_STRONG",
                long_exposure_krw=long_exposure,
            )
            if signal and signal.get("action") == "open_short":
                break

        # Simulate stop-loss hit by manually setting the flag
        strategy._stopped_out_this_regime = True

        # Try to enter again in same regime
        for i in range(150, len(df)):
            strategy.clear_position()  # Clear any position
            signal = strategy.generate_signal(
                df, i,
                regime="BEAR_STRONG",
                long_exposure_krw=long_exposure,
            )
            if signal and signal.get("action") == "open_short":
                pytest.fail("Should not re-enter after stop-loss in same regime")

    def test_regime_change_resets_stopped_flag(self):
        """Test that regime change resets the stopped-out flag."""
        df = _make_bear_market_df(300)
        strategy = ShortV2Strategy()
        df = strategy.add_indicators(df)

        long_exposure = 10_000_000

        # Simulate being stopped out
        strategy._stopped_out_this_regime = True
        strategy._current_regime = "BEAR_STRONG"

        # Regime changes to SIDEWAYS
        strategy.generate_signal(
            df, 150,
            regime="SIDEWAYS_NEUTRAL",
            long_exposure_krw=long_exposure,
        )

        # Should reset the flag
        assert strategy._stopped_out_this_regime is False

        # Back to BEAR_STRONG - should allow entry again
        for i in range(160, len(df)):
            signal = strategy.generate_signal(
                df, i,
                regime="BEAR_STRONG",
                long_exposure_krw=long_exposure,
            )
            if signal and signal.get("action") == "open_short":
                # Successfully found entry after regime reset
                return

        pytest.fail("Should be able to enter after regime change resets stopped flag")

    def test_position_size_calculation(self):
        """Test position size matches long exposure."""
        strategy = ShortV2Strategy()

        # Test position size calculation
        long_exposure_krw = 10_000_000
        fx_rate = 1400.0  # USD/KRW

        position_size_usdt = strategy.get_position_size(long_exposure_krw, fx_rate)

        expected_usdt = long_exposure_krw / fx_rate
        assert abs(position_size_usdt - expected_usdt) < 0.01

    def test_strategy_config_defaults(self):
        """Test default configuration values."""
        strategy = ShortV2Strategy()

        assert strategy.strategy_config["ema_fast"] == 30
        assert strategy.strategy_config["ema_slow"] == 100
        assert strategy.strategy_config["adx_threshold"] == 20
        assert strategy.strategy_config["leverage"] == 2
        assert strategy.strategy_config["stop_loss_pct"] == 5.0
        assert strategy.strategy_config["take_profit_pct"] is None
