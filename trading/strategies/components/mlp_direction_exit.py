"""MLP Direction Exit Strategy - Exit logic for MLPDirectionClassifier.

Implements exit strategy based on Parente & Rizzuti (2025) methodology:
- 10% fixed stop loss (as specified in the paper)
- Optional exit on MLP SELL prediction
- Optional trailing stop for profit protection

Reference: docs/plans/2026-02-01-mlp-direction-strategy-design.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from .base_exit import BaseExitStrategy
from .models import MarketData, Position, Signal, TradingContext
from .registry import exit_strategy
from trading.utils.pnl import calculate_pnl_pct, calculate_hwm_pnl_pct

logger = logging.getLogger(__name__)

# Default model path
DEFAULT_MODEL_PATH = "models/mlp_direction/model_final.pt"


@dataclass
class MLPDirectionExitParams:
    """Parameters for MLP Direction exit strategy.

    Based on Parente & Rizzuti (2025) - 10% fixed stop loss.
    """

    # Stop loss percentage (paper uses 10%)
    stop_loss_pct: float = 10.0

    # Forward Window exit (paper's approach: exit after FWin periods)
    # This creates many short-term trades like in the paper's Table 3
    fwin_exit_enabled: bool = True  # Exit after forward window periods
    fwin_periods: int = 2  # Number of candles to hold (default: 2 = 8 hours for 4H)

    # ATR-based dynamic stop loss (optional, disabled by default)
    atr_stop_enabled: bool = False
    atr_stop_multiplier: float = 3.0  # Stop at entry - (ATR * multiplier)
    atr_stop_min_pct: float = 5.0  # Minimum stop loss % (floor)
    atr_stop_max_pct: float = 15.0  # Maximum stop loss % (ceiling)

    # Trailing stop settings (NOT in paper - disabled by default)
    trailing_enabled: bool = False  # Paper does NOT use trailing stop
    trailing_activation: float = 10.0  # Activate trailing at +10%
    trailing_distance: float = 5.0  # Trail by 5% below HWM

    # MLP SELL prediction exit (NOT in paper - disabled by default)
    use_mlp_sell_exit: bool = False  # Paper does NOT use MLP SELL exit
    sell_confidence_threshold: float = 0.50  # Confidence threshold for SELL exit
    min_profit_for_sell_exit: float = 0.0  # Min profit for SELL exit

    # Take profit levels (NOT in paper - disabled by default)
    take_profit_enabled: bool = False  # Paper does NOT use take profit
    take_profit_pct: float = 25.0  # Exit at +25% profit

    market: Literal["spot", "futures"] = "spot"

    # Model path (for MLP SELL exit)
    model_path: str = DEFAULT_MODEL_PATH


@exit_strategy(params_class=MLPDirectionExitParams)
class MLPDirectionExitStrategy(BaseExitStrategy):
    """Exit strategy for MLP Direction classifier.

    Based on Parente & Rizzuti (2025) methodology:
    - 10% fixed stop loss as default
    - Forward Window (FWin) exit: Exit after FWin periods (paper default)
    - Optional trailing stop for profit protection
    - Optional exit on MLP SELL prediction

    Exit conditions (checked in order):
    1. Stop Loss: P&L <= -stop_loss_pct (10% default)
    2. FWin Exit: Exit after fwin_periods candles (paper methodology)
    3. Take Profit: P&L >= take_profit_pct (if enabled)
    4. MLP SELL: Exit when MLP predicts SELL with high confidence (if enabled)
    5. Trailing Stop: Triggers when price drops trailing_distance% below HWM

    Inherits from BaseExitStrategy for common functionality.
    """

    # Label constants
    LABEL_HOLD = 0
    LABEL_BUY = 1
    LABEL_SELL = 2

    def __init__(self, params: MLPDirectionExitParams | None = None):
        """Initialize with exit parameters.

        Args:
            params: Exit parameters. Uses defaults if not provided.
        """
        super().__init__()
        self.params = params or MLPDirectionExitParams()
        self._model = None
        self._model_available: bool | None = None
        self._feature_extractor = None
        # Track entry timestamps for FWin exit (paper methodology)
        self._entry_timestamps: dict[str, int] = {}

    def _ensure_model(self) -> bool:
        """Lazy-load MLP model on first use (for SELL exit)."""
        if not self.params.use_mlp_sell_exit:
            return False

        if self._model_available is not None:
            return self._model_available

        try:
            from mlp_trainer.src.mlp_model import MLPDirectionClassifier
            from trading.indicators.mlp_features import extract_single_features

            model_path = Path(self.params.model_path)
            if not model_path.exists():
                logger.warning(f"MLPDirectionExit: Model not found at {model_path}")
                self._model_available = False
                return False

            self._model = MLPDirectionClassifier.load(str(model_path), device="cpu")
            self._model.eval()
            self._feature_extractor = extract_single_features
            self._model_available = True
            logger.info(f"MLPDirectionExit: Model loaded from {model_path}")

        except Exception as e:
            logger.error(f"MLPDirectionExit: Failed to load model: {e}")
            self._model_available = False

        return self._model_available

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
            Signal to close position, or None to hold.
        """
        market_data = ctx.market
        key = self._get_position_key(position)
        symbol = position.symbol
        entry_price = position.entry_price
        current_price = market_data.close

        if entry_price <= 0 or position.quantity <= 0:
            return None

        p = self.params

        # Calculate P&L percentage
        pnl_pct = calculate_pnl_pct(current_price, entry_price, "long")

        # Update high water mark using the HIGH price (true peak)
        check_price = market_data.high if market_data.high > 0 else current_price
        hwm = self._update_hwm(key, check_price, entry_price)
        hwm_pnl = calculate_hwm_pnl_pct(hwm, entry_price)

        # === Exit condition 1: Stop loss (fixed or ATR-based) ===
        effective_stop_pct = self._calculate_stop_loss(market_data, entry_price)

        if pnl_pct <= -effective_stop_pct:
            reason = f"MLPDirection exit: Stop loss {pnl_pct:.2f}% (limit: -{effective_stop_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason)

        # === Exit condition 2: Forward Window exit (paper methodology) ===
        if p.fwin_exit_enabled:
            fwin_signal = self._check_fwin_exit(ctx, position, pnl_pct, key)
            if fwin_signal:
                return fwin_signal

        # === Exit condition 3: Take profit (if enabled) ===
        if p.take_profit_enabled and pnl_pct >= p.take_profit_pct:
            reason = f"MLPDirection exit: Take profit {pnl_pct:.2f}% (target: +{p.take_profit_pct:.1f}%)"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason)

        # === Exit condition 4: MLP SELL prediction (if enabled) ===
        if p.use_mlp_sell_exit and pnl_pct >= p.min_profit_for_sell_exit:
            sell_signal = self._check_mlp_sell_exit(ctx, position, pnl_pct, key)
            if sell_signal:
                return sell_signal

        # === Exit condition 5: Trailing stop (if enabled) ===
        if p.trailing_enabled and hwm_pnl >= p.trailing_activation:
            trailing_stop_price = hwm * (1 - p.trailing_distance / 100)
            if current_price <= trailing_stop_price:
                locked_pnl = ((trailing_stop_price - entry_price) / entry_price) * 100
                reason = f"MLPDirection exit: Trailing stop {locked_pnl:.2f}% (HWM={hwm_pnl:.2f}%)"
                logger.info(f"{symbol}: {reason}")
                self._clear_state(key)
                return self._create_exit_signal(position, reason)

        return None

    def _calculate_stop_loss(
        self,
        market_data: MarketData,
        entry_price: float,
    ) -> float:
        """Calculate effective stop loss percentage.

        Args:
            market_data: Current market data.
            entry_price: Position entry price.

        Returns:
            Effective stop loss percentage.
        """
        p = self.params

        if p.atr_stop_enabled and market_data.atr > 0 and entry_price > 0:
            # ATR-based dynamic stop loss
            atr_pct = (market_data.atr / entry_price) * 100
            dynamic_stop_pct = p.atr_stop_multiplier * atr_pct
            # Clamp to min/max bounds
            return max(p.atr_stop_min_pct, min(p.atr_stop_max_pct, dynamic_stop_pct))

        return p.stop_loss_pct

    def _check_fwin_exit(
        self,
        ctx: TradingContext,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        """Check for Forward Window based exit (paper methodology).

        The paper exits after FWin periods if stop loss hasn't triggered.
        This creates many short-term trades as shown in Table 3.

        Args:
            ctx: Trading context.
            position: Current position.
            pnl_pct: Current P&L percentage.
            key: Position key.

        Returns:
            Exit signal if FWin periods elapsed, None otherwise.
        """
        p = self.params
        symbol = position.symbol
        market_data = ctx.market

        # Get entry timestamp
        entry_ts = self._entry_timestamps.get(key)
        if entry_ts is None:
            # No entry timestamp tracked - skip FWin exit
            return None

        # Get current timestamp
        current_ts = getattr(market_data, "timestamp", None)
        if current_ts is None:
            return None

        # Calculate elapsed candles (assuming 4H = 14400000 ms)
        # For flexibility, use candle_ms from context if available
        candle_ms = getattr(ctx, "candle_ms", 4 * 60 * 60 * 1000)  # Default 4H
        elapsed_ms = current_ts - entry_ts
        elapsed_candles = elapsed_ms / candle_ms

        # Exit if FWin periods have elapsed
        if elapsed_candles >= p.fwin_periods:
            reason = (
                f"MLPDirection exit: FWin exit after {elapsed_candles:.1f} candles "
                f"(FWin={p.fwin_periods}), P&L={pnl_pct:.2f}%"
            )
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason)

        return None

    def _check_mlp_sell_exit(
        self,
        ctx: TradingContext,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        """Check for MLP SELL prediction exit.

        Args:
            ctx: Trading context.
            position: Current position.
            pnl_pct: Current P&L percentage.
            key: Position key.

        Returns:
            Exit signal if SELL predicted, None otherwise.
        """
        if not self._ensure_model():
            return None

        p = self.params
        symbol = position.symbol

        # Check if MLP prediction is pre-computed in context
        mlp_prediction = getattr(ctx, "mlp_prediction", None)
        mlp_confidence = getattr(ctx, "mlp_confidence", None)

        if mlp_prediction is None or mlp_confidence is None:
            # Would need to compute here for live trading
            # For now, skip if not pre-computed
            return None

        # Check for SELL prediction with sufficient confidence
        if mlp_prediction == self.LABEL_SELL and mlp_confidence >= p.sell_confidence_threshold:
            reason = (
                f"MLPDirection exit: SELL prediction (conf={mlp_confidence:.2f}) "
                f"P&L={pnl_pct:.2f}%"
            )
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason)

        return None

    def on_position_opened(
        self, position: Position, entry_timestamp: int | None = None
    ) -> None:
        """Initialize state when position is opened.

        Args:
            position: The newly opened position.
            entry_timestamp: Entry bar timestamp in milliseconds (for FWin exit).
        """
        super().on_position_opened(position)
        key = self._get_position_key(position)

        # Store entry timestamp for FWin exit calculation
        if entry_timestamp is not None:
            self._entry_timestamps[key] = entry_timestamp

        logger.debug(
            f"{position.symbol}: MLPDirection position opened at {position.entry_price:.2f}"
        )

    def on_position_closed(self, symbol: str) -> None:
        """Clean up state when position is closed.

        Args:
            symbol: The symbol whose position was closed.
        """
        super().on_position_closed(symbol)
        # Clean up entry timestamp
        key = f"{symbol}:long"
        self._entry_timestamps.pop(key, None)
        logger.debug(f"{symbol}: MLPDirection position closed")

    def _clear_state(self, key: str) -> None:
        """Clear all state for a position.

        Args:
            key: Position key (symbol:direction).
        """
        super()._clear_state(key)
        # Also clear entry timestamp for FWin tracking
        self._entry_timestamps.pop(key, None)

    @property
    def high_water_mark(self) -> dict[str, float]:
        """Get current high water marks (read-only view)."""
        return self._high_water_marks.copy()
