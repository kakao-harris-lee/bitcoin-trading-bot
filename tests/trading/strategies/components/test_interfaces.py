"""Tests for updated strategy interfaces."""

from typing import Protocol, runtime_checkable
from trading.strategies.components.interfaces import IEntryStrategy, IExitStrategy
from trading.strategies.components.models import TradingContext, MarketData, MarketContext, Position, Signal, build_market_context


def test_entry_strategy_protocol_signature():
    """IEntryStrategy.check_entry accepts TradingContext."""

    class MockEntry:
        def check_entry(self, ctx: TradingContext) -> Signal | None:
            return None

    # Should not raise - MockEntry implements IEntryStrategy
    entry: IEntryStrategy = MockEntry()
    assert entry is not None


def test_exit_strategy_protocol_signature():
    """IExitStrategy.check_exit accepts TradingContext and Position."""

    class MockExit:
        def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
            return None

        def on_position_opened(self, position: Position) -> None:
            pass

        def on_position_closed(self, symbol: str) -> None:
            pass

    # Should not raise - MockExit implements IExitStrategy
    exit_strat: IExitStrategy = MockExit()
    assert exit_strat is not None
