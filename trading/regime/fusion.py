"""Fusion and normalization helpers for multimodal regime signals."""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd


DEFAULT_EXTERNAL_WEIGHTS: dict[str, float] = {
    "onchain": 0.35,
    "sentiment": 0.25,
    "derivatives": 0.25,
    "policy": 0.15,
}


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return float(max(low, min(high, value)))


def normalize_signal(value: float, scale: float) -> float:
    """Normalize unbounded signal into [-1, 1] with tanh."""
    if scale <= 0:
        raise ValueError("scale must be > 0")
    if pd.isna(value):
        return 0.0
    return clamp(float(np.tanh(float(value) / scale)))


def compute_derivatives_stress(
    open_interest_change: float,
    funding_rate: float,
) -> float:
    """Compute derivatives stress score from OI and funding.

    Positive values indicate bullish leverage build-up.
    Negative values indicate bearish pressure / de-risking.
    """
    oi_component = normalize_signal(open_interest_change, scale=0.05)
    funding_component = normalize_signal(funding_rate, scale=0.0005)
    return clamp((0.6 * oi_component) + (0.4 * funding_component))


def compute_external_regime_score(
    *,
    onchain_score: float,
    sentiment_score: float,
    derivatives_score: float,
    policy_score: float,
    weights: Mapping[str, float] | None = None,
) -> float:
    """Combine external signals into single exogenous regime score."""
    w = dict(DEFAULT_EXTERNAL_WEIGHTS)
    if weights:
        w.update(weights)

    total_weight = sum(abs(float(v)) for v in w.values())
    if total_weight <= 0:
        return 0.0

    score = (
        float(w["onchain"]) * clamp(onchain_score)
        + float(w["sentiment"]) * clamp(sentiment_score)
        + float(w["derivatives"]) * clamp(derivatives_score)
        + float(w["policy"]) * clamp(policy_score)
    ) / total_weight
    return clamp(score)


def detect_volatility_jumps(
    volatility_series: pd.Series,
    window: int = 48,
    z_threshold: float = 2.0,
) -> pd.Series:
    """Detect structural volatility jumps from volatility z-score."""
    if window < 5:
        raise ValueError("window must be >= 5")
    if z_threshold <= 0:
        raise ValueError("z_threshold must be > 0")

    series = pd.to_numeric(volatility_series, errors="coerce").fillna(0.0)
    rolling_mean = series.rolling(window=window, min_periods=max(5, window // 2)).mean()
    rolling_std = series.rolling(window=window, min_periods=max(5, window // 2)).std()
    zscore = (series - rolling_mean) / rolling_std.replace(0.0, np.nan)
    zscore = zscore.fillna(0.0)
    return (zscore > z_threshold).astype(int)
