"""
StrategyRunner - Async strategy execution with throttling.

Evaluates strategies based on regime, using cached data.
Runs sync strategies in thread pool to avoid blocking event loop.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Any, List

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """Trading signal from strategy."""
    exchange: str
    strategy: str
    action: str  # "buy", "sell", "hold"
    price: float
    fraction: float = 1.0  # Position fraction
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exchange": self.exchange,
            "strategy": self.strategy,
            "action": self.action,
            "price": self.price,
            "fraction": self.fraction,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class Position:
    """Current position state."""
    active: bool = False
    entry_price: float = 0.0
    size: float = 0.0
    strategy: Optional[str] = None
    entry_time: Optional[datetime] = None


class StrategyRunner:
    """
    Async strategy runner for a single exchange.

    Features:
    - Throttled evaluation (skips if recently evaluated)
    - Runs sync strategies in thread pool
    - Caches regime for strategy selection
    - Tracks position state
    """

    # Strategy selection by regime
    UPBIT_STRATEGY_MAP = {
        "BULL": "v35",
        "BULL_STRONG": "v35",
        "BULL_MODERATE": "v35",
        "SIDEWAYS": "sideways_v2",
        "SIDEWAYS_BULL": "sideways_v2",
        "SIDEWAYS_NEUTRAL": "sideways_v2",
        "SIDEWAYS_BEAR": "sideways_v2",
        "BEAR": None,  # Hold cash
        "BEAR_MODERATE": None,
        "BEAR_STRONG": None,
    }

    BINANCE_STRATEGY_MAP = {
        "BULL": None,  # No shorting in bull
        "BULL_STRONG": None,
        "BULL_MODERATE": None,
        "SIDEWAYS": None,
        "SIDEWAYS_BULL": None,
        "SIDEWAYS_NEUTRAL": None,
        "SIDEWAYS_BEAR": "short_v1",
        "BEAR": "short_v1",
        "BEAR_MODERATE": "short_v1",
        "BEAR_STRONG": "short_v1",
    }

    def __init__(
        self,
        exchange: str,
        price_hub: Any,  # PriceHub
        data_cache: Any,  # DataCache
        min_eval_interval: float = 30.0,  # Minimum seconds between evaluations
    ):
        """
        Args:
            exchange: "upbit" or "binance"
            price_hub: PriceHub instance
            data_cache: DataCache instance
            min_eval_interval: Minimum seconds between evaluations
        """
        self.exchange = exchange
        self.price_hub = price_hub
        self.data_cache = data_cache
        self.min_eval_interval = min_eval_interval

        # Strategies (lazy loaded)
        self._strategies: Dict[str, Any] = {}
        self._strategies_loaded = False

        # Position tracking
        self.position = Position()

        # Evaluation state
        self._last_eval_at: Optional[datetime] = None
        self._eval_count: int = 0
        self._signal_count: int = 0

        # Strategy map based on exchange
        if exchange == "upbit":
            self._strategy_map = self.UPBIT_STRATEGY_MAP
        else:
            self._strategy_map = self.BINANCE_STRATEGY_MAP

    def _load_strategies(self) -> None:
        """Lazy load strategies."""
        if self._strategies_loaded:
            return

        try:
            if self.exchange == "upbit":
                self._load_upbit_strategies()
            else:
                self._load_binance_strategies()
            self._strategies_loaded = True
            logger.info(f"Loaded {len(self._strategies)} strategies for {self.exchange}")
        except Exception as e:
            logger.error(f"Failed to load strategies: {e}")

    def _load_upbit_strategies(self) -> None:
        """Load Upbit strategies."""
        import json
        from pathlib import Path

        # V35 Long
        try:
            from trading.strategy.v35_long import V35LongStrategy
            config_path = Path(__file__).parent.parent.parent / "config" / "strategies" / "v35_long.json"
            if config_path.exists():
                with open(config_path) as f:
                    config = json.load(f)
                self._strategies["v35"] = V35LongStrategy(config=config)
                logger.debug("Loaded V35 strategy")
        except Exception as e:
            logger.warning(f"Failed to load V35: {e}")

        # SideWays V2
        try:
            from trading.strategy.sideways_v2 import SideWaysV2Strategy
            self._strategies["sideways_v2"] = SideWaysV2Strategy()
            logger.debug("Loaded SideWays_v2 strategy")
        except Exception as e:
            logger.warning(f"Failed to load SideWays_v2: {e}")

        # H4 Conservative
        try:
            from trading.strategy.h4_conservative import H4ConservativeStrategy
            self._strategies["h4_conservative"] = H4ConservativeStrategy({
                "position_fraction": 0.5,
                "take_profit": 0.04,
                "stop_loss": -0.02,
            })
            logger.debug("Loaded H4 Conservative strategy")
        except Exception as e:
            logger.warning(f"Failed to load H4 Conservative: {e}")

    def _load_binance_strategies(self) -> None:
        """Load Binance strategies."""
        import json
        from pathlib import Path

        # SHORT_V1
        try:
            from trading.strategy.short_v1 import ShortV1Strategy
            config_path = Path(__file__).parent.parent.parent / "config" / "strategies" / "short_v1.json"
            if config_path.exists():
                with open(config_path) as f:
                    config = json.load(f)
                self._strategies["short_v1"] = ShortV1Strategy(config=config)
                logger.debug("Loaded SHORT_V1 strategy")
        except Exception as e:
            logger.warning(f"Failed to load SHORT_V1: {e}")

        # H4 Short
        try:
            from trading.strategy.h4_short import H4ShortStrategy
            self._strategies["h4_short"] = H4ShortStrategy({
                "position_fraction": 0.5,
                "take_profit": 0.05,
                "stop_loss": -0.02,
            })
            logger.debug("Loaded H4 Short strategy")
        except Exception as e:
            logger.warning(f"Failed to load H4 Short: {e}")

    async def evaluate(self, regime: str) -> Optional[Signal]:
        """
        Evaluate strategy for current regime.

        Args:
            regime: Current market regime (e.g., "BULL_STRONG")

        Returns:
            Signal if action needed, None otherwise
        """
        # Throttle: skip if recently evaluated
        now = datetime.now()
        if self._last_eval_at:
            elapsed = (now - self._last_eval_at).total_seconds()
            if elapsed < self.min_eval_interval:
                return None

        self._last_eval_at = now
        self._eval_count += 1

        # Load strategies if needed
        self._load_strategies()

        # Select strategy based on regime
        strategy_name = self._strategy_map.get(regime)
        strategy = self._strategies.get(strategy_name) if strategy_name else None

        if not strategy:
            # No strategy for this regime - check if we need to exit
            if self.position.active:
                return await self._generate_exit_signal(regime, "regime_change")
            return None

        # Get cached data (instant - no DB/network)
        prices = self.price_hub.get_prices()
        current_price = prices.get(self.exchange)
        if not current_price:
            logger.warning(f"No price available for {self.exchange}")
            return None

        df = self.data_cache.get_df("minute60", periods=200)
        if df.empty:
            logger.warning(f"No data available for {self.exchange}")
            return None

        # Run strategy in thread pool (strategies are sync)
        try:
            signal_dict = await asyncio.to_thread(
                self._run_strategy,
                strategy,
                df,
                current_price,
            )
        except Exception as e:
            logger.error(f"Strategy {strategy_name} failed: {e}")
            return None

        if not signal_dict:
            return None

        # Convert to Signal
        action = signal_dict.get("action", "hold")
        if action == "hold":
            return None

        self._signal_count += 1

        return Signal(
            exchange=self.exchange,
            strategy=strategy_name,
            action=action,
            price=current_price,
            fraction=signal_dict.get("fraction", 1.0),
            reason=signal_dict.get("reason", ""),
            metadata=signal_dict.get("metadata", {}),
        )

    def _run_strategy(
        self,
        strategy: Any,
        df: pd.DataFrame,
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """Run strategy (sync, runs in thread pool)."""
        try:
            # Most strategies have generate_signal method
            if hasattr(strategy, "generate_signal"):
                return strategy.generate_signal(df, current_price)

            # Some strategies have evaluate method
            if hasattr(strategy, "evaluate"):
                return strategy.evaluate(df, current_price)

            logger.warning(f"Strategy has no generate_signal or evaluate method")
            return None

        except Exception as e:
            logger.error(f"Strategy execution error: {e}")
            return None

    async def _generate_exit_signal(
        self,
        regime: str,
        reason: str
    ) -> Optional[Signal]:
        """Generate exit signal when regime changes."""
        if not self.position.active:
            return None

        prices = self.price_hub.get_prices()
        current_price = prices.get(self.exchange)
        if not current_price:
            return None

        self._signal_count += 1

        return Signal(
            exchange=self.exchange,
            strategy=self.position.strategy or "unknown",
            action="sell",
            price=current_price,
            reason=f"Exit on {reason}: regime={regime}",
        )

    def update_position(
        self,
        active: bool,
        entry_price: float = 0.0,
        size: float = 0.0,
        strategy: Optional[str] = None,
    ) -> None:
        """Update position state from execution."""
        self.position.active = active
        self.position.entry_price = entry_price
        self.position.size = size
        self.position.strategy = strategy
        if active:
            self.position.entry_time = datetime.now()
        else:
            self.position.entry_time = None

    def get_stats(self) -> Dict[str, Any]:
        """Get runner statistics."""
        return {
            "exchange": self.exchange,
            "strategies_loaded": list(self._strategies.keys()),
            "position": {
                "active": self.position.active,
                "entry_price": self.position.entry_price,
                "size": self.position.size,
                "strategy": self.position.strategy,
            },
            "eval_count": self._eval_count,
            "signal_count": self._signal_count,
            "last_eval_at": self._last_eval_at.isoformat() if self._last_eval_at else None,
            "min_eval_interval": self.min_eval_interval,
        }
