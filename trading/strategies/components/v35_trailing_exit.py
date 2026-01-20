"""V35 Exit Strategy - extracted from V35LongTask.

Implements IExitStrategy protocol for V35 exit logic with:
- Stop loss (wider value based on Optuna optimization)
- Multi-level partial take profit (3 levels based on market state)
- Trailing stop (DISABLED by default per Optuna optimization)
- MACD dead cross exit (exit when in profit and MACD crosses below signal)

Note: Regime change exit is DISABLED - analysis showed it cut profitable trades
short (278 trades forced exit at 14% win rate, -87% total loss).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Position, Signal
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class V35ExitParams:
    """Parameters for V35 exit strategy.

    Defaults aligned with Optuna-optimized config from v35_long.json.
    """

    # Stop loss percentage (negative P&L threshold)
    # Optuna found wider stop loss works better (~2-5%)
    stop_loss_pct: float = 2.1  # -2.1% from v35_long.json

    # Take profit levels for BULL_STRONG (aggressive targets)
    tp_bull_strong_1: float = 5.3   # First TP at +5.3%
    tp_bull_strong_2: float = 10.7  # Second TP at +10.7%
    tp_bull_strong_3: float = 20.1  # Third TP at +20.1%

    # Take profit levels for BULL_MODERATE
    tp_bull_moderate_1: float = 3.2  # First TP at +3.2%
    tp_bull_moderate_2: float = 9.4  # Second TP at +9.4%
    tp_bull_moderate_3: float = 12.2  # Third TP at +12.2%

    # Take profit levels for SIDEWAYS
    tp_sideways_1: float = 1.6  # First TP at +1.6%
    tp_sideways_2: float = 5.4  # Second TP at +5.4%
    tp_sideways_3: float = 6.8  # Third TP at +6.8%

    # Exit fractions for partial exits
    exit_fraction_1: float = 0.35  # Exit 35% at first TP
    exit_fraction_2: float = 0.38  # Exit 38% at second TP
    exit_fraction_3: float = 0.27  # Exit remaining 27% at third TP

    # Trailing stop settings - DISABLED by default per Optuna
    trailing_enabled: bool = False
    trailing_activation: float = 3.0  # Activate at +3% (if enabled)
    trailing_distance: float = 2.0    # Trail by 2% below HWM

    # MACD dead cross exit
    macd_exit_enabled: bool = True
    min_profit_for_macd_exit: float = 1.5  # Min profit % for MACD exit

    # Regime classification for exit (same thresholds as entry)
    mfi_bull: float = 54.0
    mfi_bear: float = 41.0
    adx_trend: float = 18.0

    market: Literal["futures"] = "futures"


@exit_strategy(params_class=V35ExitParams)
class V35TrailingExitStrategy:
    """V35 Exit strategy with partial exits and optional trailing stop.

    Exit conditions (checked in order):
    1. Stop Loss: P&L <= -stop_loss_pct
    2. Partial Take Profits: Multi-level exits based on market state
    3. MACD Dead Cross: Exit when MACD crosses below signal (if in profit)
    4. Trailing Stop: (DISABLED by default) Triggers when price drops
       trailing_distance% below high water mark after activation

    NOTE: Regime change exit is intentionally DISABLED.
    Analysis showed it cut profitable trades short:
    - 278 trades forced exit at 14% win rate
    - -87% total loss from this exit type
    - Trades perform better when allowed to run to TP or MACD exit

    State:
    - high_water_mark: Tracks highest price since position opened
    - partial_exits: Tracks number of partial exits taken (0-2)
    - entry_market_state: Market state when position was opened

    Implements IExitStrategy protocol (structural subtyping).
    """

    def __init__(self, params: V35ExitParams | None = None):
        """Initialize with exit parameters.

        Args:
            params: Exit parameters. Uses defaults if not provided.
        """
        self.params = params or V35ExitParams()
        # Track state per symbol
        self._high_water_mark: dict[str, float] = {}
        self._partial_exits: dict[str, int] = {}
        self._entry_market_state: dict[str, str] = {}
        self._initial_quantity: dict[str, float] = {}

    def check_exit(
        self,
        position: Position,
        market_data: MarketData,
    ) -> Signal | None:
        """Evaluate exit conditions for position.

        Args:
            position: Current open position.
            market_data: Current market state.

        Returns:
            Signal to close position (full or partial), or None to hold.
        """
        symbol = position.symbol
        entry_price = position.entry_price
        quantity = position.quantity
        current_price = market_data.close

        if entry_price <= 0 or quantity <= 0:
            return None

        p = self.params

        # Calculate P&L percentage
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Update high water mark using the HIGH price (true peak)
        check_price = market_data.high if market_data.high > 0 else current_price
        self._update_high_water_mark(symbol, check_price)
        hwm = self._high_water_mark.get(symbol, entry_price)
        hwm_pnl = ((hwm - entry_price) / entry_price) * 100

        # Exit condition 1: Stop loss
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"V35 exit: Stop loss {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(symbol)
            return self._create_exit_signal(position, reason, quantity)

        # Exit condition 2: Partial take profits
        partial_signal = self._check_partial_exit(
            position, market_data, pnl_pct
        )
        if partial_signal:
            return partial_signal

        # Exit condition 3: MACD dead cross (if in profit)
        if p.macd_exit_enabled and pnl_pct >= p.min_profit_for_macd_exit:
            if market_data.macd < market_data.macd_signal:
                reason = f"V35 exit: MACD dead cross {pnl_pct:.2f}%"
                logger.info(f"{symbol}: {reason}")
                self._clear_state(symbol)
                return self._create_exit_signal(position, reason, quantity)

        # Exit condition 4: Trailing stop (if enabled)
        if p.trailing_enabled and hwm_pnl >= p.trailing_activation:
            trailing_stop_price = hwm * (1 - p.trailing_distance / 100)
            if current_price <= trailing_stop_price:
                locked_pnl = ((trailing_stop_price - entry_price) / entry_price) * 100
                reason = f"V35 exit: Trailing stop {locked_pnl:.2f}% (HWM={hwm_pnl:.2f}%)"
                logger.info(f"{symbol}: {reason}")
                self._clear_state(symbol)
                return self._create_exit_signal(
                    position, reason, quantity, trailing_stop_price
                )

        # NOTE: Regime change exit is intentionally DISABLED
        # See class docstring for analysis showing it hurts performance

        return None

    def _check_partial_exit(
        self,
        position: Position,
        market_data: MarketData,
        pnl_pct: float,
    ) -> Signal | None:
        """Check for partial take profit exit.

        Implements 3-level partial exits with market-state-based TP levels.

        Args:
            position: Current position.
            market_data: Current market state.
            pnl_pct: Current P&L percentage.

        Returns:
            Partial exit signal or None.
        """
        symbol = position.symbol
        p = self.params

        # Get current partial exit count
        partial_count = self._partial_exits.get(symbol, 0)
        if partial_count >= 3:
            return None  # All partials taken

        # Get TP levels based on entry market state
        market_state = self._entry_market_state.get(symbol, "SIDEWAYS")
        tp_levels = self._get_tp_levels(market_state)

        # Check if we should take a partial exit
        for level, (tp_pct, fraction) in enumerate(tp_levels):
            if level == partial_count and pnl_pct >= tp_pct:
                self._partial_exits[symbol] = partial_count + 1

                # Calculate exit quantity
                initial_qty = self._initial_quantity.get(symbol, position.quantity)
                exit_qty = initial_qty * fraction

                # Don't exit more than remaining
                exit_qty = min(exit_qty, position.quantity)

                reason = f"V35 exit: TP level {level + 1} ({tp_pct:.1f}%) P&L={pnl_pct:.2f}%"
                logger.info(f"{symbol}: {reason} - exiting {fraction*100:.0f}%")

                # If this is the last partial, clear state
                if partial_count + 1 >= 3:
                    self._clear_state(symbol)

                return self._create_exit_signal(position, reason, exit_qty)

        return None

    def _get_tp_levels(self, market_state: str) -> list[tuple[float, float]]:
        """Get take profit levels based on market state.

        Returns list of (tp_percentage, exit_fraction) tuples.

        Args:
            market_state: Market state when position was opened.

        Returns:
            List of (tp_pct, fraction) for 3 levels.
        """
        p = self.params

        if market_state == "BULL_STRONG":
            return [
                (p.tp_bull_strong_1, p.exit_fraction_1),
                (p.tp_bull_strong_2, p.exit_fraction_2),
                (p.tp_bull_strong_3, p.exit_fraction_3),
            ]
        elif market_state == "BULL_MODERATE":
            return [
                (p.tp_bull_moderate_1, p.exit_fraction_1),
                (p.tp_bull_moderate_2, p.exit_fraction_2),
                (p.tp_bull_moderate_3, p.exit_fraction_3),
            ]
        else:  # SIDEWAYS or other
            return [
                (p.tp_sideways_1, p.exit_fraction_1),
                (p.tp_sideways_2, p.exit_fraction_2),
                (p.tp_sideways_3, p.exit_fraction_3),
            ]

    def on_position_opened(self, position: Position) -> None:
        """Initialize state when position is opened.

        Sets initial high water mark and determines market state for TP levels.

        Args:
            position: The newly opened position.
        """
        symbol = position.symbol
        self._high_water_mark[symbol] = position.entry_price
        self._partial_exits[symbol] = 0
        self._initial_quantity[symbol] = position.quantity

        # Determine market state from position reason if available
        market_state = "SIDEWAYS"  # Default
        reason = position.strategy or ""
        if "BULL_STRONG" in reason or "MOMENTUM_STRONG" in reason:
            market_state = "BULL_STRONG"
        elif "BULL_MODERATE" in reason or "MOMENTUM_MODERATE" in reason:
            market_state = "BULL_MODERATE"
        elif "SIDEWAYS" in reason or "BREAKOUT" in reason or "RANGE" in reason:
            market_state = "SIDEWAYS"

        self._entry_market_state[symbol] = market_state

        logger.debug(
            f"{symbol}: Position opened at {position.entry_price:.2f}, "
            f"market_state={market_state}, HWM initialized"
        )

    def on_position_closed(self, symbol: str) -> None:
        """Clean up state when position is closed.

        Args:
            symbol: The symbol whose position was closed.
        """
        self._clear_state(symbol)
        logger.debug(f"{symbol}: Position closed, state cleared")

    def _update_high_water_mark(self, symbol: str, current_price: float) -> None:
        """Update high water mark if current price is higher.

        Args:
            symbol: Trading symbol.
            current_price: Current market price (or high).
        """
        if symbol not in self._high_water_mark:
            self._high_water_mark[symbol] = current_price
        else:
            old_hwm = self._high_water_mark[symbol]
            new_hwm = max(old_hwm, current_price)
            if new_hwm > old_hwm:
                logger.debug(
                    f"{symbol}: HWM updated {old_hwm:.2f} -> {new_hwm:.2f}"
                )
            self._high_water_mark[symbol] = new_hwm

    def _clear_state(self, symbol: str) -> None:
        """Clear all state for symbol.

        Args:
            symbol: Trading symbol.
        """
        self._high_water_mark.pop(symbol, None)
        self._partial_exits.pop(symbol, None)
        self._entry_market_state.pop(symbol, None)
        self._initial_quantity.pop(symbol, None)

    def _create_exit_signal(
        self,
        position: Position,
        reason: str,
        quantity: float,
        trigger_price: float | None = None,
    ) -> Signal:
        """Create exit signal for position.

        Args:
            position: Position to close.
            reason: Exit reason for logging.
            quantity: Quantity to exit.
            trigger_price: Optional trigger price for trailing stop.

        Returns:
            Signal to close the position.
        """
        return Signal(
            symbol=position.symbol,
            side="sell",
            market=position.market,
            quantity=quantity,
            reason=reason,
            trigger_price=trigger_price,
        )

    @property
    def high_water_mark(self) -> dict[str, float]:
        """Get current high water marks (read-only view)."""
        return self._high_water_mark.copy()

    @property
    def partial_exits(self) -> dict[str, int]:
        """Get current partial exit counts (read-only view)."""
        return self._partial_exits.copy()
