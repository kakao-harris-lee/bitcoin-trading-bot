"""
metrics_service.py
Real-time trading metrics service for dashboard.

Reads from multi_asset_engine_status.json to provide:
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
    STATUS_FILE = "multi_asset_engine_status.json"
    STALE_THRESHOLD_SECONDS = 30

    def __init__(self):
        """Initialize the metrics service."""
        self._cached_data: Optional[dict] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 2

    def _load_status_file(self) -> Optional[dict]:
        """Load and cache the multi-asset engine status file."""
        now = datetime.now()
        if (self._cached_data is not None and
            self._cache_time is not None and
            (now - self._cache_time).total_seconds() < self._cache_ttl_seconds):
            return self._cached_data

        status_file = self.LOGS_DIR / self.STATUS_FILE
        if not status_file.exists():
            return None

        try:
            with open(status_file, 'r') as f:
                self._cached_data = json.load(f)
                self._cache_time = now
                return self._cached_data
        except (json.JSONDecodeError, IOError):
            return None

    def load_exchange_data(self, exchange: str) -> Optional[dict]:
        """
        Load and parse data for an exchange from multi-asset status.

        Args:
            exchange: Either 'upbit' or 'binance'

        Returns:
            ExchangeMetrics dict, or None if data not found
        """
        data = self._load_status_file()
        if not data:
            return None

        assets = data.get('assets', {})
        portfolio = data.get('portfolio', {})

        if not assets:
            return None

        # Aggregate data across all assets for this exchange
        positions = []
        total_position_value = 0.0
        configured_strategies = set()

        for asset_name, asset_data in assets.items():
            prefix = exchange
            price_key = f"{prefix}_price"
            enabled_key = f"{prefix}_enabled"
            position_active_key = f"{prefix}_position_active"
            position_qty_key = f"{prefix}_position_qty"
            strategy_key = f"{prefix}_strategy"

            if not asset_data.get(enabled_key, False):
                continue

            price = asset_data.get(price_key, 0.0)
            qty = asset_data.get(position_qty_key, 0.0)
            position_active = asset_data.get(position_active_key, False)
            strategy = asset_data.get(strategy_key)
            regime = asset_data.get('regime', 'UNKNOWN')

            # Track configured strategies (even without position)
            if strategy:
                configured_strategies.add(strategy)

            if position_active and qty > 0:
                position_value = qty * price
                total_position_value += position_value
                positions.append({
                    'asset': asset_name,
                    'qty': qty,
                    'price': price,
                    'value': position_value,
                    'strategy': strategy,
                    'regime': regime
                })

        # Get primary asset info (BTC) for backward compatibility
        btc_data = assets.get('BTC', {})
        price_key = f"{exchange}_price"
        current_price = btc_data.get(price_key, 0.0)
        regime = btc_data.get('regime', 'UNKNOWN')

        # Show configured strategies (not just from active positions)
        strategy_str = ', '.join(sorted(configured_strategies)) if configured_strategies else 'None'

        # Parse timestamp
        last_updated = None
        try:
            last_updated = datetime.fromisoformat(data.get('timestamp', ''))
        except (ValueError, TypeError):
            last_updated = datetime.now()

        # Build ExchangeMetrics response
        return {
            'exchange': exchange,
            'mode': data.get('mode', 'paper'),
            'strategy': strategy_str,
            'regime': regime,
            'market_state': regime,
            'current_price': current_price,
            'position_active': len(positions) > 0,
            'positions': positions,
            'total_position_value': total_position_value,
            'total_value': portfolio.get('total_value_krw', 0.0) if exchange == 'upbit' else 0.0,
            'cash': portfolio.get('cash_krw', 0.0) if exchange == 'upbit' else 0.0,
            'exposure_pct': portfolio.get('exposure_pct', 0.0),
            'last_updated': last_updated.isoformat() if last_updated else None,
            'last_decision': None
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
        status_file = self.LOGS_DIR / self.STATUS_FILE

        if not status_file.exists():
            return {
                'exchange': exchange,
                'connected': False,
                'last_heartbeat': None,
                'is_stale': True,
                'stale_seconds': None
            }

        # Get file modification time
        try:
            mtime = os.path.getmtime(status_file)
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

        # Check if exchange is enabled in the data
        data = self._load_status_file()
        exchange_enabled = False
        if data:
            assets = data.get('assets', {})
            for asset_data in assets.values():
                if asset_data.get(f'{exchange}_enabled', False):
                    exchange_enabled = True
                    break

        return {
            'exchange': exchange,
            'connected': exchange_enabled and not is_stale,
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
        Get recent strategy decisions from current status.

        Note: The multi-asset engine status doesn't store historical decisions.
        This returns current state as a single decision per active position.

        Args:
            hours: Number of hours of history to return (unused currently)
            limit: Maximum number of decisions to return
            exchange: Optional filter by exchange

        Returns:
            List of StrategyDecision dicts sorted by timestamp descending
        """
        data = self._load_status_file()
        if not data:
            return []

        decisions = []
        timestamp = data.get('timestamp', datetime.now().isoformat())
        assets = data.get('assets', {})

        exchanges = [exchange] if exchange else ['upbit', 'binance']

        for asset_name, asset_data in assets.items():
            regime = asset_data.get('regime', 'UNKNOWN')

            for exch in exchanges:
                enabled = asset_data.get(f'{exch}_enabled', False)
                if not enabled:
                    continue

                position_active = asset_data.get(f'{exch}_position_active', False)
                strategy = asset_data.get(f'{exch}_strategy')
                price = asset_data.get(f'{exch}_price', 0.0)

                action = 'HOLD' if position_active else 'WAIT'

                decisions.append({
                    'timestamp': timestamp,
                    'exchange': exch,
                    'asset': asset_name,
                    'strategy': strategy or 'None',
                    'action': action,
                    'reason': f'{regime} - {"Position active" if position_active else "No position"}',
                    'regime': regime,
                    'market_state': regime,
                    'indicators': {
                        'price': price
                    }
                })

        # Sort by asset name for consistent ordering
        decisions.sort(key=lambda x: (x.get('exchange', ''), x.get('asset', '')))

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

        # Get portfolio summary from status file
        data = self._load_status_file()
        portfolio = None
        if data:
            raw_portfolio = data.get('portfolio', {})
            portfolio = {
                'total_capital_krw': raw_portfolio.get('total_capital_krw', 0.0),
                'total_value_krw': raw_portfolio.get('total_value_krw', 0.0),
                'cash_krw': raw_portfolio.get('cash_krw', 0.0),
                'exposure_pct': raw_portfolio.get('exposure_pct', 0.0),
                'total_unrealized_pnl': raw_portfolio.get('total_unrealized_pnl', 0.0),
                'uptime_seconds': raw_portfolio.get('uptime_seconds', 0.0),
                'assets': raw_portfolio.get('assets', {})
            }

        return {
            'timestamp': datetime.now().isoformat(),
            'mode': data.get('mode', 'unknown') if data else 'unknown',
            'upbit': upbit_data,
            'binance': binance_data,
            'portfolio': portfolio,
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
