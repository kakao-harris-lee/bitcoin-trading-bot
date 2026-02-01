"""V35 Simple Exit Strategy - Optimized for letting winners run.

Based on comprehensive backtesting (2020-2026):
- Wider stop loss (8%) to avoid noise stops
- Higher take profit (15-30%) to capture larger moves
- Optional trailing stop for trend riding

Performance: +140% return with SL8/TP30 configuration
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
class V35SimpleExitParams:
    """Parameters for V35 Simple exit strategy.

    Optimized based on 2020-2026 backtesting:
    - Wider stop loss (8%) outperforms tight (2.1%)
    - Higher take profit (15-30%) captures larger moves
    - Trailing stop provides good risk-adjusted returns
    """

    # Stop loss - WIDER than original V35 (2.1%)
    # Backtesting showed 8% optimal for hourly data
    stop_loss_pct: float = 8.0

    # Take profit - HIGHER than original V35 (5%)
    # Let winners run - 15-30% captures more upside
    take_profit_pct: float = 15.0

    # Trailing stop (alternative to fixed TP)
    trailing_enabled: bool = False
    trailing_activation_pct: float = 5.0  # Activate after 5% profit
    trailing_distance_pct: float = 5.0    # Trail 5% below high

    # Exit below EMA200 (trend reversal protection)
    exit_below_ema200: bool = True
    ema200_buffer_pct: float = 2.0  # Exit at EMA200 - 2%

    market: Literal["spot", "futures"] = "spot"


@exit_strategy(params_class=V35SimpleExitParams)
class V35SimpleExitStrategy(BaseExitStrategy):
    """Simplified V35 exit strategy with wider stops.

    Exit conditions (checked in order):
    1. Stop Loss: P&L <= -stop_loss_pct (default 8%)
    2. Take Profit: P&L >= take_profit_pct (default 15%)
    3. Trailing Stop: If enabled, trails at trailing_distance below HWM
    4. EMA200 Exit: If price drops significantly below EMA200

    Key differences from original V35:
    - NO partial exits (simpler, and backtesting showed they hurt)
    - Wider stop loss (8% vs 2.1%)
    - Higher take profit (15% vs 5%)
    - No MACD exit (added complexity, marginal benefit)

    Inherits from BaseExitStrategy for common functionality.
    """

    def __init__(self, params: V35SimpleExitParams | None = None):
        super().__init__()
        self.params = params or V35SimpleExitParams()

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

        # === EXIT 1: Stop Loss ===
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"V35Simple: Stop loss {pnl_pct:.2f}% (limit: -{p.stop_loss_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason)

        # === EXIT 2: Take Profit ===
        if pnl_pct >= p.take_profit_pct:
            reason = f"V35Simple: Take profit {pnl_pct:.2f}% (target: +{p.take_profit_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason)

        # === EXIT 3: Trailing Stop ===
        if p.trailing_enabled:
            hwm_pnl = calculate_hwm_pnl_pct(hwm, entry)
            if hwm_pnl >= p.trailing_activation_pct:
                trail_stop = hwm * (1 - p.trailing_distance_pct / 100)
                if close < trail_stop:
                    locked_pnl = ((trail_stop - entry) / entry) * 100
                    reason = (
                        f"V35Simple: Trailing stop {pnl_pct:.2f}% "
                        f"(HWM={hwm_pnl:.1f}%, locked={locked_pnl:.1f}%)"
                    )
                    logger.info(f"{symbol}: {reason}")
                    self._clear_state(key)
                    return self._create_exit_signal(position, reason)

        # === EXIT 4: EMA200 Breakdown ===
        if p.exit_below_ema200 and market_data.ema_200 > 0:
            ema_exit_level = market_data.ema_200 * (1 - p.ema200_buffer_pct / 100)
            if close < ema_exit_level:
                reason = (
                    f"V35Simple: EMA200 breakdown "
                    f"({close:.0f} < {ema_exit_level:.0f})"
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
