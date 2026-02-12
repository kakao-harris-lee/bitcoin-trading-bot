from __future__ import annotations

import json
import pickle
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from trading.regime.runtime import RuntimeRegimeOverlay
from trading.regime.training import DEFAULT_FEATURE_COLUMNS
from trading.strategies.components.models import MarketData


class DummyHMM:
    def predict(self, X):
        return np.ones(len(X), dtype=int)


def _train_rf() -> RandomForestClassifier:
    cols = list(DEFAULT_FEATURE_COLUMNS)
    rows: list[list[float]] = []
    y: list[int] = []

    for mfi in np.linspace(15, 30, 24):
        row = [0.0] * len(cols)
        row[cols.index("mfi")] = float(mfi)
        row[cols.index("adx")] = 20.0
        row[cols.index("atr")] = 1.0
        row[cols.index("volume")] = 1000.0
        rows.append(row)
        y.append(0)

    for mfi in np.linspace(43, 57, 24):
        row = [0.0] * len(cols)
        row[cols.index("mfi")] = float(mfi)
        row[cols.index("adx")] = 16.0
        row[cols.index("atr")] = 1.0
        row[cols.index("volume")] = 1000.0
        rows.append(row)
        y.append(1)

    for mfi in np.linspace(72, 88, 24):
        row = [0.0] * len(cols)
        row[cols.index("mfi")] = float(mfi)
        row[cols.index("adx")] = 30.0
        row[cols.index("atr")] = 1.0
        row[cols.index("volume")] = 1000.0
        rows.append(row)
        y.append(2)

    X = pd.DataFrame(rows, columns=cols)
    model = RandomForestClassifier(n_estimators=120, random_state=7)
    model.fit(X, np.array(y))
    return model


def _write_artifacts(tmp_path, *, multipliers: list[float] | None = None) -> str:
    d = tmp_path / "artifacts"
    d.mkdir(parents=True, exist_ok=True)

    rf = _train_rf()
    joblib.dump(rf, d / "rf_model.joblib")

    with (d / "hmm_model.pkl").open("wb") as f:
        pickle.dump(DummyHMM(), f)

    metrics = {
        "features": list(DEFAULT_FEATURE_COLUMNS),
        "hmm_feature_columns": ["log_return", "rolling_vol"],
        "rf_calibration": {
            "best_multipliers": multipliers or [1.0, 1.0, 1.0],
        },
        "hmm_state_class_distribution": {
            "1": {"0": 0.1, "1": 0.8, "2": 0.1},
        },
        "params": {
            "rf_weight": 0.7,
            "hmm_weight": 0.3,
            "hybrid_conf_threshold": 0.55,
            "hybrid_sideways_threshold": 0.65,
            "hmm_vol_window": 24,
        },
    }
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return str(d)


def _market_data(*, mfi: float, adx: float) -> MarketData:
    return MarketData(
        symbol="BTC",
        close=50000.0,
        mfi=mfi,
        adx=adx,
        rsi=50.0,
        timestamp=1700000000000,
        atr=1200.0,
        volume=1000.0,
        avg_volume_20=900.0,
        high_30d=56000.0,
        prev_high_20=55000.0,
    )


def test_runtime_overlay_predicts_rf_calibrated(tmp_path) -> None:
    artifact_dir = _write_artifacts(tmp_path)

    overlay = RuntimeRegimeOverlay(
        {
            "enabled": True,
            "symbol_models": {
                "BTC": {
                    "model": "rf_calibrated",
                    "artifact_dir": artifact_dir,
                }
            },
        }
    )

    pred = overlay.predict(
        symbol="BTC",
        market_data=_market_data(mfi=84.0, adx=31.0),
        history_df=None,
    )

    assert pred is not None
    assert pred.model == "rf_calibrated"
    assert pred.regime_3 == "BULL"
    assert pred.regime_7 == "BULL_STRONG"
    assert pred.rf_signal == "BUY"


def test_runtime_overlay_ensemble_falls_back_when_hmm_missing(tmp_path) -> None:
    artifact_dir = _write_artifacts(tmp_path)

    overlay = RuntimeRegimeOverlay(
        {
            "enabled": True,
            "symbol_models": {
                "BTC": {
                    "model": "ensemble",
                    "artifact_dir": artifact_dir,
                }
            },
        }
    )

    pred = overlay.predict(
        symbol="BTC",
        market_data=_market_data(mfi=22.0, adx=28.0),
        history_df=None,
    )

    assert pred is not None
    assert pred.model == "rf_calibrated"
    assert pred.regime_3 == "BEAR"
    assert pred.regime_7 == "BEAR_STRONG"
