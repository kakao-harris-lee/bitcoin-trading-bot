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
from trading.strategies.components.models import MarketData, MarketContext, Position, TradingContext


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
        # V35 requires: BULL regime + MACD crossover + RSI above threshold
        market_data = MarketData(
            symbol="BTC",
            close=95000.0,
            mfi=55.0,  # Above mfi_bull threshold
            adx=25.0,  # Strong trend
            rsi=58.0,  # Above momentum_rsi_bull_strong (57.0)
            timestamp=1000000,
            macd=1.5,  # MACD crossover (above signal)
            macd_signal=1.0,
        )

        # Build context for BULL trend (MFI >= 52)
        context = MarketContext(
            trend="BULL",
            regime="BULL_STRONG",  # MFI=55, ADX=25 -> BULL_STRONG
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )

        signal = entry.check_entry(TradingContext(symbol="BTC", timestamp=1000, market=market_data, regime=context, positions={}))

        assert signal is not None
        assert signal.symbol == "BTC"
        assert signal.side == "buy"
        assert signal.market == "futures"

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

        context = MarketContext(
            trend="BEAR",
            regime="BEAR_STRONG",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )

        signal = exit_strat.check_exit(TradingContext(symbol="BTC", timestamp=1000, market=market_data, regime=context, positions={}), position)

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
        assert market == "futures"  # Default in STRATEGY_REGISTRY


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

        # Build context for NEUTRAL trend (48 < MFI < 52)
        context = MarketContext(
            trend="NEUTRAL",
            regime="SIDEWAYS_FLAT",  # MFI=50, ADX=15 -> SIDEWAYS_FLAT
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=15.0,
        )

        signal = entry.check_entry(TradingContext(symbol="BTC", timestamp=1000, market=market_data, regime=context, positions={}))

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

        # Note: SidewaysExitStrategy not yet updated to TradingContext (Task 8)
        # Using old signature (position, market_data) for now
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

        # Entry signal - V35 requires MACD crossover + RSI above threshold
        market_data = MarketData(
            symbol="SOL",
            close=130.0,
            mfi=55.0,
            adx=25.0,
            rsi=58.0,  # Above momentum_rsi_bull_strong (57.0)
            timestamp=1000000,
            macd=1.5,  # MACD crossover (above signal)
            macd_signal=1.0,
        )

        # Build context for BULL trend (MFI >= 52)
        context = MarketContext(
            trend="BULL",
            regime="BULL_STRONG",  # MFI=55, ADX=25 -> BULL_STRONG
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )

        entry_signal = entry.check_entry(TradingContext(symbol="BTC", timestamp=1000, market=market_data, regime=context, positions={}))
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

        exit_signal = exit_strat.check_exit(TradingContext(symbol="BTC", timestamp=1000, market=exit_market_data, regime=context, positions={}), position)
        assert exit_signal is not None
        assert exit_signal.market == "futures"


class TestParamOverrides:
    """Test param_overrides functionality for MLflow optimization."""

    def test_param_overrides_legacy_format(self, factory):
        """Test param_overrides with legacy config format."""
        entry = factory.create_entry(
            "v35_long",
            param_overrides={"mfi_bull_strong": 56.0, "position_size": 0.03}
        )

        assert entry.params.mfi_bull_strong == 56.0
        assert entry.params.position_size == 0.03

    def test_param_overrides_with_existing_config(self, factory):
        """Test param_overrides merges with existing config."""
        config = {"market": "futures", "position_size": 0.01}
        entry = factory.create_entry(
            "v35_long",
            config,
            param_overrides={"position_size": 0.05}  # Override config value
        )

        assert entry.params.market == "futures"
        assert entry.params.position_size == 0.05  # Override wins

    def test_param_overrides_does_not_mutate_original(self, factory):
        """Test that param_overrides doesn't mutate the original config."""
        original_config = {"position_size": 0.01, "market": "futures"}
        factory.create_entry(
            "v35_long",
            original_config,
            param_overrides={"position_size": 0.05}
        )

        # Original config should be unchanged
        assert original_config["position_size"] == 0.01
        assert original_config["market"] == "futures"

    def test_param_overrides_exit_strategy(self, factory):
        """Test param_overrides works for exit strategy."""
        exit_strat = factory.create_exit(
            "v35_long",
            param_overrides={"stop_loss_pct": 2.5, "tp_bull_strong_1": 6.0}
        )

        assert exit_strat.params.stop_loss_pct == 2.5
        assert exit_strat.params.tp_bull_strong_1 == 6.0

    def test_param_overrides_create_components(self, factory):
        """Test separate entry/exit overrides in create_components."""
        entry, exit_strat = factory.create_components(
            "v35_long",
            entry_overrides={"mfi_bull_strong": 56.0},
            exit_overrides={"stop_loss_pct": 3.0},
        )

        assert entry.params.mfi_bull_strong == 56.0
        assert exit_strat.params.stop_loss_pct == 3.0

    def test_param_overrides_empty_returns_original(self, factory):
        """Test empty param_overrides returns config unchanged."""
        config = {"market": "futures", "position_size": 0.02}
        entry = factory.create_entry("v35_long", config, param_overrides={})

        assert entry.params.market == "futures"
        assert entry.params.position_size == 0.02

    def test_param_overrides_new_config_format(self, factory):
        """Test param_overrides with new config format."""
        config = {
            "market": "futures",
            "entry": {
                "class": "V35EntryStrategy",
                "params": {"mfi_bull_strong": 54.0}
            },
            "exit": {
                "class": "V35TrailingExitStrategy",
                "params": {"stop_loss_pct": 1.5}
            }
        }
        entry = factory.create_entry(
            "custom",
            config,
            param_overrides={"mfi_bull_strong": 58.0}
        )

        # Override should take precedence
        assert entry.params.mfi_bull_strong == 58.0
