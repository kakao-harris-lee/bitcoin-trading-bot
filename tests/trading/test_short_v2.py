"""
Unit tests for SHORT_V2 Hedge Strategy.

SHORT_V2 is a defensive hedge strategy that:
- Only activates during BEAR_STRONG regime
- Uses EMA 30/100 + ADX >= 20 entry conditions
- Matches long exposure size for hedging
- Exits on regime change or 5% stop-loss
- Uses 2x leverage with no take-profit
- No re-entry after stop-loss in same regime
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock

from trading.strategy.short_v2 import ShortV2Strategy


class TestShortV2Indicators:
    """Test SHORT_V2 indicator calculations."""

    @pytest.fixture
    def strategy(self):
        """Create a ShortV2Strategy instance with mocked config."""
        config = MagicMock()
        return ShortV2Strategy(config=config)

    @pytest.fixture
    def sample_data(self):
        """Create sample OHLCV data for testing."""
        np.random.seed(42)
        n = 150  # More than buffer_size requirement

        # Create trending downward data
        prices = 50000 - np.cumsum(np.random.randn(n) * 100)

        df = pd.DataFrame({
            'open': prices + np.random.randn(n) * 50,
            'high': prices + np.abs(np.random.randn(n) * 100),
            'low': prices - np.abs(np.random.randn(n) * 100),
            'close': prices,
            'volume': np.random.randint(1000, 10000, n),
        })
        df.index = pd.date_range('2024-01-01', periods=n, freq='h')
        return df

    def test_add_indicators_creates_ema_fast(self, strategy, sample_data):
        """EMA fast (30) should be calculated."""
        df = strategy.add_indicators(sample_data)
        assert 'ema_fast' in df.columns
        assert not df['ema_fast'].iloc[-1] == 0

    def test_add_indicators_creates_ema_slow(self, strategy, sample_data):
        """EMA slow (100) should be calculated."""
        df = strategy.add_indicators(sample_data)
        assert 'ema_slow' in df.columns
        assert not df['ema_slow'].iloc[-1] == 0

    def test_add_indicators_creates_adx(self, strategy, sample_data):
        """ADX should be calculated."""
        df = strategy.add_indicators(sample_data)
        assert 'adx' in df.columns
        assert df['adx'].iloc[-1] >= 0

    def test_add_indicators_creates_plus_di(self, strategy, sample_data):
        """Plus DI should be calculated."""
        df = strategy.add_indicators(sample_data)
        assert 'plus_di' in df.columns
        assert df['plus_di'].iloc[-1] >= 0

    def test_add_indicators_creates_minus_di(self, strategy, sample_data):
        """Minus DI should be calculated."""
        df = strategy.add_indicators(sample_data)
        assert 'minus_di' in df.columns
        assert df['minus_di'].iloc[-1] >= 0

    def test_min_buffer_size(self, strategy):
        """Buffer size should be at least 100 for EMA slow."""
        assert strategy._min_buffer_size() >= 100


class TestShortV2EntryConditions:
    """Test SHORT_V2 entry conditions."""

    @pytest.fixture
    def strategy(self):
        """Create a ShortV2Strategy instance."""
        config = MagicMock()
        return ShortV2Strategy(config=config)

    @pytest.fixture
    def bearish_row(self):
        """Create a row with all bearish conditions met."""
        return pd.Series({
            'close': 45000,
            'high': 45500,
            'low': 44500,
            'ema_fast': 45000,  # EMA 30
            'ema_slow': 46000,  # EMA 100 - bearish: fast < slow
            'adx': 25,  # Strong trend >= 20
            'plus_di': 15,
            'minus_di': 30,  # Bearish: minus_di > plus_di
        })

    @pytest.fixture
    def bullish_row(self):
        """Create a row with bullish conditions (no entry)."""
        return pd.Series({
            'close': 45000,
            'high': 45500,
            'low': 44500,
            'ema_fast': 46000,  # EMA 30 > EMA 100 - bullish
            'ema_slow': 45000,
            'adx': 25,
            'plus_di': 30,  # Bullish: plus_di > minus_di
            'minus_di': 15,
        })

    def test_entry_requires_bear_strong_regime(self, strategy, bearish_row):
        """Entry should only occur in BEAR_STRONG regime."""
        # Should NOT enter in other regimes
        df = pd.DataFrame([bearish_row])
        df = strategy.add_indicators(df) if 'adx' not in df.columns else df

        # Test various regimes - should all return None except BEAR_STRONG
        for regime in ['BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS', 'BEAR_MODERATE']:
            signal = strategy.generate_signal(
                df, i=0, regime=regime, long_exposure_krw=1000000
            )
            assert signal is None, f"Should not enter in {regime} regime"

        # Should enter in BEAR_STRONG
        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is not None, "Should enter in BEAR_STRONG regime"
        assert signal['action'] == 'open_short'

    def test_entry_requires_adx_threshold(self, strategy):
        """ADX must be >= 20 for entry."""
        row_weak_adx = pd.Series({
            'close': 45000,
            'high': 45500,
            'low': 44500,
            'ema_fast': 45000,
            'ema_slow': 46000,  # Bearish EMA
            'adx': 15,  # Below threshold
            'plus_di': 15,
            'minus_di': 30,
        })
        df = pd.DataFrame([row_weak_adx])

        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is None, "Should not enter with ADX < 20"

    def test_entry_requires_bearish_ema(self, strategy, bullish_row):
        """EMA fast must be below EMA slow for entry."""
        df = pd.DataFrame([bullish_row])

        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is None, "Should not enter with bullish EMA"

    def test_entry_requires_bearish_di(self, strategy):
        """Minus DI must be > Plus DI for entry."""
        row_bullish_di = pd.Series({
            'close': 45000,
            'high': 45500,
            'low': 44500,
            'ema_fast': 45000,
            'ema_slow': 46000,  # Bearish EMA
            'adx': 25,
            'plus_di': 30,  # Bullish DI
            'minus_di': 15,
        })
        df = pd.DataFrame([row_bullish_di])

        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is None, "Should not enter with bullish DI"

    def test_entry_requires_long_exposure(self, strategy, bearish_row):
        """Entry requires long_exposure_krw > 0 (hedge only when there's exposure)."""
        df = pd.DataFrame([bearish_row])

        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=0
        )
        assert signal is None, "Should not enter without long exposure"

    def test_valid_entry_signal_structure(self, strategy, bearish_row):
        """Valid entry signal should have correct structure."""
        df = pd.DataFrame([bearish_row])

        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )

        assert signal is not None
        assert signal['action'] == 'open_short'
        assert signal['leverage'] == 2  # SHORT_V2 uses 2x leverage
        assert 'stop_loss_pct' in signal
        assert signal['stop_loss_pct'] == 5.0  # 5% stop-loss
        assert 'reason' in signal
        assert 'EMA_BEARISH' in signal['reason'] or 'ADX' in signal['reason']


class TestShortV2ExitConditions:
    """Test SHORT_V2 exit conditions."""

    @pytest.fixture
    def strategy_with_position(self):
        """Create a ShortV2Strategy with an open position."""
        config = MagicMock()
        strategy = ShortV2Strategy(config=config)
        strategy.set_position(entry_price=50000, reason='TEST_ENTRY')
        strategy.stop_loss_price = 52500  # 5% above entry
        return strategy

    def test_exit_on_stop_loss_hit(self, strategy_with_position):
        """Should exit when price hits 5% stop-loss."""
        row = pd.Series({
            'close': 53000,  # Above stop loss
            'high': 53000,
            'low': 51000,
            'ema_fast': 52000,
            'ema_slow': 51000,
            'adx': 25,
            'plus_di': 30,
            'minus_di': 20,
        })
        df = pd.DataFrame([row])

        signal = strategy_with_position.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )

        assert signal is not None
        assert signal['action'] == 'close_short'
        assert 'STOP_LOSS' in signal['reason']

    def test_exit_on_regime_change(self, strategy_with_position):
        """Should exit when regime changes from BEAR_STRONG."""
        row = pd.Series({
            'close': 48000,  # Price OK, no stop loss
            'high': 49000,
            'low': 47000,
            'ema_fast': 48000,
            'ema_slow': 49000,
            'adx': 25,
            'plus_di': 20,
            'minus_di': 30,
        })
        df = pd.DataFrame([row])

        # Test exit on various regime changes
        for regime in ['BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS', 'BEAR_MODERATE']:
            strategy_with_position.in_position = True  # Reset position
            strategy_with_position.entry_price = 50000
            strategy_with_position.stop_loss_price = 52500

            signal = strategy_with_position.generate_signal(
                df, i=0, regime=regime, long_exposure_krw=1000000
            )

            assert signal is not None, f"Should exit on regime change to {regime}"
            assert signal['action'] == 'close_short'
            assert 'REGIME_CHANGE' in signal['reason']

    def test_no_exit_when_in_bear_strong(self, strategy_with_position):
        """Should NOT exit if still in BEAR_STRONG and no stop-loss hit."""
        row = pd.Series({
            'close': 48000,  # Profitable, no stop loss
            'high': 49000,
            'low': 47000,
            'ema_fast': 48000,
            'ema_slow': 49000,
            'adx': 25,
            'plus_di': 20,
            'minus_di': 30,
        })
        df = pd.DataFrame([row])

        signal = strategy_with_position.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )

        # Should return None (hold position)
        assert signal is None, "Should hold position in BEAR_STRONG"


class TestShortV2NoReentry:
    """Test SHORT_V2 no re-entry after stop-loss."""

    @pytest.fixture
    def strategy(self):
        """Create a fresh ShortV2Strategy."""
        config = MagicMock()
        return ShortV2Strategy(config=config)

    @pytest.fixture
    def bearish_row(self):
        """Create a row with all bearish conditions met."""
        return pd.Series({
            'close': 45000,
            'high': 45500,
            'low': 44500,
            'ema_fast': 45000,
            'ema_slow': 46000,
            'adx': 25,
            'plus_di': 15,
            'minus_di': 30,
        })

    def test_no_reentry_after_stop_loss_same_regime(self, strategy, bearish_row):
        """Should NOT re-enter after stop-loss in the same BEAR_STRONG regime."""
        df = pd.DataFrame([bearish_row])

        # First entry
        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is not None and signal['action'] == 'open_short'

        # Simulate position and stop-loss hit
        strategy.set_position(entry_price=45000, reason='TEST')
        strategy.stop_loss_price = 47250  # 5% above
        strategy._stopped_out_this_regime = True
        strategy.clear_position()

        # Try to re-enter - should be blocked
        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is None, "Should not re-enter after stop-loss in same regime"

    def test_reentry_allowed_after_regime_reset(self, strategy, bearish_row):
        """Should allow entry after regime changes and returns to BEAR_STRONG."""
        df = pd.DataFrame([bearish_row])

        # Simulate stopped out state
        strategy._stopped_out_this_regime = True

        # Regime changes to something else
        strategy.on_regime_change('BULL_STRONG')

        # Verify flag is reset
        assert strategy._stopped_out_this_regime is False

        # Now should allow entry
        signal = strategy.generate_signal(
            df, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is not None, "Should allow entry after regime reset"


class TestShortV2PositionSizing:
    """Test SHORT_V2 position sizing (match long exposure)."""

    @pytest.fixture
    def strategy(self):
        """Create a ShortV2Strategy."""
        config = MagicMock()
        return ShortV2Strategy(config=config)

    def test_get_position_size_converts_krw_to_usdt(self, strategy):
        """Position size should match long exposure converted to USDT."""
        long_exposure_krw = 1_000_000  # 1M KRW
        fx_rate = 1400  # 1 USD = 1400 KRW

        position_size = strategy.get_position_size(long_exposure_krw, fx_rate)

        expected_usdt = long_exposure_krw / fx_rate  # ~714 USDT
        assert abs(position_size - expected_usdt) < 0.01

    def test_get_position_size_with_different_fx_rates(self, strategy):
        """Position size should adjust with FX rate changes."""
        long_exposure_krw = 1_000_000

        # Higher FX rate = less USDT
        size_high_fx = strategy.get_position_size(long_exposure_krw, fx_rate=1500)
        size_low_fx = strategy.get_position_size(long_exposure_krw, fx_rate=1300)

        assert size_high_fx < size_low_fx

    def test_get_position_size_zero_exposure(self, strategy):
        """Zero exposure should return zero position size."""
        position_size = strategy.get_position_size(0, fx_rate=1400)
        assert position_size == 0


class TestShortV2DefaultConfig:
    """Test SHORT_V2 default configuration."""

    def test_default_config_values(self):
        """Verify default configuration values match spec."""
        config = MagicMock()
        strategy = ShortV2Strategy(config=config)

        # EMA settings
        assert strategy.strategy_config['ema_fast'] == 30
        assert strategy.strategy_config['ema_slow'] == 100

        # ADX settings
        assert strategy.strategy_config['adx_period'] == 14
        assert strategy.strategy_config['adx_threshold'] == 20

        # Leverage and risk
        assert strategy.strategy_config['leverage'] == 2
        assert strategy.strategy_config['stop_loss_pct'] == 5.0

        # No take-profit for hedge strategy
        assert strategy.strategy_config.get('take_profit_pct') is None


class TestShortV2Integration:
    """Integration tests for SHORT_V2 strategy flow."""

    @pytest.fixture
    def strategy(self):
        """Create a ShortV2Strategy."""
        config = MagicMock()
        return ShortV2Strategy(config=config)

    def test_full_trade_cycle(self, strategy):
        """Test a full trade cycle: entry -> hold -> exit."""
        # Create bearish data
        entry_row = pd.Series({
            'close': 50000,
            'high': 50500,
            'low': 49500,
            'ema_fast': 50000,
            'ema_slow': 51000,
            'adx': 25,
            'plus_di': 15,
            'minus_di': 30,
        })
        df_entry = pd.DataFrame([entry_row])

        # Step 1: Entry
        signal = strategy.generate_signal(
            df_entry, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is not None
        assert signal['action'] == 'open_short'

        # Simulate position
        strategy.set_position(entry_price=50000, reason=signal['reason'])
        strategy.stop_loss_price = 52500

        # Step 2: Hold (price moves in favor, no exit)
        hold_row = pd.Series({
            'close': 48000,  # Profitable
            'high': 49000,
            'low': 47000,
            'ema_fast': 48000,
            'ema_slow': 49000,
            'adx': 28,
            'plus_di': 12,
            'minus_di': 35,
        })
        df_hold = pd.DataFrame([hold_row])

        signal = strategy.generate_signal(
            df_hold, i=0, regime='BEAR_STRONG', long_exposure_krw=1000000
        )
        assert signal is None  # Hold

        # Step 3: Exit on regime change
        signal = strategy.generate_signal(
            df_hold, i=0, regime='SIDEWAYS', long_exposure_krw=1000000
        )
        assert signal is not None
        assert signal['action'] == 'close_short'
        assert 'REGIME_CHANGE' in signal['reason']
