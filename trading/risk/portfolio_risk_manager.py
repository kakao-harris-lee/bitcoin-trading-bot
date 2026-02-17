"""Portfolio-level risk management.

Manages:
1. Total risk cap across all open positions
2. Maximum number of concurrent positions
3. Integration with correlation filter

The key insight: sum of individual position risks should not exceed X% of equity.
"""
# pylint: disable=broad-exception-caught

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.risk.correlation_filter import CorrelationFilter

logger = logging.getLogger(__name__)


@dataclass
class RiskCapConfig:
    """Configuration for portfolio risk limits."""

    max_total_risk_pct: float = 0.05
    """Maximum total risk across all positions (5% default)."""

    max_open_positions: int = 5
    """Maximum number of concurrent positions."""

    risk_per_trade_pct: float = 0.01
    """Risk per trade (1% default). Used for validation."""

    use_correlation_filter: bool = True
    """Whether to apply correlation filtering."""

    corr_threshold: float = 0.75
    """Block entry if correlation > this threshold."""

    corr_lookback_bars: int = 240
    """Number of bars for correlation calculation."""

    corr_action: str = "block"
    """Action on high correlation: 'block', 'reduce', 'group_cap'."""

    corr_reduction_factor: float = 0.5
    """If corr_action='reduce', multiply risk by this factor."""

    @classmethod
    def from_dict(cls, config: Dict) -> "RiskCapConfig":
        """Create from allocation.json config."""
        return cls(
            max_total_risk_pct=config.get("max_total_risk_pct", 0.05),
            max_open_positions=config.get("max_open_positions", 5),
            risk_per_trade_pct=config.get("risk_per_trade_pct", 0.01),
            use_correlation_filter=config.get("correlation_filter", True),
            corr_threshold=config.get("corr_threshold", 0.75),
            corr_lookback_bars=config.get("corr_lookback_bars", 240),
            corr_action=config.get("corr_action", "block"),
            corr_reduction_factor=config.get("corr_reduction_factor", 0.5),
        )


@dataclass
class RiskCheckResult:
    """Result of portfolio risk check."""

    allowed: bool
    """Whether the trade is allowed."""

    reason: str
    """Reason for decision."""

    adjusted_risk_pct: Optional[float] = None
    """Adjusted risk percentage (if reduced due to correlation)."""

    current_total_risk: float = 0.0
    """Current total risk across all positions."""

    remaining_risk_budget: float = 0.0
    """Remaining risk budget before hitting cap."""


@dataclass
class OpenPositionRisk:
    """Risk info for a single open position."""

    symbol: str
    entry_price: float
    quantity: float
    stop_price: float
    risk_amount: float  # USDT
    leverage: int


class PortfolioRiskManager:
    """Manages portfolio-level risk limits.

    Responsibilities:
    - Track total risk across all open positions
    - Enforce position count limits
    - Integrate correlation filtering
    - Queue trades when at capacity (optional)

    Usage:
        mgr = PortfolioRiskManager(config, redis)
        result = await mgr.can_open_trade("BTC", proposed_risk=100, equity=10000)
        if result.allowed:
            # proceed with trade
        else:
            logger.info(f"Blocked: {result.reason}")
    """

    def __init__(
        self,
        config: RiskCapConfig,
        redis: "RedisStreams",
        correlation_filter: Optional["CorrelationFilter"] = None,
        symbols: Optional[List[str]] = None,
    ):
        self.config = config
        self.redis = redis
        self.correlation_filter = correlation_filter
        self._symbols = symbols or ["BTC", "ETH", "SOL", "BNB"]

        # Cache for open position risks (refreshed periodically)
        self._risk_cache: Dict[str, OpenPositionRisk] = {}
        self._cache_ts: float = 0
        self._cache_ttl: float = 5.0  # 5 seconds

    async def can_open_trade(
        self,
        symbol: str,
        proposed_risk: float,
        equity: float,
        proposed_stop_pct: Optional[float] = None,
    ) -> RiskCheckResult:
        """Check if a new trade can be opened.

        Args:
            symbol: Symbol to trade.
            proposed_risk: Expected risk amount (USDT) for this trade.
            equity: Current account equity (USDT).
            proposed_stop_pct: Stop distance (for correlation risk grouping).

        Returns:
            RiskCheckResult indicating whether trade is allowed.
        """
        _ = proposed_stop_pct
        await self._refresh_risk_cache()
        open_positions = self._risk_cache
        current_total_risk, max_total_risk = self._calculate_risk_totals(open_positions, equity)

        if not self._has_existing_symbol_position(symbol, open_positions):
            if len(open_positions) >= self.config.max_open_positions:
                return self._blocked_result(
                    reason=f"MAX_POSITIONS:{len(open_positions)}>={self.config.max_open_positions}",
                    current_total_risk=current_total_risk,
                    remaining_risk=max(0, max_total_risk - current_total_risk),
                )

        new_total_risk = current_total_risk + proposed_risk
        if new_total_risk > max_total_risk:
            return self._blocked_result(
                reason=f"TOTAL_RISK_CAP:${new_total_risk:.0f}>${max_total_risk:.0f}",
                current_total_risk=current_total_risk,
                remaining_risk=max(0, max_total_risk - current_total_risk),
            )

        adjusted_risk_pct = None
        if self.config.use_correlation_filter and self.correlation_filter:
            existing_symbols = self._existing_symbols(open_positions, symbol)
            if existing_symbols:
                corr_result = await self._check_correlation(
                    symbol, existing_symbols, proposed_risk, equity
                )
                if not corr_result.allowed:
                    return corr_result
                if corr_result.adjusted_risk_pct:
                    adjusted_risk_pct = corr_result.adjusted_risk_pct

        reason = self._approval_reason(adjusted_risk_pct)
        logger.info(
            "%s: risk check PASSED - proposed=$%.0f, total=$%.0f/$%.0f (%.1f%%)",
            symbol,
            proposed_risk,
            new_total_risk,
            max_total_risk,
            (new_total_risk / equity * 100) if equity > 0 else 0.0,
        )
        return self._approved_result(
            reason=reason,
            adjusted_risk_pct=adjusted_risk_pct,
            current_total_risk=current_total_risk,
            remaining_risk=max(0, max_total_risk - new_total_risk),
        )

    def _calculate_risk_totals(
        self,
        open_positions: Dict[str, OpenPositionRisk],
        equity: float,
    ) -> tuple[float, float]:
        current_total_risk = sum(p.risk_amount for p in open_positions.values())
        max_total_risk = equity * self.config.max_total_risk_pct
        return current_total_risk, max_total_risk

    def _has_existing_symbol_position(
        self,
        symbol: str,
        open_positions: Dict[str, OpenPositionRisk],
    ) -> bool:
        return any(key.startswith(f"{symbol}_") for key in open_positions)

    def _existing_symbols(
        self,
        open_positions: Dict[str, OpenPositionRisk],
        symbol: str,
    ) -> List[str]:
        return list({key.split("_")[0] for key in open_positions if key.split("_")[0] != symbol})

    @staticmethod
    def _approval_reason(adjusted_risk_pct: Optional[float]) -> str:
        if adjusted_risk_pct:
            return f"CORR_ADJUSTED:{adjusted_risk_pct:.4f}"
        return "OK"

    @staticmethod
    def _blocked_result(
        reason: str,
        current_total_risk: float,
        remaining_risk: float,
    ) -> RiskCheckResult:
        return RiskCheckResult(
            allowed=False,
            reason=reason,
            current_total_risk=current_total_risk,
            remaining_risk_budget=remaining_risk,
        )

    @staticmethod
    def _approved_result(
        reason: str,
        adjusted_risk_pct: Optional[float],
        current_total_risk: float,
        remaining_risk: float,
    ) -> RiskCheckResult:
        return RiskCheckResult(
            allowed=True,
            reason=reason,
            adjusted_risk_pct=adjusted_risk_pct,
            current_total_risk=current_total_risk,
            remaining_risk_budget=remaining_risk,
        )

    async def _refresh_risk_cache(self) -> None:
        """Refresh cached position risks from Redis."""
        now = time.time()
        if now - self._cache_ts < self._cache_ttl:
            return

        self._risk_cache = {}

        for symbol in self._symbols:
            for market in ["spot", "futures"]:
                try:
                    pos = await self.redis.get_position(symbol, market)
                    if not pos:
                        continue

                    qty = float(pos.get("quantity", 0))
                    if qty <= 0:
                        continue

                    entry_price = float(pos.get("entry_price", 0))
                    stop_price = float(pos.get("stop_price", 0))
                    leverage = int(pos.get("leverage", 1))

                    # Calculate risk if stop_price is set
                    if stop_price > 0 and entry_price > 0:
                        side = pos.get("side", "buy")
                        if side == "buy":  # Long
                            stop_distance = (entry_price - stop_price) / entry_price
                        else:  # Short
                            stop_distance = (stop_price - entry_price) / entry_price

                        risk_amount = qty * entry_price * max(0, stop_distance)
                    else:
                        # Default to 3% stop if not set
                        risk_amount = qty * entry_price * 0.03

                    # Use composite key: symbol_market
                    cache_key = f"{symbol}_{market}"
                    self._risk_cache[cache_key] = OpenPositionRisk(
                        symbol=symbol,
                        entry_price=entry_price,
                        quantity=qty,
                        stop_price=stop_price,
                        risk_amount=risk_amount,
                        leverage=leverage,
                    )

                except Exception as e:
                    logger.warning(
                        "Failed to get position risk for %s %s: %s",
                        symbol,
                        market,
                        e,
                    )

        self._cache_ts = now

    async def _check_correlation(
        self,
        new_symbol: str,
        existing_symbols: List[str],
        proposed_risk: float,
        equity: float,
    ) -> RiskCheckResult:
        """Check correlation with existing positions.

        Actions based on config.corr_action:
        - 'block': Reject entry if corr > threshold
        - 'reduce': Allow but reduce risk budget
        - 'group_cap': Apply combined risk cap to correlated group
        """
        if not self.correlation_filter:
            return RiskCheckResult(allowed=True, reason="NO_CORR_FILTER")

        max_corr, correlated_with = await self._find_max_correlation(new_symbol, existing_symbols)

        if max_corr <= self.config.corr_threshold:
            return RiskCheckResult(allowed=True, reason="CORR_OK")

        logger.warning(
            "%s: high correlation with %s (corr=%.2f > %.2f)",
            new_symbol,
            correlated_with,
            max_corr,
            self.config.corr_threshold,
        )

        if self.config.corr_action == "block":
            return self._correlation_block_result(new_symbol, correlated_with, max_corr)
        if self.config.corr_action == "reduce":
            adjusted_risk = self.config.risk_per_trade_pct * self.config.corr_reduction_factor
            return RiskCheckResult(
                allowed=True,
                reason=f"CORR_REDUCED:{new_symbol}-{correlated_with}={max_corr:.2f}",
                adjusted_risk_pct=adjusted_risk,
            )
        if self.config.corr_action == "group_cap":
            return self._correlation_group_cap_result(
                new_symbol=new_symbol,
                correlated_with=correlated_with,
                proposed_risk=proposed_risk,
                equity=equity,
            )
        return RiskCheckResult(allowed=True, reason="UNKNOWN_CORR_ACTION")

    async def _find_max_correlation(
        self,
        new_symbol: str,
        existing_symbols: List[str],
    ) -> tuple[float, str | None]:
        max_corr = 0.0
        correlated_with: str | None = None
        for existing in existing_symbols:
            corr = await self.correlation_filter.get_correlation(new_symbol, existing)
            if corr > max_corr:
                max_corr = corr
                correlated_with = existing
        return max_corr, correlated_with

    @staticmethod
    def _correlation_block_result(
        new_symbol: str,
        correlated_with: str | None,
        max_corr: float,
    ) -> RiskCheckResult:
        return RiskCheckResult(
            allowed=False,
            reason=f"HIGH_CORR:{new_symbol}-{correlated_with}={max_corr:.2f}",
        )

    def _correlation_group_cap_result(
        self,
        new_symbol: str,
        correlated_with: str | None,
        proposed_risk: float,
        equity: float,
    ) -> RiskCheckResult:
        _ = new_symbol
        corr_risk = self._correlated_symbol_risk(correlated_with)
        group_risk = corr_risk + proposed_risk
        group_cap = equity * self.config.risk_per_trade_pct * 2
        if group_risk > group_cap:
            return RiskCheckResult(
                allowed=False,
                reason=f"CORR_GROUP_CAP:{group_risk:.0f}>{group_cap:.0f}",
            )
        return RiskCheckResult(allowed=True, reason="CORR_GROUP_OK")

    def _correlated_symbol_risk(self, correlated_with: str | None) -> float:
        if not correlated_with:
            return 0.0
        return sum(
            position.risk_amount
            for key, position in self._risk_cache.items()
            if key.startswith(f"{correlated_with}_")
        )

    async def get_portfolio_risk_summary(self, equity: float) -> Dict:
        """Get current portfolio risk summary.

        Useful for dashboards and monitoring.
        """
        await self._refresh_risk_cache()

        total_risk = sum(p.risk_amount for p in self._risk_cache.values())
        max_risk = equity * self.config.max_total_risk_pct

        return {
            "open_positions": len(self._risk_cache),
            "max_positions": self.config.max_open_positions,
            "total_risk_usd": total_risk,
            "max_risk_usd": max_risk,
            "total_risk_pct": (total_risk / equity * 100) if equity > 0 else 0,
            "max_risk_pct": self.config.max_total_risk_pct * 100,
            "remaining_risk_budget": max(0, max_risk - total_risk),
            "positions": {
                symbol: {
                    "risk_amount": pos.risk_amount,
                    "stop_pct": (pos.entry_price - pos.stop_price) / pos.entry_price * 100
                    if pos.entry_price > 0 and pos.stop_price > 0 else 0,
                }
                for symbol, pos in self._risk_cache.items()
            },
        }

    def invalidate_cache(self) -> None:
        """Force cache refresh on next access."""
        self._cache_ts = 0
