"""
metrics_service.py
Real-time trading metrics service for dashboard.

Reads from Redis to provide:
- Current positions and P&L data
- Risk state (kill switch, daily P&L)
- Market prices
- Connection status
"""

from datetime import datetime, timedelta
from typing import Optional
import os
import redis


class MetricsService:
    """Service for reading and transforming trading metrics data from Redis."""

    SYMBOLS = ["BTC", "ETH", "SOL"]
    MARKETS = ["spot", "futures"]
    STALE_THRESHOLD_SECONDS = 30

    def __init__(self, redis_url: str = None):
        """Initialize the metrics service.

        Args:
            redis_url: Redis connection URL. Defaults to env var or localhost.
        """
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._redis: Optional[redis.Redis] = None
        self._last_prices: dict[str, float] = {}
        self._last_price_time: Optional[datetime] = None

    def _get_redis(self) -> redis.Redis:
        """Get Redis connection (lazy initialization)."""
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def _get_position(self, symbol: str, market: str) -> dict:
        """Get position data from Redis.

        Args:
            symbol: Trading symbol (e.g., "BTC")
            market: Market type ("spot" or "futures")

        Returns:
            Position data dict
        """
        r = self._get_redis()
        key = f"positions:{symbol}:{market}"
        return r.hgetall(key)

    def _get_risk(self) -> dict:
        """Get risk data from Redis.

        Returns:
            Risk data dict
        """
        r = self._get_redis()
        return r.hgetall("risk")

    def _get_last_prices(self) -> dict[str, float]:
        """Get last known prices from Redis.

        Reads most recent entries from market:prices stream.

        Returns:
            Dict mapping symbol to last price
        """
        r = self._get_redis()
        now = datetime.now()

        # Cache prices for 2 seconds
        if (self._last_price_time is not None and
            (now - self._last_price_time).total_seconds() < 2):
            return self._last_prices

        try:
            # Read last 50 entries from market:prices stream
            entries = r.xrevrange("market:prices", count=50)

            prices = {}
            for _, data in entries:
                symbol = data.get("symbol")
                price_str = data.get("price")
                market = data.get("market", "spot")

                if symbol and price_str and symbol not in prices:
                    key = f"{symbol}:{market}"
                    prices[key] = float(price_str)

            self._last_prices = prices
            self._last_price_time = now

        except redis.ResponseError:
            # Stream might not exist yet
            pass

        return self._last_prices

    def load_exchange_data(self, exchange: str) -> Optional[dict]:
        """
        Load and parse data for an exchange from Redis.

        Args:
            exchange: Only 'binance' is supported now

        Returns:
            ExchangeMetrics dict, or None if no data
        """
        if exchange != "binance":
            return None

        prices = self._get_last_prices()
        risk = self._get_risk()

        positions = []
        total_position_value = 0.0
        configured_strategies = set()

        for symbol in self.SYMBOLS:
            for market in self.MARKETS:
                pos = self._get_position(symbol, market)
                if not pos:
                    continue

                qty = float(pos.get("quantity", 0))
                entry_price = float(pos.get("entry_price", 0))
                strategy = pos.get("strategy", "unknown")

                if strategy:
                    configured_strategies.add(strategy)

                if qty > 0:
                    # Get current price
                    price_key = f"{symbol}:{market}"
                    current_price = prices.get(price_key, entry_price)

                    position_value = qty * current_price
                    total_position_value += position_value

                    # Calculate unrealized P&L
                    if entry_price > 0:
                        pnl = (current_price - entry_price) * qty
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    else:
                        pnl = 0.0
                        pnl_pct = 0.0

                    positions.append({
                        'asset': symbol,
                        'market': market,
                        'qty': qty,
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'value': position_value,
                        'strategy': strategy,
                        'unrealized_pnl': pnl,
                        'unrealized_pnl_pct': pnl_pct,
                    })

        # Get primary price (BTC spot)
        btc_price = prices.get("BTC:spot", 0.0)

        strategy_str = ', '.join(sorted(configured_strategies)) if configured_strategies else 'None'

        daily_pnl = float(risk.get("daily_pnl", 0))
        kill_switch = risk.get("kill_switch", "false") == "true"
        blocked = risk.get("blocked", "false") == "true"

        return {
            'exchange': exchange,
            'mode': 'live' if not blocked else 'blocked',
            'strategy': strategy_str,
            'regime': 'N/A',  # No centralized regime in new architecture
            'market_state': 'ACTIVE' if not kill_switch else 'STOPPED',
            'current_price': btc_price,
            'position_active': len(positions) > 0,
            'positions': positions,
            'total_position_value': total_position_value,
            'daily_pnl': daily_pnl,
            'kill_switch': kill_switch,
            'blocked': blocked,
            'last_updated': datetime.now().isoformat(),
        }

    def get_connection_status(self, exchange: str) -> dict:
        """
        Check Redis connection and return ConnectionStatus dict.

        Args:
            exchange: Only 'binance' is supported now

        Returns:
            ConnectionStatus dict
        """
        if exchange != "binance":
            return {
                'exchange': exchange,
                'connected': False,
                'last_heartbeat': None,
                'is_stale': True,
                'stale_seconds': None,
            }

        try:
            r = self._get_redis()
            r.ping()

            # Check if we have recent prices
            prices = self._get_last_prices()
            has_prices = len(prices) > 0

            return {
                'exchange': exchange,
                'connected': has_prices,
                'last_heartbeat': datetime.now().isoformat() if has_prices else None,
                'is_stale': not has_prices,
                'stale_seconds': 0 if has_prices else None,
            }
        except redis.ConnectionError:
            return {
                'exchange': exchange,
                'connected': False,
                'last_heartbeat': None,
                'is_stale': True,
                'stale_seconds': None,
            }

    def get_recent_decisions(
        self,
        hours: int = 24,
        limit: int = 50,
        exchange: Optional[str] = None
    ) -> list[dict]:
        """
        Get recent strategy decisions from current positions.

        Note: The stream architecture doesn't store historical decisions.
        This returns current state as a single decision per active position.

        Args:
            hours: Number of hours of history (unused currently)
            limit: Maximum number of decisions to return
            exchange: Optional filter by exchange

        Returns:
            List of StrategyDecision dicts
        """
        if exchange and exchange != "binance":
            return []

        decisions = []
        prices = self._get_last_prices()
        timestamp = datetime.now().isoformat()

        for symbol in self.SYMBOLS:
            for market in self.MARKETS:
                pos = self._get_position(symbol, market)

                qty = float(pos.get("quantity", 0)) if pos else 0
                strategy = pos.get("strategy", "None") if pos else "None"

                price_key = f"{symbol}:{market}"
                price = prices.get(price_key, 0.0)

                action = 'HOLD' if qty > 0 else 'WAIT'
                reason = f"Position: {qty:.4f}" if qty > 0 else "No position"

                decisions.append({
                    'timestamp': timestamp,
                    'exchange': 'binance',
                    'asset': symbol,
                    'market': market,
                    'strategy': strategy,
                    'action': action,
                    'reason': reason,
                    'indicators': {
                        'price': price,
                    }
                })

        return decisions[:limit]

    def get_dashboard_state(self) -> dict:
        """
        Get complete dashboard state combining all metrics.

        Returns:
            DashboardState dict
        """
        binance_data = self.load_exchange_data('binance')
        risk = self._get_risk()

        connection_status = [
            self.get_connection_status('binance'),
        ]

        recent_decisions = self.get_recent_decisions(hours=24, limit=50)

        # Build portfolio summary
        total_position_value = binance_data.get('total_position_value', 0) if binance_data else 0
        daily_pnl = float(risk.get("daily_pnl", 0))

        portfolio = {
            'total_position_value': total_position_value,
            'daily_pnl': daily_pnl,
            'kill_switch': risk.get("kill_switch", "false") == "true",
            'blocked': risk.get("blocked", "false") == "true",
        }

        return {
            'timestamp': datetime.now().isoformat(),
            'mode': 'live',  # Could be paper, but we don't track this in Redis
            'binance': binance_data,
            'upbit': None,  # Upbit removed
            'portfolio': portfolio,
            'recent_decisions': recent_decisions,
            'connection_status': connection_status,
        }


# Singleton instance for use in app.py
metrics_service = MetricsService()
