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

    # Runtime switch profile (C11): use risk-on/off params by regime state
    runtime_switch_enabled: bool = False
    switch_mfi_threshold: float = 50.0
    switch_adx_threshold: float = 18.0
    switch_require_above_ema200: bool = True
    risk_on_buy_confidence_threshold: float = 0.0
    risk_off_buy_confidence_threshold: float = 0.0
    risk_on_position_size: float = 0.0
    risk_off_position_size: float = 0.0


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
            logger.info("MLPDirectionEntry: Using shared ensemble")
        elif model is not None:
            self._model = model
            self._model_available = True
            logger.info("MLPDirectionEntry: Using shared model")

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
            data_dict = self._build_feature_data_dict(market_data, indicators)
            ind_dict = self._build_feature_indicator_dict(market_data, indicators)
            self._add_ema_cross_features(ind_dict, market_data.close)
            self._add_temporal_features(ind_dict, getattr(market_data, "timestamp", None))
            return self._run_feature_extractor(data_dict, ind_dict)
        except Exception as e:
            logger.warning(f"MLPDirectionEntry: Feature extraction failed: {e}")
            return None

    def _build_feature_data_dict(self, market_data: MarketData, indicators: dict) -> dict:
        return {
            "open": indicators.get("open", market_data.open),
            "high": indicators.get("high", market_data.high),
            "low": indicators.get("low", market_data.low),
            "close": market_data.close,
            "volume": indicators.get("volume", market_data.volume),
        }

    def _build_feature_indicator_dict(self, market_data: MarketData, indicators: dict) -> dict:
        ema_50 = getattr(market_data, "ema_50", market_data.close)
        ema_200 = getattr(market_data, "ema_200", market_data.close)
        rsi = getattr(market_data, "rsi", 50.0)
        return {
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

    def _add_ema_cross_features(self, ind_dict: dict, close_price: float) -> None:
        ema_20 = ind_dict.get("ema_20", 0.0)
        ema_50 = ind_dict.get("ema_50", 0.0)
        ema_100 = ind_dict.get("ema_100", 0.0)

        if ema_20:
            ind_dict["ema_cross_1_20"] = close_price / ema_20
        if ema_20 and ema_50:
            ind_dict["ema_cross_20_50"] = ema_20 / ema_50
        if ema_50 and ema_100:
            ind_dict["ema_cross_50_100"] = ema_50 / ema_100
        if ema_50:
            ind_dict["ema_cross_1_50"] = close_price / ema_50

    def _add_temporal_features(self, ind_dict: dict, timestamp_ms: int | None) -> None:
        if not timestamp_ms:
            return
        import datetime

        dt = datetime.datetime.fromtimestamp(timestamp_ms / 1000)
        ind_dict["hour_of_day"] = dt.hour
        ind_dict["day_of_week"] = dt.weekday()
        ind_dict["month"] = dt.month

    def _run_feature_extractor(self, data_dict: dict, ind_dict: dict) -> np.ndarray:
        try:
            return self._feature_extractor(
                data_dict,
                ind_dict,
                feature_set=self.params.mlp_feature_set,
            )
        except TypeError:
            # Backward compatible with extractors that don't accept feature_set
            return self._feature_extractor(data_dict, ind_dict)

    def _is_risk_on(self, market_data: MarketData, p: MLPDirectionEntryParams) -> bool:
        if market_data.mfi < p.switch_mfi_threshold:
            return False
        if market_data.adx < p.switch_adx_threshold:
            return False
        if p.switch_require_above_ema200 and market_data.ema_200 > 0:
            if market_data.close < market_data.ema_200:
                return False
        return True

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
        active_buy_threshold, active_position_size, switch_mode = self._resolve_runtime_profile(
            market_data
        )

        if not self._passes_entry_safety_filters(market_data, context):
            return None

        if not self._ensure_model():
            logger.debug(f"{market_data.symbol}: Skip - MLP model not available")
            return None

        self._update_history(market_data)
        prediction_result = self._get_prediction_and_confidence(ctx, market_data)
        if prediction_result is None:
            return None
        mlp_prediction, mlp_confidence = prediction_result

        if mlp_prediction != MLP_LABEL_BUY:
            logger.debug(
                f"{market_data.symbol}: Skip - MLP prediction is "
                f"{self._label_name(mlp_prediction)}, not BUY"
            )
            return None

        if mlp_confidence < active_buy_threshold:
            logger.debug(
                f"{market_data.symbol}: Skip - low MLP confidence "
                f"({mlp_confidence:.2f} < {active_buy_threshold:.2f})"
            )
            return None

        return self._build_entry_signal(
            market_data=market_data,
            context=context,
            confidence=mlp_confidence,
            position_size=active_position_size,
            switch_mode=switch_mode,
        )

    def _resolve_runtime_profile(self, market_data: MarketData) -> tuple[float, float, str]:
        p = self.params
        threshold = p.buy_confidence_threshold
        position_size = p.position_size
        mode = "base"

        if not p.runtime_switch_enabled:
            return threshold, position_size, mode

        if self._is_risk_on(market_data, p):
            mode = "risk_on"
            if p.risk_on_buy_confidence_threshold > 0:
                threshold = p.risk_on_buy_confidence_threshold
            if p.risk_on_position_size > 0:
                position_size = p.risk_on_position_size
            return threshold, position_size, mode

        mode = "risk_off"
        if p.risk_off_buy_confidence_threshold > 0:
            threshold = p.risk_off_buy_confidence_threshold
        if p.risk_off_position_size > 0:
            position_size = p.risk_off_position_size
        return threshold, position_size, mode

    def _passes_entry_safety_filters(
        self,
        market_data: MarketData,
        context,
    ) -> bool:
        p = self.params
        if p.skip_bear_regime and context.regime in BEAR_REGIMES:
            logger.debug(f"{market_data.symbol}: Skip - BEAR regime ({context.regime})")
            return False
        if context.adx < p.adx_min:
            logger.debug(
                f"{market_data.symbol}: Skip - weak ADX ({context.adx:.1f} < {p.adx_min})"
            )
            return False
        if p.use_ema200_filter and market_data.ema_200 > 0 and market_data.close < market_data.ema_200:
            logger.debug(
                f"{market_data.symbol}: Skip - below EMA200 "
                f"({market_data.close:.0f} < {market_data.ema_200:.0f})"
            )
            return False
        return True

    def _get_prediction_and_confidence(
        self,
        ctx: TradingContext,
        market_data: MarketData,
    ) -> tuple[int, float] | None:
        p = self.params
        mlp_prediction = getattr(ctx, "mlp_prediction", None)
        mlp_confidence = getattr(ctx, "mlp_confidence", None)

        if mlp_prediction is not None and mlp_confidence is not None:
            return mlp_prediction, mlp_confidence

        if p.mlp_feature_set in ("paper_36", "v2_36"):
            return self._compute_history_features(market_data, p.mlp_feature_set)

        features = self._extract_features(market_data, {})
        if features is None:
            logger.debug(f"{market_data.symbol}: Skip - feature extraction failed")
            return None
        return self._predict(features)

    def _build_entry_signal(
        self,
        market_data: MarketData,
        context,
        confidence: float,
        position_size: float,
        switch_mode: str,
    ) -> Signal:
        reason = (
            f"MLPDirection: pred=BUY, conf={confidence:.2f}, "
            f"regime={context.regime}, ADX={context.adx:.1f}, mode={switch_mode}"
        )
        logger.info(f"{market_data.symbol}: {reason}")
        return Signal(
            symbol=market_data.symbol,
            side="buy",
            market=self.params.market,
            quantity=position_size,
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
