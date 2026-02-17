"""
Asset Health Tracking for per-asset error isolation.

Tracks health status of each asset to enable graceful degradation
when individual assets encounter errors.
"""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Classification of errors for retry decisions."""
    TRANSIENT = "transient"      # Network timeouts, rate limits - should retry
    PERMANENT = "permanent"      # Auth failures, invalid config - don't retry
    DATA = "data"                # Missing data, parse errors - may recover
    UNKNOWN = "unknown"          # Unclassified errors


@dataclass
class AssetHealth:
    """Health status for a single asset."""
    symbol: str
    enabled: bool = True
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    disabled_at: Optional[datetime] = None
    disable_reason: Optional[str] = None
    last_error: Optional[str] = None
    last_error_category: Optional[ErrorCategory] = None
    last_success_time: Optional[datetime] = None
    last_failure_time: Optional[datetime] = None

    # Thresholds
    MAX_CONSECUTIVE_FAILURES: int = 5
    DISABLE_DURATION_SEC: float = 300.0  # 5 minutes

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "enabled": self.enabled,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "disabled_at": self.disabled_at.isoformat() if self.disabled_at else None,
            "disable_reason": self.disable_reason,
            "last_error": self.last_error,
            "last_error_category": self.last_error_category.value if self.last_error_category else None,
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
        }


def classify_error(exception: Exception) -> ErrorCategory:
    """
    Classify an exception into a category for retry decisions.

    Args:
        exception: The exception to classify

    Returns:
        ErrorCategory indicating how to handle the error
    """
    error_str = str(exception).lower()
    error_type = type(exception).__name__.lower()

    # Transient errors - should retry
    transient_patterns = [
        "timeout", "timed out", "connection", "network",
        "rate limit", "too many requests", "429",
        "503", "502", "504", "service unavailable",
        "temporarily", "retry", "overloaded",
    ]
    for pattern in transient_patterns:
        if pattern in error_str or pattern in error_type:
            return ErrorCategory.TRANSIENT

    # Permanent errors - don't retry
    permanent_patterns = [
        "auth", "unauthorized", "forbidden", "401", "403",
        "invalid key", "api key", "permission",
        "not found", "404", "does not exist",
        "invalid", "malformed",
    ]
    for pattern in permanent_patterns:
        if pattern in error_str or pattern in error_type:
            return ErrorCategory.PERMANENT

    # Data errors - may recover
    data_patterns = [
        "parse", "decode", "json", "data",
        "empty", "missing", "null", "none",
        "index", "key error", "attribute",
    ]
    for pattern in data_patterns:
        if pattern in error_str or pattern in error_type:
            return ErrorCategory.DATA

    return ErrorCategory.UNKNOWN


class AssetHealthTracker:
    """
    Tracks health status for multiple assets.

    Enables per-asset error isolation so one failing asset
    doesn't bring down the entire system.

    Usage:
        tracker = AssetHealthTracker(["BTC", "ETH", "XRP"])

        # In trading loop
        for symbol in tracker.get_healthy_symbols():
            try:
                await process_asset(symbol)
                tracker.record_success(symbol)
            except Exception as e:
                tracker.record_failure(symbol, e)
    """

    def __init__(
        self,
        symbols: List[str],
        max_failures: int = 5,
        disable_duration_sec: float = 300.0,
        on_disable: Optional[Callable[[str, str], None]] = None,
        on_recovery: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            symbols: List of asset symbols to track
            max_failures: Consecutive failures before disabling
            disable_duration_sec: Seconds to wait before attempting recovery
            on_disable: Callback when asset is disabled (symbol, reason)
            on_recovery: Callback when asset recovers (symbol)
        """
        self._health: Dict[str, AssetHealth] = {}
        self._lock = threading.RLock()
        self._max_failures = max_failures
        self._disable_duration = disable_duration_sec
        self._on_disable = on_disable
        self._on_recovery = on_recovery

        for symbol in symbols:
            self._health[symbol] = AssetHealth(
                symbol=symbol,
                MAX_CONSECUTIVE_FAILURES=max_failures,
                DISABLE_DURATION_SEC=disable_duration_sec,
            )

        logger.info(
            f"AssetHealthTracker initialized for {len(symbols)} assets: "
            f"max_failures={max_failures}, disable_duration={disable_duration_sec}s"
        )

    def record_success(self, symbol: str) -> None:
        """Record a successful operation for an asset."""
        with self._lock:
            health = self._health.get(symbol)
            if not health:
                return

            health.consecutive_failures = 0
            health.total_successes += 1
            health.last_success_time = datetime.now()
            health.last_error = None
            health.last_error_category = None

            # Re-enable if was disabled
            if not health.enabled:
                health.enabled = True
                health.disabled_at = None
                health.disable_reason = None
                logger.info(f"[{symbol}] Asset recovered and re-enabled")

                if self._on_recovery:
                    try:
                        self._on_recovery(symbol)
                    except Exception as e:
                        logger.warning(f"Recovery callback failed: {e}")

    def record_failure(
        self,
        symbol: str,
        exception: Optional[Exception] = None,
        reason: Optional[str] = None,
    ) -> None:
        """
        Record a failed operation for an asset.

        Args:
            symbol: Asset symbol
            exception: The exception that occurred
            reason: Optional reason string (used if no exception)
        """
        with self._lock:
            health = self._health.get(symbol)
            if not health:
                return

            health.consecutive_failures += 1
            health.total_failures += 1
            health.last_failure_time = datetime.now()

            if exception:
                health.last_error = str(exception)[:200]  # Truncate long errors
                health.last_error_category = classify_error(exception)
            elif reason:
                health.last_error = reason
                health.last_error_category = ErrorCategory.UNKNOWN

            logger.warning(
                f"[{symbol}] Failure {health.consecutive_failures}/"
                f"{health.MAX_CONSECUTIVE_FAILURES}: {health.last_error}"
            )

            # Disable if threshold reached
            if (
                health.enabled
                and health.consecutive_failures >= health.MAX_CONSECUTIVE_FAILURES
            ):
                self._disable_asset(health)

    def _disable_asset(self, health: AssetHealth) -> None:
        """Disable an asset due to repeated failures."""
        health.enabled = False
        health.disabled_at = datetime.now()
        health.disable_reason = (
            f"Disabled after {health.consecutive_failures} consecutive failures: "
            f"{health.last_error}"
        )

        logger.error(
            f"[{health.symbol}] Asset DISABLED: {health.disable_reason}"
        )

        if self._on_disable:
            try:
                self._on_disable(health.symbol, health.disable_reason)
            except Exception as e:
                logger.warning(f"Disable callback failed: {e}")

    def is_healthy(self, symbol: str) -> bool:
        """Check if an asset is currently healthy and enabled."""
        with self._lock:
            health = self._health.get(symbol)
            if not health:
                return False

            if health.enabled:
                return True

            # Check if recovery period has passed
            return self._check_recovery_eligible(health)

    def _check_recovery_eligible(self, health: AssetHealth) -> bool:
        """Check if a disabled asset is eligible for recovery attempt."""
        if health.enabled:
            return True

        if health.disabled_at is None:
            return True

        elapsed = (datetime.now() - health.disabled_at).total_seconds()
        return elapsed >= health.DISABLE_DURATION_SEC

    def check_recovery(self, symbol: str) -> bool:
        """
        Check if a disabled asset should attempt recovery.

        Returns True if the asset was disabled and is now eligible
        for a recovery attempt. The asset remains disabled until
        a successful operation is recorded.
        """
        with self._lock:
            health = self._health.get(symbol)
            if not health:
                return False

            if health.enabled:
                return False

            if self._check_recovery_eligible(health):
                logger.info(f"[{symbol}] Attempting recovery after disable period")
                return True

            return False

    def get_healthy_symbols(self) -> List[str]:
        """Get list of currently healthy symbols."""
        with self._lock:
            return [
                symbol for symbol, health in self._health.items()
                if health.enabled or self._check_recovery_eligible(health)
            ]

    def get_disabled_symbols(self) -> List[str]:
        """Get list of currently disabled symbols."""
        with self._lock:
            return [
                symbol for symbol, health in self._health.items()
                if not health.enabled and not self._check_recovery_eligible(health)
            ]

    def get_health(self, symbol: str) -> Optional[AssetHealth]:
        """Get health status for a specific asset."""
        with self._lock:
            return self._health.get(symbol)

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health status for all assets."""
        with self._lock:
            return {
                symbol: health.to_dict()
                for symbol, health in self._health.items()
            }

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        with self._lock:
            total = len(self._health)
            healthy = len(self.get_healthy_symbols())
            disabled = total - healthy

            return {
                "total_assets": total,
                "healthy_assets": healthy,
                "disabled_assets": disabled,
                "assets": {
                    symbol: {
                        "enabled": health.enabled,
                        "consecutive_failures": health.consecutive_failures,
                        "total_failures": health.total_failures,
                        "total_successes": health.total_successes,
                    }
                    for symbol, health in self._health.items()
                },
            }

    def reset(self, symbol: Optional[str] = None) -> None:
        """
        Reset health status.

        Args:
            symbol: Specific symbol to reset, or None to reset all
        """
        with self._lock:
            if symbol:
                health = self._health.get(symbol)
                if health:
                    health.enabled = True
                    health.consecutive_failures = 0
                    health.disabled_at = None
                    health.disable_reason = None
                    health.last_error = None
                    health.last_error_category = None
                    logger.info(f"[{symbol}] Health reset")
            else:
                for h in self._health.values():
                    h.enabled = True
                    h.consecutive_failures = 0
                    h.disabled_at = None
                    h.disable_reason = None
                    h.last_error = None
                    h.last_error_category = None
                logger.info("All asset health reset")

    def add_symbol(self, symbol: str) -> None:
        """Add a new symbol to track."""
        with self._lock:
            if symbol not in self._health:
                self._health[symbol] = AssetHealth(
                    symbol=symbol,
                    MAX_CONSECUTIVE_FAILURES=self._max_failures,
                    DISABLE_DURATION_SEC=self._disable_duration,
                )
                logger.info(f"[{symbol}] Added to health tracker")

    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from tracking."""
        with self._lock:
            if symbol in self._health:
                del self._health[symbol]
                logger.info(f"[{symbol}] Removed from health tracker")
