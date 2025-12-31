"""
HealthMonitor - Continuous health monitoring for async engine.

Monitors:
- Price freshness
- WebSocket connectivity
- FX rate staleness
- Memory usage
- Order queue depth
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger(__name__)


class HealthStatus:
    """Health status constants."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthMonitor:
    """
    Continuous health monitoring with alerting and logging.

    Features:
    - Periodic health checks
    - Dashboard JSON output
    - Telegram alerting (optional)
    - Graceful degradation tracking
    """

    def __init__(
        self,
        engine: Any,  # AsyncTradingEngine
        check_interval: float = 10.0,
        max_price_age: float = 60.0,
        max_memory_mb: float = 500.0,
        log_dir: Optional[Path] = None,
        on_alert: Optional[Callable[[str, Dict], None]] = None,
    ):
        """
        Args:
            engine: AsyncTradingEngine instance
            check_interval: Seconds between health checks
            max_price_age: Maximum acceptable price age in seconds
            max_memory_mb: Maximum acceptable memory usage in MB
            log_dir: Directory for health logs
            on_alert: Callback for alerts (message, data)
        """
        self.engine = engine
        self.check_interval = check_interval
        self.max_price_age = max_price_age
        self.max_memory_mb = max_memory_mb
        self.log_dir = log_dir or Path(__file__).parent.parent.parent / "logs"
        self.on_alert = on_alert

        self._started = False
        self._task: Optional[asyncio.Task] = None
        self._last_health: Dict[str, Any] = {}
        self._alert_cooldown: Dict[str, datetime] = {}
        self._alert_cooldown_seconds = 300  # 5 minutes

    async def start(self) -> None:
        """Start health monitoring."""
        if self._started:
            return

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._run())
        self._started = True

        logger.info("HealthMonitor started")

    async def stop(self) -> None:
        """Stop health monitoring."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._started = False
        logger.info("HealthMonitor stopped")

    async def _run(self) -> None:
        """Main monitoring loop."""
        while True:
            try:
                health = await self._collect_health()
                self._last_health = health

                # Check for issues
                await self._check_alerts(health)

                # Write to dashboard
                await self._write_health_json(health)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

            await asyncio.sleep(self.check_interval)

    async def _collect_health(self) -> Dict[str, Any]:
        """Collect health metrics from all components."""
        now = datetime.now()

        health = {
            "timestamp": now.isoformat(),
            "status": HealthStatus.HEALTHY,
            "issues": [],
        }

        # Price freshness
        price_health = self._check_price_health()
        health["prices"] = price_health
        if price_health["status"] != HealthStatus.HEALTHY:
            health["issues"].append(f"Price: {price_health['issue']}")

        # WebSocket connectivity (informational only - polling mode doesn't need active WS)
        ws_health = self._check_websocket_health()
        health["websockets"] = ws_health
        # Note: WebSocket disconnections are expected in 5-min polling mode, so we don't alert

        # FX rate
        fx_health = self._check_fx_health()
        health["fx_rate"] = fx_health
        if fx_health["status"] != HealthStatus.HEALTHY:
            health["issues"].append(f"FX Rate: {fx_health['issue']}")

        # Memory usage
        memory_health = self._check_memory_health()
        health["memory"] = memory_health
        if memory_health["status"] != HealthStatus.HEALTHY:
            health["issues"].append(f"Memory: {memory_health['issue']}")

        # Order queue
        queue_health = self._check_queue_health()
        health["order_queue"] = queue_health
        if queue_health["status"] != HealthStatus.HEALTHY:
            health["issues"].append(f"Order Queue: {queue_health['issue']}")

        # Data cache
        cache_health = self._check_cache_health()
        health["data_cache"] = cache_health
        if cache_health["status"] != HealthStatus.HEALTHY:
            health["issues"].append(f"Data Cache: {cache_health['issue']}")

        # Determine overall status
        if len(health["issues"]) == 0:
            health["status"] = HealthStatus.HEALTHY
        elif len(health["issues"]) <= 2:
            health["status"] = HealthStatus.DEGRADED
        else:
            health["status"] = HealthStatus.UNHEALTHY

        return health

    def _check_price_health(self) -> Dict[str, Any]:
        """Check price freshness."""
        result = {
            "status": HealthStatus.HEALTHY,
            "upbit": None,
            "binance": None,
            "issue": None,
        }

        price_hub = getattr(self.engine, 'price_hub', None)
        if not price_hub:
            result["status"] = HealthStatus.UNHEALTHY
            result["issue"] = "PriceHub not available"
            return result

        for exchange in ["upbit", "binance"]:
            age = price_hub.get_price_age(exchange)
            result[exchange] = {
                "price": price_hub.get_price(exchange),
                "age_seconds": age,
                "fresh": age is not None and age < self.max_price_age,
            }

            if age is None:
                result["status"] = HealthStatus.UNHEALTHY
                result["issue"] = f"{exchange} price not available"
            elif age > self.max_price_age:
                result["status"] = HealthStatus.DEGRADED
                result["issue"] = f"{exchange} price stale ({age:.1f}s)"

        return result

    def _check_websocket_health(self) -> Dict[str, Any]:
        """Check WebSocket connectivity."""
        result = {
            "status": HealthStatus.HEALTHY,
            "upbit": False,
            "binance": False,
            "issue": None,
        }

        feed_handler = getattr(self.engine, 'feed_handler', None)
        if not feed_handler:
            result["status"] = HealthStatus.UNHEALTHY
            result["issue"] = "FeedHandler not available"
            return result

        # SimpleFeedHandler uses _upbit_ws and _binance_ws
        upbit_ws = getattr(feed_handler, '_upbit_ws', None)
        binance_ws = getattr(feed_handler, '_binance_ws', None)

        result["upbit"] = upbit_ws.is_connected if upbit_ws else False
        result["binance"] = binance_ws.is_connected if binance_ws else False

        if not result["upbit"] or not result["binance"]:
            disconnected = []
            if not result["upbit"]:
                disconnected.append("upbit")
            if not result["binance"]:
                disconnected.append("binance")

            result["status"] = HealthStatus.DEGRADED
            result["issue"] = f"Disconnected: {', '.join(disconnected)}"

        return result

    def _check_fx_health(self) -> Dict[str, Any]:
        """Check FX rate freshness."""
        result = {
            "status": HealthStatus.HEALTHY,
            "rate": None,
            "age_seconds": None,
            "issue": None,
        }

        fx_cache = getattr(self.engine, 'fx_cache', None)
        if not fx_cache:
            result["status"] = HealthStatus.DEGRADED
            result["issue"] = "FXRateCache not available"
            return result

        result["rate"] = fx_cache.rate
        result["age_seconds"] = fx_cache.age_seconds

        if fx_cache.is_stale:
            result["status"] = HealthStatus.DEGRADED
            result["issue"] = f"Rate stale ({result['age_seconds']:.0f}s)"

        return result

    def _check_memory_health(self) -> Dict[str, Any]:
        """Check memory usage."""
        result = {
            "status": HealthStatus.HEALTHY,
            "used_mb": 0,
            "percent": 0,
            "issue": None,
        }

        if not HAS_PSUTIL:
            result["issue"] = "psutil not installed"
            return result

        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            used_mb = memory_info.rss / 1024 / 1024

            result["used_mb"] = round(used_mb, 1)
            result["percent"] = round(process.memory_percent(), 1)

            # Check critical first (higher threshold), then degraded
            if used_mb > self.max_memory_mb * 1.5:
                result["status"] = HealthStatus.UNHEALTHY
                result["issue"] = f"Critical memory: {used_mb:.0f}MB"
            elif used_mb > self.max_memory_mb:
                result["status"] = HealthStatus.DEGRADED
                result["issue"] = f"High memory: {used_mb:.0f}MB"

        except Exception as e:
            result["status"] = HealthStatus.DEGRADED
            result["issue"] = f"Cannot read memory: {e}"

        return result

    def _check_queue_health(self) -> Dict[str, Any]:
        """Check order queue depth."""
        result = {
            "status": HealthStatus.HEALTHY,
            "pending": 0,
            "issue": None,
        }

        executor = getattr(self.engine, 'executor', None)
        if not executor:
            result["status"] = HealthStatus.DEGRADED
            result["issue"] = "Executor not available"
            return result

        stats = executor.get_stats()
        result["pending"] = stats.get("pending_count", 0)
        result["queue_size"] = stats.get("queue_size", 0)

        if result["pending"] > 10:
            result["status"] = HealthStatus.DEGRADED
            result["issue"] = f"High pending orders: {result['pending']}"

        return result

    def _check_cache_health(self) -> Dict[str, Any]:
        """Check data cache health."""
        result = {
            "status": HealthStatus.HEALTHY,
            "timeframes": {},
            "issue": None,
        }

        data_cache = getattr(self.engine, 'data_cache', None)
        if not data_cache:
            result["status"] = HealthStatus.DEGRADED
            result["issue"] = "DataCache not available"
            return result

        sizes = data_cache.get_sizes()
        result["timeframes"] = sizes

        for tf, size in sizes.items():
            if size == 0:
                result["status"] = HealthStatus.DEGRADED
                result["issue"] = f"Empty cache: {tf}"
                break

        return result

    async def _check_alerts(self, health: Dict[str, Any]) -> None:
        """Check for alertable conditions."""
        if not self.on_alert:
            return

        now = datetime.now()

        for issue in health["issues"]:
            # Check cooldown
            last_alert = self._alert_cooldown.get(issue)
            if last_alert:
                elapsed = (now - last_alert).total_seconds()
                if elapsed < self._alert_cooldown_seconds:
                    continue

            # Send alert
            self._alert_cooldown[issue] = now
            try:
                self.on_alert(f"Health Alert: {issue}", health)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

    async def _write_health_json(self, health: Dict[str, Any]) -> None:
        """Write health status to JSON for dashboard."""
        try:
            await asyncio.to_thread(self._write_health_json_sync, health)
        except Exception as e:
            logger.error(f"Failed to write health JSON: {e}")

    def _write_health_json_sync(self, health: Dict[str, Any]) -> None:
        """Sync helper for writing health JSON."""
        health_file = self.log_dir / "async_engine_health.json"
        with open(health_file, "w") as f:
            json.dump(health, f, indent=2, ensure_ascii=False)

    def get_health(self) -> Dict[str, Any]:
        """Get last health check result."""
        return self._last_health

    def is_healthy(self) -> bool:
        """Check if engine is healthy."""
        return self._last_health.get("status") == HealthStatus.HEALTHY

    def get_stats(self) -> Dict[str, Any]:
        """Get monitor statistics."""
        return {
            "started": self._started,
            "check_interval": self.check_interval,
            "last_check": self._last_health.get("timestamp"),
            "status": self._last_health.get("status"),
            "issue_count": len(self._last_health.get("issues", [])),
        }
