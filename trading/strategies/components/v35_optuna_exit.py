"""V35 Optuna Exit Strategy - Original 2026-01-12 optimized parameters.

Based on 500-trial Optuna optimization (cf51e472).
Key findings:
- Wider stop loss (4.9% vs 1.5%)
- Trailing DISABLED (Optuna found it hurts)
- 3-tier partial exits (37.5% + 40.3% + remaining)
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
class V35OptunaExitParams:
    """Parameters from original Optuna optimization (BTC, 500 trials).

    Key insight: Trailing stop was DISABLED in optimized config.
    """

    # Stop loss - WIDER than default (4.9% vs 1.5%)
    stop_loss_pct: float = 4.9

    # Trailing stop - DISABLED by Optuna
    trailing_enabled: bool = False
    trailing_activation: float = 1.7
    trailing_distance: float = 2.3

    # Take profit levels (3-tier) - Bull Strong
    tp_bull_strong_1: float = 5.5
    tp_bull_strong_2: float = 12.5
    tp_bull_strong_3: float = 21.0

    # Take profit levels - Bull Moderate
    tp_bull_moderate_1: float = 3.8
    tp_bull_moderate_2: float = 9.3
    tp_bull_moderate_3: float = 14.9

    # Take profit levels - Sideways
    tp_sideways_1: float = 2.3
    tp_sideways_2: float = 5.1
    tp_sideways_3: float = 9.2

    # Exit fractions for partial exits
    exit_fraction_1: float = 0.375
    exit_fraction_2: float = 0.403

    # MFI for regime detection
    mfi_bull_strong: float = 49.0
    mfi_bull_moderate: float = 42.0
    mfi_sideways: float = 50.0

    market: Literal["spot", "futures"] = "spot"


@exit_strategy(params_class=V35OptunaExitParams)
class V35OptunaExitStrategy(BaseExitStrategy):
    """V35 Optuna exit strategy - original optimized parameters.

    Exit conditions (checked in order):
    1. Stop Loss: P&L <= -4.9%
    2. Take Profit 1: Partial exit (37.5%) at TP1
    3. Take Profit 2: Partial exit (40.3%) at TP2
    4. Take Profit 3: Full exit at TP3

    Key difference from complex V35:
    - NO trailing stop (Optuna found it hurts)
    - WIDER stop loss (4.9% vs 1.5-2.1%)
    - Regime-specific take profit levels

    Inherits from BaseExitStrategy for common functionality.
    """

    def __init__(self, params: V35OptunaExitParams | None = None):
        super().__init__()
        self.params = params or V35OptunaExitParams()

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        """Check exit conditions."""
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

        # Get current exit stage
        stage = self._get_exit_stage(key)

        # Update high water mark
        hwm = self._update_hwm(key, close, entry)

        # Determine current regime for TP levels
        regime = self._classify_regime(market_data.mfi)
        tp1, tp2, tp3 = self._get_tp_levels(regime)

        # === EXIT 1: Stop Loss ===
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"V35Optuna: Stop loss {pnl_pct:.2f}% (limit: -{p.stop_loss_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason, quantity=1.0)

        # === EXIT 2: Take Profit 1 (partial) ===
        if stage == 0 and pnl_pct >= tp1:
            self._set_exit_stage(key, 1)
            reason = f"V35Optuna: TP1 {pnl_pct:.2f}% (target: {tp1:.1f}%), exit {p.exit_fraction_1*100:.0f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason, quantity=p.exit_fraction_1)

        # === EXIT 3: Take Profit 2 (partial) ===
        if stage == 1 and pnl_pct >= tp2:
            self._set_exit_stage(key, 2)
            # Adjust fraction for remaining position
            remaining_after_tp1 = 1.0 - p.exit_fraction_1
            adjusted_fraction = p.exit_fraction_2 / remaining_after_tp1
            reason = f"V35Optuna: TP2 {pnl_pct:.2f}% (target: {tp2:.1f}%), exit {p.exit_fraction_2*100:.0f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason, quantity=adjusted_fraction)

        # === EXIT 4: Take Profit 3 (full) ===
        if stage >= 1 and pnl_pct >= tp3:
            reason = f"V35Optuna: TP3 {pnl_pct:.2f}% (target: {tp3:.1f}%), full exit"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason, quantity=1.0)

        # === EXIT 5: Trailing Stop (if enabled) ===
        if p.trailing_enabled:
            hwm_pnl = calculate_hwm_pnl_pct(hwm, entry)
            if hwm_pnl >= p.trailing_activation:
                trail_stop = hwm * (1 - p.trailing_distance / 100)
                if close < trail_stop:
                    locked_pnl = ((trail_stop - entry) / entry) * 100
                    reason = (
                        f"V35Optuna: Trailing stop {pnl_pct:.2f}% "
                        f"(HWM={hwm_pnl:.1f}%, locked={locked_pnl:.1f}%)"
                    )
                    logger.info(f"{symbol}: {reason}")
                    self._clear_state(key)
                    return self._create_exit_signal(position, reason, quantity=1.0)

        return None

    def _classify_regime(self, mfi: float) -> str:
        """Simple regime classification for TP level selection."""
        p = self.params
        if mfi >= p.mfi_bull_strong:
            return "BULL_STRONG"
        elif mfi >= p.mfi_bull_moderate:
            return "BULL_MODERATE"
        elif mfi >= p.mfi_sideways:
            return "SIDEWAYS"
        else:
            return "BEAR"

    def _get_tp_levels(self, regime: str) -> tuple[float, float, float]:
        """Get take profit levels for regime."""
        p = self.params
        if regime == "BULL_STRONG":
            return p.tp_bull_strong_1, p.tp_bull_strong_2, p.tp_bull_strong_3
        elif regime == "BULL_MODERATE":
            return p.tp_bull_moderate_1, p.tp_bull_moderate_2, p.tp_bull_moderate_3
        else:  # SIDEWAYS or BEAR
            return p.tp_sideways_1, p.tp_sideways_2, p.tp_sideways_3

    def _create_exit_signal(self, position: Position, reason: str, quantity: float) -> Signal:
        """Create exit signal with correct market from params."""
        return Signal(
            symbol=position.symbol,
            side="sell",
            market=self.params.market,
            quantity=quantity,
            reason=reason,
        )
