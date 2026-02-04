"""Tests for BaseExitStrategy base class."""

import pytest
from unittest.mock import MagicMock

from trading.strategies.components.base_exit import BaseExitStrategy
from trading.strategies.components.models import Position, Signal, TradingContext


class ConcreteExitStrategy(BaseExitStrategy):
    """Concrete implementation for testing abstract base class."""

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        """Simple implementation that always returns None."""
        return None


class TestBaseExitStrategyInit:
    """Tests for BaseExitStrategy initialization."""

    def test_init_creates_empty_state(self):
        """Strategy initializes with empty state dictionaries."""
        strategy = ConcreteExitStrategy()
        assert strategy._high_water_marks == {}
        assert strategy._exit_stages == {}


class TestPositionKeyManagement:
    """Tests for position key generation."""

    def test_get_position_key_format(self):
        """Position key has correct format."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.symbol = "BTC"
        position.strategy = "v35_classic_wide"

        key = strategy._get_position_key(position)
        assert key == "BTC:v35_classic_wide"

    def test_get_position_key_different_symbols(self):
        """Different symbols produce different keys."""
        strategy = ConcreteExitStrategy()

        btc_pos = MagicMock()
        btc_pos.symbol = "BTC"
        btc_pos.strategy = "test"

        eth_pos = MagicMock()
        eth_pos.symbol = "ETH"
        eth_pos.strategy = "test"

        assert strategy._get_position_key(btc_pos) != strategy._get_position_key(eth_pos)


class TestPnLCalculations:
    """Tests for PnL calculation wrappers."""

    def test_calculate_pnl_long_profit(self):
        """PnL calculation for profitable long position."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.entry_price = 100.0

        pnl = strategy._calculate_pnl(position, 110.0, "long")
        assert pnl == pytest.approx(10.0)  # 10% profit

    def test_calculate_pnl_long_loss(self):
        """PnL calculation for losing long position."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.entry_price = 100.0

        pnl = strategy._calculate_pnl(position, 95.0, "long")
        assert pnl == pytest.approx(-5.0)  # 5% loss

    def test_calculate_pnl_short_profit(self):
        """PnL calculation for profitable short position."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.entry_price = 100.0

        pnl = strategy._calculate_pnl(position, 90.0, "short")
        assert pnl == pytest.approx(10.0)  # 10% profit on short

    def test_calculate_hwm_pnl(self):
        """HWM PnL calculation."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.entry_price = 100.0

        hwm_pnl = strategy._calculate_hwm_pnl(position, 115.0)
        assert hwm_pnl == pytest.approx(15.0)  # 15% at HWM


class TestHighWaterMarkManagement:
    """Tests for HWM tracking."""

    def test_update_hwm_initializes_with_entry_price(self):
        """First update uses entry price as initial HWM."""
        strategy = ConcreteExitStrategy()

        hwm = strategy._update_hwm("BTC:test", 105.0, 100.0)
        # Price (105) > entry (100), so HWM = 105
        assert hwm == 105.0
        assert strategy._high_water_marks["BTC:test"] == 105.0

    def test_update_hwm_increases_when_price_higher(self):
        """HWM increases when price exceeds previous HWM."""
        strategy = ConcreteExitStrategy()
        strategy._high_water_marks["BTC:test"] = 100.0

        hwm = strategy._update_hwm("BTC:test", 110.0, 90.0)
        assert hwm == 110.0
        assert strategy._high_water_marks["BTC:test"] == 110.0

    def test_update_hwm_unchanged_when_price_lower(self):
        """HWM stays unchanged when price is below previous HWM."""
        strategy = ConcreteExitStrategy()
        strategy._high_water_marks["BTC:test"] = 110.0

        hwm = strategy._update_hwm("BTC:test", 105.0, 100.0)
        assert hwm == 110.0  # Unchanged
        assert strategy._high_water_marks["BTC:test"] == 110.0

    def test_get_hwm_returns_stored_value(self):
        """Get HWM returns stored value."""
        strategy = ConcreteExitStrategy()
        strategy._high_water_marks["BTC:test"] = 115.0

        assert strategy._get_hwm("BTC:test") == 115.0

    def test_get_hwm_returns_default_when_missing(self):
        """Get HWM returns default for unknown key."""
        strategy = ConcreteExitStrategy()

        assert strategy._get_hwm("UNKNOWN:test", default=50.0) == 50.0


class TestExitStageManagement:
    """Tests for partial exit stage tracking."""

    def test_get_exit_stage_default_zero(self):
        """Default exit stage is 0."""
        strategy = ConcreteExitStrategy()
        assert strategy._get_exit_stage("BTC:test") == 0

    def test_set_and_get_exit_stage(self):
        """Can set and retrieve exit stage."""
        strategy = ConcreteExitStrategy()

        strategy._set_exit_stage("BTC:test", 1)
        assert strategy._get_exit_stage("BTC:test") == 1

        strategy._set_exit_stage("BTC:test", 2)
        assert strategy._get_exit_stage("BTC:test") == 2

    def test_exit_stages_independent_per_position(self):
        """Exit stages are tracked independently per position."""
        strategy = ConcreteExitStrategy()

        strategy._set_exit_stage("BTC:strategy1", 1)
        strategy._set_exit_stage("ETH:strategy1", 2)

        assert strategy._get_exit_stage("BTC:strategy1") == 1
        assert strategy._get_exit_stage("ETH:strategy1") == 2


class TestSignalCreation:
    """Tests for exit signal creation."""

    def test_create_exit_signal_full_exit(self):
        """Create signal for full position exit."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.symbol = "BTC"
        position.market = "spot"

        signal = strategy._create_exit_signal(position, "Stop loss hit")

        assert signal.symbol == "BTC"
        assert signal.side == "sell"
        assert signal.market == "spot"
        assert signal.quantity == 1.0
        assert signal.reason == "Stop loss hit"

    def test_create_exit_signal_partial_exit(self):
        """Create signal for partial position exit."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.symbol = "BTC"
        position.market = "futures"

        signal = strategy._create_exit_signal(position, "TP1 hit", quantity=0.5)

        assert signal.quantity == 0.5
        assert signal.reason == "TP1 hit"

    def test_create_exit_signal_short_position(self):
        """Create signal for short position exit (buy to cover)."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.symbol = "BTC"
        position.market = "futures"

        signal = strategy._create_exit_signal(position, "Cover short", side="buy")

        assert signal.side == "buy"


class TestStateManagement:
    """Tests for state clearing."""

    def test_clear_state_removes_hwm(self):
        """Clear state removes HWM entry."""
        strategy = ConcreteExitStrategy()
        strategy._high_water_marks["BTC:test"] = 100.0

        strategy._clear_state("BTC:test")

        assert "BTC:test" not in strategy._high_water_marks

    def test_clear_state_removes_exit_stage(self):
        """Clear state removes exit stage entry."""
        strategy = ConcreteExitStrategy()
        strategy._exit_stages["BTC:test"] = 2

        strategy._clear_state("BTC:test")

        assert "BTC:test" not in strategy._exit_stages

    def test_clear_state_handles_missing_key(self):
        """Clear state doesn't error for missing keys."""
        strategy = ConcreteExitStrategy()
        # Should not raise
        strategy._clear_state("NONEXISTENT:test")


class TestLifecycleHooks:
    """Tests for position lifecycle hooks."""

    def test_on_position_opened_initializes_state(self):
        """Opening position initializes all state."""
        strategy = ConcreteExitStrategy()
        position = MagicMock()
        position.symbol = "BTC"
        position.strategy = "v35_classic_wide"
        position.entry_price = 50000.0

        strategy.on_position_opened(position)

        key = "BTC:v35_classic_wide"
        assert strategy._high_water_marks[key] == 50000.0
        assert strategy._exit_stages[key] == 0

    def test_on_position_closed_clears_all_state_for_symbol(self):
        """Closing position clears all state for that symbol."""
        strategy = ConcreteExitStrategy()
        # Set up state for multiple strategies on same symbol
        strategy._high_water_marks["BTC:strategy1"] = 100.0
        strategy._high_water_marks["BTC:strategy2"] = 110.0
        strategy._high_water_marks["ETH:strategy1"] = 50.0
        strategy._exit_stages["BTC:strategy1"] = 1
        strategy._exit_stages["BTC:strategy2"] = 2

        strategy.on_position_closed("BTC")

        # BTC keys should be cleared
        assert "BTC:strategy1" not in strategy._high_water_marks
        assert "BTC:strategy2" not in strategy._high_water_marks
        assert "BTC:strategy1" not in strategy._exit_stages
        assert "BTC:strategy2" not in strategy._exit_stages
        # ETH should be unchanged
        assert strategy._high_water_marks["ETH:strategy1"] == 50.0

    def test_on_position_closed_handles_no_matching_state(self):
        """Closing position with no state doesn't error."""
        strategy = ConcreteExitStrategy()
        # Should not raise
        strategy.on_position_closed("UNKNOWN")


class TestAbstractMethod:
    """Tests for abstract method enforcement."""

    def test_cannot_instantiate_base_class(self):
        """Cannot instantiate abstract base class directly."""
        with pytest.raises(TypeError):
            BaseExitStrategy()

    def test_subclass_must_implement_check_exit(self):
        """Subclass without check_exit cannot be instantiated."""

        class IncompleteStrategy(BaseExitStrategy):
            pass

        with pytest.raises(TypeError):
            IncompleteStrategy()
