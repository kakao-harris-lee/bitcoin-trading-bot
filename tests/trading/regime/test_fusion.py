import pandas as pd
import pytest

from trading.regime.fusion import (
    clamp,
    compute_derivatives_stress,
    compute_external_regime_score,
    detect_volatility_jumps,
    normalize_signal,
)


def test_clamp_bounds_value() -> None:
    assert clamp(2.0) == 1.0
    assert clamp(-2.0) == -1.0
    assert clamp(0.4) == 0.4


def test_normalize_signal_nan_and_validation() -> None:
    assert normalize_signal(float("nan"), scale=1.0) == 0.0
    with pytest.raises(ValueError, match="scale must be > 0"):
        normalize_signal(1.0, scale=0.0)


def test_compute_derivatives_stress_directionality() -> None:
    bullish = compute_derivatives_stress(open_interest_change=0.08, funding_rate=0.001)
    bearish = compute_derivatives_stress(open_interest_change=-0.08, funding_rate=-0.001)

    assert bullish > 0.0
    assert bearish < 0.0
    assert -1.0 <= bullish <= 1.0
    assert -1.0 <= bearish <= 1.0


def test_compute_external_regime_score_with_custom_weights() -> None:
    score = compute_external_regime_score(
        onchain_score=0.9,
        sentiment_score=0.5,
        derivatives_score=0.2,
        policy_score=0.1,
        weights={"onchain": 1.0, "sentiment": 0.0, "derivatives": 0.0, "policy": 0.0},
    )
    assert score == pytest.approx(0.9, abs=1e-6)


def test_compute_external_regime_score_zero_total_weight() -> None:
    score = compute_external_regime_score(
        onchain_score=0.7,
        sentiment_score=0.6,
        derivatives_score=0.5,
        policy_score=0.4,
        weights={"onchain": 0.0, "sentiment": 0.0, "derivatives": 0.0, "policy": 0.0},
    )
    assert score == 0.0


def test_detect_volatility_jumps_flags_spike() -> None:
    base = [0.01] * 60
    base[55] = 0.08
    series = pd.Series(base)

    jumps = detect_volatility_jumps(series, window=24, z_threshold=2.0)

    assert jumps.iloc[55] == 1
    assert int(jumps.sum()) >= 1


def test_detect_volatility_jumps_validates_params() -> None:
    series = pd.Series([0.01, 0.02, 0.03])
    with pytest.raises(ValueError, match="window must be >= 5"):
        detect_volatility_jumps(series, window=3)
    with pytest.raises(ValueError, match="z_threshold must be > 0"):
        detect_volatility_jumps(series, window=6, z_threshold=0.0)
