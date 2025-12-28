"""
DeltaRebalancer - Automatic delta-neutral rebalancing for hedge positions.

Tracks delta drift between Upbit long and Binance short positions,
and triggers automatic rebalancing when drift exceeds dynamic threshold.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .paper_account import PaperTradingAccount
    from .hedge_manager import HedgeManager
    from ..risk.premium_controller import PremiumController

logger = logging.getLogger(__name__)


@dataclass
class DeltaState:
    """Current delta exposure state."""
    long_btc: float          # Upbit BTC holdings
    short_btc: float         # Binance short position
    net_delta: float         # long - short (positive = net long)
    drift_pct: float         # abs(net_delta) / long_btc * 100
    threshold_pct: float     # Current dynamic threshold
    needs_rebalance: bool    # drift_pct > threshold_pct


@dataclass
class RebalanceResult:
    """Result of a rebalance operation."""
    direction: str           # "increase" or "decrease"
    qty_adjusted: float      # BTC quantity adjusted
    new_short_qty: float     # New total short position
    fees_paid: float         # Fees for adjustment
    success: bool


class DeltaRebalancer:
    """
    Automatic delta-neutral rebalancing.

    Responsibilities:
    - Track delta drift between Upbit long and Binance short
    - Calculate dynamic threshold from premium volatility
    - Trigger HedgeManager.adjust_position() when drift exceeds threshold
    - Batch multiple Alpha trades into single adjustment

    Features:
    - Dynamic threshold based on premium volatility (σ)
    - Batching of multiple Alpha trades into single adjustment
    - Minimum interval between rebalances to avoid over-trading
    """

    # Default configuration
    DEFAULT_CONFIG = {
        "calm_threshold_pct": 3.0,      # Threshold when σ < 0.5%
        "normal_threshold_pct": 5.0,    # Threshold when 0.5% <= σ <= 1.5%
        "volatile_threshold_pct": 8.0,  # Threshold when σ > 1.5%
        "volatility_calm": 0.5,         # Premium σ considered "calm"
        "volatility_high": 1.5,         # Premium σ considered "volatile"
        "min_rebalance_interval": 30,   # Minimum seconds between rebalances
    }

    def __init__(
        self,
        upbit_account: "PaperTradingAccount",
        hedge_manager: "HedgeManager",
        premium_controller: "PremiumController",
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize DeltaRebalancer.

        Args:
            upbit_account: Upbit trading account for balance queries
            hedge_manager: HedgeManager for position adjustments
            premium_controller: PremiumController for volatility stats
            config: Optional configuration overrides
        """
        self.upbit_account = upbit_account
        self.hedge_manager = hedge_manager
        self.premium_controller = premium_controller

        # Merge config with defaults
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}

        # Extract config values
        self.calm_threshold = self.config["calm_threshold_pct"]
        self.normal_threshold = self.config["normal_threshold_pct"]
        self.volatile_threshold = self.config["volatile_threshold_pct"]
        self.volatility_calm = self.config["volatility_calm"]
        self.volatility_high = self.config["volatility_high"]
        self.min_rebalance_interval = self.config["min_rebalance_interval"]

        # Batching state
        self._pending_delta: float = 0.0
        self._last_rebalance_time: Optional[datetime] = None

        # Statistics
        self._rebalance_count: int = 0
        self._total_qty_adjusted: float = 0.0
        self._total_fees_paid: float = 0.0

    def get_dynamic_threshold(self) -> float:
        """
        Calculate rebalancing threshold based on premium volatility.

        Returns:
            Threshold percentage (3.0 to 8.0 based on volatility)
        """
        stats = self.premium_controller.get_stats()
        if stats is None:
            return self.normal_threshold

        sigma = stats.get('std', 0.0) if isinstance(stats, dict) else getattr(stats, 'std', 0.0)

        if sigma < self.volatility_calm:
            return self.calm_threshold
        elif sigma > self.volatility_high:
            return self.volatile_threshold
        else:
            # Linear interpolation between calm and volatile thresholds
            ratio = (sigma - self.volatility_calm) / (self.volatility_high - self.volatility_calm)
            return self.calm_threshold + ratio * (self.volatile_threshold - self.calm_threshold)

    def get_delta_state(self) -> DeltaState:
        """
        Calculate current delta exposure and rebalance need.

        Returns:
            DeltaState with current positions and drift info
        """
        # Get long position (Upbit)
        _, long_btc = self.upbit_account.get_balance()

        # Get short position (Binance hedge)
        short_btc = 0.0
        if self.hedge_manager.hedge_position:
            short_btc = self.hedge_manager.hedge_position.qty

        # Calculate delta
        net_delta = long_btc - short_btc

        # Calculate drift percentage
        if long_btc > 0:
            drift_pct = abs(net_delta) / long_btc * 100
        else:
            drift_pct = 0.0

        # Get dynamic threshold
        threshold_pct = self.get_dynamic_threshold()

        return DeltaState(
            long_btc=round(long_btc, 8),
            short_btc=round(short_btc, 8),
            net_delta=round(net_delta, 8),
            drift_pct=round(drift_pct, 2),
            threshold_pct=round(threshold_pct, 2),
            needs_rebalance=drift_pct > threshold_pct,
        )

    def on_alpha_trade(self, qty_change: float, direction: str) -> None:
        """
        Record an Alpha trade for batched rebalancing.

        Called after each Alpha trade execution to accumulate delta changes.
        Actual rebalancing happens in flush_rebalance().

        Args:
            qty_change: BTC quantity changed (positive)
            direction: "buy" or "sell"
        """
        if direction == "buy":
            self._pending_delta += qty_change
        else:  # sell
            self._pending_delta -= qty_change

        logger.debug(f"Alpha trade recorded: {direction} {qty_change:.4f} BTC, pending delta: {self._pending_delta:.4f}")

    async def flush_rebalance(self, binance_price: float) -> Optional[RebalanceResult]:
        """
        Execute batched rebalance if threshold exceeded.

        Called at the end of Alpha execution cycle to process accumulated
        delta changes. Executes a single adjustment order if needed.

        Args:
            binance_price: Current Binance BTC price for order execution

        Returns:
            RebalanceResult if adjustment made, None otherwise
        """
        # No hedge position to adjust
        if not self.hedge_manager.hedge_position:
            self._pending_delta = 0.0
            return None

        # Get current state
        state = self.get_delta_state()

        # Check if rebalancing needed
        if not state.needs_rebalance:
            logger.debug(f"No rebalance needed: drift {state.drift_pct:.2f}% <= threshold {state.threshold_pct:.2f}%")
            self._pending_delta = 0.0
            return None

        # Check minimum interval
        now = datetime.now()
        if self._last_rebalance_time:
            elapsed = (now - self._last_rebalance_time).total_seconds()
            if elapsed < self.min_rebalance_interval:
                logger.debug(f"Rebalance skipped: {elapsed:.0f}s < {self.min_rebalance_interval}s interval")
                return None

        # Calculate target (1:1 delta-neutral)
        target_qty = state.long_btc

        # Execute adjustment via HedgeManager
        logger.info(f"Rebalancing: drift {state.drift_pct:.2f}% > threshold {state.threshold_pct:.2f}%, "
                    f"adjusting to {target_qty:.4f} BTC")

        result = await self.hedge_manager.adjust_position(target_qty, binance_price)

        if result and result.get('success'):
            self._last_rebalance_time = now
            self._rebalance_count += 1
            self._total_qty_adjusted += result.get('qty_adjusted', 0)
            self._total_fees_paid += result.get('fees_paid', 0)

            logger.info(f"Rebalance complete: {result.get('direction')} {result.get('qty_adjusted', 0):.4f} BTC, "
                        f"fees: ${result.get('fees_paid', 0):.2f}")

        self._pending_delta = 0.0
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get rebalancing statistics."""
        state = self.get_delta_state()
        return {
            "current_state": {
                "long_btc": state.long_btc,
                "short_btc": state.short_btc,
                "net_delta": state.net_delta,
                "drift_pct": state.drift_pct,
                "threshold_pct": state.threshold_pct,
                "needs_rebalance": state.needs_rebalance,
            },
            "pending_delta": round(self._pending_delta, 8),
            "rebalance_count": self._rebalance_count,
            "total_qty_adjusted": round(self._total_qty_adjusted, 8),
            "total_fees_paid": round(self._total_fees_paid, 2),
            "last_rebalance": self._last_rebalance_time.isoformat() if self._last_rebalance_time else None,
        }
