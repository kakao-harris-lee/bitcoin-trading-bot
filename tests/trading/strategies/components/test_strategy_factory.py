# tests/trading/strategies/components/test_strategy_factory.py
"""Tests for strategy factory with futures support."""
import pytest
from trading.strategies.components.strategy_factory import (
    StrategyFactory,
    STRATEGY_REGISTRY,
)
from trading.strategies.components.v35_entry import V35EntryStrategy
from trading.strategies.components.v35_trailing_exit import V35TrailingExitStrategy
from trading.strategies.components.sideways_entry import SidewaysEntryStrategy
from trading.strategies.components.sideways_exit import SidewaysExitStrategy
from trading.strategies.components.models import MarketData, Position


@pytest.fixture
def factory():
    """Create factory instance."""
    return StrategyFactory()


class TestStrategyFactoryBasics:
    """Test basic factory functionality."""

    def test_get_available_strategies(self, factory):
        """Test listing available strategies."""
        strategies = factory.get_available_strategies()
        assert "v35_long" in strategies
        assert "sideways_v2" in strategies
        assert "short_v1" in strategies

    def test_create_entry_unknown_strategy(self, factory):
        """Test error for unknown strategy."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            factory.create_entry("unknown_strategy")

    def test_create_exit_unknown_strategy(self, factory):
        """Test error for unknown exit strategy."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            factory.create_exit("unknown_strategy")


class TestV35LongFutures:
    """Test V35 long strategy with futures market."""

    def test_create_v35_entry_with_futures(self, factory):
        """Test V35 entry created with futures market."""
        config = {"market": "futures", "position_size": 0.02}
        entry = factory.create_entry("v35_long", config)

        assert isinstance(entry, V35EntryStrategy)
        assert entry.params.market == "futures"
        assert entry.params.position_size == 0.02

    def test_create_v35_exit_with_futures(self, factory):
        """Test V35 exit created with futures market."""
        config = {"market": "futures"}
        exit_strat = factory.create_exit("v35_long", config)

        assert isinstance(exit_strat, V35TrailingExitStrategy)
        assert exit_strat.params.market == "futures"

    def test_v35_entry_generates_futures_signal(self, factory):
        """Test V35 entry generates futures signal."""
        config = {"market": "futures", "position_size": 0.01}
        entry = factory.create_entry("v35_long", config)

        # Bullish market data that should trigger entry
        market_data = MarketData(
            symbol="BTC",
            close=95000.0,
            mfi=55.0,  # Above mfi_bull threshold
            adx=25.0,  # Strong trend
            rsi=50.0,
            timestamp=1000000,
        )

        signal = entry.check_entry(market_data)

        assert signal is not None
        assert signal.symbol == "BTC"
        assert signal.side == "buy"
        assert signal.market == "futures"
        assert signal.quantity == 0.01

    def test_v35_exit_generates_futures_signal(self, factory):
        """Test V35 exit generates futures signal."""
        config = {"market": "futures", "stop_loss_pct": 1.5}
        exit_strat = factory.create_exit("v35_long", config)

        # Position in futures market
        position = Position(
            symbol="BTC",
            entry_price=95000.0,
            quantity=0.01,
            strategy="v35_long",
            market="futures",
            timestamp=1000000,
        )

        # Market data triggering stop loss
        market_data = MarketData(
            symbol="BTC",
            close=93000.0,  # Down ~2.1% (below stop loss)
            mfi=45.0,
            adx=25.0,
            rsi=40.0,
            timestamp=1000001,
        )

        signal = exit_strat.check_exit(position, market_data)

        assert signal is not None
        assert signal.symbol == "BTC"
        assert signal.side == "sell"
        assert signal.market == "futures"

    def test_get_market_from_config(self, factory):
        """Test get_market returns config market when specified."""
        config = {"market": "futures"}
        market = factory.get_market("v35_long", config)
        assert market == "futures"

    def test_get_market_default_from_spec(self, factory):
        """Test get_market returns spec default when no config."""
        market = factory.get_market("v35_long")
        assert market == "spot"  # Default in STRATEGY_REGISTRY


class TestSidewaysV2Futures:
    """Test SidewaysV2 strategy with futures market."""

    def test_create_sideways_entry_with_futures(self, factory):
        """Test SidewaysV2 entry created with futures market."""
        config = {"market": "futures", "position_size": 0.015}
        entry = factory.create_entry("sideways_v2", config)

        assert isinstance(entry, SidewaysEntryStrategy)
        assert entry.params.market == "futures"
        assert entry.params.position_size == 0.015

    def test_create_sideways_exit_with_futures(self, factory):
        """Test SidewaysV2 exit created with futures market."""
        config = {"market": "futures", "take_profit_pct": 2.0}
        exit_strat = factory.create_exit("sideways_v2", config)

        assert isinstance(exit_strat, SidewaysExitStrategy)
        assert exit_strat.params.market == "futures"

    def test_sideways_entry_generates_futures_signal(self, factory):
        """Test SidewaysV2 entry generates futures signal on oversold RSI."""
        config = {"market": "futures", "position_size": 0.01, "rsi_oversold": 35.0}
        entry = factory.create_entry("sideways_v2", config)

        # Sideways market with oversold RSI
        market_data = MarketData(
            symbol="ETH",
            close=3200.0,
            mfi=50.0,  # Neutral MFI
            adx=15.0,  # Low trend strength
            rsi=30.0,  # Oversold
            timestamp=1000000,
        )

        signal = entry.check_entry(market_data)

        assert signal is not None
        assert signal.symbol == "ETH"
        assert signal.side == "buy"
        assert signal.market == "futures"

    def test_sideways_exit_generates_futures_signal(self, factory):
        """Test SidewaysV2 exit generates futures signal."""
        config = {"market": "futures", "take_profit_pct": 1.5}
        exit_strat = factory.create_exit("sideways_v2", config)

        # Position in futures
        position = Position(
            symbol="ETH",
            entry_price=3200.0,
            quantity=0.1,
            strategy="sideways_v2",
            market="futures",
            timestamp=1000000,
        )

        # Market data at take profit level
        market_data = MarketData(
            symbol="ETH",
            close=3260.0,  # Up ~1.9% (above take profit)
            mfi=50.0,
            adx=15.0,
            rsi=55.0,
            timestamp=1000001,
        )

        signal = exit_strat.check_exit(position, market_data)

        assert signal is not None
        assert signal.symbol == "ETH"
        assert signal.side == "sell"
        assert signal.market == "futures"


class TestCreateComponents:
    """Test creating both entry and exit components together."""

    def test_create_components_with_futures(self, factory):
        """Test creating both components with futures config."""
        config = {"market": "futures", "position_size": 0.01}
        entry, exit_strat = factory.create_components("v35_long", config)

        assert isinstance(entry, V35EntryStrategy)
        assert isinstance(exit_strat, V35TrailingExitStrategy)
        assert entry.params.market == "futures"
        assert exit_strat.params.market == "futures"

    def test_entry_and_exit_market_consistency(self, factory):
        """Test that entry and exit use consistent market type."""
        config = {"market": "futures", "position_size": 0.01}
        entry, exit_strat = factory.create_components("v35_long", config)

        # Entry signal
        market_data = MarketData(
            symbol="SOL",
            close=130.0,
            mfi=55.0,
            adx=25.0,
            rsi=50.0,
            timestamp=1000000,
        )

        entry_signal = entry.check_entry(market_data)
        assert entry_signal is not None
        assert entry_signal.market == "futures"

        # Position created from entry signal
        position = Position(
            symbol=entry_signal.symbol,
            entry_price=130.0,
            quantity=entry_signal.quantity,
            strategy="v35_long",
            market=entry_signal.market,  # Should be "futures"
            timestamp=1000000,
        )

        # Exit signal should also use futures market
        exit_market_data = MarketData(
            symbol="SOL",
            close=127.0,  # Down ~2.3%
            mfi=45.0,
            adx=25.0,
            rsi=40.0,
            timestamp=1000001,
        )

        exit_signal = exit_strat.check_exit(position, exit_market_data)
        assert exit_signal is not None
        assert exit_signal.market == "futures"
