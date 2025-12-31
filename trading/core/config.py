"""
Trading Engine V2 - Configuration
환경 변수 및 설정 관리
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv

# Explicitly load .env from project root
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / '.env')


@dataclass
class RedisConfig:
    """Redis 연결 설정"""
    host: str = "chsvr.duckdns.org"
    port: int = 6379
    username: str = "bitcoin_trader"
    password: str = "@1tidh6ls6ls"
    db: int = 0

    # Stream 이름
    streams: Dict[str, str] = field(default_factory=lambda: {
        "prices": "market:prices",
        "orderbook": "market:orderbook",
        "signals": "strategy:signals",
        "pending_orders": "orders:pending",
        "executed_orders": "orders:executed",
        "positions": "positions:updates",
        "events": "system:events",
    })

    # Consumer Groups
    consumer_groups: Dict[str, List[str]] = field(default_factory=lambda: {
        "market:prices": [
            "strategy-v35",
            "strategy-short-v1",
            "risk-manager",
            "position-manager",
            "dashboard",
        ],
        "market:orderbook": [
            "execution-manager",
        ],
        "strategy:signals": [
            "risk-manager",
        ],
        "orders:pending": [
            "executor-upbit",
            "executor-binance",
        ],
        "orders:executed": [
            "position-manager",
            "notifier",
        ],
        "positions:updates": [
            "risk-manager",
            "dashboard",
            "notifier",
        ],
        "system:events": [
            "all-modules",
        ],
    })


@dataclass
class TradingConfig:
    """트레이딩 설정"""
    # 거래소 설정
    upbit_enabled: bool = True
    binance_enabled: bool = True

    # 초기 자본
    upbit_capital: float = 10_000_000  # 10M KRW
    binance_capital: float = 10_000     # 10K USDT

    # 리스크 파라미터
    max_drawdown_pct: float = 20.0
    max_position_pct: float = 50.0
    daily_loss_limit_pct: float = 5.0
    min_hedge_ratio: float = 0.3
    max_hedge_ratio: float = 0.7
    max_leverage: int = 3

    # 실행 간격 (초)
    feed_interval: float = 1.0
    strategy_interval: float = 5.0
    risk_check_interval: float = 1.0


@dataclass
class TelegramConfig:
    """텔레그램 알림 설정"""
    enabled: bool = True
    bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))


@dataclass
class Config:
    """전체 설정"""
    redis: RedisConfig = field(default_factory=RedisConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    # 모드
    paper_trading: bool = True
    debug: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        """환경 변수에서 설정 로드"""
        config = cls()

        # Redis 설정 오버라이드
        redis_host = os.getenv("REDIS_HOST")
        if redis_host is not None:
            config.redis.host = redis_host
        redis_port = os.getenv("REDIS_PORT")
        if redis_port is not None:
            config.redis.port = int(redis_port)
        redis_username = os.getenv("REDIS_USERNAME")
        if redis_username is not None:
            config.redis.username = redis_username
        redis_password = os.getenv("REDIS_PASSWORD")
        if redis_password is not None:
            config.redis.password = redis_password

        # 트레이딩 모드
        config.paper_trading = os.getenv("PAPER_TRADING", "true").lower() == "true"
        config.debug = os.getenv("DEBUG", "false").lower() == "true"

        return config
