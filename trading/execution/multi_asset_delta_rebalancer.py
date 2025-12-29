"""
MultiAssetDeltaRebalancer - Per-asset delta tracking and rebalancing.

Tracks delta drift between long and short positions for each hedgeable asset.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any

from core.types import DeltaState

logger = logging.getLogger(__name__)


@dataclass
class RebalanceResult:
    """Result of a rebalance operation."""
    symbol: str
    direction: str  # "increase" or "decrease"
    qty_adjusted: float
    new_short_qty: float
    fees_paid: float
    success: bool


class MultiAssetDeltaRebalancer:
    """
    Multi-asset delta rebalancer.

    Tracks delta drift per hedgeable asset and triggers rebalancing
    when drift exceeds dynamic threshold.

    Features:
    - Per-asset delta tracking
    - Dynamic threshold based on volatility
    - Batching of trades into single adjustment
    - Minimum interval between rebalances
    """

    DEFAULT_CONFIG = {
        "calm_threshold_pct": 3.0,
        "normal_threshold_pct": 5.0,
        "volatile_threshold_pct": 8.0,
        "volatility_calm": 0.5,
        "volatility_high": 1.5,
        "min_rebalance_interval": 30,
    }

    def __init__(
        self,
        hedgeable_symbols: List[str],
        hedge_manager: Any,  # MultiAssetHedgeManager
        premium_controller: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            hedgeable_symbols: List of symbols that can be hedged
            hedge_manager: MultiAssetHedgeManager instance
            premium_controller: Optional premium controller for volatility
            config: Optional configuration overrides
        """
        self._hedgeable = hedgeable_symbols
        self._hedge_manager = hedge_manager
        self._premium_controller = premium_controller
        self._config = {**self.DEFAULT_CONFIG, **(config or {})}

        # Per-symbol state
        self._states: Dict[str, DeltaState] = {
            sym: DeltaState(symbol=sym) for sym in hedgeable_symbols
        }
        self._last_rebalance: Dict[str, Optional[datetime]] = {
            sym: None for sym in hedgeable_symbols
        }

        # Statistics
        self._rebalance_counts: Dict[str, int] = {sym: 0 for sym in hedgeable_symbols}
        self._total_fees: Dict[str, float] = {sym: 0.0 for sym in hedgeable_symbols}

        logger.info(f"MultiAssetDeltaRebalancer initialized for {hedgeable_symbols}")

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        hedge_manager: Any,
        premium_controller: Optional[Any] = None,
    ) -> "MultiAssetDeltaRebalancer":
        """Create from allocation config."""
        assets = config.get("assets", {})
        hedgeable = [
            symbol for symbol, cfg in assets.items()
            if cfg.get("enabled") and cfg.get("hedge_enabled")
        ]
        return cls(
            hedgeable_symbols=hedgeable,
            hedge_manager=hedge_manager,
            premium_controller=premium_controller,
        )

    def get_dynamic_threshold(self, symbol: str) -> float:
        """Get dynamic threshold based on volatility for a symbol."""
        if not self._premium_controller:
            return self._config["normal_threshold_pct"]

        try:
            # Get volatility from premium controller
            stats = self._premium_controller.get_stats(symbol)
            if stats is None:
                return self._config["normal_threshold_pct"]

            sigma = stats.get('std', 0.0) if isinstance(stats, dict) else getattr(stats, 'std', 0.0)

            calm = self._config["volatility_calm"]
            high = self._config["volatility_high"]
            calm_thresh = self._config["calm_threshold_pct"]
            vol_thresh = self._config["volatile_threshold_pct"]

            if sigma < calm:
                return calm_thresh
            elif sigma > high:
                return vol_thresh
            else:
                ratio = (sigma - calm) / (high - calm)
                return calm_thresh + ratio * (vol_thresh - calm_thresh)

        except Exception:
            return self._config["normal_threshold_pct"]

    def get_delta_state(
        self,
        symbol: str,
        long_qty: float,
        short_qty: float,
    ) -> DeltaState:
        """
        Calculate delta state for a symbol.

        Args:
            symbol: Asset symbol
            long_qty: Long position quantity
            short_qty: Short position quantity

        Returns:
            DeltaState with current delta info
        """
        if symbol not in self._states:
            self._states[symbol] = DeltaState(symbol=symbol)

        state = self._states[symbol]
        state.update(long_qty, short_qty)

        return state

    def on_alpha_trade(
        self,
        symbol: str,
        qty: float,
        direction: str,
    ) -> None:
        """
        Record an alpha trade for batched rebalancing.

        Args:
            symbol: Asset symbol
            qty: Quantity traded
            direction: "buy" or "sell"
        """
        if symbol not in self._hedgeable:
            return

        if symbol not in self._states:
            self._states[symbol] = DeltaState(symbol=symbol)

        if direction == "buy":
            self._states[symbol].add_pending(qty)
        else:
            self._states[symbol].add_pending(-qty)

        logger.debug(f"[{symbol}] Alpha trade: {direction} {qty:.6f}, "
                    f"pending delta: {self._states[symbol].pending_delta:.6f}")

    async def flush_rebalance(
        self,
        positions: Dict[str, float],
        prices: Dict[str, float],
    ) -> List[RebalanceResult]:
        """
        Execute batched rebalancing for all symbols.

        Args:
            positions: Dict of symbol -> long position quantity
            prices: Dict of symbol -> current price

        Returns:
            List of rebalance results
        """
        results = []

        for symbol in self._hedgeable:
            result = await self._rebalance_symbol(
                symbol,
                positions.get(symbol, 0),
                prices.get(symbol, 0),
            )
            if result:
                results.append(result)

        return results

    async def _rebalance_symbol(
        self,
        symbol: str,
        long_qty: float,
        price: float,
    ) -> Optional[RebalanceResult]:
        """Rebalance a single symbol."""
        # Get current short position
        short_qty = self._hedge_manager.get_position_qty(symbol)

        # Get delta state
        state = self.get_delta_state(symbol, long_qty, short_qty)

        # Check if has hedge position
        if short_qty <= 0:
            state.clear_pending()
            return None

        # Get threshold
        threshold = self.get_dynamic_threshold(symbol)

        # Check if rebalancing needed
        if state.drift_pct <= threshold:
            logger.debug(f"[{symbol}] No rebalance needed: "
                        f"drift {state.drift_pct:.2f}% <= threshold {threshold:.2f}%")
            state.clear_pending()
            return None

        # Check minimum interval
        now = datetime.now()
        last = self._last_rebalance.get(symbol)
        min_interval = self._config["min_rebalance_interval"]

        if last:
            elapsed = (now - last).total_seconds()
            if elapsed < min_interval:
                logger.debug(f"[{symbol}] Rebalance skipped: "
                            f"{elapsed:.0f}s < {min_interval}s interval")
                return None

        # Target is 1:1 delta-neutral
        target_qty = long_qty

        logger.info(f"[{symbol}] Rebalancing: drift {state.drift_pct:.2f}% > "
                   f"threshold {threshold:.2f}%, target: {target_qty:.6f}")

        try:
            result = await self._hedge_manager.adjust_position(
                symbol, target_qty, price
            )

            if result and result.get('success'):
                self._last_rebalance[symbol] = now
                self._rebalance_counts[symbol] += 1
                self._total_fees[symbol] += result.get('fees_paid', 0)
                state.clear_pending()
                state.last_rebalance = int(now.timestamp() * 1000)

                return RebalanceResult(
                    symbol=symbol,
                    direction=result.get('direction', 'unknown'),
                    qty_adjusted=result.get('qty_adjusted', 0),
                    new_short_qty=result.get('new_short_qty', 0),
                    fees_paid=result.get('fees_paid', 0),
                    success=True,
                )

        except Exception as e:
            logger.error(f"[{symbol}] Rebalance failed: {e}")

        return RebalanceResult(
            symbol=symbol,
            direction="unknown",
            qty_adjusted=0,
            new_short_qty=short_qty,
            fees_paid=0,
            success=False,
        )

    def get_all_states(self) -> Dict[str, DeltaState]:
        """Get delta states for all symbols."""
        return self._states.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get rebalancing statistics."""
        return {
            "hedgeable_symbols": self._hedgeable,
            "states": {
                symbol: {
                    "long_qty": state.long_qty,
                    "short_qty": state.short_qty,
                    "net_delta": state.net_delta,
                    "drift_pct": state.drift_pct,
                    "pending_delta": state.pending_delta,
                    "threshold_pct": self.get_dynamic_threshold(symbol),
                }
                for symbol, state in self._states.items()
            },
            "rebalance_counts": self._rebalance_counts,
            "total_fees": self._total_fees,
            "last_rebalance": {
                sym: ts.isoformat() if ts else None
                for sym, ts in self._last_rebalance.items()
            },
        }
