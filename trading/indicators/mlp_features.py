"""
MLP Direction Strategy Feature Extraction Module.

Based on Parente & Rizzuti (2025) - "Trading strategy for Bitcoin and Ethereum
by neural network model"

Features are selected based on SHAP importance analysis from the paper.
Candlestick patterns are explicitly excluded as they were found ineffective.

Reference: https://doi.org/10.1007/s00500-025-10980-7
"""

import numpy as np
import pandas as pd
import talib

# Feature names for reference
FEATURE_NAMES = [
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

NUM_FEATURES = len(FEATURE_NAMES)


def calculate_mlp_features(
    df: pd.DataFrame,
    bwin: int = 5,
    include_temporal: bool = True,
) -> pd.DataFrame:
    """
    Calculate all 13 MLP features from OHLCV data.

    Based on SHAP feature importance from the paper:
    1. Bollinger %B (most important)
    2. RSI
    3. Ultimate Oscillator
    4. EMA Cross 1/21
    5. EMA Cross 21/50
    6. EMA Cross 50/100
    7. EMA Cross 1/50
    8. Price Z-Score
    9. Volume Z-Score
    10. Hour of Day (normalized 0-1)
    11. Day of Week (normalized 0-1)
    12. Month (normalized 0-1)
    13. Close % Change

    Args:
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
             and optionally 'timestamp'
        bwin: Backward window size (used for reference, default 5)
        include_temporal: Whether to include temporal features

    Returns:
        DataFrame with 13 feature columns, normalized to roughly 0-1 range
    """
    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)
    volume = df["volume"].values.astype(np.float64)

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
) -> np.ndarray:
    """
    Extract features for a single time point from pre-calculated indicators.

    This is used during live trading when indicators are pre-computed
    by IndicatorService.

    Args:
        market_data: Dict with 'close', 'volume', 'timestamp' etc.
        indicators: Dict with pre-calculated indicator values

    Returns:
        numpy array of 13 features
    """
    features = np.zeros(NUM_FEATURES, dtype=np.float32)

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
