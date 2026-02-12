"""Probability calibration helpers for regime classifiers."""
from __future__ import annotations

from itertools import product
from typing import Iterable

import numpy as np
from sklearn.metrics import f1_score


def apply_class_multipliers(proba: np.ndarray, multipliers: Iterable[float]) -> np.ndarray:
    """Apply per-class multipliers and renormalize probabilities."""
    p = np.asarray(proba, dtype=float)
    m = np.asarray(list(multipliers), dtype=float)
    if p.ndim != 2:
        raise ValueError("proba must be 2D")
    if len(m) != p.shape[1]:
        raise ValueError("multipliers length must match number of classes")
    if np.any(m <= 0):
        raise ValueError("all multipliers must be > 0")

    out = p * m.reshape(1, -1)
    row_sum = out.sum(axis=1, keepdims=True)
    row_sum[row_sum == 0.0] = 1.0
    return out / row_sum


def tune_class_multipliers(
    proba: np.ndarray,
    y_true: np.ndarray,
    *,
    grid_values: Iterable[float],
) -> tuple[np.ndarray, dict[str, float]]:
    """Grid-search class multipliers to maximize macro F1."""
    p = np.asarray(proba, dtype=float)
    y = np.asarray(y_true, dtype=int)
    if p.ndim != 2:
        raise ValueError("proba must be 2D")
    if len(p) != len(y):
        raise ValueError("proba and y_true length mismatch")

    values = [float(v) for v in grid_values]
    if not values:
        raise ValueError("grid_values must not be empty")
    if any(v <= 0 for v in values):
        raise ValueError("all grid values must be > 0")

    n_classes = p.shape[1]
    best_mult = np.ones(n_classes, dtype=float)
    best_f1 = -1.0
    best_acc = -1.0

    for combo in product(values, repeat=n_classes):
        calibrated = apply_class_multipliers(p, combo)
        pred = calibrated.argmax(axis=1)
        macro_f1 = float(f1_score(y, pred, average="macro"))
        acc = float((pred == y).mean())
        if (macro_f1 > best_f1) or (macro_f1 == best_f1 and acc > best_acc):
            best_f1 = macro_f1
            best_acc = acc
            best_mult = np.array(combo, dtype=float)

    return best_mult, {"macro_f1": best_f1, "accuracy": best_acc}
