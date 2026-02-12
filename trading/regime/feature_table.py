"""Build multimodal regime feature tables from local datasets."""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from .fusion import (
    compute_derivatives_stress,
    compute_external_regime_score,
    detect_volatility_jumps,
)


REQUIRED_PRICE_COLUMNS = {"timestamp", "close"}
OPTIONAL_PRICE_COLUMNS = {"symbol", "volume", "mfi", "adx", "atr"}

EXTERNAL_COLUMNS = {
    "onchain_activity_score",
    "sentiment_score",
    "open_interest_change",
    "funding_rate",
    "policy_event_score",
}


def _normalize_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce", utc=True).dt.tz_localize(None)
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp")
    return out


def _require_columns(df: pd.DataFrame, columns: Iterable[str], frame_name: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{frame_name} missing required columns: {missing}")


def _merge_asof_external(
    base: pd.DataFrame,
    ext: pd.DataFrame | None,
    *,
    columns: list[str],
    tolerance: pd.Timedelta,
) -> pd.DataFrame:
    if ext is None or ext.empty:
        out = base.copy()
        for col in columns:
            out[col] = pd.NA
        return out

    ext2 = _normalize_timestamp(ext)
    _require_columns(ext2, ["timestamp"], "external")

    if "symbol" in base.columns and "symbol" in ext2.columns:
        left = base.sort_values(["symbol", "timestamp"])
        right = ext2.sort_values(["symbol", "timestamp"])
        merged = pd.merge_asof(
            left,
            right[["symbol", "timestamp", *[c for c in columns if c in right.columns]]],
            on="timestamp",
            by="symbol",
            direction="backward",
            tolerance=tolerance,
        )
        return merged.sort_index()

    left = base.sort_values("timestamp")
    right = ext2.sort_values("timestamp")
    merged = pd.merge_asof(
        left,
        right[["timestamp", *[c for c in columns if c in right.columns]]],
        on="timestamp",
        direction="backward",
        tolerance=tolerance,
    )
    return merged.sort_index()


def _trend_label_from_returns(returns: pd.Series, eps: float = 0.001) -> pd.Series:
    labels = pd.Series("NEUTRAL", index=returns.index, dtype="object")
    labels[returns > eps] = "BULL"
    labels[returns < -eps] = "BEAR"
    return labels


def _attach_multitimeframe_trends(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.sort_values("timestamp")
    close = pd.to_numeric(out["close"], errors="coerce").ffill().fillna(0.0)

    ret_1h = close.pct_change()
    trend_1h = _trend_label_from_returns(ret_1h)

    indexed = out.set_index("timestamp")
    c4 = indexed["close"].resample("4h").last().pct_change()
    c1d = indexed["close"].resample("1D").last().pct_change()
    trend_4h = _trend_label_from_returns(c4).reindex(indexed.index, method="ffill").fillna("NEUTRAL")
    trend_1d = _trend_label_from_returns(c1d).reindex(indexed.index, method="ffill").fillna("NEUTRAL")

    out["trend_1h"] = trend_1h.values
    out["trend_4h"] = trend_4h.values
    out["trend_1d"] = trend_1d.values
    return out


def build_regime_feature_table(
    *,
    price_df: pd.DataFrame,
    onchain_df: pd.DataFrame | None = None,
    sentiment_df: pd.DataFrame | None = None,
    derivatives_df: pd.DataFrame | None = None,
    policy_df: pd.DataFrame | None = None,
    join_tolerance: str = "4h",
    vol_jump_window: int = 48,
    vol_jump_z: float = 2.0,
) -> pd.DataFrame:
    """Build 1h-aligned multimodal regime feature table."""
    price = _normalize_timestamp(price_df)
    _require_columns(price, REQUIRED_PRICE_COLUMNS, "price")

    if "symbol" not in price.columns:
        price["symbol"] = "BTC"
    for col in OPTIONAL_PRICE_COLUMNS:
        if col not in price.columns:
            price[col] = 0.0

    tolerance = pd.Timedelta(join_tolerance)
    merged = price.copy()
    merged = _merge_asof_external(
        merged,
        onchain_df,
        columns=["onchain_activity_score"],
        tolerance=tolerance,
    )
    merged = _merge_asof_external(
        merged,
        sentiment_df,
        columns=["sentiment_score"],
        tolerance=tolerance,
    )
    merged = _merge_asof_external(
        merged,
        derivatives_df,
        columns=["open_interest_change", "funding_rate"],
        tolerance=tolerance,
    )
    merged = _merge_asof_external(
        merged,
        policy_df,
        columns=["policy_event_score"],
        tolerance=tolerance,
    )

    for col in EXTERNAL_COLUMNS:
        if col not in merged.columns:
            merged[col] = pd.NA

    coverage_cols = [
        "onchain_activity_score",
        "sentiment_score",
        "open_interest_change",
        "funding_rate",
        "policy_event_score",
    ]
    merged["data_quality_score"] = (
        merged[coverage_cols].notna().sum(axis=1) / float(len(coverage_cols))
    ).clip(lower=0.0, upper=1.0)

    for col in coverage_cols:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)

    merged["derivatives_stress_score"] = merged.apply(
        lambda r: compute_derivatives_stress(
            open_interest_change=float(r["open_interest_change"]),
            funding_rate=float(r["funding_rate"]),
        ),
        axis=1,
    )
    merged["external_regime_score"] = merged.apply(
        lambda r: compute_external_regime_score(
            onchain_score=float(r["onchain_activity_score"]),
            sentiment_score=float(r["sentiment_score"]),
            derivatives_score=float(r["derivatives_stress_score"]),
            policy_score=float(r["policy_event_score"]),
        ),
        axis=1,
    )

    close = pd.to_numeric(merged["close"], errors="coerce").fillna(0.0)
    atr = pd.to_numeric(merged["atr"], errors="coerce").fillna(0.0)
    volatility = (atr / close.replace(0.0, pd.NA)).fillna(0.0)
    merged["volatility_jump"] = detect_volatility_jumps(
        volatility_series=volatility,
        window=vol_jump_window,
        z_threshold=vol_jump_z,
    )

    merged = _attach_multitimeframe_trends(merged)
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    return merged
