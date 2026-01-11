"""
Trading Engine V3 - Core Module
Redis Streams 기반 트레이딩 엔진
"""

from .config import Config
from .redis_client import RedisClient
from .price_hub import PriceHub
from .data_cache import DataCache

# Re-export from new locations for backwards compatibility
from core.types import (
    PriceMessage,
    SignalMessage,
    OrderMessage,
    PositionMessage,
    SystemEvent,
    # Multi-asset types (v0.0.6)
    AssetConfig,
    AssetPosition,
    PortfolioState,
)
from trading.risk.risk_controls import (
    RiskConfig,
    clamp_fraction,
    kill_switch_active,
    set_kill_switch,
    should_block_new_entries,
    today,
)
from trading.risk.trade_logger import TradeLogger

__all__ = [
    "Config",
    "RedisClient",
    "PriceHub",
    "DataCache",
    "PriceMessage",
    "SignalMessage",
    "OrderMessage",
    "PositionMessage",
    "SystemEvent",
    "AssetConfig",
    "AssetPosition",
    "PortfolioState",
    "RiskConfig",
    "clamp_fraction",
    "kill_switch_active",
    "set_kill_switch",
    "should_block_new_entries",
    "today",
    "TradeLogger",
]
