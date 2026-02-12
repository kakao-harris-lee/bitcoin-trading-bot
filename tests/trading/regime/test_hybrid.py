from __future__ import annotations

import numpy as np
import pytest

from trading.regime.hybrid import apply_sideways_guard


def test_apply_sideways_guard_overrides_low_conf_trend() -> None:
    rf_pred = np.array([2, 0, 1])
    rf_proba = np.array(
        [
            [0.2, 0.3, 0.5],  # low-conf BULL
            [0.45, 0.4, 0.15],  # low-conf BEAR
            [0.1, 0.8, 0.1],  # SIDEWAYS
        ]
    )
    hmm_proba = np.array(
        [
            [0.1, 0.75, 0.15],
            [0.2, 0.7, 0.1],
            [0.1, 0.9, 0.0],
        ]
    )

    out = apply_sideways_guard(
        rf_pred=rf_pred,
        rf_proba=rf_proba,
        hmm_proba=hmm_proba,
        conf_threshold=0.55,
        hmm_sideways_threshold=0.65,
    )

    assert out.tolist() == [1, 1, 1]


def test_apply_sideways_guard_keeps_high_conf_trend() -> None:
    rf_pred = np.array([2])
    rf_proba = np.array([[0.05, 0.15, 0.8]])
    hmm_proba = np.array([[0.1, 0.9, 0.0]])

    out = apply_sideways_guard(
        rf_pred=rf_pred,
        rf_proba=rf_proba,
        hmm_proba=hmm_proba,
        conf_threshold=0.55,
        hmm_sideways_threshold=0.65,
    )
    assert out.tolist() == [2]


def test_apply_sideways_guard_validates_inputs() -> None:
    rf_pred = np.array([1, 2])
    rf_proba = np.array([[0.2, 0.3, 0.5], [0.3, 0.4, 0.3]])
    hmm_proba = np.array([[0.1, 0.9, 0.0]])

    with pytest.raises(ValueError, match="same shape"):
        apply_sideways_guard(rf_pred=rf_pred, rf_proba=rf_proba, hmm_proba=hmm_proba)

    with pytest.raises(ValueError, match="conf_threshold"):
        apply_sideways_guard(
            rf_pred=np.array([1]),
            rf_proba=np.array([[0.2, 0.3, 0.5]]),
            hmm_proba=np.array([[0.2, 0.6, 0.2]]),
            conf_threshold=1.2,
        )
