from __future__ import annotations

import pandas as pd
import pytest

from trading.regime.feature_table import build_regime_feature_table
from trading.regime.types import RegimeFeatureRow


def _price_df(rows: int = 12, symbol: str = "BTC") -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=rows, freq="1h")
    close = [100.0 + i for i in range(rows)]
    atr = [1.0] * rows
    atr[-1] = 20.0  # force vol jump at end
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": [symbol] * rows,
            "close": close,
            "volume": [1000 + i for i in range(rows)],
            "mfi": [50 + (i % 5) for i in range(rows)],
            "adx": [20 + (i % 3) for i in range(rows)],
            "atr": atr,
        }
    )


def test_regime_feature_row_roundtrip() -> None:
    row = RegimeFeatureRow(timestamp="2026-01-01T00:00:00", symbol="BTC", close=100.0)
    payload = row.to_dict()
    restored = RegimeFeatureRow.from_dict(payload)

    assert restored.timestamp == "2026-01-01T00:00:00"
    assert restored.symbol == "BTC"
    assert restored.close == 100.0


def test_build_table_requires_price_columns() -> None:
    bad = pd.DataFrame({"timestamp": ["2026-01-01T00:00:00"]})
    with pytest.raises(ValueError, match="price missing required columns"):
        build_regime_feature_table(price_df=bad)


def test_build_table_with_missing_external_sources() -> None:
    out = build_regime_feature_table(price_df=_price_df(), vol_jump_window=8)

    assert len(out) == 12
    assert "external_regime_score" in out.columns
    assert "derivatives_stress_score" in out.columns
    assert "data_quality_score" in out.columns
    assert out["data_quality_score"].eq(0.0).all()
    assert out["trend_1h"].isin(["BULL", "BEAR", "NEUTRAL"]).all()
    assert out["trend_4h"].isin(["BULL", "BEAR", "NEUTRAL"]).all()
    assert out["trend_1d"].isin(["BULL", "BEAR", "NEUTRAL"]).all()


def test_build_table_asof_merge_and_quality_score() -> None:
    price = _price_df(rows=8)

    onchain = pd.DataFrame(
        {
            "timestamp": ["2026-01-01 00:00:00", "2026-01-01 04:00:00"],
            "symbol": ["BTC", "BTC"],
            "onchain_activity_score": [0.7, 0.6],
        }
    )
    sentiment = pd.DataFrame(
        {
            "timestamp": ["2026-01-01 01:00:00"],
            "sentiment_score": [0.4],
        }
    )
    derivatives = pd.DataFrame(
        {
            "timestamp": ["2026-01-01 02:00:00"],
            "open_interest_change": [0.03],
            "funding_rate": [0.0002],
        }
    )
    policy = pd.DataFrame(
        {
            "timestamp": ["2026-01-01 03:00:00"],
            "policy_event_score": [0.5],
        }
    )

    out = build_regime_feature_table(
        price_df=price,
        onchain_df=onchain,
        sentiment_df=sentiment,
        derivatives_df=derivatives,
        policy_df=policy,
        join_tolerance="4h",
        vol_jump_window=6,
    )

    # Asof merge should populate at least part of rows with source data.
    assert out["onchain_activity_score"].max() > 0.0
    assert out["sentiment_score"].max() > 0.0
    assert out["open_interest_change"].max() > 0.0
    assert out["policy_event_score"].max() > 0.0

    # Quality score is bounded and non-zero for merged rows.
    assert out["data_quality_score"].between(0.0, 1.0).all()
    assert out["data_quality_score"].max() > 0.0

    # Derived scores are bounded.
    assert out["derivatives_stress_score"].between(-1.0, 1.0).all()
    assert out["external_regime_score"].between(-1.0, 1.0).all()


def test_build_table_detects_vol_jump() -> None:
    out = build_regime_feature_table(price_df=_price_df(rows=30), vol_jump_window=10, vol_jump_z=1.5)

    assert out["volatility_jump"].dtype.kind in {"i", "u"}
    assert out["volatility_jump"].sum() >= 1
