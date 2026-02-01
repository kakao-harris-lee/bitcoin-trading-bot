"""Hybrid LSTM Exit Strategy - Trailing stop with RF-aware adjustments.

Uses trailing stop loss with optional RF confidence-based adjustments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Position, Signal, TradingContext
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class HybridLSTMExitParams:
    """Parameters for Hybrid LSTM exit strategy."""

    # Stop loss
    stop_loss_pct: float = 3.0  # Initial stop loss percentage

    # Trailing stop
    trailing_enabled: bool = True
    trailing_activation_pct: float = 2.0  # Activate trailing after 2% profit
    trailing_distance_pct: float = 1.5  # Trail by 1.5%

    # Take profit levels
    take_profit_1_pct: float = 5.0  # First TP at 5%
    take_profit_2_pct: float = 10.0  # Second TP at 10%
    take_profit_3_pct: float = 20.0  # Third TP at 20%

    # Exit fractions
    exit_fraction_1: float = 0.3  # Exit 30% at TP1
    exit_fraction_2: float = 0.3  # Exit 30% at TP2
    exit_fraction_3: float = 0.4  # Exit remaining at TP3

    # RF-aware exits
    exit_on_low_confidence: bool = False  # Exit when RF confidence drops
    low_confidence_threshold: float = 0.40  # Exit if confidence < 40%
    min_profit_for_confidence_exit: float = 1.0  # Only exit if profit >= 1%

    market: Literal["spot", "futures"] = "spot"


@exit_strategy(params_class=HybridLSTMExitParams)
class HybridLSTMExitStrategy:
    """Exit strategy with trailing stop and RF-aware adjustments.

    Exit conditions:
    1. Stop loss hit (price < entry * (1 - stop_loss_pct))
    2. Trailing stop hit (price < HWM * (1 - trailing_distance))
    3. Take profit levels (partial exits)
    4. Low RF confidence (optional, if profitable)
    """

    def __init__(self, params: HybridLSTMExitParams | None = None):
        self.params = params or HybridLSTMExitParams()
        self._high_water_marks: dict[str, float] = {}
        self._tp1_hit: dict[str, bool] = {}
        self._tp2_hit: dict[str, bool] = {}

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        """Check exit conditions.

        Args:
            ctx: Trading context with market data and regime info.
            position: Current position to evaluate.

        Returns:
            Signal if exit conditions met, None otherwise.
        """
        market_data = ctx.market
        context = ctx.regime
        p = self.params
        symbol = position.symbol
        key = f"{symbol}:{position.strategy}"

        close = market_data.close
        entry = position.entry_price

        if entry <= 0:
            return None

        # Calculate PnL percentage
        is_long = position.side == "long" or position.side == "buy"
        if is_long:
            pnl_pct = ((close - entry) / entry) * 100
        else:
            pnl_pct = ((entry - close) / entry) * 100

        # Update high water mark
        hwm = self._high_water_marks.get(key, entry)
        if is_long:
            hwm = max(hwm, close)
        else:
            hwm = min(hwm, close)
        self._high_water_marks[key] = hwm

        # === EXIT 1: Stop Loss ===
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"Stop loss: {pnl_pct:.2f}% <= -{p.stop_loss_pct:.1f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(symbol, 1.0, reason)

        # === EXIT 2: Trailing Stop ===
        if p.trailing_enabled and pnl_pct >= p.trailing_activation_pct:
            if is_long:
                trail_stop = hwm * (1 - p.trailing_distance_pct / 100)
                if close < trail_stop:
                    reason = (
                        f"Trailing stop: close={close:.0f} < trail={trail_stop:.0f} "
                        f"(HWM={hwm:.0f}, trail={p.trailing_distance_pct:.1f}%)"
                    )
                    logger.info(f"{symbol}: {reason}")
                    return self._create_exit_signal(symbol, 1.0, reason)
            else:
                trail_stop = hwm * (1 + p.trailing_distance_pct / 100)
                if close > trail_stop:
                    reason = f"Trailing stop (short): close={close:.0f} > trail={trail_stop:.0f}"
                    logger.info(f"{symbol}: {reason}")
                    return self._create_exit_signal(symbol, 1.0, reason)

        # === EXIT 3: Take Profit Levels ===
        tp1_hit = self._tp1_hit.get(key, False)
        tp2_hit = self._tp2_hit.get(key, False)

        if not tp1_hit and pnl_pct >= p.take_profit_1_pct:
            self._tp1_hit[key] = True
            reason = f"TP1: {pnl_pct:.2f}% >= {p.take_profit_1_pct:.1f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(symbol, p.exit_fraction_1, reason)

        if not tp2_hit and pnl_pct >= p.take_profit_2_pct:
            self._tp2_hit[key] = True
            reason = f"TP2: {pnl_pct:.2f}% >= {p.take_profit_2_pct:.1f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(symbol, p.exit_fraction_2, reason)

        if pnl_pct >= p.take_profit_3_pct:
            reason = f"TP3 (full exit): {pnl_pct:.2f}% >= {p.take_profit_3_pct:.1f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(symbol, 1.0, reason)

        # === EXIT 4: Low RF Confidence (optional) ===
        if p.exit_on_low_confidence and pnl_pct >= p.min_profit_for_confidence_exit:
            rf_conf = context.rf_confidence
            if rf_conf > 0 and rf_conf < p.low_confidence_threshold:
                reason = (
                    f"Low RF confidence exit: conf={rf_conf:.2f} < {p.low_confidence_threshold:.2f}, "
                    f"pnl={pnl_pct:.2f}%"
                )
                logger.info(f"{symbol}: {reason}")
                return self._create_exit_signal(symbol, 1.0, reason)

        return None

    def _create_exit_signal(self, symbol: str, fraction: float, reason: str) -> Signal:
        """Create exit signal."""
        return Signal(
            symbol=symbol,
            side="sell",
            market=self.params.market,
            quantity=fraction,
            reason=reason,
        )

    def on_position_opened(self, position: Position) -> None:
        """Called when a new position is opened."""
        key = f"{position.symbol}:{position.strategy}"
        self._high_water_marks[key] = position.entry_price
        self._tp1_hit[key] = False
        self._tp2_hit[key] = False

    def on_position_closed(self, symbol: str) -> None:
        """Called when a position is closed."""
        # Clean up state for all strategies for this symbol
        keys_to_remove = [k for k in self._high_water_marks if k.startswith(f"{symbol}:")]
        for k in keys_to_remove:
            self._high_water_marks.pop(k, None)
            self._tp1_hit.pop(k, None)
            self._tp2_hit.pop(k, None)
