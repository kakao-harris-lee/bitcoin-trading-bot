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

from .base_exit import BaseExitStrategy
from .models import Position, Signal, TradingContext
from .registry import exit_strategy
from trading.utils.pnl import calculate_pnl_pct, calculate_hwm_pnl_pct

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
class V35ClassicExitStrategy(BaseExitStrategy):
    """V35 Classic exit strategy - simple and effective.

    Exit conditions (checked in order):
    1. Stop Loss: P&L <= -stop_loss_pct
    2. Take Profit: P&L >= take_profit_pct
    3. Trailing Stop: Activated after trailing_activation %,
       triggers when price drops trailing_distance % below HWM
    4. Regime Change: Exit on bearish MFI if in profit

    No partial exits. Full position exit only.

    Inherits from BaseExitStrategy for common functionality:
    - High water mark tracking
    - PnL calculations
    - State management
    """

    def __init__(self, params: V35ClassicExitParams | None = None):
        super().__init__()
        self.params = params or V35ClassicExitParams()

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
        entry = position.entry_price

        if entry <= 0:
            return None

        close = market_data.close
        key = self._get_position_key(position)

        # Calculate PnL using utility
        pnl_pct = calculate_pnl_pct(close, entry, "long")

        # Update high water mark using base class method
        hwm = self._update_hwm(key, close, entry)
        hwm_pnl = calculate_hwm_pnl_pct(hwm, entry)

        # === EXIT 1: Stop Loss ===
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"V35Classic: Stop loss {pnl_pct:.2f}% (limit: -{p.stop_loss_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason)

        # === EXIT 2: Take Profit ===
        if pnl_pct >= p.take_profit_pct:
            reason = f"V35Classic: Take profit {pnl_pct:.2f}% (target: +{p.take_profit_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason)

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
                self._clear_state(key)
                return self._create_exit_signal(position, reason)

        # === EXIT 4: Regime Change (Bearish) ===
        if p.regime_exit_enabled and pnl_pct >= p.min_profit_for_regime_exit:
            if market_data.mfi <= p.mfi_bear:
                reason = (
                    f"V35Classic: Regime bearish exit "
                    f"(MFI={market_data.mfi:.1f}, profit={pnl_pct:.2f}%)"
                )
                logger.info(f"{symbol}: {reason}")
                self._clear_state(key)
                return self._create_exit_signal(position, reason)

        return None

    def _create_exit_signal(self, position: Position, reason: str) -> Signal:
        """Create exit signal with correct market from params."""
        return Signal(
            symbol=position.symbol,
            side="sell",
            market=self.params.market,
            quantity=1.0,  # Full exit
            reason=reason,
        )
