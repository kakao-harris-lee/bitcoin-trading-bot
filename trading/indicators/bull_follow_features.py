"""Feature engineering helpers for cross-asset bull-follow modeling.

This module builds per-symbol technical features and cross-sectional market
features used by the bull-follow training/backtest pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib


BULL_FOLLOW_FEATURE_COLUMNS: list[str] = [
    "ret_1",
    "ret_3",
    "ret_6",
    "ret_12",
    "ema_ratio_1_20",
    "ema_ratio_1_50",
    "ema_ratio_20_50",
    "ema_ratio_50_200",
    "trend_ema_5_20",
    "trend_ema_20_120",
    "volume_trend_3_24",
    "volume_trend_6_48",
    "illiq_ret3_interaction",
    "trend_volume_interaction",
    "rsi_14",
    "adx_14",
    "plus_di_minus_di",
    "mfi_14",
    "atr_pct_14",
    "bb_width",
    "bb_pct_b",
    "vol_ratio_20",
    "vol_zscore_20",
    "breakout_20",
    "close_pos_range_20",
    "drawdown_50",
    "cs_ret_1_median",
    "cs_ret_3_median",
    "cs_above_ema50_ratio",
    "cs_positive_ret1_ratio",
    "cs_breakout_ratio",
    "cs_volume_ratio_median",
]

# Optional liquidity/risk-transfer features for aggressive universe rotation.
LIQUIDITY_FEATURE_COLUMNS: list[str] = [
    "quote_volume",
    "quote_volume_ratio_20",
    "quote_volume_zscore_20",
    "amihud_illiq_20",
    "range_pct",
    "range_volume_pressure",
    "cs_quote_volume_ratio_median",
    "cs_amihud_illiq_median",
]


@dataclass(frozen=True)
class BullFollowTargetConfig:
    """Forward target construction config."""

    horizon_bars: int = 6
    pnl_downside_penalty: float = 1.0
    pnl_fee_buffer: float = 0.0012


def _safe_div(num: np.ndarray, den: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    den_safe = np.where(np.abs(den) < eps, np.nan, den)
    return num / den_safe


def add_symbol_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add bull-follow technical features for one symbol frame.

    Required columns: timestamp, open, high, low, close, volume
    """
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    out = df.copy()
    out = out.sort_values("timestamp").reset_index(drop=True)

    close = np.asarray(out["close"], dtype=np.float64)
    high = np.asarray(out["high"], dtype=np.float64)
    low = np.asarray(out["low"], dtype=np.float64)
    volume = np.asarray(out["volume"], dtype=np.float64)

    ema5 = talib.EMA(close, timeperiod=5)
    ema20 = talib.EMA(close, timeperiod=20)
    ema120 = talib.EMA(close, timeperiod=120)
    ema50 = talib.EMA(close, timeperiod=50)
    ema200 = talib.EMA(close, timeperiod=200)

    ret_1 = pd.Series(close).pct_change()
    out["ret_1"] = ret_1
    out["ret_3"] = pd.Series(close).pct_change(3)
    out["ret_6"] = pd.Series(close).pct_change(6)
    out["ret_12"] = pd.Series(close).pct_change(12)

    out["ema_ratio_1_20"] = _safe_div(close, ema20)
    out["ema_ratio_1_50"] = _safe_div(close, ema50)
    out["ema_ratio_20_50"] = _safe_div(ema20, ema50)
    out["ema_ratio_50_200"] = _safe_div(ema50, ema200)
    out["trend_ema_5_20"] = _safe_div(ema5, ema20) - 1.0
    out["trend_ema_20_120"] = _safe_div(ema20, ema120) - 1.0

    out["rsi_14"] = talib.RSI(close, timeperiod=14)
    adx = talib.ADX(high, low, close, timeperiod=14)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=14)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=14)
    out["adx_14"] = adx
    out["plus_di_minus_di"] = (plus_di - minus_di) / 100.0
    out["mfi_14"] = talib.MFI(high, low, close, volume, timeperiod=14)

    atr = talib.ATR(high, low, close, timeperiod=14)
    out["atr_pct_14"] = _safe_div(atr, close)

    bb_upper, bb_mid, bb_lower = talib.BBANDS(
        close,
        timeperiod=20,
        nbdevup=2,
        nbdevdn=2,
    )
    out["bb_width"] = _safe_div(bb_upper - bb_lower, bb_mid)
    out["bb_pct_b"] = _safe_div(close - bb_lower, bb_upper - bb_lower)

    vol_s = pd.Series(volume)
    vol_mean20 = vol_s.rolling(20).mean().to_numpy()
    vol_std20 = vol_s.rolling(20).std().to_numpy()
    vol_mean3 = vol_s.rolling(3).mean().to_numpy()
    vol_mean6 = vol_s.rolling(6).mean().to_numpy()
    vol_mean24 = vol_s.rolling(24).mean().to_numpy()
    vol_mean48 = vol_s.rolling(48).mean().to_numpy()
    out["vol_ratio_20"] = _safe_div(volume, vol_mean20)
    out["vol_zscore_20"] = _safe_div(volume - vol_mean20, vol_std20)
    out["volume_trend_3_24"] = _safe_div(vol_mean3, vol_mean24) - 1.0
    out["volume_trend_6_48"] = _safe_div(vol_mean6, vol_mean48) - 1.0

    # Liquidity/flow features
    quote_volume = close * volume
    qv_s = pd.Series(quote_volume)
    qv_mean20 = qv_s.rolling(20).mean().to_numpy()
    qv_std20 = qv_s.rolling(20).std().to_numpy()
    out["quote_volume"] = quote_volume
    out["quote_volume_ratio_20"] = _safe_div(quote_volume, qv_mean20)
    out["quote_volume_zscore_20"] = _safe_div(quote_volume - qv_mean20, qv_std20)

    amihud_raw = np.abs(np.asarray(ret_1, dtype=np.float64)) / np.maximum(
        quote_volume, 1e-12
    )
    out["amihud_illiq_20"] = pd.Series(amihud_raw).rolling(20).mean().to_numpy()
    illiq_med50 = out["amihud_illiq_20"].rolling(50).median().to_numpy()
    out["illiq_ret3_interaction"] = out["ret_3"] * (
        1.0 - _safe_div(out["amihud_illiq_20"].to_numpy(), illiq_med50)
    )
    out["trend_volume_interaction"] = out["trend_ema_5_20"] * out["volume_trend_3_24"]

    high20 = pd.Series(high).rolling(20).max().to_numpy()
    low20 = pd.Series(low).rolling(20).min().to_numpy()
    high50 = pd.Series(high).rolling(50).max().to_numpy()

    out["breakout_20"] = _safe_div(close, high20) - 1.0
    out["close_pos_range_20"] = _safe_div(close - low20, high20 - low20)
    out["drawdown_50"] = _safe_div(close, high50) - 1.0
    out["range_pct"] = _safe_div(high - low, close)
    out["range_volume_pressure"] = out["range_pct"] * out["vol_ratio_20"]

    out["fwd_ret_1"] = pd.Series(close).shift(-1) / pd.Series(close) - 1.0

    return out


def add_cross_sectional_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add cross-sectional features per timestamp across all symbols."""
    if frame.empty:
        return frame

    grouped = frame.groupby("timestamp", sort=False)
    cs = grouped.agg(
        cs_ret_1_median=("ret_1", "median"),
        cs_ret_3_median=("ret_3", "median"),
        cs_above_ema50_ratio=("ema_ratio_1_50", lambda s: float(np.mean(s > 1.0))),
        cs_positive_ret1_ratio=("ret_1", lambda s: float(np.mean(s > 0.0))),
        cs_breakout_ratio=("breakout_20", lambda s: float(np.mean(s > 0.0))),
        cs_volume_ratio_median=("vol_ratio_20", "median"),
        cs_quote_volume_ratio_median=("quote_volume_ratio_20", "median"),
        cs_amihud_illiq_median=("amihud_illiq_20", "median"),
    )
    return frame.merge(cs, left_on="timestamp", right_index=True, how="left")


def _forward_targets(
    close: np.ndarray, horizon_bars: int
) -> tuple[np.ndarray, np.ndarray]:
    n = len(close)
    fwd = np.full(n, np.nan, dtype=np.float64)
    worst = np.full(n, np.nan, dtype=np.float64)
    if horizon_bars <= 0:
        return fwd, worst

    for i in range(0, max(0, n - horizon_bars)):
        base = close[i]
        if not np.isfinite(base) or base <= 0:
            continue

        end_px = close[i + horizon_bars]
        window = close[i + 1 : i + horizon_bars + 1]
        if window.size == 0:
            continue

        fwd[i] = (end_px / base) - 1.0
        worst_px = np.nanmin(window)
        worst[i] = (worst_px / base) - 1.0

    return fwd, worst


def add_forward_targets(
    frame: pd.DataFrame,
    config: BullFollowTargetConfig | None = None,
) -> pd.DataFrame:
    """Add forward/worst targets and cross-sectional excess-return target."""
    cfg = config or BullFollowTargetConfig()
    out = frame.copy()
    out["target_forward_return"] = np.nan
    out["target_worst_drawdown"] = np.nan

    for symbol, grp in out.groupby("symbol", sort=False):
        idx = grp.index.to_numpy()
        close = np.asarray(grp["close"], dtype=np.float64)
        fwd, worst = _forward_targets(close, horizon_bars=cfg.horizon_bars)
        out.loc[idx, "target_forward_return"] = fwd
        out.loc[idx, "target_worst_drawdown"] = worst

    out["cs_forward_return_median"] = out.groupby("timestamp", sort=False)[
        "target_forward_return"
    ].transform("median")
    out["target_forward_excess_return"] = (
        out["target_forward_return"] - out["cs_forward_return_median"]
    )

    downside = np.abs(np.minimum(out["target_worst_drawdown"].to_numpy(), 0.0))
    out["target_forward_pnl_utility"] = (
        out["target_forward_return"].to_numpy()
        - float(cfg.pnl_fee_buffer)
        - float(cfg.pnl_downside_penalty) * downside
    )

    return out


def prepare_universe_features(
    symbol_frames: dict[str, pd.DataFrame],
    target_config: BullFollowTargetConfig | None = None,
    min_history: int = 240,
) -> pd.DataFrame:
    """Build final feature+target frame from raw per-symbol OHLCV frames."""
    if not symbol_frames:
        return pd.DataFrame()

    rows: list[pd.DataFrame] = []
    for symbol, df in symbol_frames.items():
        feat = add_symbol_features(df)
        feat = feat.copy()
        feat["symbol"] = str(symbol).upper()
        feat["symbol_row"] = np.arange(len(feat), dtype=np.int32)
        rows.append(feat)

    frame = pd.concat(rows, ignore_index=True)
    frame = frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    frame = add_cross_sectional_features(frame)
    frame = add_forward_targets(frame, config=target_config)

    if min_history > 0:
        frame = frame[frame["symbol_row"] >= int(min_history)].copy()

    frame = frame.drop(columns=["symbol_row"])
    frame = frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    return frame
