"""
MLP Direction Strategy Feature Extraction Module.

Paper reference: Parente & Rizzuti (2025) - "Trading strategy for Bitcoin and Ethereum
by neural network model" (https://doi.org/10.1007/s00500-025-10980-7)

This module provides feature sets:
1) paper_36: 23 candlestick patterns + 6 indicators + 4 EMA crossovers + 3 temporal features
2) shap_13: reduced 13-feature set derived from SHAP analysis (legacy)
3) v2_36: 23 effective technical indicators + 6 indicators + 4 EMA crossovers + 3 temporal features
4) cross_44: paper_36 + 8 cross-asset features
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib

FEATURE_SET_PAPER = "paper_36"
FEATURE_SET_SHAP = "shap_13"
FEATURE_SET_CROSS = "cross_44"  # paper_36 + 8 cross-asset features
FEATURE_SET_V2 = "v2_36"  # Replaces candlestick patterns with effective indicators

# Feature names for reference (legacy SHAP 13)
FEATURE_NAMES_SHAP = [
    "bollinger_pct_b",
    "rsi",
    "ultosc",
    "ema_cross_1_21",
    "ema_cross_21_50",
    "ema_cross_50_100",
    "ema_cross_1_50",
    "price_zscore",
    "volume_zscore",
    "hour_of_day",
    "day_of_week",
    "month",
    "close_pct_change",
]

NUM_FEATURES_SHAP = len(FEATURE_NAMES_SHAP)

# Candlestick patterns (paper uses 23 patterns from Pring 1991).
# NOTE: The paper does not enumerate the exact list; this default list uses
# common Pring-style patterns available in TA-Lib. Adjust if you have the
# exact list from the authors.
CANDLE_PATTERNS_PAPER = [
    ("doji", talib.CDLDOJI),
    ("dragonfly_doji", talib.CDLDRAGONFLYDOJI),
    ("gravestone_doji", talib.CDLGRAVESTONEDOJI),
    ("engulfing", talib.CDLENGULFING),
    ("hammer", talib.CDLHAMMER),
    ("hanging_man", talib.CDLHANGINGMAN),
    ("inverted_hammer", talib.CDLINVERTEDHAMMER),
    ("shooting_star", talib.CDLSHOOTINGSTAR),
    ("morning_star", talib.CDLMORNINGSTAR),
    ("evening_star", talib.CDLEVENINGSTAR),
    ("morning_doji_star", talib.CDLMORNINGDOJISTAR),
    ("evening_doji_star", talib.CDLEVENINGDOJISTAR),
    ("piercing", talib.CDLPIERCING),
    ("dark_cloud_cover", talib.CDLDARKCLOUDCOVER),
    ("harami", talib.CDLHARAMI),
    ("harami_cross", talib.CDLHARAMICROSS),
    ("spinning_top", talib.CDLSPINNINGTOP),
    ("3_white_soldiers", talib.CDL3WHITESOLDIERS),
    ("3_black_crows", talib.CDL3BLACKCROWS),
    ("3_inside", talib.CDL3INSIDE),
    ("3_outside", talib.CDL3OUTSIDE),
    ("2_crows", talib.CDL2CROWS),
    ("belt_hold", talib.CDLBELTHOLD),
]

FEATURE_NAMES_PAPER = (
    [f"cdl_{name}" for name, _ in CANDLE_PATTERNS_PAPER]
    + [
        "bollinger_pct_b",
        "ultosc",
        "rsi",
        "close_pct_change",
        "price_zscore",
        "volume_zscore",
        "ema_cross_1_20",
        "ema_cross_20_50",
        "ema_cross_50_100",
        "ema_cross_1_50",
        "samples_in_day",
        "day_of_week",
        "month",
    ]
)

NUM_FEATURES_PAPER = len(FEATURE_NAMES_PAPER)

# Cross-asset feature names (8 additional features)
CROSS_ASSET_FEATURE_NAMES = [
    "btc_return_4h",      # BTC 4-hour return
    "btc_return_24h",     # BTC 24-hour return
    "btc_volatility",     # BTC 20-period volatility
    "btc_correlation",    # Correlation with BTC (rolling 20)
    "market_momentum",    # Average return of top coins
    "market_volatility",  # Average volatility of top coins
    "volume_ratio",       # Asset volume / market average volume
    "dominance_change",   # Change in BTC dominance proxy
]

FEATURE_NAMES_CROSS = FEATURE_NAMES_PAPER + CROSS_ASSET_FEATURE_NAMES
NUM_FEATURES_CROSS = len(FEATURE_NAMES_CROSS)  # 36 + 8 = 44

# V2 feature set: replaces 23 candlestick patterns with proven technical indicators.
# Keeps the 13 effective features from paper_36 (6 tech + 4 EMA + 3 temporal) and
# adds 23 new technical indicators that capture momentum, trend, volatility, volume,
# and support/resistance dynamics.
FEATURE_NAMES_V2 = [
    # === 13 KEPT from paper_36 (proven effective by SHAP analysis) ===
    "bollinger_pct_b",     # 0  - (close - lower) / band_width
    "ultosc",              # 1  - Ultimate Oscillator (7/14/28)
    "rsi",                 # 2  - RSI(14)
    "close_pct_change",    # 3  - 1-bar price change
    "price_zscore",        # 4  - (close - SMA30) / STD30
    "volume_zscore",       # 5  - (volume - SMA30) / STD30
    "ema_cross_1_20",      # 6  - close / EMA(20)
    "ema_cross_20_50",     # 7  - EMA(20) / EMA(50)
    "ema_cross_50_100",    # 8  - EMA(50) / EMA(100)
    "ema_cross_1_50",      # 9  - close / EMA(50)
    "samples_in_day",      # 10 - hour // 4 (for 4H bars)
    "day_of_week",         # 11 - 0-6
    "month",               # 12 - 1-12
    # === 23 NEW replacements for candlestick patterns ===
    "macd_hist",           # 13 - MACD histogram (trend momentum)
    "macd_signal_dist",    # 14 - (MACD - Signal) / price (crossover proximity)
    "adx",                 # 15 - ADX(14) trend strength (0-100)
    "plus_di_minus_di",    # 16 - (+DI - -DI) / 100 (directional strength)
    "stoch_k",             # 17 - Stochastic %K (0-100)
    "stoch_d",             # 18 - Stochastic %D (0-100)
    "mfi",                 # 19 - Money Flow Index (0-100)
    "atr_pct",             # 20 - ATR / price (normalized volatility)
    "bb_width",            # 21 - (upper - lower) / middle (volatility regime)
    "return_4bar",         # 22 - 4-bar return (16H momentum for 4H data)
    "return_6bar",         # 23 - 6-bar return (24H momentum)
    "return_30bar",        # 24 - 30-bar return (5-day momentum)
    "vol_ratio_20",        # 25 - volume / SMA(volume, 20)
    "ema_cross_1_200",     # 26 - close / EMA(200) (macro trend)
    "ema_cross_100_200",   # 27 - EMA(100) / EMA(200) (golden/death cross)
    "rsi_ema",             # 28 - EMA(RSI, 14) (smoothed momentum)
    "high_low_range",      # 29 - (high - low) / close (bar range %)
    "close_vs_high20",     # 30 - close / 20-period high (distance from resistance)
    "close_vs_low20",      # 31 - close / 20-period low (distance from support)
    "market_stress",       # 32 - composite stress indicator (0-100)
    "obv_zscore",          # 33 - OBV z-score (accumulation/distribution)
    "willr",               # 34 - Williams %R (-100 to 0)
    "cci",                 # 35 - Commodity Channel Index
]

NUM_FEATURES_V2 = len(FEATURE_NAMES_V2)  # 36


def calculate_mlp_features(
    df: pd.DataFrame,
    bwin: int = 5,
    include_temporal: bool = True,
    feature_set: str = FEATURE_SET_SHAP,
    btc_df: pd.DataFrame | None = None,
    market_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Dispatch to the requested feature set.

    Args:
        df: DataFrame with OHLCV data for the target asset
        bwin: Backward window (unused, kept for API compatibility)
        include_temporal: Whether to include temporal features
        feature_set: Feature set name ('paper_36', 'shap_13', 'cross_44')
        btc_df: BTC OHLCV DataFrame (required for cross_44 when target is not BTC)
        market_df: Market aggregate DataFrame with columns ['avg_return', 'avg_volatility', 'avg_volume']
                   (optional for cross_44, will use defaults if not provided)

    Returns:
        DataFrame with features
    """
    if feature_set == FEATURE_SET_PAPER:
        return calculate_mlp_features_paper(df, include_temporal=include_temporal)
    if feature_set == FEATURE_SET_SHAP:
        return calculate_mlp_features_shap(df, include_temporal=include_temporal)
    if feature_set == FEATURE_SET_CROSS:
        return calculate_mlp_features_cross(
            df,
            include_temporal=include_temporal,
            btc_df=btc_df,
            market_df=market_df,
        )
    if feature_set == FEATURE_SET_V2:
        return calculate_mlp_features_v2(df, include_temporal=include_temporal)
    raise ValueError(f"Unknown feature_set: {feature_set}")


def calculate_mlp_features_paper(
    df: pd.DataFrame,
    include_temporal: bool = True,
) -> pd.DataFrame:
    """
    Calculate the 36 paper features from OHLCV data.

    Feature groups:
    - 23 candlestick patterns (TA-Lib pattern outputs)
    - 6 technical indicators: Bollinger %B, ULTOSC, RSI, Close % Change, Z-Score, Volume Z-Score
    - 4 EMA crossovers: EMA(1/20), EMA(20/50), EMA(50/100), EMA(1/50)
    - 3 temporal features: samples_in_day, day_of_week, month

    Args:
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
             and optionally 'timestamp'
        include_temporal: Whether to include temporal features

    Returns:
        DataFrame with 36 feature columns (paper feature order)
    """
    # Use np.asarray to avoid copying if dtype already matches
    open_ = np.asarray(df["open"].values, dtype=np.float64)
    high = np.asarray(df["high"].values, dtype=np.float64)
    low = np.asarray(df["low"].values, dtype=np.float64)
    close = np.asarray(df["close"].values, dtype=np.float64)
    volume = np.asarray(df["volume"].values, dtype=np.float64)

    features = pd.DataFrame(index=df.index)

    # 1) Candlestick patterns (TA-Lib outputs: -100, 0, +100)
    for name, func in CANDLE_PATTERNS_PAPER:
        features[f"cdl_{name}"] = func(open_, high, low, close)

    # 2) Technical indicators (paper uses 14-period Bollinger)
    upper, middle, lower = talib.BBANDS(close, timeperiod=14, nbdevup=2, nbdevdn=2)
    band_width = upper - lower
    band_width = np.where(band_width < 1e-10, 1e-10, band_width)
    features["bollinger_pct_b"] = (close - lower) / band_width

    features["ultosc"] = talib.ULTOSC(high, low, close, timeperiod1=7, timeperiod2=14, timeperiod3=28)
    features["rsi"] = talib.RSI(close, timeperiod=14)

    close_series = pd.Series(close, index=df.index)
    features["close_pct_change"] = close_series.pct_change()

    sma30 = talib.SMA(close, timeperiod=30)
    std30 = talib.STDDEV(close, timeperiod=30)
    std30_safe = np.where(std30 < 1e-10, 1e-10, std30)
    features["price_zscore"] = (close - sma30) / std30_safe

    vol_sma = talib.SMA(volume, timeperiod=30)
    vol_std = talib.STDDEV(volume, timeperiod=30)
    vol_std_safe = np.where(vol_std < 1e-10, 1e-10, vol_std)
    features["volume_zscore"] = (volume - vol_sma) / vol_std_safe

    # 3) EMA crossovers (paper uses 1/20/50/100)
    ema20 = talib.EMA(close, timeperiod=20)
    ema50 = talib.EMA(close, timeperiod=50)
    ema100 = talib.EMA(close, timeperiod=100)

    features["ema_cross_1_20"] = np.where(np.isnan(ema20), np.nan, close / ema20)
    features["ema_cross_20_50"] = np.where(np.isnan(ema50) | np.isnan(ema20), np.nan, ema20 / ema50)
    features["ema_cross_50_100"] = np.where(np.isnan(ema100) | np.isnan(ema50), np.nan, ema50 / ema100)
    features["ema_cross_1_50"] = np.where(np.isnan(ema50), np.nan, close / ema50)

    # 4) Temporal features (paper: samples-in-day, day-of-week, month)
    if include_temporal and "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
        features["samples_in_day"] = (ts.dt.hour // 4).astype(np.float64)
        features["day_of_week"] = ts.dt.dayofweek.astype(np.float64)
        features["month"] = ts.dt.month.astype(np.float64)
    else:
        features["samples_in_day"] = 0.0
        features["day_of_week"] = 0.0
        features["month"] = 0.0

    return features


def calculate_mlp_features_v2(
    df: pd.DataFrame,
    include_temporal: bool = True,
) -> pd.DataFrame:
    """
    Calculate 36 v2 features from OHLCV data.

    Replaces 23 ineffective candlestick patterns from paper_36 with proven
    technical indicators while keeping the 13 effective features identified
    by SHAP analysis.

    Feature groups:
    - 6 technical indicators (kept from paper_36): Bollinger %B, ULTOSC, RSI,
      Close % Change, Price Z-Score, Volume Z-Score
    - 4 EMA crossovers (kept): 1/20, 20/50, 50/100, 1/50
    - 3 temporal features (kept): samples_in_day, day_of_week, month
    - 23 new technical indicators: MACD, ADX, Stochastic, MFI, ATR, BB width,
      multi-period returns, macro EMA crossovers, RSI smoothed, range, S/R levels,
      market stress, OBV, Williams %R, CCI

    Args:
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
             and optionally 'timestamp'
        include_temporal: Whether to include temporal features

    Returns:
        DataFrame with 36 feature columns (v2 feature order)
    """
    open_ = np.asarray(df["open"].values, dtype=np.float64)
    high = np.asarray(df["high"].values, dtype=np.float64)
    low = np.asarray(df["low"].values, dtype=np.float64)
    close = np.asarray(df["close"].values, dtype=np.float64)
    volume = np.asarray(df["volume"].values, dtype=np.float64)

    features = pd.DataFrame(index=df.index)
    close_series = pd.Series(close, index=df.index)
    volume_series = pd.Series(volume, index=df.index)

    # === 13 KEPT features (same calculation as paper_36) ===

    # Bollinger %B (14-period, same as paper)
    upper, middle, lower = talib.BBANDS(close, timeperiod=14, nbdevup=2, nbdevdn=2)
    band_width = upper - lower
    band_width = np.where(band_width < 1e-10, 1e-10, band_width)
    features["bollinger_pct_b"] = (close - lower) / band_width

    features["ultosc"] = talib.ULTOSC(high, low, close, timeperiod1=7, timeperiod2=14, timeperiod3=28)
    features["rsi"] = talib.RSI(close, timeperiod=14)
    features["close_pct_change"] = close_series.pct_change()

    sma30 = talib.SMA(close, timeperiod=30)
    std30 = talib.STDDEV(close, timeperiod=30)
    std30_safe = np.where(std30 < 1e-10, 1e-10, std30)
    features["price_zscore"] = (close - sma30) / std30_safe

    vol_sma30 = talib.SMA(volume, timeperiod=30)
    vol_std30 = talib.STDDEV(volume, timeperiod=30)
    vol_std30_safe = np.where(vol_std30 < 1e-10, 1e-10, vol_std30)
    features["volume_zscore"] = (volume - vol_sma30) / vol_std30_safe

    ema20 = talib.EMA(close, timeperiod=20)
    ema50 = talib.EMA(close, timeperiod=50)
    ema100 = talib.EMA(close, timeperiod=100)

    features["ema_cross_1_20"] = np.where(np.isnan(ema20), np.nan, close / ema20)
    features["ema_cross_20_50"] = np.where(np.isnan(ema50) | np.isnan(ema20), np.nan, ema20 / ema50)
    features["ema_cross_50_100"] = np.where(np.isnan(ema100) | np.isnan(ema50), np.nan, ema50 / ema100)
    features["ema_cross_1_50"] = np.where(np.isnan(ema50), np.nan, close / ema50)

    # Temporal features
    if include_temporal and "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
        features["samples_in_day"] = (ts.dt.hour // 4).astype(np.float64)
        features["day_of_week"] = ts.dt.dayofweek.astype(np.float64)
        features["month"] = ts.dt.month.astype(np.float64)
    else:
        features["samples_in_day"] = 0.0
        features["day_of_week"] = 0.0
        features["month"] = 0.0

    # === 23 NEW features (replacing candlestick patterns) ===

    # MACD features
    macd_line, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    features["macd_hist"] = macd_hist
    # Normalize MACD-Signal distance by price to make cross-asset comparable
    close_safe = np.where(close < 1e-10, 1e-10, close)
    features["macd_signal_dist"] = (macd_line - macd_signal) / close_safe

    # ADX and directional indicators
    features["adx"] = talib.ADX(high, low, close, timeperiod=14)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=14)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=14)
    features["plus_di_minus_di"] = (plus_di - minus_di) / 100.0

    # Stochastic
    stoch_k, stoch_d = talib.STOCH(high, low, close, fastk_period=14, slowk_period=3, slowd_period=3)
    features["stoch_k"] = stoch_k
    features["stoch_d"] = stoch_d

    # MFI (volume-weighted RSI)
    features["mfi"] = talib.MFI(high, low, close, volume, timeperiod=14)

    # ATR as percentage of price (normalized volatility)
    atr_val = talib.ATR(high, low, close, timeperiod=14)
    features["atr_pct"] = atr_val / close_safe

    # Bollinger bandwidth (volatility regime)
    middle_safe = np.where(middle < 1e-10, 1e-10, middle)
    features["bb_width"] = (upper - lower) / middle_safe

    # Multi-period returns
    features["return_4bar"] = close_series.pct_change(periods=4)
    features["return_6bar"] = close_series.pct_change(periods=6)
    features["return_30bar"] = close_series.pct_change(periods=30)

    # Volume ratio
    vol_sma20 = talib.SMA(volume, timeperiod=20)
    vol_sma20_safe = np.where(vol_sma20 < 1e-10, 1e-10, vol_sma20)
    features["vol_ratio_20"] = volume / vol_sma20_safe

    # Macro EMA crossovers
    ema200 = talib.EMA(close, timeperiod=200)
    features["ema_cross_1_200"] = np.where(np.isnan(ema200), np.nan, close / ema200)
    features["ema_cross_100_200"] = np.where(
        np.isnan(ema200) | np.isnan(ema100), np.nan, ema100 / ema200
    )

    # RSI smoothed (EMA of RSI)
    rsi_raw = features["rsi"].values.astype(np.float64)
    features["rsi_ema"] = talib.EMA(rsi_raw, timeperiod=14)

    # Bar range as percentage of close
    features["high_low_range"] = (high - low) / close_safe

    # Support/Resistance proximity
    high20 = pd.Series(high, index=df.index).rolling(window=20).max()
    low20 = pd.Series(low, index=df.index).rolling(window=20).min()
    high20_safe = high20.replace(0, np.nan)
    low20_safe = low20.replace(0, np.nan)
    features["close_vs_high20"] = close_series / high20_safe
    features["close_vs_low20"] = close_series / low20_safe

    # Market stress (reuse from precompute if available, else calculate)
    if "market_stress" in df.columns:
        features["market_stress"] = df["market_stress"].values
    else:
        # Simplified stress: ATR% * 10, capped at 100
        features["market_stress"] = np.clip(atr_val / close_safe * 1000, 0, 100)

    # OBV Z-score
    obv = talib.OBV(close, volume)
    obv_series = pd.Series(obv, index=df.index)
    obv_sma = obv_series.rolling(window=30).mean()
    obv_std = obv_series.rolling(window=30).std()
    obv_std_safe = obv_std.replace(0, 1e-10)
    features["obv_zscore"] = (obv_series - obv_sma) / obv_std_safe

    # Williams %R
    features["willr"] = talib.WILLR(high, low, close, timeperiod=14)

    # CCI
    features["cci"] = talib.CCI(high, low, close, timeperiod=14)

    return features


def calculate_mlp_features_cross(
    df: pd.DataFrame,
    include_temporal: bool = True,
    btc_df: pd.DataFrame | None = None,
    market_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Calculate 44 cross-asset features (paper_36 + 8 cross-asset features).

    Cross-asset features capture market-wide dynamics and BTC leadership:
    - btc_return_4h: BTC 4-hour return (1 bar for 4H data)
    - btc_return_24h: BTC 24-hour return (6 bars for 4H data)
    - btc_volatility: BTC 20-period rolling volatility
    - btc_correlation: 20-period rolling correlation with BTC
    - market_momentum: Average return across top coins
    - market_volatility: Average volatility across top coins
    - volume_ratio: Asset volume / market average volume
    - dominance_change: Change in BTC dominance proxy (BTC vol / total vol)

    Args:
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
        include_temporal: Whether to include temporal features
        btc_df: BTC OHLCV DataFrame (required for non-BTC assets)
        market_df: Market aggregate DataFrame (optional)

    Returns:
        DataFrame with 44 feature columns
    """
    # Start with paper_36 features
    features = calculate_mlp_features_paper(df, include_temporal=include_temporal)

    # Use np.asarray to avoid copying if dtype already matches
    close = np.asarray(df["close"].values, dtype=np.float64)
    volume = np.asarray(df["volume"].values, dtype=np.float64)

    # Calculate asset returns
    close_series = pd.Series(close, index=df.index)
    asset_returns = close_series.pct_change()

    # Determine if this is BTC data (for self-referencing)
    # Add bounds checking for comparison slice
    min_compare = min(100, len(close))
    is_btc = btc_df is None or (
        len(btc_df) == len(df) and min_compare > 0 and np.allclose(
            btc_df["close"].values[:min_compare], close[:min_compare], rtol=1e-5
        )
    )

    if is_btc:
        # BTC self-reference: use its own data
        btc_close_series = close_series
        btc_volume = volume
        btc_returns = asset_returns
    else:
        # Use provided BTC data
        if btc_df is None:
            raise ValueError("btc_df is required for non-BTC assets in cross_44 feature set")

        # Align BTC data with target asset by index
        btc_aligned = btc_df.reindex(df.index)
        btc_close = np.asarray(btc_aligned["close"].values, dtype=np.float64)
        btc_volume = np.asarray(btc_aligned["volume"].values, dtype=np.float64)
        # Create Series once and reuse for multiple calculations
        btc_close_series = pd.Series(btc_close, index=df.index)
        btc_returns = btc_close_series.pct_change()

    # 1. btc_return_4h (1-bar return for 4H data)
    features["btc_return_4h"] = btc_returns.fillna(0.0)

    # 2. btc_return_24h (6-bar return for 4H data) - reuse btc_close_series
    features["btc_return_24h"] = btc_close_series.pct_change(periods=6).fillna(0.0)

    # 3. btc_volatility (20-period rolling std of returns)
    btc_volatility = btc_returns.rolling(window=20, min_periods=1).std().fillna(0.0)
    features["btc_volatility"] = btc_volatility

    # 4. btc_correlation (20-period rolling correlation with BTC)
    if is_btc:
        # BTC correlation with itself is always 1
        features["btc_correlation"] = 1.0
    else:
        # Rolling correlation between asset returns and BTC returns
        corr = asset_returns.rolling(window=20, min_periods=5).corr(btc_returns)
        features["btc_correlation"] = corr.fillna(0.0)

    # 5-6. Market momentum and volatility
    if market_df is not None and "avg_return" in market_df.columns:
        # Use provided market data
        market_aligned = market_df.reindex(df.index)
        market_momentum = market_aligned["avg_return"].fillna(0.0)
        market_volatility = market_aligned.get("avg_volatility", pd.Series(0.0, index=df.index)).fillna(0.0)
        # Clip to reasonable ranges
        features["market_momentum"] = market_momentum.clip(-0.5, 0.5)
        features["market_volatility"] = market_volatility.clip(0, 0.5)
    else:
        # Proxy: use BTC as market proxy (BTC dominance ~40-50%)
        features["market_momentum"] = btc_returns.fillna(0.0).clip(-0.5, 0.5)
        features["market_volatility"] = btc_volatility.clip(0, 0.5)

    # 7. volume_ratio (asset volume / BTC volume as market proxy)
    # Normalize to prevent extreme values
    btc_vol_safe = np.where(btc_volume < 1e-10, 1e-10, btc_volume)
    volume_ratio = volume / btc_vol_safe
    # Clip and normalize (typical ratio is 0.01-10x)
    features["volume_ratio"] = np.clip(volume_ratio, 0.01, 10.0) / 10.0

    # 8. dominance_change (proxy: BTC return minus asset return)
    # When BTC outperforms, dominance typically rises
    if is_btc:
        features["dominance_change"] = 0.0  # BTC relative to itself is 0
    else:
        dominance_proxy = btc_returns - asset_returns
        # Clip to reasonable range (±50% difference is extreme)
        dominance_proxy = dominance_proxy.clip(-0.5, 0.5)
        features["dominance_change"] = dominance_proxy.fillna(0.0)

    return features


def calculate_mlp_features_shap(
    df: pd.DataFrame,
    include_temporal: bool = True,
) -> pd.DataFrame:
    """
    Calculate legacy 13-feature MLP set derived from SHAP analysis.

    Returns:
        DataFrame with 13 feature columns, normalized to roughly 0-1 range
    """
    # Use np.asarray to avoid copying if dtype already matches
    close = np.asarray(df["close"].values, dtype=np.float64)
    high = np.asarray(df["high"].values, dtype=np.float64)
    low = np.asarray(df["low"].values, dtype=np.float64)
    volume = np.asarray(df["volume"].values, dtype=np.float64)

    features = pd.DataFrame(index=df.index)

    # 1. Bollinger %B (most important feature per SHAP)
    # %B = (Price - Lower Band) / (Upper Band - Lower Band)
    # Range: typically 0-1, can exceed during strong moves
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    band_width = upper - lower
    # Avoid division by zero
    band_width = np.where(band_width < 1e-10, 1e-10, band_width)
    bollinger_pct_b = (close - lower) / band_width
    # Clip to reasonable range and normalize
    features["bollinger_pct_b"] = np.clip(bollinger_pct_b, -0.5, 1.5)

    # 2. RSI (normalized to 0-1)
    rsi_raw = talib.RSI(close, timeperiod=14)
    features["rsi"] = rsi_raw / 100.0

    # 3. Ultimate Oscillator (normalized to 0-1)
    # Uses 3 different time periods for better signal quality
    ultosc = talib.ULTOSC(high, low, close, timeperiod1=7, timeperiod2=14, timeperiod3=28)
    features["ultosc"] = ultosc / 100.0

    # 4-7. EMA Crossovers (ratio form)
    # Ratio > 1 means short-term EMA above long-term (bullish)
    # Ratio < 1 means short-term EMA below long-term (bearish)
    # Note: EMA(1) is just the close price itself
    ema21 = talib.EMA(close, timeperiod=21)
    ema50 = talib.EMA(close, timeperiod=50)
    ema100 = talib.EMA(close, timeperiod=100)

    # EMA(1) = close price
    # For crossover ratios, we compute the ratio and set NaN where EMA is not yet valid
    # Then fill NaN with 1.0 (neutral - no crossover signal)
    ema_cross_1_21 = np.where(np.isnan(ema21), np.nan, close / ema21)
    ema_cross_21_50 = np.where(np.isnan(ema50) | np.isnan(ema21), np.nan, ema21 / ema50)
    ema_cross_50_100 = np.where(np.isnan(ema100) | np.isnan(ema50), np.nan, ema50 / ema100)
    ema_cross_1_50 = np.where(np.isnan(ema50), np.nan, close / ema50)

    features["ema_cross_1_21"] = ema_cross_1_21
    features["ema_cross_21_50"] = ema_cross_21_50
    features["ema_cross_50_100"] = ema_cross_50_100
    features["ema_cross_1_50"] = ema_cross_1_50

    # 8. Price Z-Score
    # How many standard deviations current price is from 30-period mean
    sma30 = talib.SMA(close, timeperiod=30)
    std30 = talib.STDDEV(close, timeperiod=30)
    std30_safe = np.where(std30 < 1e-10, 1e-10, std30)
    price_zscore = (close - sma30) / std30_safe
    # Clip to ±3 and normalize to roughly -1 to 1
    features["price_zscore"] = np.clip(price_zscore, -3, 3) / 3.0

    # 9. Volume Z-Score
    # Allows comparing volumes across different assets
    vol_sma = talib.SMA(volume, timeperiod=30)
    vol_std = talib.STDDEV(volume, timeperiod=30)
    vol_std_safe = np.where(vol_std < 1e-10, 1e-10, vol_std)
    volume_zscore = (volume - vol_sma) / vol_std_safe
    features["volume_zscore"] = np.clip(volume_zscore, -3, 3) / 3.0

    # 10-12. Temporal Features (normalized to 0-1)
    if include_temporal and "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
        # For 4H bars: hour 0,4,8,12,16,20 maps to 0,1,2,3,4,5
        features["hour_of_day"] = (ts.dt.hour // 4) / 5.0
        features["day_of_week"] = ts.dt.dayofweek / 6.0
        features["month"] = (ts.dt.month - 1) / 11.0
    else:
        # Default values when temporal info not available
        features["hour_of_day"] = 0.5
        features["day_of_week"] = 0.5
        features["month"] = 0.5

    # 13. Close % Change
    # Magnitude of price change from previous bar
    close_series = pd.Series(close, index=df.index)
    pct_change = close_series.pct_change()
    # Clip extreme moves (>10%) and normalize
    features["close_pct_change"] = pct_change.clip(-0.1, 0.1) / 0.1

    # Fill NaN values (from indicator warm-up periods)
    features = features.fillna(0.0)

    return features


def extract_single_features(
    market_data: dict,
    indicators: dict,
    feature_set: str = FEATURE_SET_SHAP,
) -> np.ndarray:
    """
    Extract features for a single time point from pre-calculated indicators.

    This is used during live trading when indicators are pre-computed
    by IndicatorService.

    Args:
        market_data: Dict with 'close', 'volume', 'timestamp' etc.
        indicators: Dict with pre-calculated indicator values
        feature_set: Feature set name

    Returns:
        numpy array of features in the selected feature order
    """
    if feature_set == FEATURE_SET_PAPER:
        return extract_single_features_paper(market_data, indicators)
    if feature_set == FEATURE_SET_SHAP:
        return extract_single_features_shap(market_data, indicators)
    if feature_set == FEATURE_SET_CROSS:
        return extract_single_features_cross(market_data, indicators)
    if feature_set == FEATURE_SET_V2:
        return extract_single_features_v2(market_data, indicators)
    raise ValueError(f"Unknown feature_set: {feature_set}")


def extract_single_features_shap(
    market_data: dict,
    indicators: dict,
) -> np.ndarray:
    """Extract legacy 13-feature set for live trading."""
    features = np.zeros(NUM_FEATURES_SHAP, dtype=np.float32)

    # Map indicator names to feature array
    feature_map = {
        "bollinger_pct_b": 0,
        "rsi": 1,
        "ultosc": 2,
        "ema_cross_1_21": 3,
        "ema_cross_21_50": 4,
        "ema_cross_50_100": 5,
        "ema_cross_1_50": 6,
        "price_zscore": 7,
        "volume_zscore": 8,
        "hour_of_day": 9,
        "day_of_week": 10,
        "month": 11,
        "close_pct_change": 12,
    }

    for name, idx in feature_map.items():
        if name in indicators:
            features[idx] = indicators[name]
        else:
            # Default values
            if name == "rsi":
                features[idx] = 0.5  # Neutral RSI
            elif name == "bollinger_pct_b":
                features[idx] = 0.5  # Middle of bands
            elif name.startswith("ema_cross"):
                features[idx] = 1.0  # No crossover
            else:
                features[idx] = 0.0

    return features


def extract_single_features_paper(
    market_data: dict,
    indicators: dict,
) -> np.ndarray:
    """
    Extract paper 36-feature set for a single time point.

    Note: Candlestick patterns require multi-bar OHLC history and are not
    currently computed in live mode. This returns zeros for candlestick
    features unless the caller provides pre-computed pattern values in
    `indicators` using keys that match FEATURE_NAMES_PAPER.
    """
    features = np.zeros(NUM_FEATURES_PAPER, dtype=np.float32)

    feature_index = {name: idx for idx, name in enumerate(FEATURE_NAMES_PAPER)}

    # If caller pre-populates pattern keys (e.g. from cached history), use them.
    for name in FEATURE_NAMES_PAPER:
        if name in indicators:
            features[feature_index[name]] = indicators[name]

    # Map basic indicators if present (fallbacks)
    def _set(name: str, value: float):
        idx = feature_index.get(name)
        if idx is not None:
            features[idx] = value

    _set("bollinger_pct_b", indicators.get("bollinger_pct_b", 0.0))
    _set("ultosc", indicators.get("ultosc", 0.0))
    _set("rsi", indicators.get("rsi", 0.0))
    _set("close_pct_change", indicators.get("close_pct_change", 0.0))
    _set("price_zscore", indicators.get("price_zscore", 0.0))
    _set("volume_zscore", indicators.get("volume_zscore", 0.0))
    _set("ema_cross_1_20", indicators.get("ema_cross_1_20", 1.0))
    _set("ema_cross_20_50", indicators.get("ema_cross_20_50", 1.0))
    _set("ema_cross_50_100", indicators.get("ema_cross_50_100", 1.0))
    _set("ema_cross_1_50", indicators.get("ema_cross_1_50", 1.0))

    if "timestamp" in market_data:
        ts = pd.to_datetime(market_data["timestamp"], unit="ms", errors="coerce")
        if pd.notna(ts):
            _set("samples_in_day", float(ts.hour // 4))
            _set("day_of_week", float(ts.dayofweek))
            _set("month", float(ts.month))

    return features


def extract_single_features_v2(
    market_data: dict,
    indicators: dict,
) -> np.ndarray:
    """
    Extract v2 36-feature set for a single time point (live trading).

    All features are mapped from pre-computed indicators. Unlike paper_36,
    v2 does not rely on candlestick patterns (which need multi-bar history).

    Args:
        market_data: Dict with 'close', 'volume', 'timestamp', 'high', 'low' etc.
        indicators: Dict with pre-calculated indicator values

    Returns:
        numpy array of 36 features in v2 feature order
    """
    features = np.zeros(NUM_FEATURES_V2, dtype=np.float32)
    feature_index = {name: idx for idx, name in enumerate(FEATURE_NAMES_V2)}

    def _set(name: str, value: float):
        idx = feature_index.get(name)
        if idx is not None and value is not None and np.isfinite(value):
            features[idx] = value

    # --- 13 kept features ---
    _set("bollinger_pct_b", indicators.get("bollinger_pct_b", 0.0))
    _set("ultosc", indicators.get("ultosc", 0.0))
    _set("rsi", indicators.get("rsi", 0.0))
    _set("close_pct_change", indicators.get("close_pct_change", 0.0))
    _set("price_zscore", indicators.get("price_zscore", 0.0))
    _set("volume_zscore", indicators.get("volume_zscore", 0.0))
    _set("ema_cross_1_20", indicators.get("ema_cross_1_20", 1.0))
    _set("ema_cross_20_50", indicators.get("ema_cross_20_50", 1.0))
    _set("ema_cross_50_100", indicators.get("ema_cross_50_100", 1.0))
    _set("ema_cross_1_50", indicators.get("ema_cross_1_50", 1.0))

    # Temporal
    if "timestamp" in market_data:
        ts = pd.to_datetime(market_data["timestamp"], unit="ms", errors="coerce")
        if pd.notna(ts):
            _set("samples_in_day", float(ts.hour // 4))
            _set("day_of_week", float(ts.dayofweek))
            _set("month", float(ts.month))

    # --- 23 new features ---
    _set("macd_hist", indicators.get("macd_hist", 0.0))
    _set("macd_signal_dist", indicators.get("macd_signal_dist", 0.0))
    _set("adx", indicators.get("adx", 0.0))
    _set("plus_di_minus_di", indicators.get("plus_di_minus_di", 0.0))
    _set("stoch_k", indicators.get("stoch_k", 50.0))
    _set("stoch_d", indicators.get("stoch_d", 50.0))
    _set("mfi", indicators.get("mfi", 50.0))
    _set("atr_pct", indicators.get("atr_pct", 0.0))
    _set("bb_width", indicators.get("bb_width", 0.0))
    _set("return_4bar", indicators.get("return_4bar", 0.0))
    _set("return_6bar", indicators.get("return_6bar", 0.0))
    _set("return_30bar", indicators.get("return_30bar", 0.0))
    _set("vol_ratio_20", indicators.get("vol_ratio_20", 1.0))
    _set("ema_cross_1_200", indicators.get("ema_cross_1_200", 1.0))
    _set("ema_cross_100_200", indicators.get("ema_cross_100_200", 1.0))
    _set("rsi_ema", indicators.get("rsi_ema", 0.0))
    _set("high_low_range", indicators.get("high_low_range", 0.0))
    _set("close_vs_high20", indicators.get("close_vs_high20", 1.0))
    _set("close_vs_low20", indicators.get("close_vs_low20", 1.0))
    _set("market_stress", indicators.get("market_stress", 0.0))
    _set("obv_zscore", indicators.get("obv_zscore", 0.0))
    _set("willr", indicators.get("willr", -50.0))
    _set("cci", indicators.get("cci", 0.0))

    return features


def calculate_bollinger_pct_b(close: np.ndarray, period: int = 20) -> np.ndarray:
    """Calculate Bollinger %B indicator."""
    upper, _, lower = talib.BBANDS(close, timeperiod=period, nbdevup=2, nbdevdn=2)
    band_width = upper - lower
    band_width = np.where(band_width < 1e-10, 1e-10, band_width)
    return (close - lower) / band_width


def calculate_ema_crossover(close: np.ndarray, fast: int, slow: int) -> np.ndarray:
    """Calculate EMA crossover ratio (fast/slow)."""
    # Handle fast=1 case (EMA(1) = close price)
    if fast == 1:
        ema_fast = close.copy()
    else:
        ema_fast = talib.EMA(close, timeperiod=fast)
    ema_slow = talib.EMA(close, timeperiod=slow)
    # Return NaN where slow EMA is not yet valid
    return np.where(np.isnan(ema_slow), np.nan, ema_fast / ema_slow)


def calculate_zscore(values: np.ndarray, period: int = 30) -> np.ndarray:
    """Calculate Z-score of values over rolling period."""
    sma = talib.SMA(values, timeperiod=period)
    std = talib.STDDEV(values, timeperiod=period)
    std_safe = np.where(std < 1e-10, 1e-10, std)
    zscore = (values - sma) / std_safe
    return np.clip(zscore, -3, 3) / 3.0


def extract_single_features_cross(
    market_data: dict,
    indicators: dict,
) -> np.ndarray:
    """
    Extract cross_44 feature set for a single time point.

    Requires pre-computed cross-asset indicators in the indicators dict:
    - btc_return_4h, btc_return_24h, btc_volatility, btc_correlation
    - market_momentum, market_volatility, volume_ratio, dominance_change

    Args:
        market_data: Dict with 'close', 'volume', 'timestamp' etc.
        indicators: Dict with pre-calculated indicator values

    Returns:
        numpy array of 44 features
    """
    features = np.zeros(NUM_FEATURES_CROSS, dtype=np.float32)

    # First fill paper_36 features
    paper_features = extract_single_features_paper(market_data, indicators)
    features[:NUM_FEATURES_PAPER] = paper_features

    # Then fill cross-asset features (indices 36-43)
    cross_feature_map = {
        "btc_return_4h": 36,
        "btc_return_24h": 37,
        "btc_volatility": 38,
        "btc_correlation": 39,
        "market_momentum": 40,
        "market_volatility": 41,
        "volume_ratio": 42,
        "dominance_change": 43,
    }

    for name, idx in cross_feature_map.items():
        if name in indicators:
            features[idx] = indicators[name]
        else:
            # Default values
            if name == "btc_correlation":
                features[idx] = 1.0  # Assume correlated with BTC
            elif name == "volume_ratio":
                features[idx] = 0.1  # Neutral volume ratio (normalized)
            else:
                features[idx] = 0.0

    return features


def get_feature_importance_ranking() -> list[tuple[str, float]]:
    """
    Return feature importance ranking from the paper's SHAP analysis.

    These are approximate values based on Figure 6 and 7 in the paper.
    Higher values indicate more important features for prediction.
    """
    return [
        ("bollinger_pct_b", 0.18),
        ("rsi", 0.10),
        ("ema_cross_1_21", 0.09),
        ("ema_cross_21_50", 0.07),
        ("day_of_week", 0.06),
        ("month", 0.06),
        ("hour_of_day", 0.06),
        ("price_zscore", 0.06),
        ("ema_cross_50_100", 0.05),
        ("ema_cross_1_50", 0.04),
        ("volume_zscore", 0.04),
        ("ultosc", 0.05),
        ("close_pct_change", 0.04),
    ]
