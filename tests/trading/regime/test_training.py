from __future__ import annotations

import pandas as pd
import pytest

from trading.regime.training import (
    add_regime_target,
    build_supervised_dataset,
    chronological_split,
    compute_class_weight_map,
)


def _base_frame(rows: int = 60) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=rows, freq="1h")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "close": [100 + i * 0.5 for i in range(rows)],
            "mfi": [50 + (i % 10) for i in range(rows)],
            "adx": [20 + (i % 5) for i in range(rows)],
            "atr": [1.0 + (i % 3) * 0.1 for i in range(rows)],
            "volume": [1000 + i for i in range(rows)],
            "onchain_activity_score": [0.2] * rows,
            "sentiment_score": [0.1] * rows,
            "open_interest_change": [0.01] * rows,
            "funding_rate": [0.0001] * rows,
            "policy_event_score": [0.0] * rows,
            "derivatives_stress_score": [0.05] * rows,
            "external_regime_score": [0.1] * rows,
            "data_quality_score": [0.8] * rows,
            "volatility_jump": [0] * rows,
        }
    )


def test_add_regime_target_creates_columns() -> None:
    frame = _base_frame()
    out = add_regime_target(frame, forward_horizon=4, bull_threshold=0.01, bear_threshold=-0.01)

    assert "forward_return" in out.columns
    assert "regime_target" in out.columns
    assert "regime_target_class" in out.columns
    assert out["regime_target"].dropna().isin(["BULL", "BEAR", "SIDEWAYS"]).all()


def test_add_regime_target_validates_args() -> None:
    frame = _base_frame()
    with pytest.raises(ValueError, match="forward_horizon"):
        add_regime_target(frame, forward_horizon=0)
    with pytest.raises(ValueError, match="bull_threshold"):
        add_regime_target(frame, bull_threshold=0.0)
    with pytest.raises(ValueError, match="bear_threshold"):
        add_regime_target(frame, bear_threshold=0.0)


def test_build_supervised_dataset_and_split() -> None:
    frame = add_regime_target(_base_frame(), forward_horizon=3, bull_threshold=0.005, bear_threshold=-0.005)
    data = build_supervised_dataset(frame)

    assert len(data.X) == len(data.y)
    assert len(data.X) > 10

    X_train, X_val, X_test, y_train, y_val, y_test = chronological_split(data.X, data.y)
    assert len(X_train) > 0
    assert len(X_val) > 0
    assert len(X_test) > 0
    assert len(X_train) + len(X_val) + len(X_test) == len(data.X)
    assert len(y_train) + len(y_val) + len(y_test) == len(data.y)


def test_compute_class_weight_map_non_empty() -> None:
    y = pd.Series([0, 0, 1, 2, 2, 2])
    weights = compute_class_weight_map(y)

    assert set(weights.keys()) == {0, 1, 2}
    assert weights[1] > weights[2]  # rarer class gets higher weight
    assert weights[0] > 0.0


def test_chronological_split_validates_small_dataset() -> None:
    X = pd.DataFrame({"x": list(range(8))})
    y = pd.Series([0] * 8)
    with pytest.raises(ValueError, match="at least 10"):
        chronological_split(X, y)
