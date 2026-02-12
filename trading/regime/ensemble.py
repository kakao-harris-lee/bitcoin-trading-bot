"""Helpers for combining RF and HMM regime predictions."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_hmm_feature_frame(close_series: pd.Series, vol_window: int = 24) -> pd.DataFrame:
    """Build HMM input features from close prices.

    Returns a frame aligned to the input index with NaNs during warmup.
    """
    if vol_window < 5:
        raise ValueError("vol_window must be >= 5")

    close = pd.to_numeric(close_series, errors="coerce")
    log_return = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan)
    rolling_vol = log_return.rolling(vol_window, min_periods=max(5, vol_window // 2)).std()
    return pd.DataFrame({"log_return": log_return, "rolling_vol": rolling_vol})


def build_hmm_feature_frame_from_table(
    frame: pd.DataFrame,
    *,
    close_column: str = "close",
    vol_window: int = 24,
    include_atr: bool = True,
    include_adx: bool = True,
    include_volume: bool = True,
) -> pd.DataFrame:
    """Build HMM input features from a regime feature table.

    Base features:
    - log_return
    - rolling_vol

    Optional expanded features:
    - atr_pct: atr / close
    - adx_norm: adx / 100
    - volume_z: rolling z-score of log1p(volume)
    """
    if close_column not in frame.columns:
        raise ValueError(f"missing close column: {close_column}")

    out = build_hmm_feature_frame(frame[close_column], vol_window=vol_window)

    if include_atr and "atr" in frame.columns:
        close = pd.to_numeric(frame[close_column], errors="coerce")
        atr = pd.to_numeric(frame["atr"], errors="coerce")
        out["atr_pct"] = (atr / close.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)

    if include_adx and "adx" in frame.columns:
        adx = pd.to_numeric(frame["adx"], errors="coerce")
        out["adx_norm"] = adx / 100.0

    if include_volume and "volume" in frame.columns:
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        log_vol = np.log1p(volume.clip(lower=0.0))
        mean = log_vol.rolling(vol_window, min_periods=max(5, vol_window // 2)).mean()
        std = log_vol.rolling(vol_window, min_periods=max(5, vol_window // 2)).std()
        out["volume_z"] = ((log_vol - mean) / std.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)

    return out


def build_state_class_distribution(
    states: np.ndarray,
    y: np.ndarray,
    n_classes: int,
) -> dict[int, np.ndarray]:
    """Estimate P(class | state) from training labels."""
    if n_classes < 2:
        raise ValueError("n_classes must be >= 2")
    if len(states) != len(y):
        raise ValueError("states and y length mismatch")

    distributions: dict[int, np.ndarray] = {}
    for state in np.unique(states):
        mask = states == state
        counts = np.bincount(y[mask].astype(int), minlength=n_classes).astype(float)
        total = float(counts.sum())
        if total <= 0:
            distributions[int(state)] = np.full(n_classes, 1.0 / n_classes)
        else:
            distributions[int(state)] = counts / total
    return distributions


def states_to_class_proba(
    states: np.ndarray,
    distributions: dict[int, np.ndarray],
    n_classes: int,
) -> np.ndarray:
    """Convert HMM hidden states into class probabilities."""
    fallback = np.full(n_classes, 1.0 / n_classes)
    out = np.zeros((len(states), n_classes), dtype=float)
    for i, state in enumerate(states):
        probs = distributions.get(int(state), fallback)
        if len(probs) != n_classes:
            raise ValueError("distribution size mismatch")
        out[i] = probs
    return out


def combine_probabilities(
    rf_proba: np.ndarray,
    hmm_proba: np.ndarray,
    *,
    rf_weight: float = 0.7,
    hmm_weight: float = 0.3,
) -> np.ndarray:
    """Combine RF/HMM probabilities with weighted average."""
    if rf_proba.shape != hmm_proba.shape:
        raise ValueError("rf_proba and hmm_proba must have same shape")
    if rf_weight < 0 or hmm_weight < 0:
        raise ValueError("weights must be >= 0")

    total = rf_weight + hmm_weight
    if total <= 0:
        raise ValueError("rf_weight + hmm_weight must be > 0")

    rf_w = rf_weight / total
    hmm_w = hmm_weight / total
    combined = (rf_w * rf_proba) + (hmm_w * hmm_proba)

    row_sum = combined.sum(axis=1, keepdims=True)
    row_sum[row_sum == 0.0] = 1.0
    return combined / row_sum


def predict_proba_all_classes(
    model,
    X: pd.DataFrame,
    all_classes: list[int],
) -> np.ndarray:
    """Predict probabilities and align columns to all_classes ordering."""
    raw = model.predict_proba(X)
    out = np.zeros((len(X), len(all_classes)), dtype=float)

    class_to_col = {int(c): i for i, c in enumerate(all_classes)}
    for src_i, cls in enumerate(model.classes_):
        dst = class_to_col.get(int(cls))
        if dst is not None:
            out[:, dst] = raw[:, src_i]

    row_sum = out.sum(axis=1, keepdims=True)
    zero_mask = row_sum.squeeze() == 0.0
    if np.any(zero_mask):
        out[zero_mask] = 1.0 / len(all_classes)
        row_sum = out.sum(axis=1, keepdims=True)
    return out / row_sum
