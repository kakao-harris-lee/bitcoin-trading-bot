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

from .base_exit import BaseExitStrategy
from .models import MarketData, Position, Signal, TradingContext
from .registry import exit_strategy
from trading.utils.pnl import calculate_pnl_pct, calculate_hwm_pnl_pct

logger = logging.getLogger(__name__)


@dataclass
class V35ExitParams:
    """Parameters for V35 exit strategy.

    Defaults aligned with allocation.json tuned_v35_long_v2_core_overlay_v2 baseline.
    """

    # Stop loss percentage (negative P&L threshold)
    # Optuna found wider stop loss works better (~2-5%)
    stop_loss_pct: float = 2.1  # -2.1% baseline (allocation defaults)

    # ATR-based dynamic stop loss (adapts to volatility)
    # High volatility = wider stop (avoid noise), Low volatility = tighter stop
    atr_stop_enabled: bool = False  # Enable ATR-based stop loss
    atr_stop_multiplier: float = 2.0  # Stop at entry - (ATR * multiplier)
    atr_stop_min_pct: float = 1.5  # Minimum stop loss % (floor)
    atr_stop_max_pct: float = 4.0  # Maximum stop loss % (ceiling)

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

    # Regime change exit (optional, disabled in V35TrailingExitStrategy)
    # Minimum profit required to trigger regime-based exit
    # Prevents exiting on small profits during volatile regime swings
    min_profit_for_regime_exit: float = 5.0  # Only exit on regime change if P&L >= 5%

    # Regime classification for exit (same thresholds as entry)
    mfi_bull: float = 54.0
    mfi_bear: float = 41.0
    adx_trend: float = 18.0

    market: Literal["spot", "futures"] = "spot"


@exit_strategy(params_class=V35ExitParams)
class V35TrailingExitStrategy(BaseExitStrategy):
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

    State (inherited from BaseExitStrategy):
    - _high_water_marks: Tracks highest price since position opened
    - _exit_stages: Tracks partial exit stage (maps to _partial_exits)

    Additional state:
    - _entry_market_state: Market state when position was opened
    - _initial_quantity: Original position quantity for partial exit calculation

    Inherits from BaseExitStrategy for common functionality.
    """

    def __init__(self, params: V35ExitParams | None = None):
        """Initialize with exit parameters.

        Args:
            params: Exit parameters. Uses defaults if not provided.
        """
        super().__init__()
        self.params = params or V35ExitParams()
        # Additional state not provided by base class
        self._entry_market_state: dict[str, str] = {}
        self._initial_quantity: dict[str, float] = {}

    def check_exit(
        self,
        ctx: TradingContext,
        position: Position,
    ) -> Signal | None:
        """Evaluate exit conditions for position.

        Args:
            ctx: Trading context with market data and regime.
            position: Current open position.

        Returns:
            Signal to close position (full or partial), or None to hold.
        """
        market_data = ctx.market
        key = self._get_position_key(position)
        symbol = position.symbol
        entry_price = position.entry_price
        quantity = position.quantity
        current_price = market_data.close

        if entry_price <= 0 or quantity <= 0:
            return None

        p = self.params

        # Calculate P&L percentage using utility
        pnl_pct = calculate_pnl_pct(current_price, entry_price, "long")

        # Update high water mark using the HIGH price (true peak)
        check_price = market_data.high if market_data.high > 0 else current_price
        hwm = self._update_hwm(key, check_price, entry_price)
        hwm_pnl = calculate_hwm_pnl_pct(hwm, entry_price)

        # Exit condition 1: Stop loss (fixed or ATR-based)
        if p.atr_stop_enabled and market_data.atr > 0 and entry_price > 0:
            # ATR-based dynamic stop loss
            # High volatility = wider stop, Low volatility = tighter stop
            atr_pct = (market_data.atr / entry_price) * 100
            dynamic_stop_pct = p.atr_stop_multiplier * atr_pct
            # Clamp to min/max bounds
            effective_stop_pct = max(p.atr_stop_min_pct, min(p.atr_stop_max_pct, dynamic_stop_pct))
        else:
            effective_stop_pct = p.stop_loss_pct

        if pnl_pct <= -effective_stop_pct:
            reason = f"V35 exit: Stop loss {pnl_pct:.2f}% (limit: -{effective_stop_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_all_state(key)
            return self._create_exit_signal(position, reason)

        # Exit condition 2: Partial take profits
        partial_signal = self._check_partial_exit(position, market_data, pnl_pct, key)
        if partial_signal:
            return partial_signal

        # Exit condition 3: MACD dead cross (if in profit)
        if p.macd_exit_enabled and pnl_pct >= p.min_profit_for_macd_exit:
            if market_data.macd < market_data.macd_signal:
                reason = f"V35 exit: MACD dead cross {pnl_pct:.2f}%"
                logger.info(f"{symbol}: {reason}")
                self._clear_all_state(key)
                return self._create_exit_signal(position, reason)

        # Exit condition 4: Trailing stop (if enabled)
        if p.trailing_enabled and hwm_pnl >= p.trailing_activation:
            trailing_stop_price = hwm * (1 - p.trailing_distance / 100)
            if current_price <= trailing_stop_price:
                locked_pnl = ((trailing_stop_price - entry_price) / entry_price) * 100
                reason = f"V35 exit: Trailing stop {locked_pnl:.2f}% (HWM={hwm_pnl:.2f}%)"
                logger.info(f"{symbol}: {reason}")
                self._clear_all_state(key)
                return self._create_exit_signal(position, reason)

        # NOTE: Regime change exit is intentionally DISABLED
        # See class docstring for analysis showing it hurts performance

        return None

    def _check_partial_exit(
        self,
        position: Position,
        market_data: MarketData,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        """Check for partial take profit exit.

        Implements 3-level partial exits with market-state-based TP levels.

        Args:
            position: Current position.
            market_data: Current market state.
            pnl_pct: Current P&L percentage.
            key: Position key for state tracking.

        Returns:
            Partial exit signal or None.
        """
        symbol = position.symbol
        p = self.params

        # Get current partial exit count (using base class exit_stages)
        partial_count = self._get_exit_stage(key)
        if partial_count >= 3:
            return None  # All partials taken

        # Get TP levels based on entry market state
        market_state = self._entry_market_state.get(key, "SIDEWAYS")
        tp_levels = self._get_tp_levels(market_state)

        # Check if we should take a partial exit
        for level, (tp_pct, fraction) in enumerate(tp_levels):
            if level == partial_count and pnl_pct >= tp_pct:
                self._set_exit_stage(key, partial_count + 1)

                # Calculate exit quantity
                initial_qty = self._initial_quantity.get(key, position.quantity)
                exit_qty = initial_qty * fraction

                # Don't exit more than remaining
                exit_qty = min(exit_qty, position.quantity)

                reason = f"V35 exit: TP level {level + 1} ({tp_pct:.1f}%) P&L={pnl_pct:.2f}%"
                logger.info(f"{symbol}: {reason} - exiting {fraction*100:.0f}%")

                # If this is the last partial, clear state
                if partial_count + 1 >= 3:
                    self._clear_all_state(key)

                return self._create_exit_signal(position, reason, quantity=exit_qty)

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

    def _clear_all_state(self, key: str) -> None:
        """Clear all state for a position including V35-specific state.

        Args:
            key: Position key to clear.
        """
        # Clear base class state
        self._clear_state(key)
        # Clear V35-specific state
        self._entry_market_state.pop(key, None)
        self._initial_quantity.pop(key, None)

    def on_position_opened(self, position: Position) -> None:
        """Initialize state when position is opened.

        Sets initial high water mark and determines market state for TP levels.

        Args:
            position: The newly opened position.
        """
        # Initialize base class state
        super().on_position_opened(position)

        key = self._get_position_key(position)
        self._initial_quantity[key] = position.quantity

        # Determine market state from position reason if available
        market_state = "SIDEWAYS"  # Default
        reason = position.strategy or ""
        if "BULL_STRONG" in reason or "MOMENTUM_STRONG" in reason:
            market_state = "BULL_STRONG"
        elif "BULL_MODERATE" in reason or "MOMENTUM_MODERATE" in reason:
            market_state = "BULL_MODERATE"
        elif "SIDEWAYS" in reason or "BREAKOUT" in reason or "RANGE" in reason:
            market_state = "SIDEWAYS"

        self._entry_market_state[key] = market_state

        logger.debug(
            f"{position.symbol}: Position opened at {position.entry_price:.2f}, "
            f"market_state={market_state}, HWM initialized"
        )

    def on_position_closed(self, symbol: str) -> None:
        """Clean up state when position is closed.

        Args:
            symbol: The symbol whose position was closed.
        """
        # Clear V35-specific state for all matching keys
        keys_to_clear = [k for k in self._entry_market_state if k.startswith(f"{symbol}:")]
        for k in keys_to_clear:
            self._entry_market_state.pop(k, None)
            self._initial_quantity.pop(k, None)

        # Clear base class state
        super().on_position_closed(symbol)

        logger.debug(f"{symbol}: Position closed, state cleared")

    @property
    def high_water_mark(self) -> dict[str, float]:
        """Get current high water marks (read-only view)."""
        return self._high_water_marks.copy()

    @property
    def partial_exits(self) -> dict[str, int]:
        """Get current partial exit counts (read-only view)."""
        return self._exit_stages.copy()
