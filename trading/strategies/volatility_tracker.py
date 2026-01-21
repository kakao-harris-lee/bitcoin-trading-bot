# trading/strategies/volatility_tracker.py
"""Volatility tracking for smart execution."""
from __future__ import annotations
from collections import deque
import statistics


class VolatilityTracker:
    """Tracks price volatility using rolling window of returns.

    All thresholds are configurable via constructor parameters.
    Defaults are calibrated for BTC minute-level returns.
    """

    # Default trail distances by volatility level (percentage)
    DEFAULT_TRAIL_DISTANCES = {
        "low": 0.8,
        "medium": 1.2,
        "high": 1.8,
    }

    # Default volatility thresholds (stddev/mean of returns)
    # Calibrated for BTC minute-level returns (25th/75th percentiles)
    DEFAULT_LOW_VOL_THRESHOLD = 0.71
    DEFAULT_HIGH_VOL_THRESHOLD = 0.92

    def __init__(
        self,
        window: int = 20,
        low_vol_threshold: float | None = None,
        high_vol_threshold: float | None = None,
        trail_distances: dict[str, float] | None = None,
    ):
        """Initialize tracker with configurable parameters.

        Args:
            window: Rolling window size for volatility calculation.
            low_vol_threshold: Threshold below which volatility is "low".
            high_vol_threshold: Threshold above which volatility is "high".
            trail_distances: Dict of trail distances by volatility level.
        """
        self.window = window
        self.prices: deque[float] = deque(maxlen=window + 1)

        # Use provided values or defaults
        self.LOW_VOL_THRESHOLD = low_vol_threshold or self.DEFAULT_LOW_VOL_THRESHOLD
        self.HIGH_VOL_THRESHOLD = high_vol_threshold or self.DEFAULT_HIGH_VOL_THRESHOLD
        self.TRAIL_DISTANCES = trail_distances or self.DEFAULT_TRAIL_DISTANCES.copy()

    def add_price(self, price: float) -> None:
        """Add a price point."""
        self.prices.append(price)

    def get_returns(self) -> list[float]:
        """Calculate percentage returns from prices."""
        if len(self.prices) < 2:
            return []

        returns = []
        prices_list = list(self.prices)
        for i in range(1, len(prices_list)):
            ret = (prices_list[i] - prices_list[i-1]) / prices_list[i-1]
            returns.append(ret)
        return returns

    def get_volatility(self) -> float | None:
        """Calculate volatility as stddev/mean of absolute returns."""
        returns = self.get_returns()
        if len(returns) < self.window:
            return None

        # Use last `window` returns
        recent = returns[-self.window:]
        abs_returns = [abs(r) for r in recent]

        if not abs_returns:
            return None

        mean_ret = statistics.mean(abs_returns)
        if mean_ret == 0:
            return 0.0

        stddev_ret = statistics.stdev(abs_returns) if len(abs_returns) > 1 else 0.0
        return stddev_ret / mean_ret if mean_ret > 0 else 0.0

    def classify_volatility(self) -> str:
        """Classify current volatility level."""
        vol = self.get_volatility()
        if vol is None:
            return "medium"  # Default when insufficient data

        if vol < self.LOW_VOL_THRESHOLD:
            return "low"
        elif vol > self.HIGH_VOL_THRESHOLD:
            return "high"
        else:
            return "medium"

    def get_trail_distance(self, classification: str | None = None) -> float:
        """Get trail distance percentage for volatility level."""
        if classification is None:
            classification = self.classify_volatility()
        return self.TRAIL_DISTANCES.get(classification, 1.2)

    def clear(self) -> None:
        """Clear all price data."""
        self.prices.clear()
