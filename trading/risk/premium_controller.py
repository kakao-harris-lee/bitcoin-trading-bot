"""
PremiumController - Kimchi Premium hedge execution controller.

Upgraded from PremiumTracker with execution decision authority.
Uses mean-reversion logic for entry/exit signals.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Literal
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


@dataclass
class HedgeSignal:
    """Signal for hedge execution."""
    action: Literal["open", "close", "hold"]
    reason: str
    target_btc_qty: float
    premium_stats: PremiumStats
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "target_btc_qty": self.target_btc_qty,
            "premium_stats": asdict(self.premium_stats),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class HedgeRiskConfig:
    """Risk configuration for hedge operations."""
    max_hedge_capital_pct: float = 0.8      # Max 80% of hedge pool
    min_premium_for_entry: float = 1.5      # Absolute minimum premium %
    volatility_block_threshold: float = 2.0  # Block if std > 2%
    negative_funding_exit: float = -0.05    # Exit if funding < -0.05%
    min_hold_minutes: int = 30              # Prevent flip-flopping


class PremiumController:
    """
    Premium-based hedge execution controller.

    Entry Logic:
      current_premium > (mean_24h + entry_sigma * std_24h)
      AND current_premium > entry_threshold (1.5%)
      AND volatility_state != "high"

    Exit Logic:
      current_premium <= mean_24h
      OR funding_rate < negative_funding_exit threshold

    Delta-Neutral:
      hedge_qty = upbit_btc_qty (1:1 matching)
    """

    DEFAULT_CONFIG = {
        # History settings
        "history_file": "logs/premium_history.json",
        "max_history_hours": 168,  # 7 days
        "volatility_window_hours": 24,

        # Entry/exit thresholds
        "entry_threshold_pct": 1.5,      # Minimum premium to consider
        "entry_sigma": 2.0,              # Standard deviations above mean
        "exit_to_mean": True,            # Exit when premium reverts to mean

        # Risk settings
        "min_hold_minutes": 30,          # Prevent rapid flip-flopping
        "negative_funding_exit": -0.05,  # Exit if funding too negative

        # Volatility thresholds
        "high_volatility_threshold": 2.0,
        "elevated_volatility_threshold": 1.0,

        # Funding rate alert thresholds
        "funding_rate_sharp_change_pct": 0.03,  # 0.03% absolute change triggers alert
        "funding_rate_critical_threshold": -0.1,  # Critical negative funding
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self.history: List[PremiumReading] = []
        self._history_path = Path(self.config["history_file"])

        # Position state (tracked by controller for signal generation)
        self._has_position: bool = False
        self._position_entry_time: Optional[datetime] = None
        self._last_funding_rate: float = 0.0
        self._previous_funding_rate: float = 0.0  # For detecting sharp changes
        self._funding_rate_change_time: Optional[datetime] = None

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

    def set_position_state(self, has_position: bool, entry_time: Optional[datetime] = None) -> None:
        """Update position state (called by HedgeManager after execution)."""
        self._has_position = has_position
        self._position_entry_time = entry_time if has_position else None

    def set_funding_rate(self, rate: float) -> None:
        """Update current funding rate (called periodically)."""
        self._previous_funding_rate = self._last_funding_rate
        self._last_funding_rate = rate
        self._funding_rate_change_time = datetime.now()

    def get_funding_rate_change(self) -> float:
        """Get the absolute change in funding rate from previous reading."""
        return abs(self._last_funding_rate - self._previous_funding_rate)

    def is_funding_rate_sharp_change(self) -> bool:
        """Check if funding rate has changed sharply since last reading."""
        threshold = self.config["funding_rate_sharp_change_pct"]
        return self.get_funding_rate_change() >= threshold

    def generate_signal(
        self,
        premium_info: Dict[str, float],
        upbit_btc_qty: float,
    ) -> HedgeSignal:
        """
        Generate hedge signal based on premium mean-reversion.

        Args:
            premium_info: Current premium data
            upbit_btc_qty: Current Upbit BTC balance to hedge

        Returns:
            HedgeSignal with action (open/close/hold)
        """
        # Record the premium reading
        self.record(premium_info)

        # Get current stats
        stats = self.get_stats()

        # ══════════════════════════════════════════════
        # SLIPPAGE GUARD: Block entry in high volatility
        # ══════════════════════════════════════════════
        if stats.volatility_state == "high" and not self._has_position:
            return HedgeSignal(
                action="hold",
                reason=f"volatility_guard: std={stats.std_24h:.2f}% too high",
                target_btc_qty=0,
                premium_stats=stats,
            )

        # ══════════════════════════════════════════════
        # ENTRY: Mean reversion + threshold
        # ══════════════════════════════════════════════
        entry_threshold = stats.mean_24h + (self.config["entry_sigma"] * stats.std_24h)
        min_premium = self.config["entry_threshold_pct"]

        if not self._has_position:
            if stats.current > entry_threshold and stats.current > min_premium:
                return HedgeSignal(
                    action="open",
                    reason=f"entry: {stats.current:.2f}% > {entry_threshold:.2f}% (μ+2σ) and > {min_premium}%",
                    target_btc_qty=upbit_btc_qty,  # 1:1 delta-neutral
                    premium_stats=stats,
                )

        # ══════════════════════════════════════════════
        # EXIT: Mean reversion OR negative funding
        # ══════════════════════════════════════════════
        if self._has_position:
            # Check minimum hold time
            if self._position_entry_time:
                hold_minutes = (datetime.now() - self._position_entry_time).total_seconds() / 60
                if hold_minutes < self.config["min_hold_minutes"]:
                    return HedgeSignal(
                        action="hold",
                        reason=f"min_hold: {hold_minutes:.0f}m < {self.config['min_hold_minutes']}m",
                        target_btc_qty=0,
                        premium_stats=stats,
                    )

            # Exit on mean reversion
            if stats.current <= stats.mean_24h:
                return HedgeSignal(
                    action="close",
                    reason=f"mean_reversion: {stats.current:.2f}% <= mean {stats.mean_24h:.2f}%",
                    target_btc_qty=0,
                    premium_stats=stats,
                )

            # Exit on negative funding
            if self._last_funding_rate < self.config["negative_funding_exit"]:
                return HedgeSignal(
                    action="close",
                    reason=f"negative_funding: {self._last_funding_rate:.4f}% < {self.config['negative_funding_exit']}%",
                    target_btc_qty=0,
                    premium_stats=stats,
                )

        # No action needed
        return HedgeSignal(
            action="hold",
            reason="no_action",
            target_btc_qty=0,
            premium_stats=stats,
        )

    def format_status(self, stats: Optional[PremiumStats] = None) -> str:
        """Format premium stats for display."""
        if stats is None:
            stats = self.get_stats()

        vol_emoji = {"normal": "🟢", "elevated": "🟡", "high": "🔴"}
        trend_emoji = {"stable": "➡️", "rising": "📈", "falling": "📉"}

        entry_threshold = stats.mean_24h + (self.config["entry_sigma"] * stats.std_24h)

        return (
            f"Premium: {stats.current:+.2f}% "
            f"(24h: {stats.mean_24h:+.2f}% ±{stats.std_24h:.2f}%) "
            f"[entry>{entry_threshold:.1f}%] "
            f"{vol_emoji.get(stats.volatility_state, '')} "
            f"{trend_emoji.get(stats.trend, '')}"
        )

    def should_alert(self, stats: Optional[PremiumStats] = None) -> Optional[str]:
        """
        Check if an alert should be sent.

        Returns alert message if threshold exceeded, None otherwise.
        Alert priority: CRITICAL > URGENT > NORMAL
        """
        if stats is None:
            stats = self.get_stats()

        critical_alerts = []  # Highest priority - immediate action needed
        urgent_alerts = []    # High priority - sharp changes detected
        normal_alerts = []    # Normal priority

        # ═══════════════════════════════════════════════════════
        # CRITICAL: Funding rate below critical threshold
        # ═══════════════════════════════════════════════════════
        critical_threshold = self.config["funding_rate_critical_threshold"]
        if self._last_funding_rate < critical_threshold:
            critical_alerts.append(
                f"🚨 CRITICAL Negative Funding: {self._last_funding_rate:.4f}% < {critical_threshold}%\n"
                f"   Immediate action required!"
            )

        # ═══════════════════════════════════════════════════════
        # URGENT: Sharp funding rate change detected
        # ═══════════════════════════════════════════════════════
        if self.is_funding_rate_sharp_change():
            change = self._last_funding_rate - self._previous_funding_rate
            direction = "↗️" if change > 0 else "↘️"
            urgent_alerts.append(
                f"⚡ Funding Rate Sharp Change {direction}: "
                f"{self._previous_funding_rate:.4f}% → {self._last_funding_rate:.4f}% "
                f"(Δ{change:+.4f}%)"
            )

        # ═══════════════════════════════════════════════════════
        # URGENT: High volatility warning
        # ═══════════════════════════════════════════════════════
        if stats.volatility_state == "high":
            urgent_alerts.append(f"⚠️ High Volatility: σ={stats.std_24h:.2f}%")

        # ═══════════════════════════════════════════════════════
        # NORMAL: Negative funding (but not critical)
        # ═══════════════════════════════════════════════════════
        if self._last_funding_rate < self.config["negative_funding_exit"] and not critical_alerts:
            normal_alerts.append(f"💸 Negative Funding: {self._last_funding_rate:.4f}%")

        # ═══════════════════════════════════════════════════════
        # NORMAL: Entry opportunity
        # ═══════════════════════════════════════════════════════
        entry_threshold = stats.mean_24h + (self.config["entry_sigma"] * stats.std_24h)
        if stats.current > entry_threshold and stats.current > self.config["entry_threshold_pct"]:
            if not self._has_position:
                normal_alerts.append(f"📊 Hedge Entry Opportunity: {stats.current:+.2f}% > {entry_threshold:.2f}%")

        # Combine alerts by priority
        all_alerts = critical_alerts + urgent_alerts + normal_alerts

        if all_alerts:
            return "\n".join(all_alerts)
        return None
