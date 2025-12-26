"""
Trading Engine V2 - Core Module
Redis 기반 이벤트 드리븐 트레이딩 엔진
"""

from .config import Config
from .redis_client import RedisClient
from .message_types import (
    PriceMessage,
    SignalMessage,
    OrderMessage,
    PositionMessage,
    SystemEvent,
)
from .risk_controls import (
    RiskConfig,
    clamp_fraction,
    kill_switch_active,
    set_kill_switch,
    should_block_new_entries,
    today,
)
from .trade_logger import TradeLogger

__all__ = [
    "Config",
    "RedisClient",
    "PriceMessage",
    "SignalMessage",
    "OrderMessage",
    "PositionMessage",
    "SystemEvent",
    "RiskConfig",
    "clamp_fraction",
    "kill_switch_active",
    "set_kill_switch",
    "should_block_new_entries",
    "today",
    "TradeLogger",
]
