"""
PortfolioManager - Capital allocation across multiple assets.

Manages portfolio-level capital allocation and position tracking
for multi-asset trading.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from core.types import (
    AssetConfig,
    AssetPosition,
    PortfolioState,
    current_timestamp,
)

logger = logging.getLogger(__name__)


class PortfolioManager:
    """
    Manages capital allocation across multiple assets.

    Responsibilities:
    - Track total capital and per-asset allocation
    - Calculate allocation drift from targets
    - Provide capital limits for each asset's trading
    - Aggregate portfolio state for monitoring
    """

    def __init__(
        self,
        total_capital_krw: float,
        config: Dict[str, Any],
    ):
        """
        Args:
            total_capital_krw: Total portfolio capital in KRW
            config: Allocation config with "assets" section
        """
        self._total_capital = total_capital_krw
        self._config = config
        self._assets: Dict[str, AssetConfig] = {}
        self._positions: Dict[str, AssetPosition] = {}
        self._cash_krw = total_capital_krw
        self._started_at = datetime.now()

        self._load_assets()
        self._init_positions()

        logger.info(
            "PortfolioManager initialized with %d assets, total capital: %,.0f KRW",
            len(self._assets),
            total_capital_krw,
        )

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        total_capital_krw: float = 10_000_000,
    ) -> "PortfolioManager":
        """
        Create PortfolioManager from allocation config.

        Args:
            config: Allocation config with "assets" section
            total_capital_krw: Total portfolio capital

        Returns:
            Configured PortfolioManager
        """
        return cls(total_capital_krw=total_capital_krw, config=config)

    def _load_assets(self) -> None:
        """Load asset configurations from config."""
        assets_config = self._config.get("assets", {})

        for symbol, cfg in assets_config.items():
            if cfg.get("binance_enabled", False):
                self._assets[symbol] = AssetConfig(
                    symbol=symbol,
                    enabled=cfg.get("binance_enabled", False),
                    alpha_ratio=cfg.get("alpha_ratio", 0.0),
                    binance_symbol=cfg.get("binance_symbol", f"{symbol}USDT"),
                    db_path=cfg.get("db_path", f"data/binance_{symbol.lower()}.db"),
                    strategies=cfg.get("strategies", {}),
                    params_override=cfg.get("params_override", {}),
                )

        # Validate ratios sum to ~1.0
        total_ratio = sum(a.alpha_ratio for a in self._assets.values())
        if abs(total_ratio - 1.0) > 0.01:
            logger.warning("Asset ratios sum to %.2f, not 1.0", total_ratio)

    def _init_positions(self) -> None:
        """Initialize empty positions for all assets."""
        for symbol in self._assets:
            self._positions[symbol] = AssetPosition(symbol=symbol)

    def get_symbols(self) -> List[str]:
        """Get list of enabled asset symbols."""
        return list(self._assets.keys())

    def get_asset_config(self, symbol: str) -> Optional[AssetConfig]:
        """Get configuration for a specific asset."""
        return self._assets.get(symbol)

    def get_capital_for_asset(self, symbol: str) -> float:
        """
        Get allocated capital for a specific asset.

        Args:
            symbol: Asset symbol (e.g., "BTC")

        Returns:
            Allocated capital in KRW
        """
        asset = self._assets.get(symbol)
        if not asset:
            return 0.0

        return self._total_capital * asset.alpha_ratio

    def get_available_capital(self, symbol: str) -> float:
        """
        Get available (undeployed) capital for an asset.

        Args:
            symbol: Asset symbol

        Returns:
            Available capital in KRW
        """
        allocated = self.get_capital_for_asset(symbol)
        position = self._positions.get(symbol)

        if not position:
            return allocated

        deployed = position.value_krw
        return max(0, allocated - deployed)

    def update_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        strategy: Optional[str] = None,
    ) -> None:
        """
        Update position for an asset.

        Args:
            symbol: Asset symbol
            quantity: Asset quantity held
            entry_price: Average entry price
            current_price: Current market price
            strategy: Active strategy name
        """
        if symbol not in self._positions:
            self._positions[symbol] = AssetPosition(symbol=symbol)

        pos = self._positions[symbol]
        pos.quantity = quantity
        pos.entry_price = entry_price
        pos.current_price = current_price
        pos.value_krw = quantity * current_price
        pos.strategy = strategy

        if entry_price > 0 and quantity > 0:
            pos.unrealized_pnl = (current_price - entry_price) * quantity
            pos.unrealized_pnl_pct = ((current_price / entry_price) - 1) * 100
        else:
            pos.unrealized_pnl = 0.0
            pos.unrealized_pnl_pct = 0.0

    def update_prices(self, prices: Dict[str, float]) -> None:
        """
        Update current prices for all positions.

        Args:
            prices: Dict of symbol -> current price
        """
        for symbol, price in prices.items():
            if symbol in self._positions:
                pos = self._positions[symbol]
                pos.current_price = price
                pos.value_krw = pos.quantity * price

                if pos.entry_price > 0 and pos.quantity > 0:
                    pos.unrealized_pnl = (price - pos.entry_price) * pos.quantity
                    pos.unrealized_pnl_pct = ((price / pos.entry_price) - 1) * 100

    def get_position(self, symbol: str) -> Optional[AssetPosition]:
        """Get position for a specific asset."""
        return self._positions.get(symbol)

    def get_portfolio_state(self) -> PortfolioState:
        """
        Get current portfolio state.

        Returns:
            PortfolioState with all positions and metrics
        """
        # Calculate totals
        total_value = self._cash_krw
        for pos in self._positions.values():
            total_value += pos.value_krw

        # Calculate exposure
        deployed_value = sum(pos.value_krw for pos in self._positions.values())
        exposure_pct = (deployed_value / total_value * 100) if total_value > 0 else 0

        # Calculate allocation drift
        drift = {}
        for symbol, asset in self._assets.items():
            target_value = total_value * asset.alpha_ratio
            actual_value = self._positions.get(symbol, AssetPosition(symbol=symbol)).value_krw
            if target_value > 0:
                drift[symbol] = ((actual_value - target_value) / target_value) * 100
            else:
                drift[symbol] = 0.0

        return PortfolioState(
            timestamp=current_timestamp(),
            total_value_krw=total_value,
            cash_krw=self._cash_krw,
            positions={s: p.model_copy() for s, p in self._positions.items()},
            exposure_pct=round(exposure_pct, 2),
            allocation_drift=drift,
        )

    def set_cash(self, cash_krw: float) -> None:
        """Set current cash balance."""
        self._cash_krw = cash_krw

    def adjust_cash(self, delta: float) -> None:
        """Adjust cash by delta (positive = add, negative = subtract)."""
        self._cash_krw += delta

    def get_total_exposure(self) -> float:
        """Get total deployed value across all assets."""
        return sum(pos.value_krw for pos in self._positions.values())

    def get_total_unrealized_pnl(self) -> float:
        """Get total unrealized P&L across all assets."""
        return sum(pos.unrealized_pnl for pos in self._positions.values())

    def is_overweight(self, symbol: str, threshold_pct: float = 10.0) -> bool:
        """Check if an asset is overweight vs target allocation."""
        state = self.get_portfolio_state()
        drift_map: Dict[str, float] = dict(state.allocation_drift)
        drift = drift_map.get(symbol, 0)
        return drift > threshold_pct

    def is_underweight(self, symbol: str, threshold_pct: float = 10.0) -> bool:
        """Check if an asset is underweight vs target allocation."""
        state = self.get_portfolio_state()
        drift_map: Dict[str, float] = dict(state.allocation_drift)
        drift = drift_map.get(symbol, 0)
        return drift < -threshold_pct

    def get_stats(self) -> Dict[str, Any]:
        """Get portfolio statistics."""
        state = self.get_portfolio_state()

        return {
            "uptime_seconds": (datetime.now() - self._started_at).total_seconds(),
            "total_capital_krw": self._total_capital,
            "total_value_krw": state.total_value_krw,
            "cash_krw": state.cash_krw,
            "exposure_pct": state.exposure_pct,
            "total_unrealized_pnl": self.get_total_unrealized_pnl(),
            "assets": {
                symbol: {
                    "target_ratio": self._assets[symbol].alpha_ratio,
                    "allocated_krw": self.get_capital_for_asset(symbol),
                    "position_value_krw": self._positions.get(symbol, AssetPosition(symbol=symbol)).value_krw,
                    "drift_pct": dict(state.allocation_drift).get(symbol, 0),
                }
                for symbol in self._assets
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/monitoring."""
        return self.get_stats()
