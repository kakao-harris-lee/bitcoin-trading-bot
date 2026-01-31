"""V35 Classic Exit Strategy - Original simple approach.

Restored from initial implementation (c96dad8f) with wider stops.
Exit logic: Stop loss, Take profit, Trailing stop, Regime change.
No partial exits, no MACD, no complex conditions.

Philosophy: Simple exit rules with room to breathe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Position, Signal, TradingContext
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class V35ClassicExitParams:
    """Parameters for V35 Classic exit strategy.

    Defaults optimized based on backtesting:
    - Wider stop loss (5%) to avoid noise stops
    - Higher take profit (10%) to capture larger moves
    - Trailing stop for trend riding
    """

    # Stop loss - wider than original 1.5%
    stop_loss_pct: float = 5.0

    # Take profit - higher than original 3%
    take_profit_pct: float = 10.0

    # Trailing stop settings
    trailing_enabled: bool = True
    trailing_activation: float = 3.0  # Activate after 3% gain
    trailing_distance: float = 2.0    # Trail 2% below high water mark

    # Regime change exit (exit on bearish if in profit)
    regime_exit_enabled: bool = True
    min_profit_for_regime_exit: float = 1.0  # Min profit % to exit on regime change

    # MFI threshold for bearish detection
    mfi_bear: float = 48.0

    market: Literal["spot", "futures"] = "spot"


@exit_strategy(params_class=V35ClassicExitParams)
class V35ClassicExitStrategy:
    """V35 Classic exit strategy - simple and effective.

    Exit conditions (checked in order):
    1. Stop Loss: P&L <= -stop_loss_pct
    2. Take Profit: P&L >= take_profit_pct
    3. Trailing Stop: Activated after trailing_activation %,
       triggers when price drops trailing_distance % below HWM
    4. Regime Change: Exit on bearish MFI if in profit

    No partial exits. Full position exit only.
    """

    def __init__(self, params: V35ClassicExitParams | None = None):
        self.params = params or V35ClassicExitParams()
        self._high_water_marks: dict[str, float] = {}

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        """Check exit conditions.

        Args:
            ctx: Trading context with market data.
            position: Current position to evaluate.

        Returns:
            Signal if exit conditions met, None otherwise.
        """
        market_data = ctx.market
        p = self.params
        symbol = position.symbol

        close = market_data.close
        entry = position.entry_price

        if entry <= 0:
            return None

        # Calculate PnL percentage
        pnl_pct = ((close - entry) / entry) * 100

        # Update high water mark
        key = f"{symbol}:{position.strategy}"
        hwm = self._high_water_marks.get(key, entry)
        if close > hwm:
            hwm = close
            self._high_water_marks[key] = hwm

        hwm_pnl = ((hwm - entry) / entry) * 100

        # === EXIT 1: Stop Loss ===
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"V35Classic: Stop loss {pnl_pct:.2f}% (limit: -{p.stop_loss_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(symbol, position.strategy)
            return self._create_exit_signal(symbol, reason)

        # === EXIT 2: Take Profit ===
        if pnl_pct >= p.take_profit_pct:
            reason = f"V35Classic: Take profit {pnl_pct:.2f}% (target: +{p.take_profit_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(symbol, position.strategy)
            return self._create_exit_signal(symbol, reason)

        # === EXIT 3: Trailing Stop ===
        if p.trailing_enabled and hwm_pnl >= p.trailing_activation:
            trail_stop = hwm * (1 - p.trailing_distance / 100)
            if close < trail_stop:
                locked_pnl = ((trail_stop - entry) / entry) * 100
                reason = (
                    f"V35Classic: Trailing stop {pnl_pct:.2f}% "
                    f"(HWM={hwm_pnl:.1f}%, locked={locked_pnl:.1f}%)"
                )
                logger.info(f"{symbol}: {reason}")
                self._clear_state(symbol, position.strategy)
                return self._create_exit_signal(symbol, reason)

        # === EXIT 4: Regime Change (Bearish) ===
        if p.regime_exit_enabled and pnl_pct >= p.min_profit_for_regime_exit:
            if market_data.mfi <= p.mfi_bear:
                reason = (
                    f"V35Classic: Regime bearish exit "
                    f"(MFI={market_data.mfi:.1f}, profit={pnl_pct:.2f}%)"
                )
                logger.info(f"{symbol}: {reason}")
                self._clear_state(symbol, position.strategy)
                return self._create_exit_signal(symbol, reason)

        return None

    def _create_exit_signal(self, symbol: str, reason: str) -> Signal:
        """Create exit signal."""
        return Signal(
            symbol=symbol,
            side="sell",
            market=self.params.market,
            quantity=1.0,  # Full exit
            reason=reason,
        )

    def _clear_state(self, symbol: str, strategy: str) -> None:
        """Clear state for position."""
        key = f"{symbol}:{strategy}"
        self._high_water_marks.pop(key, None)

    def on_position_opened(self, position: Position) -> None:
        """Called when a new position is opened."""
        key = f"{position.symbol}:{position.strategy}"
        self._high_water_marks[key] = position.entry_price

    def on_position_closed(self, symbol: str) -> None:
        """Called when a position is closed."""
        keys_to_remove = [k for k in self._high_water_marks if k.startswith(f"{symbol}:")]
        for k in keys_to_remove:
            self._high_water_marks.pop(k, None)
