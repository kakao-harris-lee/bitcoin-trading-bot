"""
Trading Engine V2 - Modules
"""

from .feed_handler import FeedHandler, UpbitWebSocket, BinanceWebSocket
from .base_strategy import BaseStrategy
from .v35_long_strategy import V35LongStrategy, MarketClassifier, DynamicExitManager
from .short_v1_strategy import ShortV1Strategy
from .sideways_v1_strategy import SideWaysV1Strategy
from .strategies.sideways_v2 import SideWaysV2Strategy
from .regime_router import RegimeRouter, RegimeDecision
from .risk_manager import RiskManager
from .execution_manager import (
    ExecutionManager, UpbitAdapter, BinanceAdapter, OrderTracker, OrderState
)
from .position_manager import (
    PositionManager, PositionEntry, ClosedPosition
)

__all__ = [
    # Feed Handler
    "FeedHandler",
    "UpbitWebSocket",
    "BinanceWebSocket",
    # Strategies
    "BaseStrategy",
    "V35LongStrategy",
    "MarketClassifier",
    "DynamicExitManager",
    "ShortV1Strategy",
    "SideWaysV1Strategy",
    "SideWaysV2Strategy",
    # Router
    "RegimeRouter",
    "RegimeDecision",
    # Risk Management
    "RiskManager",
    # Execution
    "ExecutionManager",
    "UpbitAdapter",
    "BinanceAdapter",
    "OrderTracker",
    "OrderState",
    # Position
    "PositionManager",
    "PositionEntry",
    "ClosedPosition",
]
