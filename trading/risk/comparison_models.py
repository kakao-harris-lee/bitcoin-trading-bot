"""
Data models for daily backtest comparison reports.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import List, Optional
import json


class MatchStatus(Enum):
    """Status of trade comparison match."""
    MATCH = "match"
    MISMATCH = "mismatch"
    EXTRA = "extra"
    MISSING = "missing"


class DiscrepancyType(Enum):
    """Types of discrepancies between actual and backtest trades."""
    MISSED_TRADE = "missed_trade"
    EXTRA_TRADE = "extra_trade"
    WRONG_DIRECTION = "wrong_direction"
    TIMING_DIFFERENCE = "timing_difference"
    PRICE_DEVIATION = "price_deviation"


class Severity(Enum):
    """Severity levels for discrepancies."""
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


@dataclass
class TradeComparison:
    """Represents a single comparison point between actual and backtest trade."""
    actual_timestamp: Optional[datetime]
    backtest_timestamp: Optional[datetime]
    actual_action: Optional[str]  # "BUY" / "SELL" / None
    backtest_action: Optional[str]
    actual_price: Optional[float]
    backtest_price: Optional[float]
    price_difference: float
    price_difference_pct: float
    match_status: MatchStatus

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'actual_timestamp': self.actual_timestamp.isoformat() if self.actual_timestamp else None,
            'backtest_timestamp': self.backtest_timestamp.isoformat() if self.backtest_timestamp else None,
            'actual_action': self.actual_action,
            'backtest_action': self.backtest_action,
            'actual_price': self.actual_price,
            'backtest_price': self.backtest_price,
            'price_difference': self.price_difference,
            'price_difference_pct': self.price_difference_pct,
            'match_status': self.match_status.value
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TradeComparison':
        """Create from dictionary."""
        return cls(
            actual_timestamp=datetime.fromisoformat(data['actual_timestamp']) if data.get('actual_timestamp') else None,
            backtest_timestamp=datetime.fromisoformat(data['backtest_timestamp']) if data.get('backtest_timestamp') else None,
            actual_action=data.get('actual_action'),
            backtest_action=data.get('backtest_action'),
            actual_price=data.get('actual_price'),
            backtest_price=data.get('backtest_price'),
            price_difference=data.get('price_difference', 0.0),
            price_difference_pct=data.get('price_difference_pct', 0.0),
            match_status=MatchStatus(data['match_status'])
        )


@dataclass
class DiscrepancyRecord:
    """Represents a mismatch between expected and actual behavior."""
    timestamp: datetime
    discrepancy_type: DiscrepancyType
    severity: Severity
    actual_value: Optional[str]
    expected_value: Optional[str]
    pnl_impact: float
    pnl_impact_pct: float
    explanation: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'discrepancy_type': self.discrepancy_type.value,
            'severity': self.severity.value,
            'actual_value': self.actual_value,
            'expected_value': self.expected_value,
            'pnl_impact': self.pnl_impact,
            'pnl_impact_pct': self.pnl_impact_pct,
            'explanation': self.explanation
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DiscrepancyRecord':
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data['timestamp']),
            discrepancy_type=DiscrepancyType(data['discrepancy_type']),
            severity=Severity(data['severity']),
            actual_value=data.get('actual_value'),
            expected_value=data.get('expected_value'),
            pnl_impact=data.get('pnl_impact', 0.0),
            pnl_impact_pct=data.get('pnl_impact_pct', 0.0),
            explanation=data.get('explanation', '')
        )


@dataclass
class DailyComparisonReport:
    """Represents a full comparison report for a single day and strategy."""
    report_date: date
    strategy_name: str
    actual_trades_count: int
    backtest_trades_count: int
    actual_pnl: float
    backtest_pnl: float
    actual_pnl_pct: float
    backtest_pnl_pct: float
    actual_win_rate: float
    backtest_win_rate: float
    actual_max_drawdown: float
    backtest_max_drawdown: float
    discrepancy_count: int
    max_severity: Severity
    trade_comparisons: List[TradeComparison] = field(default_factory=list)
    discrepancies: List[DiscrepancyRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'report_date': self.report_date.isoformat(),
            'strategy_name': self.strategy_name,
            'actual_trades_count': self.actual_trades_count,
            'backtest_trades_count': self.backtest_trades_count,
            'actual_pnl': self.actual_pnl,
            'backtest_pnl': self.backtest_pnl,
            'actual_pnl_pct': self.actual_pnl_pct,
            'backtest_pnl_pct': self.backtest_pnl_pct,
            'actual_win_rate': self.actual_win_rate,
            'backtest_win_rate': self.backtest_win_rate,
            'actual_max_drawdown': self.actual_max_drawdown,
            'backtest_max_drawdown': self.backtest_max_drawdown,
            'discrepancy_count': self.discrepancy_count,
            'max_severity': self.max_severity.value,
            'trade_comparisons': [tc.to_dict() for tc in self.trade_comparisons],
            'discrepancies': [d.to_dict() for d in self.discrepancies],
            'created_at': self.created_at.isoformat()
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> 'DailyComparisonReport':
        """Create from dictionary."""
        return cls(
            report_date=date.fromisoformat(data['report_date']),
            strategy_name=data['strategy_name'],
            actual_trades_count=data.get('actual_trades_count', 0),
            backtest_trades_count=data.get('backtest_trades_count', 0),
            actual_pnl=data.get('actual_pnl', 0.0),
            backtest_pnl=data.get('backtest_pnl', 0.0),
            actual_pnl_pct=data.get('actual_pnl_pct', 0.0),
            backtest_pnl_pct=data.get('backtest_pnl_pct', 0.0),
            actual_win_rate=data.get('actual_win_rate', 0.0),
            backtest_win_rate=data.get('backtest_win_rate', 0.0),
            actual_max_drawdown=data.get('actual_max_drawdown', 0.0),
            backtest_max_drawdown=data.get('backtest_max_drawdown', 0.0),
            discrepancy_count=data.get('discrepancy_count', 0),
            max_severity=Severity(data.get('max_severity', 'Low')),
            trade_comparisons=[TradeComparison.from_dict(tc) for tc in data.get('trade_comparisons', [])],
            discrepancies=[DiscrepancyRecord.from_dict(d) for d in data.get('discrepancies', [])],
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now()
        )

    @classmethod
    def from_json(cls, json_str: str) -> 'DailyComparisonReport':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass
class ComparisonResult:
    """Result of comparing actual vs backtest trades."""
    trade_comparisons: List[TradeComparison]
    discrepancies: List[DiscrepancyRecord]
    match_rate: float
