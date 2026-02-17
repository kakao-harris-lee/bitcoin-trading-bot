"""
metrics_service.py
Real-time trading metrics service for dashboard.

Reads from Redis to provide:
- Current positions and P&L data
- Risk state (kill switch, daily P&L)
- Market prices
- Connection status
"""

# pylint: disable=broad-exception-caught

from datetime import datetime
from typing import Optional
import json
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
                market = data.get("market", "futures")

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
        positions, total_position_value, configured_strategies = self._collect_positions(prices)
        btc_price = prices.get("BTC:spot", 0.0)
        strategy_str = ", ".join(sorted(configured_strategies)) if configured_strategies else "None"
        daily_pnl = float(risk.get("daily_pnl", 0))
        kill_switch = risk.get("kill_switch", "false") == "true"
        blocked = risk.get("blocked", "false") == "true"
        return self._build_exchange_data_response(
            exchange=exchange,
            strategy_str=strategy_str,
            btc_price=btc_price,
            positions=positions,
            total_position_value=total_position_value,
            daily_pnl=daily_pnl,
            kill_switch=kill_switch,
            blocked=blocked,
        )

    def _collect_positions(self, prices: dict[str, float]) -> tuple[list[dict], float, set[str]]:
        positions: list[dict] = []
        total_position_value = 0.0
        configured_strategies: set[str] = set()
        for symbol in self.SYMBOLS:
            for market in self.MARKETS:
                pos = self._get_position(symbol, market)
                if not pos:
                    continue
                entry = self._parse_position_entry(pos, symbol, market, prices)
                if entry["strategy"]:
                    configured_strategies.add(entry["strategy"])
                if entry["position"] is not None:
                    positions.append(entry["position"])
                    total_position_value += entry["position"]["value"]
        return positions, total_position_value, configured_strategies

    def _parse_position_entry(
        self,
        pos: dict,
        symbol: str,
        market: str,
        prices: dict[str, float],
    ) -> dict:
        qty = float(pos.get("quantity", 0))
        entry_price = float(pos.get("entry_price", 0))
        strategy = pos.get("strategy", "unknown")
        if qty <= 0:
            return {"strategy": strategy, "position": None}
        price_key = f"{symbol}:{market}"
        current_price = prices.get(price_key, entry_price)
        position_value = qty * current_price
        pnl, pnl_pct = self._calculate_unrealized_pnl(qty, current_price, entry_price)
        return {
            "strategy": strategy,
            "position": {
                "asset": symbol,
                "market": market,
                "qty": qty,
                "entry_price": entry_price,
                "current_price": current_price,
                "value": position_value,
                "strategy": strategy,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct,
            },
        }

    def _calculate_unrealized_pnl(
        self,
        qty: float,
        current_price: float,
        entry_price: float,
    ) -> tuple[float, float]:
        if entry_price <= 0:
            return 0.0, 0.0
        pnl = (current_price - entry_price) * qty
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        return pnl, pnl_pct

    def _build_exchange_data_response(
        self,
        exchange: str,
        strategy_str: str,
        btc_price: float,
        positions: list[dict],
        total_position_value: float,
        daily_pnl: float,
        kill_switch: bool,
        blocked: bool,
    ) -> dict:
        return {
            "exchange": exchange,
            "mode": "live" if not blocked else "blocked",
            "strategy": strategy_str,
            "regime": "N/A",
            "market_state": "ACTIVE" if not kill_switch else "STOPPED",
            "current_price": btc_price,
            "position_active": len(positions) > 0,
            "positions": positions,
            "total_position_value": total_position_value,
            "daily_pnl": daily_pnl,
            "kill_switch": kill_switch,
            "blocked": blocked,
            "last_updated": datetime.now().isoformat(),
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
        Get recent strategy decisions from strategy:decisions stream.

        Reads hourly decision records written by CompositeStrategyTask.

        Args:
            hours: Number of hours of history to retrieve
            limit: Maximum number of decisions to return
            exchange: Optional filter by exchange (only 'binance' supported)

        Returns:
            List of StrategyDecision dicts
        """
        _ = hours
        if exchange and exchange != "binance":
            return []

        try:
            r = self._get_redis()
            is_paper_mode = self._is_paper_mode(r)
            entries = self._read_decision_entries(r, limit)
            if not entries:
                return self._get_position_based_decisions(limit)
            return self._parse_decision_entries(entries, is_paper_mode, limit)

        except Exception as e:
            # Any error - fall back to position-based decisions
            print(f"Error reading strategy:decisions stream: {e}")
            return self._get_position_based_decisions(limit)

    def _is_paper_mode(self, redis_client: redis.Redis) -> bool:
        risk_data = redis_client.hgetall("risk") or {}
        return risk_data.get("mode", "paper") == "paper"

    def _read_decision_entries(self, redis_client: redis.Redis, limit: int) -> list:
        return redis_client.xrevrange("strategy:decisions", count=limit * 2)

    def _parse_decision_entries(self, entries: list, is_paper_mode: bool, limit: int) -> list[dict]:
        decisions: list[dict] = []
        for _msg_id, data in entries:
            decision = self._parse_single_decision(data, is_paper_mode)
            if decision is None:
                continue
            decisions.append(decision)
            if len(decisions) >= limit:
                break
        return decisions

    def _parse_single_decision(self, data: dict, is_paper_mode: bool) -> Optional[dict]:
        entry_is_paper = data.get("paper", "true") == "true"
        if entry_is_paper != is_paper_mode:
            return None
        position_data = self._parse_position_payload(data.get("position"))
        return {
            "timestamp": data.get("timestamp", ""),
            "exchange": "binance",
            "symbol": data.get("symbol", ""),
            "market": data.get("market", "futures"),
            "strategy": data.get("strategy", ""),
            "decision": data.get("decision", ""),
            "reason": data.get("reason", ""),
            "regime": data.get("regime", ""),
            "indicators": {
                "price": float(data.get("price", 0)),
                "mfi": float(data.get("mfi", 0)),
                "adx": float(data.get("adx", 0)),
            },
            "position": position_data,
        }

    def _parse_position_payload(self, payload: Optional[str]) -> dict:
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return {}

    def _get_position_based_decisions(self, limit: int = 50) -> list[dict]:
        """Fallback: generate decisions from current position state.

        Used when strategy:decisions stream is empty or doesn't exist.
        """
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

                decision = 'HOLD' if qty > 0 else 'WAIT'
                reason = f"Position: {qty:.4f}" if qty > 0 else "No position"

                decisions.append({
                    'timestamp': timestamp,
                    'exchange': 'binance',
                    'symbol': symbol,
                    'market': market,
                    'strategy': strategy,
                    'decision': decision,
                    'reason': reason,
                    'regime': 'UNKNOWN',
                    'indicators': {
                        'price': price,
                        'mfi': 0,
                        'adx': 0,
                    },
                    'position': {'active': qty > 0},
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
            'portfolio': portfolio,
            'recent_decisions': recent_decisions,
            'connection_status': connection_status,
        }


    # =============================================================================
    # Event Stream Methods (for observability feature)
    # =============================================================================

    def get_entry_events(
        self,
        hours: int = 24,
        limit: int = 50,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> list[dict]:
        """
        Get entry evaluation events from strategy:entry:events stream.

        Args:
            hours: Number of hours of history to retrieve
            limit: Maximum number of events to return
            symbol: Optional filter by symbol
            strategy: Optional filter by strategy

        Returns:
            List of entry evaluation event dicts
        """
        _ = hours
        try:
            r = self._get_redis()

            # Read from strategy:entry:events stream (newest first)
            entries = r.xrevrange("strategy:entry:events", count=limit * 2)

            events = []
            for _msg_id, data in entries:
                # Apply filters
                if symbol and data.get("symbol") != symbol:
                    continue
                if strategy and data.get("strategy") != strategy:
                    continue

                events.append(data)

                if len(events) >= limit:
                    break

            return events

        except Exception as e:
            print(f"Error reading entry events: {e}")
            return []

    def get_exit_events(
        self,
        hours: int = 24,
        limit: int = 50,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> list[dict]:
        """
        Get exit evaluation events from strategy:exit:events stream.

        Args:
            hours: Number of hours of history to retrieve
            limit: Maximum number of events to return
            symbol: Optional filter by symbol
            strategy: Optional filter by strategy

        Returns:
            List of exit evaluation event dicts
        """
        _ = hours
        try:
            r = self._get_redis()

            # Read from strategy:exit:events stream (newest first)
            entries = r.xrevrange("strategy:exit:events", count=limit * 2)

            events = []
            for _msg_id, data in entries:
                # Apply filters
                if symbol and data.get("symbol") != symbol:
                    continue
                if strategy and data.get("strategy") != strategy:
                    continue

                events.append(data)

                if len(events) >= limit:
                    break

            return events

        except Exception as e:
            print(f"Error reading exit events: {e}")
            return []

    def get_hwm_timeline(
        self,
        symbol: str,
        strategy: str,
        hours: int = 24,
    ) -> list[dict]:
        """
        Get HWM update timeline from strategy:hwm:updates stream.

        Returns chronologically ordered (oldest first) HWM updates for a position.

        Args:
            symbol: Filter by symbol
            strategy: Filter by strategy
            hours: Number of hours of history

        Returns:
            List of HWM update event dicts in chronological order
        """
        _ = hours
        try:
            r = self._get_redis()

            # Read from strategy:hwm:updates stream (oldest first for timeline)
            entries = r.xrange("strategy:hwm:updates", count=1000)

            timeline = []
            for _msg_id, data in entries:
                # Filter by symbol and strategy
                if data.get("symbol") != symbol:
                    continue
                if data.get("strategy") != strategy:
                    continue

                timeline.append(data)

            return timeline

        except Exception as e:
            print(f"Error reading HWM timeline: {e}")
            return []

    def get_safety_rejections(
        self,
        hours: int = 24,
        limit: int = 50,
        rejection_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Get safety rejection events from strategy:safety:events stream.

        Args:
            hours: Number of hours of history to retrieve
            limit: Maximum number of events to return
            rejection_type: Optional filter by rejection type

        Returns:
            List of safety rejection event dicts
        """
        _ = hours
        try:
            r = self._get_redis()

            # Read from strategy:safety:events stream (newest first)
            entries = r.xrevrange("strategy:safety:events", count=limit * 2)

            rejections = []
            for _msg_id, data in entries:
                # Apply filter
                if rejection_type and data.get("rejection_type") != rejection_type:
                    continue

                rejections.append(data)

                if len(rejections) >= limit:
                    break

            return rejections

        except Exception as e:
            print(f"Error reading safety rejections: {e}")
            return []


# Singleton instance for use in app.py
metrics_service = MetricsService()
