"""
Kimchi Premium Tracker - Phase 3 Implementation

Tracks premium history, calculates volatility, and provides
dynamic hedge ratio adjustments based on premium conditions.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
import statistics


@dataclass
class PremiumReading:
    """Single premium reading."""
    timestamp: str
    premium_pct: float
    upbit_usd: float
    binance_usd: float
    usd_krw_rate: float


@dataclass
class PremiumStats:
    """Calculated premium statistics."""
    current: float = 0.0
    mean_24h: float = 0.0
    std_24h: float = 0.0
    min_24h: float = 0.0
    max_24h: float = 0.0
    readings_count: int = 0
    volatility_state: str = "normal"  # normal, elevated, high
    trend: str = "stable"  # rising, falling, stable


class PremiumTracker:
    """
    Tracks Kimchi Premium history and provides analytics.

    Features:
    - Persistent history storage (JSON)
    - Rolling volatility calculation (24h window)
    - Premium state classification
    - Dynamic hedge ratio recommendations
    """

    DEFAULT_CONFIG = {
        "history_file": "logs/premium_history.json",
        "max_history_hours": 168,  # 7 days
        "volatility_window_hours": 24,
        "alert_threshold_pct": 5.0,
        "high_volatility_threshold": 2.0,  # std dev threshold
        "elevated_volatility_threshold": 1.0,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self.history: List[PremiumReading] = []
        self._history_path = Path(self.config["history_file"])
        self._load_history()

    def _load_history(self) -> None:
        """Load premium history from file."""
        try:
            if self._history_path.exists():
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                self.history = [
                    PremiumReading(**r) for r in data.get("readings", [])
                ]
                self._prune_old_readings()
        except Exception as e:
            print(f"⚠️ Premium history load failed: {e}")
            self.history = []

    def _save_history(self) -> None:
        """Save premium history to file."""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "updated_at": datetime.now().isoformat(),
                "readings": [asdict(r) for r in self.history],
            }
            self._history_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"⚠️ Premium history save failed: {e}")

    def _prune_old_readings(self) -> None:
        """Remove readings older than max_history_hours."""
        cutoff = datetime.now() - timedelta(hours=self.config["max_history_hours"])
        cutoff_str = cutoff.isoformat()
        self.history = [r for r in self.history if r.timestamp >= cutoff_str]

    def record(self, premium_info: Dict[str, float]) -> None:
        """Record a new premium reading."""
        reading = PremiumReading(
            timestamp=datetime.now().isoformat(),
            premium_pct=premium_info.get("premium_pct", 0.0),
            upbit_usd=premium_info.get("upbit_usd", 0.0),
            binance_usd=premium_info.get("binance_usd", 0.0),
            usd_krw_rate=premium_info.get("usd_krw_rate", 1450),
        )
        self.history.append(reading)
        self._prune_old_readings()
        self._save_history()

    def get_stats(self) -> PremiumStats:
        """Calculate premium statistics from history."""
        if not self.history:
            return PremiumStats()

        # Get readings from last 24 hours
        cutoff = datetime.now() - timedelta(hours=self.config["volatility_window_hours"])
        cutoff_str = cutoff.isoformat()
        recent = [r for r in self.history if r.timestamp >= cutoff_str]

        if not recent:
            return PremiumStats(current=self.history[-1].premium_pct if self.history else 0.0)

        premiums = [r.premium_pct for r in recent]
        current = premiums[-1]
        mean = statistics.mean(premiums)
        std = statistics.stdev(premiums) if len(premiums) > 1 else 0.0

        # Classify volatility state
        high_thresh = self.config["high_volatility_threshold"]
        elevated_thresh = self.config["elevated_volatility_threshold"]

        if std >= high_thresh:
            volatility_state = "high"
        elif std >= elevated_thresh:
            volatility_state = "elevated"
        else:
            volatility_state = "normal"

        # Determine trend (compare last 3 readings if available)
        if len(premiums) >= 3:
            recent_3 = premiums[-3:]
            if recent_3[-1] > recent_3[0] + 0.5:
                trend = "rising"
            elif recent_3[-1] < recent_3[0] - 0.5:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return PremiumStats(
            current=round(current, 2),
            mean_24h=round(mean, 2),
            std_24h=round(std, 2),
            min_24h=round(min(premiums), 2),
            max_24h=round(max(premiums), 2),
            readings_count=len(recent),
            volatility_state=volatility_state,
            trend=trend,
        )

    def get_hedge_adjustment(
        self,
        base_target: float,
        regime: str,
        stats: Optional[PremiumStats] = None
    ) -> Dict[str, Any]:
        """
        Calculate dynamic hedge ratio adjustment based on premium conditions.

        Strategy:
        - High premium (>5%): Increase hedge to lock in premium
        - Low/negative premium: Reduce hedge, wait for better entry
        - High volatility: Widen bounds, more cautious
        - Rising premium in SIDEWAYS: Aggressive hedging opportunity
        """
        if stats is None:
            stats = self.get_stats()

        alert_threshold = self.config["alert_threshold_pct"]
        adjustment = 0.0
        reason = "normal"

        # Premium-based adjustments
        if stats.current >= alert_threshold:
            # High premium - increase hedge to capture it
            adjustment = 0.1
            reason = f"high_premium ({stats.current:+.1f}%)"
        elif stats.current <= -alert_threshold:
            # Negative premium - reduce hedge, unfavorable
            adjustment = -0.15
            reason = f"negative_premium ({stats.current:+.1f}%)"
        elif stats.current >= 3.0:
            # Moderately high premium
            adjustment = 0.05
            reason = f"elevated_premium ({stats.current:+.1f}%)"

        # Volatility-based adjustments
        if stats.volatility_state == "high":
            # High volatility - be more cautious
            adjustment *= 0.5
            reason += " + high_volatility"

        # Trend-based adjustments (for SIDEWAYS regime)
        if regime == "SIDEWAYS" and stats.trend == "rising":
            adjustment += 0.05
            reason += " + rising_trend"

        adjusted_target = max(0.0, min(1.0, base_target + adjustment))

        return {
            "base_target": base_target,
            "adjusted_target": round(adjusted_target, 2),
            "adjustment": round(adjustment, 2),
            "reason": reason,
            "premium_stats": asdict(stats),
        }

    def should_alert(self, stats: Optional[PremiumStats] = None) -> Optional[str]:
        """
        Check if an alert should be sent.

        Returns alert message if threshold exceeded, None otherwise.
        """
        if stats is None:
            stats = self.get_stats()

        alert_threshold = self.config["alert_threshold_pct"]

        alerts = []

        # Premium threshold alerts
        if abs(stats.current) >= alert_threshold:
            direction = "HIGH" if stats.current > 0 else "NEGATIVE"
            alerts.append(f"📊 {direction} Premium: {stats.current:+.2f}%")

        # Volatility alerts
        if stats.volatility_state == "high":
            alerts.append(f"⚠️ High Volatility: σ={stats.std_24h:.2f}%")

        # Trend alerts (significant moves)
        if stats.trend == "rising" and stats.current > stats.mean_24h + 1.0:
            alerts.append(f"📈 Premium Rising: {stats.mean_24h:.1f}% → {stats.current:.1f}%")
        elif stats.trend == "falling" and stats.current < stats.mean_24h - 1.0:
            alerts.append(f"📉 Premium Falling: {stats.mean_24h:.1f}% → {stats.current:.1f}%")

        if alerts:
            return "\n".join(alerts)
        return None

    def format_status(self, stats: Optional[PremiumStats] = None) -> str:
        """Format premium stats for display."""
        if stats is None:
            stats = self.get_stats()

        vol_emoji = {"normal": "🟢", "elevated": "🟡", "high": "🔴"}
        trend_emoji = {"stable": "➡️", "rising": "📈", "falling": "📉"}

        return (
            f"Premium: {stats.current:+.2f}% "
            f"(24h: {stats.mean_24h:+.2f}% ±{stats.std_24h:.2f}%) "
            f"{vol_emoji.get(stats.volatility_state, '')} "
            f"{trend_emoji.get(stats.trend, '')}"
        )
