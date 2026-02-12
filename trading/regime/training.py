"""Training utilities for multimodal regime models."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_FEATURE_COLUMNS: tuple[str, ...] = (
    "mfi",
    "adx",
    "atr",
    "volume",
    "onchain_activity_score",
    "sentiment_score",
    "open_interest_change",
    "funding_rate",
    "policy_event_score",
    "derivatives_stress_score",
    "external_regime_score",
    "data_quality_score",
    "volatility_jump",
)

REGIME_TO_CLASS: dict[str, int] = {
    "BEAR": 0,
    "SIDEWAYS": 1,
    "BULL": 2,
}
CLASS_TO_REGIME: dict[int, str] = {v: k for k, v in REGIME_TO_CLASS.items()}


@dataclass(frozen=True)
class SupervisedDataset:
    """Prepared supervised dataset for regime classification."""

    X: pd.DataFrame
    y: pd.Series
    frame: pd.DataFrame


def _safe_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out


def _regime_from_return(ret: float, bull_threshold: float, bear_threshold: float) -> str:
    if ret >= bull_threshold:
        return "BULL"
    if ret <= bear_threshold:
        return "BEAR"
    return "SIDEWAYS"


def add_regime_target(
    frame: pd.DataFrame,
    *,
    close_column: str = "close",
    forward_horizon: int = 24,
    bull_threshold: float = 0.02,
    bear_threshold: float = -0.02,
) -> pd.DataFrame:
    """Add forward-return based regime target columns."""
    if forward_horizon < 1:
        raise ValueError("forward_horizon must be >= 1")
    if bull_threshold <= 0:
        raise ValueError("bull_threshold must be > 0")
    if bear_threshold >= 0:
        raise ValueError("bear_threshold must be < 0")
    if close_column not in frame.columns:
        raise ValueError(f"missing close column: {close_column}")

    out = frame.copy()
    close = pd.to_numeric(out[close_column], errors="coerce")
    future = close.shift(-forward_horizon)
    out["forward_return"] = (future / close.replace(0.0, np.nan)) - 1.0
    out["regime_target"] = out["forward_return"].apply(
        lambda r: _regime_from_return(float(r), bull_threshold, bear_threshold)
        if pd.notna(r)
        else pd.NA
    )
    out["regime_target_class"] = out["regime_target"].map(REGIME_TO_CLASS)
    return out


def build_supervised_dataset(
    frame: pd.DataFrame,
    *,
    feature_columns: list[str] | None = None,
    target_column: str = "regime_target_class",
    dropna_target: bool = True,
) -> SupervisedDataset:
    """Build supervised X/y from a feature table."""
    columns = list(feature_columns or DEFAULT_FEATURE_COLUMNS)
    working = _safe_numeric(frame, columns)

    if target_column not in working.columns:
        raise ValueError(f"missing target column: {target_column}")

    if dropna_target:
        working = working[working[target_column].notna()].copy()

    y = pd.to_numeric(working[target_column], errors="coerce")
    valid = y.notna()
    working = working[valid].copy()
    y = y[valid].astype(int)

    X = working[columns].copy()
    return SupervisedDataset(X=X, y=y, frame=working)


def chronological_split(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Chronologically split dataset into train/val/test."""
    if len(X) != len(y):
        raise ValueError("X and y length mismatch")
    if len(X) < 10:
        raise ValueError("need at least 10 rows for split")
    if not (0.0 < train_ratio < 1.0) or not (0.0 <= val_ratio < 1.0):
        raise ValueError("invalid split ratios")
    if train_ratio + val_ratio >= 1.0:
        raise ValueError("train_ratio + val_ratio must be < 1")

    n = len(X)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    X_train = X.iloc[:train_end].copy()
    X_val = X.iloc[train_end:val_end].copy()
    X_test = X.iloc[val_end:].copy()

    y_train = y.iloc[:train_end].copy()
    y_val = y.iloc[train_end:val_end].copy()
    y_test = y.iloc[val_end:].copy()
    return X_train, X_val, X_test, y_train, y_val, y_test


def compute_class_weight_map(y: pd.Series) -> dict[int, float]:
    """Compute inverse-frequency class weights."""
    if y.empty:
        return {}

    counts = y.value_counts().sort_index()
    total = float(len(y))
    n_classes = float(len(counts))
    return {int(cls): float(total / (n_classes * cnt)) for cls, cnt in counts.items() if cnt > 0}
