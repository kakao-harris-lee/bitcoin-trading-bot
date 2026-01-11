# tests/trading/strategies/test_volatility_tracker.py
import pytest
from trading.strategies.volatility_tracker import VolatilityTracker


def test_volatility_tracker_requires_minimum_data():
    """Tracker returns None when insufficient data."""
    tracker = VolatilityTracker(window=20)
    tracker.add_price(100.0)
    tracker.add_price(101.0)

    assert tracker.get_volatility() is None


def test_volatility_tracker_calculates_volatility():
    """Tracker calculates volatility from price returns."""
    tracker = VolatilityTracker(window=5)

    # Add 6 prices (need window+1 for returns)
    prices = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0]
    for p in prices:
        tracker.add_price(p)

    vol = tracker.get_volatility()
    assert vol is not None
    assert vol > 0  # Valid positive volatility


def test_volatility_classification_low():
    """Low volatility when stddev/mean < 0.71."""
    tracker = VolatilityTracker(window=5)

    # Steady uptrend with small moves (low variance in return sizes)
    prices = [100.0, 100.1, 100.2, 100.3, 100.4, 100.5]
    for p in prices:
        tracker.add_price(p)

    assert tracker.classify_volatility() == "low"


def test_volatility_classification_high():
    """High volatility when stddev/mean > 0.92."""
    tracker = VolatilityTracker(window=5)

    # Mixed small and large moves create high variance in return sizes
    # Returns: +1%, -1%, +10%, -9%, +1% -> high stddev/mean ratio
    prices = [100.0, 101.0, 100.0, 110.0, 100.0, 101.0]
    for p in prices:
        tracker.add_price(p)

    assert tracker.classify_volatility() == "high"


def test_get_trail_distance():
    """Trail distance varies by volatility classification."""
    tracker = VolatilityTracker(window=5)

    # Low vol config
    assert tracker.get_trail_distance("low") == 0.8
    assert tracker.get_trail_distance("medium") == 1.2
    assert tracker.get_trail_distance("high") == 1.8
