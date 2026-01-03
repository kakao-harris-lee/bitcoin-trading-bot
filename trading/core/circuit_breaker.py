"""
Circuit Breaker pattern for exchange adapters.

Prevents cascading failures by temporarily blocking calls to failing services.

States:
- CLOSED: Normal operation, calls pass through
- OPEN: Calls blocked, fail fast
- HALF_OPEN: Testing if service recovered
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, name: str, time_until_reset: float):
        self.name = name
        self.time_until_reset = time_until_reset
        super().__init__(
            f"Circuit breaker '{name}' is open. "
            f"Retry in {time_until_reset:.1f}s"
        )


@dataclass
class CircuitStats:
    """Statistics for circuit breaker."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    state_changes: int = 0


class CircuitBreaker:
    """
    Circuit breaker for protecting external service calls.

    Usage:
        breaker = CircuitBreaker("upbit")

        # Option 1: Execute with protection
        result = breaker.execute(api_call, arg1, arg2)

        # Option 2: Decorator style
        @breaker.protect
        def api_call(): ...

        # Option 3: Manual control
        if not breaker.is_open():
            try:
                result = api_call()
                breaker.record_success()
            except Exception as e:
                breaker.record_failure(e)
                raise
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_timeout_sec: float = 60.0,
        half_open_max_calls: int = 1,
        excluded_exceptions: tuple = (),
    ):
        """
        Args:
            name: Identifier for this circuit breaker
            failure_threshold: Failures before opening circuit
            reset_timeout_sec: Seconds before trying half-open
            half_open_max_calls: Calls allowed in half-open state
            excluded_exceptions: Exceptions that don't count as failures
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_sec = reset_timeout_sec
        self.half_open_max_calls = half_open_max_calls
        self.excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.RLock()

        self._stats = CircuitStats()

        logger.info(
            f"CircuitBreaker '{name}' initialized: "
            f"threshold={failure_threshold}, timeout={reset_timeout_sec}s"
        )

    @property
    def state(self) -> CircuitState:
        """Get current state, checking for timeout-based transitions."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to(CircuitState.HALF_OPEN)
            return self._state

    def is_open(self) -> bool:
        """Check if circuit is open (blocking calls)."""
        return self.state == CircuitState.OPEN

    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED

    def get_state(self) -> str:
        """Get state as string."""
        return self.state.value

    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "stats": {
                    "total_calls": self._stats.total_calls,
                    "successful_calls": self._stats.successful_calls,
                    "failed_calls": self._stats.failed_calls,
                    "rejected_calls": self._stats.rejected_calls,
                    "state_changes": self._stats.state_changes,
                    "last_failure": (
                        self._stats.last_failure_time.isoformat()
                        if self._stats.last_failure_time
                        else None
                    ),
                    "last_success": (
                        self._stats.last_success_time.isoformat()
                        if self._stats.last_success_time
                        else None
                    ),
                },
            }

    def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitOpenError: If circuit is open
            Exception: Original exception from func
        """
        self._before_call()

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except self.excluded_exceptions:
            # Don't count excluded exceptions as failures
            self.record_success()
            raise
        except Exception as e:
            self.record_failure(e)
            raise

    async def execute_async(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute async function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitOpenError: If circuit is open
            Exception: Original exception from func
        """
        self._before_call()

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except self.excluded_exceptions:
            self.record_success()
            raise
        except Exception as e:
            self.record_failure(e)
            raise

    def protect(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to protect a function with circuit breaker."""
        def wrapper(*args, **kwargs) -> T:
            return self.execute(func, *args, **kwargs)
        return wrapper

    def _before_call(self) -> None:
        """Check if call should proceed, raise if circuit open."""
        with self._lock:
            self._stats.total_calls += 1
            current_state = self.state  # Triggers timeout check

            if current_state == CircuitState.OPEN:
                self._stats.rejected_calls += 1
                time_until_reset = self._time_until_reset()
                raise CircuitOpenError(self.name, time_until_reset)

            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    self._stats.rejected_calls += 1
                    raise CircuitOpenError(self.name, 0)
                self._half_open_calls += 1

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self._stats.successful_calls += 1
            self._stats.last_success_time = datetime.now()

            if self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def record_failure(self, exception: Optional[Exception] = None) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            self._stats.failed_calls += 1
            self._stats.last_failure_time = datetime.now()

            error_msg = str(exception) if exception else "Unknown"
            logger.warning(
                f"CircuitBreaker '{self.name}': failure {self._failure_count}/"
                f"{self.failure_threshold} - {error_msg}"
            )

            if self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            logger.info(f"CircuitBreaker '{self.name}': manually reset")

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self._stats.state_changes += 1

            if new_state == CircuitState.CLOSED:
                self._failure_count = 0
            elif new_state == CircuitState.HALF_OPEN:
                self._half_open_calls = 0

            logger.info(
                f"CircuitBreaker '{self.name}': "
                f"{old_state.value} -> {new_state.value}"
            )

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try half-open."""
        if self._last_failure_time is None:
            return True
        elapsed = time.monotonic() - self._last_failure_time
        return elapsed >= self.reset_timeout_sec

    def _time_until_reset(self) -> float:
        """Get seconds until circuit might reset."""
        if self._last_failure_time is None:
            return 0
        elapsed = time.monotonic() - self._last_failure_time
        remaining = self.reset_timeout_sec - elapsed
        return max(0, remaining)


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    Usage:
        registry = CircuitBreakerRegistry()
        upbit_breaker = registry.get_or_create("upbit", failure_threshold=3)
        binance_breaker = registry.get_or_create("binance", failure_threshold=5)

        # Get all stats
        all_stats = registry.get_all_stats()
    """

    _instance: Optional["CircuitBreakerRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "CircuitBreakerRegistry":
        """Singleton pattern."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._breakers: Dict[str, CircuitBreaker] = {}
                cls._instance._breaker_lock = threading.RLock()
            return cls._instance

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_timeout_sec: float = 60.0,
        **kwargs,
    ) -> CircuitBreaker:
        """Get existing or create new circuit breaker."""
        with self._breaker_lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    reset_timeout_sec=reset_timeout_sec,
                    **kwargs,
                )
            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name."""
        with self._breaker_lock:
            return self._breakers.get(name)

    def get_all_stats(self) -> Dict[str, Dict]:
        """Get stats for all circuit breakers."""
        with self._breaker_lock:
            return {
                name: breaker.get_stats()
                for name, breaker in self._breakers.items()
            }

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        with self._breaker_lock:
            for breaker in self._breakers.values():
                breaker.reset()


# Global registry instance
circuit_registry = CircuitBreakerRegistry()
