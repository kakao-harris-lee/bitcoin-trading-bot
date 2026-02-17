"""Runtime helpers for loading and applying offline regime model artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import pickle
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from trading.regime.calibration import apply_class_multipliers
from trading.regime.ensemble import (
    build_hmm_feature_frame_from_table,
    combine_probabilities,
    predict_proba_all_classes,
    states_to_class_proba,
)
from trading.regime.hybrid import apply_sideways_guard
from trading.regime.training import CLASS_TO_REGIME, DEFAULT_FEATURE_COLUMNS

logger = logging.getLogger(__name__)

_ALL_CLASSES: list[int] = sorted(CLASS_TO_REGIME.keys())
_DEFAULT_MODEL = "rf"
_SUPPORTED_MODELS: frozenset[str] = frozenset(
    {
        "rf",
        "rf_calibrated",
        "hmm",
        "ensemble",
        "ensemble_calibrated",
        "hybrid",
    }
)


@dataclass(frozen=True)
class RuntimeRegimePrediction:
    """Runtime regime prediction details."""

    symbol: str
    model: str
    regime_3: str
    regime_7: str
    confidence: float
    rf_confidence: float
    rf_signal: str


@dataclass(frozen=True)
class _RuntimeArtifactBundle:
    """Loaded runtime artifacts for one symbol."""

    rf_model: Any
    hmm_model: Any
    feature_columns: list[str]
    hmm_feature_columns: list[str]
    state_distribution: dict[int, np.ndarray]
    rf_multipliers: np.ndarray
    rf_weight: float
    hmm_weight: float
    hybrid_conf_threshold: float
    hybrid_sideways_threshold: float
    hmm_vol_window: int


class RuntimeRegimeOverlay:
    """Optional runtime regime overlay using offline RF/HMM artifacts."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.apply_v2_filters = bool(cfg.get("apply_v2_filters", False))
        self.default_model = str(cfg.get("default_model", _DEFAULT_MODEL)).lower()
        self.symbol_models = cfg.get("symbol_models", {}) if isinstance(cfg.get("symbol_models", {}), dict) else {}
        self._bundle_cache: dict[str, _RuntimeArtifactBundle | None] = {}

    def is_enabled_for(self, symbol: str) -> bool:
        if not self.enabled:
            return False
        settings = self._symbol_settings(symbol)
        return bool(settings.get("artifact_dir"))

    def predict(
        self,
        *,
        symbol: str,
        market_data: Any,
        history_df: pd.DataFrame | None,
    ) -> RuntimeRegimePrediction | None:
        settings = self._symbol_settings(symbol)
        model = str(settings.get("model", self.default_model)).lower()
        if model not in _SUPPORTED_MODELS:
            logger.warning("%s: unsupported runtime regime model '%s'", symbol, model)
            return None

        artifact_dir = str(settings.get("artifact_dir", "")).strip()
        if not artifact_dir:
            return None

        bundle = self._load_bundle(artifact_dir)
        if bundle is None:
            return None

        feature_row = self._build_rf_feature_row(market_data, bundle.feature_columns)
        X_rf = pd.DataFrame([feature_row], columns=bundle.feature_columns)
        rf_proba = predict_proba_all_classes(bundle.rf_model, X_rf, _ALL_CLASSES)
        rf_cal_proba = apply_class_multipliers(rf_proba, bundle.rf_multipliers)

        hmm_proba = self._predict_hmm_proba(
            bundle=bundle,
            history_df=history_df,
            market_data=market_data,
        )
        if hmm_proba is None and model in {"hmm", "ensemble", "ensemble_calibrated", "hybrid"}:
            logger.warning("%s: HMM inference unavailable, fallback to RF-calibrated", symbol)
            model = "rf_calibrated"

        selected_proba = self._select_model_proba(
            model=model,
            rf_proba=rf_proba,
            rf_cal_proba=rf_cal_proba,
            hmm_proba=hmm_proba,
            bundle=bundle,
        )
        if selected_proba is None:
            return None

        pred_class = int(np.argmax(selected_proba[0]))
        confidence = float(np.max(selected_proba[0]))
        regime_3 = CLASS_TO_REGIME.get(pred_class, "SIDEWAYS")
        regime_7 = self._map_regime_3_to_7(
            regime_3=regime_3,
            mfi=float(getattr(market_data, "mfi", 50.0)),
            adx=float(getattr(market_data, "adx", 20.0)),
        )
        rf_confidence = float(np.max(rf_cal_proba[0]))
        rf_signal = self._rf_signal_from_regime(regime_3)

        return RuntimeRegimePrediction(
            symbol=symbol,
            model=model,
            regime_3=regime_3,
            regime_7=regime_7,
            confidence=confidence,
            rf_confidence=rf_confidence,
            rf_signal=rf_signal,
        )

    def _symbol_settings(self, symbol: str) -> dict[str, Any]:
        raw = self.symbol_models.get(symbol)
        if isinstance(raw, str):
            return {"model": raw}
        if isinstance(raw, dict):
            return raw
        return {}

    def _load_bundle(self, artifact_dir: str) -> _RuntimeArtifactBundle | None:
        if artifact_dir in self._bundle_cache:
            return self._bundle_cache[artifact_dir]

        base = Path(artifact_dir)
        rf_path = base / "rf_model.joblib"
        hmm_path = base / "hmm_model.pkl"
        metrics_path = base / "metrics.json"

        if not (rf_path.exists() and hmm_path.exists() and metrics_path.exists()):
            logger.warning("Runtime artifact incomplete: %s", base)
            self._bundle_cache[artifact_dir] = None
            return None

        try:
            rf_model = joblib.load(rf_path)
            with hmm_path.open("rb") as f:
                hmm_model = pickle.load(f)

            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            feature_columns = list(metrics.get("features", [])) or list(DEFAULT_FEATURE_COLUMNS)
            hmm_feature_columns = list(metrics.get("hmm_feature_columns", [])) or ["log_return", "rolling_vol"]
            raw_dist = metrics.get("hmm_state_class_distribution", {})
            state_distribution = {
                int(state): np.array([float(v.get(str(i), 0.0)) for i in _ALL_CLASSES], dtype=float)
                for state, v in raw_dist.items()
                if isinstance(v, dict)
            }
            if not state_distribution:
                logger.warning("Missing HMM state distribution in %s", metrics_path)
                self._bundle_cache[artifact_dir] = None
                return None

            rf_multipliers = np.array(
                metrics.get("rf_calibration", {}).get("best_multipliers", [1.0, 1.0, 1.0]),
                dtype=float,
            )
            if len(rf_multipliers) != len(_ALL_CLASSES):
                rf_multipliers = np.ones(len(_ALL_CLASSES), dtype=float)

            params = metrics.get("params", {})
            bundle = _RuntimeArtifactBundle(
                rf_model=rf_model,
                hmm_model=hmm_model,
                feature_columns=feature_columns,
                hmm_feature_columns=hmm_feature_columns,
                state_distribution=state_distribution,
                rf_multipliers=rf_multipliers,
                rf_weight=float(params.get("rf_weight", 0.7)),
                hmm_weight=float(params.get("hmm_weight", 0.3)),
                hybrid_conf_threshold=float(params.get("hybrid_conf_threshold", 0.55)),
                hybrid_sideways_threshold=float(params.get("hybrid_sideways_threshold", 0.65)),
                hmm_vol_window=int(params.get("hmm_vol_window", 24)),
            )
            self._bundle_cache[artifact_dir] = bundle
            return bundle
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Failed loading runtime artifact %s: %s", base, exc)
            self._bundle_cache[artifact_dir] = None
            return None

    def _build_rf_feature_row(
        self,
        market_data: Any,
        feature_columns: list[str],
    ) -> dict[str, float]:
        row = {col: 0.0 for col in feature_columns}

        direct = {
            "mfi": float(getattr(market_data, "mfi", 0.0)),
            "adx": float(getattr(market_data, "adx", 0.0)),
            "atr": float(getattr(market_data, "atr", 0.0)),
            "volume": float(getattr(market_data, "volume", 0.0)),
            "open_interest_change": 0.0,
            "funding_rate": 0.0,
            "onchain_activity_score": 0.0,
            "sentiment_score": 0.0,
            "policy_event_score": 0.0,
            "derivatives_stress_score": 0.0,
            "external_regime_score": 0.0,
            "volatility_jump": 0.0,
            "data_quality_score": 1.0,
        }
        for k, v in direct.items():
            if k in row:
                row[k] = float(v)
        return row

    def _predict_hmm_proba(
        self,
        *,
        bundle: _RuntimeArtifactBundle,
        history_df: pd.DataFrame | None,
        market_data: Any,
    ) -> np.ndarray | None:
        if history_df is None or history_df.empty:
            return None

        frame = history_df.copy()
        if "close" not in frame.columns:
            frame["close"] = float(getattr(market_data, "close", 0.0))
        for col_name in ("atr", "adx", "volume"):
            if col_name not in frame.columns:
                frame[col_name] = float(getattr(market_data, col_name, 0.0))

        include_atr = "atr_pct" in bundle.hmm_feature_columns
        include_adx = "adx_norm" in bundle.hmm_feature_columns
        include_volume = "volume_z" in bundle.hmm_feature_columns
        hmm_frame = build_hmm_feature_frame_from_table(
            frame,
            vol_window=max(5, int(bundle.hmm_vol_window)),
            include_atr=include_atr,
            include_adx=include_adx,
            include_volume=include_volume,
        )
        for col in bundle.hmm_feature_columns:
            if col not in hmm_frame.columns:
                hmm_frame[col] = 0.0
        hmm_frame = hmm_frame[bundle.hmm_feature_columns].dropna()
        if hmm_frame.empty:
            return None

        last = hmm_frame.iloc[[-1]].to_numpy(dtype=float)
        states = bundle.hmm_model.predict(last)
        return states_to_class_proba(states, bundle.state_distribution, n_classes=len(_ALL_CLASSES))

    def _select_model_proba(
        self,
        *,
        model: str,
        rf_proba: np.ndarray,
        rf_cal_proba: np.ndarray,
        hmm_proba: np.ndarray | None,
        bundle: _RuntimeArtifactBundle,
    ) -> np.ndarray | None:
        if model == "rf":
            return rf_proba
        if model == "rf_calibrated":
            return rf_cal_proba
        if model == "hmm":
            return hmm_proba
        if hmm_proba is None:
            return None
        if model == "ensemble":
            return combine_probabilities(
                rf_proba,
                hmm_proba,
                rf_weight=bundle.rf_weight,
                hmm_weight=bundle.hmm_weight,
            )
        if model == "ensemble_calibrated":
            return combine_probabilities(
                rf_cal_proba,
                hmm_proba,
                rf_weight=bundle.rf_weight,
                hmm_weight=bundle.hmm_weight,
            )
        if model == "hybrid":
            hybrid_pred = apply_sideways_guard(
                rf_pred=rf_cal_proba.argmax(axis=1),
                rf_proba=rf_cal_proba,
                hmm_proba=hmm_proba,
                sideways_class=1,
                conf_threshold=bundle.hybrid_conf_threshold,
                hmm_sideways_threshold=bundle.hybrid_sideways_threshold,
            )
            out = np.zeros_like(rf_cal_proba)
            out[np.arange(len(hybrid_pred)), hybrid_pred] = 1.0
            return out
        return rf_cal_proba

    def _map_regime_3_to_7(
        self,
        *,
        regime_3: str,
        mfi: float,
        adx: float,
    ) -> str:
        if regime_3 == "BULL":
            return "BULL_STRONG" if adx >= 25.0 else "BULL_MODERATE"
        if regime_3 == "BEAR":
            return "BEAR_STRONG" if adx >= 25.0 else "BEAR_MODERATE"
        if mfi >= 54.0:
            return "SIDEWAYS_UP"
        if mfi <= 34.0:
            return "SIDEWAYS_DOWN"
        return "SIDEWAYS_FLAT"

    def _rf_signal_from_regime(self, regime_3: str) -> str:
        if regime_3 == "BULL":
            return "BUY"
        if regime_3 == "BEAR":
            return "SELL"
        return "HOLD"
