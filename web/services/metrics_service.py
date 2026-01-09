"""
metrics_service.py
Real-time trading metrics service for dashboard.

Reads from existing JSON log files to provide:
- Current strategy decisions
- Position and P&L data
- Market regime information
- Connection status
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import json
import os


# Project root for log files
PROJECT_ROOT = Path(__file__).parent.parent.parent


class MetricsService:
    """Service for reading and transforming trading metrics data."""

    LOGS_DIR = PROJECT_ROOT / "logs"
    STALE_THRESHOLD_SECONDS = 30

    def __init__(self):
        """Initialize the metrics service."""
        pass

    def load_exchange_data(self, exchange: str) -> Optional[dict]:
        """
        Load and parse JSON log file for an exchange.

        Args:
            exchange: Either 'upbit' or 'binance'

        Returns:
            ExchangeMetrics dict per data-model.md, or None if file not found
        """
        log_file = self.LOGS_DIR / f"v2_engine_{exchange}.json"

        if not log_file.exists():
            return None

        try:
            with open(log_file, 'r') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

        # Extract latest signal for current decision
        signals = data.get('signals', [])
        last_signal = signals[0] if signals else None

        # Get current price from latest signal
        current_price = 0.0
        if last_signal and 'indicators' in last_signal:
            current_price = last_signal['indicators'].get('close', 0.0)

        # Calculate position info
        btc_balance = data.get('btc_balance', 0.0)
        position_active = btc_balance > 0

        # Get entry price from last buy trade if position is active
        entry_price = 0.0
        trades = data.get('trades', [])
        if position_active and trades:
            # Find last buy trade
            for trade in reversed(trades):
                if trade.get('type') == 'buy':
                    entry_price = trade.get('price', 0.0)
                    break

        # Calculate unrealized P&L
        unrealized_pnl, unrealized_pnl_pct = self.calculate_unrealized_pnl(
            position_active, btc_balance, entry_price, current_price
        )

        # Parse last update timestamp
        last_updated = None
        if last_signal:
            try:
                last_updated = datetime.fromisoformat(last_signal.get('timestamp', ''))
            except (ValueError, TypeError):
                last_updated = None

        # Build ExchangeMetrics response
        return {
            'exchange': exchange,
            'mode': data.get('mode', 'paper'),
            'strategy': data.get('strategy', 'unknown'),
            'regime': data.get('regime', 'UNKNOWN'),
            'market_state': data.get('market_state', 'UNKNOWN'),
            'current_price': current_price,
            'position_active': position_active,
            'position_qty': btc_balance,
            'entry_price': entry_price,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pnl_pct': unrealized_pnl_pct,
            'total_value': data.get('total_value', 0.0),
            'last_updated': last_updated.isoformat() if last_updated else None,
            'last_decision': self._format_decision(last_signal) if last_signal else None
        }

    def calculate_unrealized_pnl(
        self,
        position_active: bool,
        qty: float,
        entry_price: float,
        current_price: float
    ) -> tuple[float, float]:
        """
        Calculate unrealized P&L from position and current price.

        Args:
            position_active: Whether a position is open
            qty: Position quantity
            entry_price: Entry price
            current_price: Current market price

        Returns:
            Tuple of (unrealized_pnl, unrealized_pnl_pct)
        """
        if not position_active or entry_price == 0 or qty == 0:
            return 0.0, 0.0

        entry_value = qty * entry_price
        current_value = qty * current_price
        unrealized_pnl = current_value - entry_value
        unrealized_pnl_pct = ((current_price - entry_price) / entry_price) * 100

        return unrealized_pnl, unrealized_pnl_pct

    def get_connection_status(self, exchange: str) -> dict:
        """
        Check file freshness and return ConnectionStatus dict.

        Args:
            exchange: Either 'upbit' or 'binance'

        Returns:
            ConnectionStatus dict per data-model.md
        """
        log_file = self.LOGS_DIR / f"v2_engine_{exchange}.json"

        if not log_file.exists():
            return {
                'exchange': exchange,
                'connected': False,
                'last_heartbeat': None,
                'is_stale': True,
                'stale_seconds': None
            }

        # Get file modification time
        try:
            mtime = os.path.getmtime(log_file)
            last_heartbeat = datetime.fromtimestamp(mtime)
        except OSError:
            return {
                'exchange': exchange,
                'connected': False,
                'last_heartbeat': None,
                'is_stale': True,
                'stale_seconds': None
            }

        # Check if data is stale
        now = datetime.now()
        stale_seconds = int((now - last_heartbeat).total_seconds())
        is_stale = stale_seconds > self.STALE_THRESHOLD_SECONDS

        return {
            'exchange': exchange,
            'connected': True,
            'last_heartbeat': last_heartbeat.isoformat(),
            'is_stale': is_stale,
            'stale_seconds': stale_seconds
        }

    def get_recent_decisions(
        self,
        hours: int = 24,
        limit: int = 50,
        exchange: Optional[str] = None
    ) -> list[dict]:
        """
        Get recent strategy decisions from both exchanges.

        Args:
            hours: Number of hours of history to return
            limit: Maximum number of decisions to return
            exchange: Optional filter by exchange

        Returns:
            List of StrategyDecision dicts sorted by timestamp descending
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        decisions = []

        exchanges = [exchange] if exchange else ['upbit', 'binance']

        for exch in exchanges:
            log_file = self.LOGS_DIR / f"v2_engine_{exch}.json"
            if not log_file.exists():
                continue

            try:
                with open(log_file, 'r') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            signals = data.get('signals', [])
            for signal in signals:
                try:
                    timestamp = datetime.fromisoformat(signal.get('timestamp', ''))
                    if timestamp >= cutoff:
                        decision = self._format_decision(signal)
                        decision['exchange'] = exch
                        decisions.append(decision)
                except (ValueError, TypeError):
                    continue

        # Sort by timestamp descending
        decisions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

        # Apply limit
        return decisions[:limit]

    def get_dashboard_state(self) -> dict:
        """
        Get complete dashboard state combining all metrics.

        Returns:
            DashboardState dict per data-model.md
        """
        upbit_data = self.load_exchange_data('upbit')
        binance_data = self.load_exchange_data('binance')

        connection_status = [
            self.get_connection_status('upbit'),
            self.get_connection_status('binance')
        ]

        recent_decisions = self.get_recent_decisions(hours=24, limit=50)

        return {
            'timestamp': datetime.now().isoformat(),
            'upbit': upbit_data,
            'binance': binance_data,
            'recent_decisions': recent_decisions,
            'connection_status': connection_status
        }

    def _format_decision(self, signal: dict) -> dict:
        """
        Format a signal as a StrategyDecision dict.

        Args:
            signal: Raw signal dict from JSON log

        Returns:
            Formatted StrategyDecision dict
        """
        return {
            'timestamp': signal.get('timestamp'),
            'strategy': signal.get('strategy'),
            'action': signal.get('action'),
            'reason': signal.get('reason'),
            'regime': signal.get('regime'),
            'market_state': signal.get('market_state'),
            'indicators': signal.get('indicators', {})
        }


# Singleton instance for use in app.py
metrics_service = MetricsService()
