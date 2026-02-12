"""Rule-based hybrid helpers for RF/HMM regime predictions."""
from __future__ import annotations

import numpy as np


def apply_sideways_guard(
    *,
    rf_pred: np.ndarray,
    rf_proba: np.ndarray,
    hmm_proba: np.ndarray,
    sideways_class: int = 1,
    conf_threshold: float = 0.55,
    hmm_sideways_threshold: float = 0.65,
) -> np.ndarray:
    """Guard RF trend predictions using HMM sideways probability.

    Rule:
    - If RF predicts non-sideways class and RF confidence <= conf_threshold
      and HMM sideways probability >= hmm_sideways_threshold,
      override prediction to SIDEWAYS.
    """
    if rf_proba.shape != hmm_proba.shape:
        raise ValueError("rf_proba and hmm_proba must have same shape")
    if rf_proba.ndim != 2:
        raise ValueError("probability arrays must be 2D")
    if len(rf_pred) != len(rf_proba):
        raise ValueError("rf_pred length mismatch with probability arrays")
    if not (0.0 <= conf_threshold <= 1.0):
        raise ValueError("conf_threshold must be in [0, 1]")
    if not (0.0 <= hmm_sideways_threshold <= 1.0):
        raise ValueError("hmm_sideways_threshold must be in [0, 1]")
    if not (0 <= sideways_class < rf_proba.shape[1]):
        raise ValueError("sideways_class out of range")

    rf_pred = np.asarray(rf_pred, dtype=int).copy()
    rf_conf = rf_proba.max(axis=1)
    hmm_sideways = hmm_proba[:, sideways_class]

    mask = (
        (rf_pred != sideways_class)
        & (rf_conf <= conf_threshold)
        & (hmm_sideways >= hmm_sideways_threshold)
    )
    rf_pred[mask] = sideways_class
    return rf_pred
