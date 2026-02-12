from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading.regime.ensemble import (
    build_hmm_feature_frame,
    build_hmm_feature_frame_from_table,
    build_state_class_distribution,
    combine_probabilities,
    predict_proba_all_classes,
    states_to_class_proba,
)


class _DummyModel:
    def __init__(self, classes_, proba):
        self.classes_ = np.array(classes_)
        self._proba = np.array(proba, dtype=float)

    def predict_proba(self, X):
        return self._proba[: len(X)]


def test_build_hmm_feature_frame_has_columns() -> None:
    close = pd.Series([100, 101, 102, 100, 99, 100, 103, 104, 105, 106])
    feat = build_hmm_feature_frame(close, vol_window=5)

    assert list(feat.columns) == ["log_return", "rolling_vol"]
    assert len(feat) == len(close)


def test_build_hmm_feature_frame_validates_window() -> None:
    with pytest.raises(ValueError, match="vol_window"):
        build_hmm_feature_frame(pd.Series([1, 2, 3, 4, 5]), vol_window=3)


def test_build_hmm_feature_frame_from_table_with_extras() -> None:
    rows = 20
    frame = pd.DataFrame(
        {
            "close": [100 + i for i in range(rows)],
            "atr": [1.0 + (i % 3) * 0.1 for i in range(rows)],
            "adx": [20 + (i % 5) for i in range(rows)],
            "volume": [1000 + i * 5 for i in range(rows)],
        }
    )
    out = build_hmm_feature_frame_from_table(
        frame,
        vol_window=5,
        include_atr=True,
        include_adx=True,
        include_volume=True,
    )
    assert {"log_return", "rolling_vol", "atr_pct", "adx_norm", "volume_z"} <= set(out.columns)
    assert len(out) == rows


def test_build_hmm_feature_frame_from_table_requires_close() -> None:
    with pytest.raises(ValueError, match="missing close column"):
        build_hmm_feature_frame_from_table(pd.DataFrame({"x": [1, 2, 3]}))


def test_build_state_class_distribution_normalized() -> None:
    states = np.array([0, 0, 1, 1, 1])
    y = np.array([2, 2, 1, 0, 1])
    dist = build_state_class_distribution(states, y, n_classes=3)

    assert set(dist.keys()) == {0, 1}
    assert np.isclose(dist[0].sum(), 1.0)
    assert np.isclose(dist[1].sum(), 1.0)
    assert dist[0][2] == 1.0


def test_states_to_class_proba_fallback_uniform() -> None:
    states = np.array([0, 2])
    dist = {0: np.array([0.1, 0.2, 0.7])}
    proba = states_to_class_proba(states, dist, n_classes=3)

    assert proba.shape == (2, 3)
    assert np.allclose(proba[0], [0.1, 0.2, 0.7])
    assert np.allclose(proba[1], [1 / 3, 1 / 3, 1 / 3])


def test_combine_probabilities_weighted() -> None:
    rf = np.array([[0.9, 0.1, 0.0], [0.2, 0.3, 0.5]])
    hmm = np.array([[0.3, 0.7, 0.0], [0.6, 0.2, 0.2]])
    out = combine_probabilities(rf, hmm, rf_weight=0.8, hmm_weight=0.2)

    assert out.shape == (2, 3)
    assert np.allclose(out.sum(axis=1), 1.0)
    assert out[0, 0] > out[0, 1]


def test_predict_proba_all_classes_aligns_columns() -> None:
    model = _DummyModel(classes_=[1, 2], proba=[[0.6, 0.4], [0.2, 0.8]])
    X = pd.DataFrame({"x": [1, 2]})
    out = predict_proba_all_classes(model, X, all_classes=[0, 1, 2])

    assert out.shape == (2, 3)
    assert np.allclose(out[0], [0.0, 0.6, 0.4])
    assert np.allclose(out.sum(axis=1), 1.0)
