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
from .models import (
    MarketData,
    Position,
    Signal,
    TradingContext,
    BULL_REGIMES,
    MLP_LABEL_HOLD,
    MLP_LABEL_BUY,
    MLP_LABEL_SELL,
)
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
    min_hold_bars_for_sell_exit: int = 0  # Hold at least N bars before MLP SELL exit
    bull_regime_sell_guard: bool = False  # Require stricter SELL confidence in BULL regimes

    # Take profit levels (NOT in paper - disabled by default)
    take_profit_enabled: bool = False  # Paper does NOT use take profit
    take_profit_pct: float = 25.0  # Exit at +25% profit

    market: Literal["spot", "futures"] = "spot"

    # Model path (for MLP SELL exit)
    model_path: str = DEFAULT_MODEL_PATH

    # Feature set (paper_36 or shap_13)
    mlp_feature_set: str = "paper_36"

    # Runtime switch profile (C11): use risk-on/off params by regime state
    runtime_switch_enabled: bool = False
    switch_mfi_threshold: float = 50.0
    switch_adx_threshold: float = 18.0
    switch_require_above_ema200: bool = True
    risk_on_sell_confidence_threshold: float = 0.0
    risk_off_sell_confidence_threshold: float = 0.0
    risk_on_stop_loss_pct: float = 0.0
    risk_off_stop_loss_pct: float = 0.0


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

    # Minimum history required for paper_36 features (EMA100 + buffer)
    MIN_HISTORY_BARS = 120

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
        self._ensemble = None  # MLPEnsemblePredictor if configured
        # History buffer for paper_36 live feature computation
        self._history: dict[str, list[dict]] = {}  # symbol -> history bars
        self._last_timestamp: dict[str, int] = {}  # symbol -> last timestamp

    def set_model(self, model, ensemble=None):
        """Inject a pre-loaded model to avoid duplicate loading.

        Args:
            model: Pre-loaded MLPDirectionClassifier model.
            ensemble: Pre-loaded MLPEnsemblePredictor (takes priority).
        """
        from trading.indicators.mlp_features import extract_single_features
        self._feature_extractor = extract_single_features

        if ensemble is not None:
            self._ensemble = ensemble
            self._model_available = True
            logger.info("MLPDirectionExit: Using shared ensemble")
        elif model is not None:
            self._model = model
            self._model_available = True
            logger.info("MLPDirectionExit: Using shared model")

    def _ensure_model(self) -> bool:
        """Lazy-load MLP model (or ensemble) on first use (for SELL exit)."""
        if not self.params.use_mlp_sell_exit:
            return False

        if self._model_available is not None:
            return self._model_available

        try:
            from trading.indicators.mlp_features import extract_single_features
            self._feature_extractor = extract_single_features

            # Try ensemble first (check if ensemble_models param exists)
            ensemble_models = getattr(self.params, "ensemble_models", None)
            if ensemble_models:
                from .mlp_ensemble import MLPEnsemblePredictor

                self._ensemble = MLPEnsemblePredictor(ensemble_models)
                self._model_available = self._ensemble.load(device="cpu")
                if self._model_available:
                    logger.info(
                        f"MLPDirectionExit: Ensemble loaded "
                        f"({self._ensemble.num_models} models)"
                    )
                else:
                    logger.warning("MLPDirectionExit: Ensemble load failed")
                return self._model_available

            # Single model fallback
            from mlp_trainer.src.mlp_model import MLPDirectionClassifier

            model_path = Path(self.params.model_path)
            if not model_path.exists():
                logger.warning(f"MLPDirectionExit: Model not found at {model_path}")
                self._model_available = False
                return False

            # Load with path validation enabled for security
            self._model = MLPDirectionClassifier.load(
                str(model_path), device="cpu", validate_path=True
            )
            self._model.eval()
            self._model_available = True
            logger.info(f"MLPDirectionExit: Model loaded from {model_path}")

        except ValueError as e:
            # Path validation failed - security issue
            logger.error(f"MLPDirectionExit: Invalid model path: {e}")
            self._model_available = False
        except ImportError as e:
            logger.error(f"MLPDirectionExit: Missing dependency: {e}")
            self._model_available = False
        except Exception as e:
            logger.error(f"MLPDirectionExit: Failed to load model: {e}")
            self._model_available = False

        return self._model_available

    def _is_risk_on(self, market_data: MarketData, p: MLPDirectionExitParams) -> bool:
        if market_data.mfi < p.switch_mfi_threshold:
            return False
        if market_data.adx < p.switch_adx_threshold:
            return False
        if p.switch_require_above_ema200 and market_data.ema_200 > 0:
            if market_data.close < market_data.ema_200:
                return False
        return True

    def _active_sell_threshold(self, ctx: TradingContext) -> float:
        p = self.params
        threshold = p.sell_confidence_threshold
        if not p.runtime_switch_enabled:
            return threshold
        if self._is_risk_on(ctx.market, p):
            return p.risk_on_sell_confidence_threshold if p.risk_on_sell_confidence_threshold > 0 else threshold
        return p.risk_off_sell_confidence_threshold if p.risk_off_sell_confidence_threshold > 0 else threshold

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
        if position.entry_price <= 0 or position.quantity <= 0:
            return None

        key = self._get_position_key(position)
        candles_held = self._increment_candles_held(key)
        pnl_pct, hwm, hwm_pnl = self._compute_position_metrics(position, market_data, key)

        stop_signal = self._check_stop_loss_exit(ctx, position, pnl_pct, key)
        if stop_signal:
            return stop_signal

        fwin_signal = self._check_fwin_exit_if_enabled(ctx, position, pnl_pct, key)
        if fwin_signal:
            return fwin_signal

        take_profit_signal = self._check_take_profit_exit(position, pnl_pct, key)
        if take_profit_signal:
            return take_profit_signal

        sell_signal = self._check_mlp_sell_exit_if_enabled(
            ctx=ctx,
            position=position,
            pnl_pct=pnl_pct,
            key=key,
            candles_held=candles_held,
        )
        if sell_signal:
            return sell_signal

        trailing_signal = self._check_trailing_stop_exit(
            position=position,
            current_price=market_data.close,
            hwm=hwm,
            hwm_pnl=hwm_pnl,
            key=key,
        )
        if trailing_signal:
            return trailing_signal

        return None

    def _compute_position_metrics(
        self,
        position: Position,
        market_data: MarketData,
        key: str,
    ) -> tuple[float, float, float]:
        current_price = market_data.close
        entry_price = position.entry_price
        pnl_pct = calculate_pnl_pct(current_price, entry_price, "long")
        check_price = market_data.high if market_data.high > 0 else current_price
        hwm = self._update_hwm(key, check_price, entry_price)
        hwm_pnl = calculate_hwm_pnl_pct(hwm, entry_price)
        return pnl_pct, hwm, hwm_pnl

    def _check_stop_loss_exit(
        self,
        ctx: TradingContext,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        stop_pct = self._calculate_stop_loss(ctx, ctx.market, position.entry_price)
        if pnl_pct > -stop_pct:
            return None
        reason = f"MLPDirection exit: Stop loss {pnl_pct:.2f}% (limit: -{stop_pct:.1f}%)"
        logger.info(f"{position.symbol}: {reason}")
        self._clear_state(key)
        return self._create_exit_signal(position, reason)

    def _check_fwin_exit_if_enabled(
        self,
        ctx: TradingContext,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        if not self.params.fwin_exit_enabled:
            return None
        return self._check_fwin_exit(ctx, position, pnl_pct, key)

    def _check_take_profit_exit(
        self,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        p = self.params
        if not p.take_profit_enabled or pnl_pct < p.take_profit_pct:
            return None
        reason = (
            f"MLPDirection exit: Take profit {pnl_pct:.2f}% "
            f"(target: +{p.take_profit_pct:.1f}%)"
        )
        logger.info(f"{position.symbol}: {reason}")
        self._clear_state(key)
        return self._create_exit_signal(position, reason)

    def _check_mlp_sell_exit_if_enabled(
        self,
        ctx: TradingContext,
        position: Position,
        pnl_pct: float,
        key: str,
        candles_held: int,
    ) -> Signal | None:
        p = self.params
        if not p.use_mlp_sell_exit or pnl_pct < p.min_profit_for_sell_exit:
            return None
        if p.min_hold_bars_for_sell_exit > 0 and candles_held < p.min_hold_bars_for_sell_exit:
            logger.debug(
                f"{position.symbol}: MLP SELL exit skipped - hold guard "
                f"({candles_held}/{p.min_hold_bars_for_sell_exit} bars)"
            )
            return None
        return self._check_mlp_sell_exit(ctx, position, pnl_pct, key)

    def _resolve_sell_threshold(self, ctx: TradingContext) -> float:
        """Resolve effective SELL confidence threshold including bull-regime guard."""
        threshold = self._active_sell_threshold(ctx)
        if not self.params.bull_regime_sell_guard:
            return threshold
        if ctx.regime.regime not in BULL_REGIMES:
            return threshold

        # In strong bullish regimes, demand stricter SELL confidence to reduce early exits.
        risk_on_floor = self.params.risk_on_sell_confidence_threshold
        bull_floor = risk_on_floor if risk_on_floor > 0 else min(0.95, threshold + 0.15)
        return max(threshold, bull_floor)

    def _check_trailing_stop_exit(
        self,
        position: Position,
        current_price: float,
        hwm: float,
        hwm_pnl: float,
        key: str,
    ) -> Signal | None:
        p = self.params
        if not p.trailing_enabled or hwm_pnl < p.trailing_activation:
            return None
        trailing_stop_price = hwm * (1 - p.trailing_distance / 100)
        if current_price > trailing_stop_price:
            return None
        locked_pnl = ((trailing_stop_price - position.entry_price) / position.entry_price) * 100
        reason = f"MLPDirection exit: Trailing stop {locked_pnl:.2f}% (HWM={hwm_pnl:.2f}%)"
        logger.info(f"{position.symbol}: {reason}")
        self._clear_state(key)
        return self._create_exit_signal(position, reason)

    def _calculate_stop_loss(
        self,
        ctx: TradingContext,
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
        base_stop_pct = p.stop_loss_pct
        if p.runtime_switch_enabled:
            if self._is_risk_on(ctx.market, p):
                if p.risk_on_stop_loss_pct > 0:
                    base_stop_pct = p.risk_on_stop_loss_pct
            else:
                if p.risk_off_stop_loss_pct > 0:
                    base_stop_pct = p.risk_off_stop_loss_pct

        if p.atr_stop_enabled and market_data.atr > 0 and entry_price > 0:
            # ATR-based dynamic stop loss
            atr_pct = (market_data.atr / entry_price) * 100
            dynamic_stop_pct = p.atr_stop_multiplier * atr_pct
            # Clamp to min/max bounds
            return max(p.atr_stop_min_pct, min(p.atr_stop_max_pct, dynamic_stop_pct))

        return base_stop_pct

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

        # Get entry timestamp from position's entry_time (Redis-backed)
        entry_ts = getattr(position, "entry_time", None)
        if entry_ts is None:
            # No entry timestamp available - skip FWin exit
            logger.debug(f"{symbol}: FWin exit skipped - no entry_time in position")
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
        market_data = ctx.market

        # Update history buffer for live computation
        self._update_history(market_data)

        # Check if MLP prediction is pre-computed in context
        mlp_prediction = getattr(ctx, "mlp_prediction", None)
        mlp_confidence = getattr(ctx, "mlp_confidence", None)

        if mlp_prediction is None or mlp_confidence is None:
            # Compute prediction for live trading
            if p.mlp_feature_set in ("paper_36", "v2_36"):
                # Live paper_36/v2_36: compute from history buffer
                result = self._compute_history_features(market_data, p.mlp_feature_set)
                if result is None:
                    return None
                mlp_prediction, mlp_confidence = result
            else:
                # Fallback for other feature sets (not implemented yet)
                logger.debug(f"{symbol}: MLP SELL exit: Feature set {p.mlp_feature_set} not supported for live computation")
                return None

        active_sell_threshold = self._resolve_sell_threshold(ctx)

        # Check for SELL prediction with sufficient confidence
        if mlp_prediction == MLP_LABEL_SELL and mlp_confidence >= active_sell_threshold:
            reason = (
                f"MLPDirection exit: SELL prediction (conf={mlp_confidence:.2f}, "
                f"thr={active_sell_threshold:.2f}) "
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
            entry_timestamp: Entry bar timestamp (deprecated - using position.entry_time).
        """
        super().on_position_opened(position)

        logger.debug(
            f"{position.symbol}: MLPDirection position opened at {position.entry_price:.2f}"
        )

    def on_position_closed(self, symbol: str) -> None:
        """Clean up state when position is closed.

        Args:
            symbol: The symbol whose position was closed.
        """
        super().on_position_closed(symbol)
        logger.debug(f"{symbol}: MLPDirection position closed")

    def _clear_state(self, key: str) -> None:
        """Clear all state for a position.

        Args:
            key: Position key (symbol:direction).
        """
        super()._clear_state(key)

    def _update_history(self, market_data: MarketData) -> None:
        """Update history buffer with current bar data.

        Args:
            market_data: Current market data bar.
        """
        symbol = market_data.symbol
        timestamp = getattr(market_data, "timestamp", 0)

        # Initialize symbol history if needed
        if symbol not in self._history:
            self._history[symbol] = []
            self._last_timestamp[symbol] = 0

        # Skip if same timestamp (duplicate update)
        if timestamp == self._last_timestamp[symbol] and timestamp > 0:
            return

        self._last_timestamp[symbol] = timestamp

        bar = {
            "open": market_data.open,
            "high": market_data.high,
            "low": market_data.low,
            "close": market_data.close,
            "volume": market_data.volume,
            "timestamp": timestamp,
        }

        self._history[symbol].append(bar)

        # Keep only recent history (2x minimum for safety)
        max_history = self.MIN_HISTORY_BARS * 2
        if len(self._history[symbol]) > max_history:
            self._history[symbol] = self._history[symbol][-max_history:]

    def _compute_history_features(
        self, market_data: MarketData, feature_set: str,
    ) -> tuple[int, float] | None:
        """Compute features from history buffer and make prediction.

        Supports paper_36, v2_36, and any future history-based feature sets.

        Args:
            market_data: Current market data (for timestamp).
            feature_set: Feature set name ('paper_36', 'v2_36').

        Returns:
            Tuple of (prediction, confidence) or None if insufficient history.
        """
        import pandas as pd
        from trading.indicators.mlp_features import calculate_mlp_features

        symbol = market_data.symbol
        history = self._history.get(symbol, [])

        if len(history) < self.MIN_HISTORY_BARS:
            if len(history) % 10 == 0:
                logger.info(
                    f"{symbol}: MLP {feature_set} exit warming up "
                    f"({len(history)}/{self.MIN_HISTORY_BARS} bars)"
                )
            return None

        try:
            df = pd.DataFrame(history)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

            features_df = calculate_mlp_features(
                df, include_temporal=True, feature_set=feature_set,
            )

            last_features = features_df.iloc[-1].values.astype(np.float32)

            if np.isnan(last_features).any():
                logger.debug(f"{symbol}: Exit features contain NaN, skipping")
                return None

            pred, conf = self._predict(last_features)
            logger.debug(
                f"{symbol}: MLP {feature_set} exit prediction: "
                f"{self._label_name(pred)} (conf={conf:.2f})"
            )
            return pred, conf

        except Exception as e:
            logger.warning(f"{symbol}: {feature_set} exit feature computation failed: {e}")
            return None

    def _predict(self, features: np.ndarray) -> tuple[int, float]:
        """Make prediction with MLP model or ensemble.

        Args:
            features: Feature array.

        Returns:
            Tuple of (predicted_class, confidence).
        """
        try:
            # Use ensemble if available
            if self._ensemble is not None:
                pred_class, confidence, _ = self._ensemble.predict(features)
                return pred_class, confidence

            # Single model fallback
            import torch
            x = torch.FloatTensor(features).unsqueeze(0)
            with torch.no_grad():
                probs = self._model.predict_proba(x).cpu().numpy()[0]

            pred_class = probs.argmax()
            confidence = probs[pred_class]

            return int(pred_class), float(confidence)

        except Exception as e:
            logger.error(f"MLP exit prediction failed: {e}")
            return MLP_LABEL_HOLD, 0.0

    @staticmethod
    def _label_name(label: int) -> str:
        """Convert label to human-readable name."""
        names = {0: "HOLD", 1: "BUY", 2: "SELL"}
        return names.get(label, "UNKNOWN")

    @property
    def high_water_mark(self) -> dict[str, float]:
        """Get current high water marks (read-only view)."""
        return self._high_water_marks.copy()
