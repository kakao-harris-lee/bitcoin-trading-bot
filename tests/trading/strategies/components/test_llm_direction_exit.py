from unittest.mock import MagicMock

from trading.strategies.components.llm_direction_exit import (
    LLMDirectionExitParams,
    LLMDirectionExitStrategy,
)
from trading.strategies.components.llm_hybrid_exit import (
    LLMHybridExitParams,
    LLMHybridExitStrategy,
)
from trading.strategies.components.models import MarketData, Position, Signal, TradingContext, build_market_context


def _ctx(
    *,
    close: float = 100000.0,
    high: float = 101000.0,
    low: float = 0.0,
    mfi: float = 55.0,
    adx: float = 25.0,
    atr: float = 1000.0,
    timestamp: int = 1000,
    ema_200: float = 0.0,
    ema_5: float = 0.0,
    ema_10: float = 0.0,
    ema_20: float = 0.0,
    ema_120: float = 0.0,
    trix: float = 0.0,
    trix_signal: float = 0.0,
) -> TradingContext:
    market = MarketData(
        symbol="BTC",
        close=close,
        high=high,
        low=low,
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
        ema_120=ema_120,
        trix=trix,
        trix_signal=trix_signal,
    )
    regime = build_market_context(mfi=mfi, adx=adx, atr=atr, close=close)
    return TradingContext(symbol="BTC", timestamp=timestamp, market=market, regime=regime, positions={})


def _position(entry_price: float = 100000.0, strategy: str = "llm_direction_btc", entry_time: int | None = None) -> Position:
    return Position(
        symbol="BTC",
        entry_price=entry_price,
        quantity=0.1,
        strategy=strategy,
        market="spot",
        timestamp=1000,
        side="buy",
        entry_time=entry_time,
    )


def test_stop_loss_triggers():
    strategy = LLMDirectionExitStrategy(LLMDirectionExitParams())
    signal = strategy.check_exit(_ctx(close=89000.0), _position())
    assert signal is not None
    assert "LLMDirection exit: Stop loss" in signal.reason


def test_intrabar_stop_ignored_on_entry_candle():
    strategy = LLMDirectionExitStrategy(
        LLMDirectionExitParams(
            stop_loss_pct=2.0,
            fwin_exit_enabled=False,
            intrabar_stop_requires_post_entry_candle=True,
        )
    )
    position = _position(entry_time=2000)
    signal = strategy.check_exit(
        _ctx(close=99000.0, high=100500.0, low=97000.0, timestamp=2000, atr=0.0),
        position,
    )
    assert signal is None


def test_trailing_stop_triggers_after_activation():
    strategy = LLMDirectionExitStrategy(
        LLMDirectionExitParams(
            stop_loss_pct=20.0,
            fwin_exit_enabled=False,
            trailing_enabled=True,
            trailing_activation=5.0,
            trailing_distance=2.0,
        )
    )
    position = _position(entry_price=100000.0)
    strategy.on_position_opened(position)

    assert strategy.check_exit(_ctx(close=108000.0, high=110000.0, low=107000.0, timestamp=1000), position) is None
    signal = strategy.check_exit(_ctx(close=107500.0, high=107500.0, low=107000.0, timestamp=2000), position)
    assert signal is not None
    assert "Trailing stop" in signal.reason


def test_hybrid_exit_prefers_regime_protection():
    strategy = LLMHybridExitStrategy(LLMHybridExitParams())
    regime_signal = Signal(symbol="BTC", side="sell", market="spot", quantity=1.0, reason="bear regime")
    strategy._regime = MagicMock()
    strategy._regime.check_exit.return_value = regime_signal
    strategy._protective = MagicMock()
    strategy._protective.check_exit.return_value = None

    signal = strategy.check_exit(_ctx(), _position())

    assert signal is not None
    assert signal.reason.startswith("LLMHybridExit[regime_protect]")
    strategy._protective.check_exit.assert_not_called()


def test_hybrid_exit_uses_protective_when_regime_none():
    strategy = LLMHybridExitStrategy(LLMHybridExitParams())
    protective_signal = Signal(symbol="BTC", side="sell", market="spot", quantity=1.0, reason="stop loss")
    strategy._regime = MagicMock()
    strategy._regime.check_exit.return_value = None
    strategy._protective = MagicMock()
    strategy._protective.check_exit.return_value = protective_signal

    signal = strategy.check_exit(_ctx(), _position())

    assert signal is not None
    assert signal.reason.startswith("LLMHybridExit[protective]")
