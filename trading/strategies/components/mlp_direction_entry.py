"""MLP Direction Entry Strategy - Component wrapper for MLPDirectionClassifier.

Uses MLP neural network for 3-class direction prediction (Hold/Buy/Sell).
Based on Parente & Rizzuti (2025) methodology.

Reference: docs/plans/2026-02-01-mlp-direction-strategy-design.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from .models import (
    MarketData,
    Signal,
    TradingContext,
    BEAR_REGIMES,
    MLP_LABEL_HOLD,
    MLP_LABEL_BUY,
    MLP_LABEL_SELL,
)
from .registry import entry_strategy

logger = logging.getLogger(__name__)

# Default model path
DEFAULT_MODEL_PATH = "models/mlp_direction/model_final.pt"


@dataclass
class MLPDirectionEntryParams:
    """Parameters for MLP Direction entry strategy."""

    # Confidence thresholds
    buy_confidence_threshold: float = 0.40  # Minimum confidence for BUY prediction (relaxed)

    # Regime filters
    skip_bear_regime: bool = False  # Allow entry in BEAR regimes (relaxed)
    adx_min: float = 0.0  # No ADX filter (relaxed)

    # EMA200 filter
    use_ema200_filter: bool = False  # No EMA200 filter (relaxed)

    # Position sizing
    position_size: float = 0.01
    market: Literal["spot", "futures"] = "spot"

    # Model path
    model_path: str = DEFAULT_MODEL_PATH

    # Feature set (paper_36 or shap_13)
    mlp_feature_set: str = "paper_36"

    # Ensemble configuration (list of model configs)
    # Each: {"model_path": "...", "weight": 1.0}
    # If non-empty, ensemble soft-voting is used instead of single model.
    ensemble_models: list | None = None


@entry_strategy(params_class=MLPDirectionEntryParams)
class MLPDirectionEntryStrategy:
    """Entry strategy using MLP direction prediction.

    Based on Parente & Rizzuti (2025) methodology:
    - 3-class classification: Hold (0), Buy (1), Sell (2)
    - Feature set selectable (paper_36 or shap_13)
    - Entry only on BUY prediction with high confidence

    Entry conditions:
    1. MLP predicts BUY (class 1)
    2. Confidence >= threshold (default 60%)
    3. Not in BEAR regime (if skip_bear_regime)
    4. ADX >= threshold (trend strength)
    5. Price >= EMA200 (if use_ema200_filter)
    """

    # Minimum history required for paper_36 features (EMA100 + buffer)
    MIN_HISTORY_BARS = 120

    def __init__(self, params: MLPDirectionEntryParams | None = None):
        self.params = params or MLPDirectionEntryParams()
        self._model = None
        self._model_available: bool | None = None
        self._feature_extractor = None
        self._ensemble = None  # MLPEnsemblePredictor if configured
        # History buffer for paper_36 live feature computation
        self._history: list[dict] = []
        self._last_timestamp: int = 0

    def _ensure_model(self) -> bool:
        """Lazy-load MLP model (or ensemble) on first use."""
        if self._model_available is not None:
            return self._model_available

        try:
            from trading.indicators.mlp_features import extract_single_features
            self._feature_extractor = extract_single_features

            # Try ensemble first
            if self.params.ensemble_models:
                from .mlp_ensemble import MLPEnsemblePredictor

                self._ensemble = MLPEnsemblePredictor(self.params.ensemble_models)
                self._model_available = self._ensemble.load(device="cpu")
                if self._model_available:
                    logger.info(
                        f"MLPDirectionEntry: Ensemble loaded "
                        f"({self._ensemble.num_models} models)"
                    )
                else:
                    logger.warning("MLPDirectionEntry: Ensemble load failed")
                return self._model_available

            # Single model fallback
            from mlp_trainer.src.mlp_model import MLPDirectionClassifier

            model_path = Path(self.params.model_path)
            if not model_path.exists():
                logger.warning(f"MLPDirectionEntry: Model not found at {model_path}")
                self._model_available = False
                return False

            self._model = MLPDirectionClassifier.load(
                str(model_path), device="cpu", validate_path=True
            )
            self._model.eval()
            self._model_available = True
            logger.info(f"MLPDirectionEntry: Model loaded from {model_path}")

        except ValueError as e:
            logger.error(f"MLPDirectionEntry: Invalid model path: {e}")
            self._model_available = False
        except ImportError as e:
            logger.error(f"MLPDirectionEntry: Missing dependency: {e}")
            self._model_available = False
        except Exception as e:
            logger.error(f"MLPDirectionEntry: Failed to load model: {e}")
            self._model_available = False

        return self._model_available

    def _extract_features(self, market_data: MarketData, indicators: dict) -> np.ndarray | None:
        """Extract features from market data for MLP prediction.

        Args:
            market_data: Current market data.
            indicators: Additional indicators dict.

        Returns:
            Feature array or None if extraction fails.
        """
        if self._feature_extractor is None:
            return None

        try:
            # Build market_data dict for feature extraction
            data_dict = {
                "open": indicators.get("open", market_data.open),
                "high": indicators.get("high", market_data.high),
                "low": indicators.get("low", market_data.low),
                "close": market_data.close,
                "volume": indicators.get("volume", market_data.volume),
            }

            # Build indicators dict (use getattr with defaults for optional fields)
            ema_50 = getattr(market_data, "ema_50", market_data.close)
            ema_200 = getattr(market_data, "ema_200", market_data.close)
            rsi = getattr(market_data, "rsi", 50.0)

            ind_dict = {
                "bollinger_pct_b": indicators.get("bollinger_pct_b", 0.5),
                "rsi": indicators.get("rsi", rsi),
                "ultosc": indicators.get("ultosc", 50.0),
                "ema_20": indicators.get("ema_20", ema_50),
                "ema_21": indicators.get("ema_21", ema_50),
                "ema_50": ema_50,
                "ema_100": indicators.get("ema_100", ema_200),
                "price_zscore": indicators.get("price_zscore", 0.0),
                "volume_zscore": indicators.get("volume_zscore", 0.0),
            }

            # EMA cross ratios if available (paper set)
            ema20 = ind_dict.get("ema_20", 0.0)
            if ema20:
                ind_dict["ema_cross_1_20"] = market_data.close / ema20
            if ema20 and ema_50:
                ind_dict["ema_cross_20_50"] = ema20 / ema_50
            if ema_50 and ind_dict.get("ema_100", 0.0):
                ind_dict["ema_cross_50_100"] = ema_50 / ind_dict["ema_100"]
            if ema_50:
                ind_dict["ema_cross_1_50"] = market_data.close / ema_50

            # Add temporal features if available
            if hasattr(market_data, "timestamp"):
                import datetime
                ts = market_data.timestamp / 1000  # Convert from ms
                dt = datetime.datetime.fromtimestamp(ts)
                ind_dict["hour_of_day"] = dt.hour
                ind_dict["day_of_week"] = dt.weekday()
                ind_dict["month"] = dt.month

            try:
                features = self._feature_extractor(
                    data_dict,
                    ind_dict,
                    feature_set=self.params.mlp_feature_set,
                )
            except TypeError:
                # Backward compatible with extractors that don't accept feature_set
                features = self._feature_extractor(data_dict, ind_dict)
            return features

        except Exception as e:
            logger.warning(f"MLPDirectionEntry: Feature extraction failed: {e}")
            return None

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        """Check entry conditions using MLP direction prediction.

        Args:
            ctx: Trading context with market data and regime info.

        Returns:
            Signal if entry conditions met, None otherwise.
        """
        market_data = ctx.market
        context = ctx.regime
        p = self.params

        # === SAFETY FILTER 1: BEAR regime ===
        if p.skip_bear_regime and context.regime in BEAR_REGIMES:
            logger.debug(f"{market_data.symbol}: Skip - BEAR regime ({context.regime})")
            return None

        # === SAFETY FILTER 2: ADX threshold ===
        if context.adx < p.adx_min:
            logger.debug(f"{market_data.symbol}: Skip - weak ADX ({context.adx:.1f} < {p.adx_min})")
            return None

        # === SAFETY FILTER 3: EMA200 filter ===
        if p.use_ema200_filter and market_data.ema_200 > 0:
            if market_data.close < market_data.ema_200:
                logger.debug(
                    f"{market_data.symbol}: Skip - below EMA200 "
                    f"({market_data.close:.0f} < {market_data.ema_200:.0f})"
                )
                return None

        # === MLP PREDICTION ===
        if not self._ensure_model():
            logger.debug(f"{market_data.symbol}: Skip - MLP model not available")
            return None

        # Update history buffer for live paper_36 computation
        self._update_history(market_data)

        # Check if MLP features are pre-computed in context (backtest mode)
        mlp_prediction = getattr(ctx, "mlp_prediction", None)
        mlp_confidence = getattr(ctx, "mlp_confidence", None)

        if mlp_prediction is None or mlp_confidence is None:
            if p.mlp_feature_set in ("paper_36", "v2_36"):
                # Live paper_36/v2_36: compute from history buffer
                result = self._compute_history_features(market_data, p.mlp_feature_set)
                if result is None:
                    return None
                mlp_prediction, mlp_confidence = result
            else:
                # Compute MLP prediction on the fly (shap_13 or other)
                features = self._extract_features(market_data, {})
                if features is None:
                    logger.debug(f"{market_data.symbol}: Skip - feature extraction failed")
                    return None
                mlp_prediction, mlp_confidence = self._predict(features)

        # === MLP FILTER 1: Prediction must be BUY ===
        if mlp_prediction != MLP_LABEL_BUY:
            logger.debug(
                f"{market_data.symbol}: Skip - MLP prediction is "
                f"{self._label_name(mlp_prediction)}, not BUY"
            )
            return None

        # === MLP FILTER 2: Confidence threshold ===
        if mlp_confidence < p.buy_confidence_threshold:
            logger.debug(
                f"{market_data.symbol}: Skip - low MLP confidence "
                f"({mlp_confidence:.2f} < {p.buy_confidence_threshold:.2f})"
            )
            return None

        # All conditions met - generate entry signal
        reason = (
            f"MLPDirection: pred=BUY, conf={mlp_confidence:.2f}, "
            f"regime={context.regime}, ADX={context.adx:.1f}"
        )
        logger.info(f"{market_data.symbol}: {reason}")

        return Signal(
            symbol=market_data.symbol,
            side="buy",
            market=p.market,
            quantity=p.position_size,
            reason=reason,
        )

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
            logger.error(f"MLP prediction failed: {e}")
            return MLP_LABEL_HOLD, 0.0

    @staticmethod
    def _label_name(label: int) -> str:
        """Convert label to human-readable name."""
        names = {0: "HOLD", 1: "BUY", 2: "SELL"}
        return names.get(label, "UNKNOWN")

    def _update_history(self, market_data: MarketData) -> None:
        """Update history buffer with current bar data.

        Args:
            market_data: Current market data bar.
        """
        timestamp = getattr(market_data, "timestamp", 0)

        # Skip if same timestamp (duplicate update)
        if timestamp == self._last_timestamp and timestamp > 0:
            return

        self._last_timestamp = timestamp

        bar = {
            "open": market_data.open,
            "high": market_data.high,
            "low": market_data.low,
            "close": market_data.close,
            "volume": market_data.volume,
            "timestamp": timestamp,
        }

        self._history.append(bar)

        # Keep only recent history (2x minimum for safety)
        max_history = self.MIN_HISTORY_BARS * 2
        if len(self._history) > max_history:
            self._history = self._history[-max_history:]

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

        if len(self._history) < self.MIN_HISTORY_BARS:
            if len(self._history) % 10 == 0:
                logger.info(
                    f"{market_data.symbol}: MLP {feature_set} warming up "
                    f"({len(self._history)}/{self.MIN_HISTORY_BARS} bars)"
                )
            return None

        try:
            df = pd.DataFrame(self._history)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

            features_df = calculate_mlp_features(
                df, include_temporal=True, feature_set=feature_set,
            )

            last_features = features_df.iloc[-1].values.astype(np.float32)

            if np.isnan(last_features).any():
                logger.debug(f"{market_data.symbol}: Features contain NaN, skipping")
                return None

            pred, conf = self._predict(last_features)
            logger.info(
                f"{market_data.symbol}: MLP {feature_set} prediction: "
                f"{self._label_name(pred)} (conf={conf:.2f})"
            )
            return pred, conf

        except Exception as e:
            logger.warning(f"{market_data.symbol}: {feature_set} feature computation failed: {e}")
            return None

    def _compute_paper36_features(self, market_data: MarketData) -> tuple[int, float] | None:
        """Backward-compatible wrapper for paper_36 features."""
        return self._compute_history_features(market_data, "paper_36")
