"""
Trading Engine V2 - Message Types
Pydantic 모델로 정의된 메시지 타입
"""

from datetime import datetime
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class Exchange(str, Enum):
    """거래소"""
    BINANCE = "binance"


class Direction(str, Enum):
    """포지션 방향"""
    LONG = "long"
    SHORT = "short"


class Action(str, Enum):
    """거래 액션"""
    BUY = "buy"
    SELL = "sell"
    OPEN_SHORT = "open_short"
    CLOSE_SHORT = "close_short"
    HOLD = "hold"


class OrderStatus(str, Enum):
    """주문 상태"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class MarketState(str, Enum):
    """시장 상태"""
    BULL_STRONG = "BULL_STRONG"
    BULL_MODERATE = "BULL_MODERATE"
    SIDEWAYS_BULL = "SIDEWAYS_BULL"
    SIDEWAYS_NEUTRAL = "SIDEWAYS_NEUTRAL"
    SIDEWAYS_BEAR = "SIDEWAYS_BEAR"
    BEAR_MODERATE = "BEAR_MODERATE"
    BEAR_STRONG = "BEAR_STRONG"


# ========== 가격 메시지 ==========

class OHLCV(BaseModel):
    """OHLCV 데이터"""
    open: float
    high: float
    low: float
    close: float
    volume: float


class PriceMessage(BaseModel):
    """실시간 가격 메시지"""
    model_config = ConfigDict(use_enum_values=True)

    timestamp: int = Field(description="Unix timestamp (ms)")
    exchange: Exchange
    symbol: str = Field(description="거래 심볼 (예: BTC-KRW, BTCUSDT)")
    price: float
    volume_24h: Optional[float] = None
    ohlcv: Optional[OHLCV] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PriceMessage":
        return cls(**data)


# ========== 신호 메시지 ==========

class SignalMessage(BaseModel):
    """전략 신호 메시지"""
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(description="신호 고유 ID")
    timestamp: int
    strategy: str = Field(description="전략 이름 (예: mlp-direction, short-v1)")
    exchange: Exchange
    symbol: str
    action: Action
    direction: Direction
    fraction: float = Field(ge=0.0, le=1.0, description="포지션 비율")
    confidence: float = Field(ge=0.0, le=1.0, description="신뢰도")
    reason: str = Field(description="신호 발생 사유")
    leverage: Optional[int] = Field(default=1, description="레버리지 (선물)")
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ========== 주문 메시지 ==========

class OrderMessage(BaseModel):
    """주문 메시지"""
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(description="주문 고유 ID")
    timestamp: int
    signal_id: str = Field(description="원본 신호 ID")
    exchange: Exchange
    symbol: str
    action: Action
    direction: Direction
    quantity: float = Field(description="주문 수량")
    price: Optional[float] = Field(default=None, description="지정가 (없으면 시장가)")
    leverage: int = 1
    status: OrderStatus = OrderStatus.PENDING

    # 체결 정보
    executed_qty: Optional[float] = None
    executed_price: Optional[float] = None
    fee: Optional[float] = None

    # 결과
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ========== 포지션 메시지 ==========

class Position(BaseModel):
    """단일 포지션"""
    model_config = ConfigDict(use_enum_values=True)

    exchange: Exchange
    symbol: str
    side: Direction
    quantity: float
    entry_price: float
    current_price: float
    leverage: int = 1
    unrealized_pnl: float
    unrealized_pnl_pct: float


class PositionMessage(BaseModel):
    """포지션 업데이트 메시지"""
    model_config = ConfigDict(use_enum_values=True)

    timestamp: int
    total_equity_krw: float = Field(description="총 자산 (KRW 환산)")
    positions: Dict[str, Position] = Field(description="거래소별 포지션")
    total_pnl_pct: float = Field(description="총 수익률")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ========== 시스템 이벤트 ==========

class EventType(str, Enum):
    """시스템 이벤트 타입"""
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    HEARTBEAT = "heartbeat"
    CONFIG_CHANGE = "config_change"


class SystemEvent(BaseModel):
    """시스템 이벤트 메시지"""
    model_config = ConfigDict(use_enum_values=True)

    timestamp: int
    event_type: EventType
    module: str = Field(description="이벤트 발생 모듈")
    message: str
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ========== 헬퍼 함수 ==========

def create_message_id(prefix: str = "msg") -> str:
    """고유 메시지 ID 생성"""
    import uuid
    timestamp = int(datetime.now().timestamp() * 1000)
    unique = str(uuid.uuid4())[:8]
    return f"{prefix}-{timestamp}-{unique}"


def current_timestamp() -> int:
    """현재 Unix timestamp (ms)"""
    return int(datetime.now().timestamp() * 1000)


# ========== Multi-Asset Types (v0.0.6) ==========

class AssetConfig(BaseModel):
    """Configuration for a single tradeable asset."""
    model_config = ConfigDict(use_enum_values=True)

    symbol: str = Field(description="Asset symbol (e.g., BTC, ETH, SOL)")
    enabled: bool = Field(default=True, description="Whether this asset is active")
    alpha_ratio: float = Field(ge=0.0, le=1.0, description="Capital allocation ratio")
    binance_symbol: str = Field(description="Binance trading pair (e.g., BTCUSDT)")
    db_path: str = Field(description="Path to historical data DB")
    strategies: Dict[str, Optional[str]] = Field(
        description="Strategy mapping per regime (BULL, SIDEWAYS, BEAR)"
    )
    params_override: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-asset strategy parameter overrides"
    )


class AssetPosition(BaseModel):
    """Position state for a single asset."""
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    quantity: float = Field(default=0.0, description="Asset quantity held")
    entry_price: float = Field(default=0.0, description="Average entry price")
    current_price: float = Field(default=0.0, description="Current market price")
    value_krw: float = Field(default=0.0, description="Position value in KRW")
    unrealized_pnl: float = Field(default=0.0, description="Unrealized P&L in KRW")
    unrealized_pnl_pct: float = Field(default=0.0, description="Unrealized P&L %")
    strategy: Optional[str] = Field(default=None, description="Active strategy name")


class PortfolioState(BaseModel):
    """Aggregate portfolio state across all assets."""
    model_config = ConfigDict(use_enum_values=True)

    timestamp: int = Field(description="Unix timestamp (ms)")
    total_value_krw: float = Field(description="Total portfolio value in KRW")
    cash_krw: float = Field(description="Available cash in KRW")
    positions: Dict[str, AssetPosition] = Field(
        default_factory=dict,
        description="Per-asset positions"
    )
    exposure_pct: float = Field(
        default=0.0,
        description="Total exposure as % of portfolio"
    )
    allocation_drift: Dict[str, float] = Field(
        default_factory=dict,
        description="Drift from target allocation per asset"
    )

    def get_position(self, symbol: str) -> Optional[AssetPosition]:
        """Get position for a specific asset."""
        return self.positions.get(symbol)


