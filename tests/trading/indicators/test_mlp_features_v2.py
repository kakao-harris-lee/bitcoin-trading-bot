"""Tests for v2_36 MLP feature set."""

import numpy as np
import pandas as pd
import pytest

from trading.indicators.mlp_features import (
    FEATURE_NAMES_V2,
    FEATURE_SET_V2,
    NUM_FEATURES_V2,
    calculate_mlp_features,
    calculate_mlp_features_v2,
    extract_single_features,
    extract_single_features_v2,
)


def _make_ohlcv_df(n: int = 300) -> pd.DataFrame:
    """Create synthetic OHLCV DataFrame with realistic price action."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="4h")
    close = 40000 + np.cumsum(np.random.randn(n) * 200)
    high = close + np.abs(np.random.randn(n) * 100)
    low = close - np.abs(np.random.randn(n) * 100)
    open_ = close + np.random.randn(n) * 50
    volume = np.abs(np.random.randn(n) * 1000) + 500

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "timestamp": dates,  # datetime objects (matches production data pipeline)
    })


class TestV2FeatureConstants:
    """Test v2_36 feature set constants."""

    def test_num_features(self):
        assert NUM_FEATURES_V2 == 36

    def test_feature_names_length(self):
        assert len(FEATURE_NAMES_V2) == 36

    def test_no_duplicate_names(self):
        assert len(set(FEATURE_NAMES_V2)) == len(FEATURE_NAMES_V2)

    def test_no_candlestick_patterns(self):
        """V2 should not contain any candlestick pattern features."""
        for name in FEATURE_NAMES_V2:
            assert not name.startswith("cdl_"), f"Found candlestick pattern: {name}"

    def test_kept_features_present(self):
        """All 13 kept features from paper_36 should be present."""
        kept = [
            "bollinger_pct_b", "ultosc", "rsi", "close_pct_change",
            "price_zscore", "volume_zscore", "ema_cross_1_20",
            "ema_cross_20_50", "ema_cross_50_100", "ema_cross_1_50",
            "samples_in_day", "day_of_week", "month",
        ]
        for name in kept:
            assert name in FEATURE_NAMES_V2, f"Missing kept feature: {name}"

    def test_new_features_present(self):
        """All 23 new features should be present."""
        new = [
            "macd_hist", "macd_signal_dist", "adx", "plus_di_minus_di",
            "stoch_k", "stoch_d", "mfi", "atr_pct", "bb_width",
            "return_4bar", "return_6bar", "return_30bar", "vol_ratio_20",
            "ema_cross_1_200", "ema_cross_100_200", "rsi_ema",
            "high_low_range", "close_vs_high20", "close_vs_low20",
            "market_stress", "obv_zscore", "willr", "cci",
        ]
        for name in new:
            assert name in FEATURE_NAMES_V2, f"Missing new feature: {name}"


class TestCalculateV2Features:
    """Test calculate_mlp_features_v2() batch computation."""

    def test_output_shape(self):
        """Output should have 36 columns and same number of rows as input."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        assert features.shape[1] == 36
        assert features.shape[0] == len(df)

    def test_column_names_match(self):
        """Output column names should match FEATURE_NAMES_V2."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        assert list(features.columns) == FEATURE_NAMES_V2

    def test_no_all_nan_columns(self):
        """No column should be entirely NaN after warmup period."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        # After 200 bars warmup, no column should be all NaN
        after_warmup = features.iloc[200:]
        for col in features.columns:
            assert not after_warmup[col].isna().all(), f"Column {col} is all NaN"

    def test_finite_values_after_warmup(self):
        """All values should be finite after warmup period."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        after_warmup = features.iloc[210:]
        for col in features.columns:
            col_vals = after_warmup[col].dropna()
            if len(col_vals) > 0:
                assert np.all(np.isfinite(col_vals)), f"Non-finite values in {col}"

    def test_temporal_features_with_timestamp(self):
        """Temporal features should be populated when timestamp is present."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df, include_temporal=True)
        # Should have varying values (not all identical)
        assert features["samples_in_day"].nunique() > 1
        assert features["day_of_week"].nunique() > 1
        assert features["month"].nunique() > 1

    def test_temporal_features_without_timestamp(self):
        """Temporal features should default to 0 without timestamp."""
        df = _make_ohlcv_df(300)
        df = df.drop(columns=["timestamp"])
        features = calculate_mlp_features_v2(df, include_temporal=True)
        assert (features["samples_in_day"] == 0).all()
        assert (features["day_of_week"] == 0).all()
        assert (features["month"] == 0).all()

    def test_dispatcher_routes_correctly(self):
        """calculate_mlp_features with feature_set='v2_36' should work."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features(df, feature_set=FEATURE_SET_V2)
        assert features.shape[1] == 36
        assert list(features.columns) == FEATURE_NAMES_V2

    def test_rsi_range(self):
        """RSI should be in 0-100 range."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        rsi_vals = features["rsi"].dropna()
        assert rsi_vals.min() >= 0
        assert rsi_vals.max() <= 100

    def test_adx_range(self):
        """ADX should be in 0-100 range."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        adx_vals = features["adx"].dropna()
        assert adx_vals.min() >= 0
        assert adx_vals.max() <= 100

    def test_stochastic_range(self):
        """Stochastic K and D should be in 0-100 range."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        for col in ["stoch_k", "stoch_d"]:
            vals = features[col].dropna()
            assert vals.min() >= 0, f"{col} below 0"
            assert vals.max() <= 100, f"{col} above 100"

    def test_mfi_range(self):
        """MFI should be in 0-100 range."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        mfi_vals = features["mfi"].dropna()
        assert mfi_vals.min() >= 0
        assert mfi_vals.max() <= 100

    def test_atr_pct_positive(self):
        """ATR percentage should be positive."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        atr_vals = features["atr_pct"].dropna()
        assert (atr_vals >= 0).all()

    def test_willr_range(self):
        """Williams %R should be in -100 to 0 range."""
        df = _make_ohlcv_df(300)
        features = calculate_mlp_features_v2(df)
        willr_vals = features["willr"].dropna()
        assert willr_vals.min() >= -100
        assert willr_vals.max() <= 0


class TestExtractSingleFeaturesV2:
    """Test extract_single_features_v2() for live trading."""

    def test_output_shape(self):
        """Output should be a 36-element numpy array."""
        market_data = {"timestamp": 1700000000000}
        indicators = {}
        features = extract_single_features_v2(market_data, indicators)
        assert features.shape == (36,)
        assert features.dtype == np.float32

    def test_kept_features_mapping(self):
        """Kept features should map from indicators correctly."""
        market_data = {"timestamp": 1700000000000}
        indicators = {
            "bollinger_pct_b": 0.75,
            "rsi": 65.0,
            "ultosc": 55.0,
            "ema_cross_1_20": 1.02,
            "ema_cross_20_50": 1.01,
        }
        features = extract_single_features_v2(market_data, indicators)
        assert features[0] == pytest.approx(0.75)  # bollinger_pct_b
        assert features[2] == pytest.approx(65.0)   # rsi
        assert features[1] == pytest.approx(55.0)   # ultosc
        assert features[6] == pytest.approx(1.02)   # ema_cross_1_20
        assert features[7] == pytest.approx(1.01)   # ema_cross_20_50

    def test_new_features_mapping(self):
        """New features should map from indicators correctly."""
        market_data = {"timestamp": 1700000000000}
        indicators = {
            "macd_hist": 150.0,
            "adx": 35.0,
            "stoch_k": 80.0,
            "mfi": 60.0,
            "atr_pct": 0.025,
            "willr": -20.0,
            "cci": 100.0,
        }
        features = extract_single_features_v2(market_data, indicators)
        idx = {name: i for i, name in enumerate(FEATURE_NAMES_V2)}
        assert features[idx["macd_hist"]] == pytest.approx(150.0)
        assert features[idx["adx"]] == pytest.approx(35.0)
        assert features[idx["stoch_k"]] == pytest.approx(80.0)
        assert features[idx["mfi"]] == pytest.approx(60.0)
        assert features[idx["atr_pct"]] == pytest.approx(0.025)
        assert features[idx["willr"]] == pytest.approx(-20.0)
        assert features[idx["cci"]] == pytest.approx(100.0)

    def test_defaults_when_missing(self):
        """Missing indicators should use sensible defaults."""
        market_data = {}
        indicators = {}
        features = extract_single_features_v2(market_data, indicators)
        idx = {name: i for i, name in enumerate(FEATURE_NAMES_V2)}
        # EMA crossovers default to 1.0 (neutral)
        assert features[idx["ema_cross_1_20"]] == pytest.approx(1.0)
        assert features[idx["ema_cross_1_200"]] == pytest.approx(1.0)
        # Stochastic defaults to 50 (neutral)
        assert features[idx["stoch_k"]] == pytest.approx(50.0)
        # Volume ratio defaults to 1.0 (neutral)
        assert features[idx["vol_ratio_20"]] == pytest.approx(1.0)

    def test_dispatcher_routes_correctly(self):
        """extract_single_features with feature_set='v2_36' should work."""
        market_data = {"timestamp": 1700000000000}
        indicators = {"rsi": 50.0}
        features = extract_single_features(market_data, indicators, feature_set=FEATURE_SET_V2)
        assert features.shape == (36,)

    def test_nan_handling(self):
        """NaN values in indicators should be replaced with defaults."""
        market_data = {"timestamp": 1700000000000}
        indicators = {"rsi": float("nan"), "adx": float("inf")}
        features = extract_single_features_v2(market_data, indicators)
        # NaN and inf should be replaced with 0 (default)
        idx = {name: i for i, name in enumerate(FEATURE_NAMES_V2)}
        assert np.isfinite(features[idx["rsi"]])
        assert np.isfinite(features[idx["adx"]])
