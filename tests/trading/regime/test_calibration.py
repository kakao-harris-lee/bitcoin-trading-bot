from __future__ import annotations

import numpy as np
import pytest

from trading.regime.calibration import apply_class_multipliers, tune_class_multipliers


def test_apply_class_multipliers_normalizes() -> None:
    p = np.array([[0.2, 0.3, 0.5], [0.7, 0.2, 0.1]])
    out = apply_class_multipliers(p, [1.0, 2.0, 1.0])

    assert out.shape == p.shape
    assert np.allclose(out.sum(axis=1), 1.0)
    assert out[0, 1] > p[0, 1]


def test_apply_class_multipliers_validates() -> None:
    with pytest.raises(ValueError, match="2D"):
        apply_class_multipliers(np.array([0.2, 0.8]), [1.0, 1.0])
    with pytest.raises(ValueError, match="length"):
        apply_class_multipliers(np.array([[0.2, 0.8]]), [1.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="> 0"):
        apply_class_multipliers(np.array([[0.2, 0.8]]), [1.0, 0.0])


def test_tune_class_multipliers_returns_best_combo() -> None:
    # class 0 is under-predicted initially; multiplier search should improve macro-f1.
    p = np.array(
        [
            [0.45, 0.5, 0.05],
            [0.4, 0.5, 0.1],
            [0.1, 0.2, 0.7],
            [0.1, 0.2, 0.7],
        ]
    )
    y = np.array([0, 0, 2, 2])

    best_mult, best = tune_class_multipliers(p, y, grid_values=[0.8, 1.0, 1.2, 1.5])

    assert len(best_mult) == 3
    assert best["macro_f1"] >= 0.6
    assert best_mult[0] >= 1.0


def test_tune_class_multipliers_validates() -> None:
    p = np.array([[0.3, 0.7]])
    y = np.array([1])
    with pytest.raises(ValueError, match="must not be empty"):
        tune_class_multipliers(p, y, grid_values=[])
