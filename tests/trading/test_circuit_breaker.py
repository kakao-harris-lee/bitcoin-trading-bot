"""Tests for circuit breaker pattern implementation."""

import pytest
import time
from threading import Thread
from unittest.mock import Mock

from trading.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
)


class TestCircuitBreaker:
    """Test CircuitBreaker class."""

    def test_initial_state_closed(self):
        """Circuit starts in closed state."""
        breaker = CircuitBreaker("test", failure_threshold=3)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed()
        assert not breaker.is_open()

    def test_success_does_not_open_circuit(self):
        """Successful calls keep circuit closed."""
        breaker = CircuitBreaker("test", failure_threshold=3)

        for _ in range(10):
            result = breaker.execute(lambda: "success")
            assert result == "success"

        assert breaker.is_closed()

    def test_failures_open_circuit(self):
        """Circuit opens after threshold failures."""
        breaker = CircuitBreaker("test", failure_threshold=3)

        def failing_func():
            raise ValueError("test error")

        # First 2 failures should not open circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.execute(failing_func)
            assert breaker.is_closed()

        # Third failure should open circuit
        with pytest.raises(ValueError):
            breaker.execute(failing_func)

        assert breaker.is_open()

    def test_open_circuit_rejects_calls(self):
        """Open circuit raises CircuitOpenError."""
        breaker = CircuitBreaker("test", failure_threshold=1, reset_timeout_sec=60)

        # Open the circuit
        with pytest.raises(ValueError):
            breaker.execute(lambda: (_ for _ in ()).throw(ValueError("fail")))

        # Next call should be rejected
        with pytest.raises(CircuitOpenError) as exc_info:
            breaker.execute(lambda: "should not run")

        assert exc_info.value.name == "test"
        assert exc_info.value.time_until_reset > 0

    def test_half_open_after_timeout(self):
        """Circuit transitions to half-open after timeout."""
        breaker = CircuitBreaker("test", failure_threshold=1, reset_timeout_sec=0.1)

        # Open the circuit
        with pytest.raises(ValueError):
            breaker.execute(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.is_open()

        # Wait for reset timeout
        time.sleep(0.15)

        # Should be half-open now
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        """Successful call in half-open state closes circuit."""
        breaker = CircuitBreaker("test", failure_threshold=1, reset_timeout_sec=0.1)

        # Open circuit
        with pytest.raises(ValueError):
            breaker.execute(lambda: (_ for _ in ()).throw(ValueError("fail")))

        # Wait for half-open
        time.sleep(0.15)

        # Success should close circuit
        result = breaker.execute(lambda: "success")
        assert result == "success"
        assert breaker.is_closed()

    def test_half_open_failure_reopens_circuit(self):
        """Failure in half-open state reopens circuit."""
        breaker = CircuitBreaker("test", failure_threshold=1, reset_timeout_sec=0.1)

        # Open circuit
        with pytest.raises(ValueError):
            breaker.execute(lambda: (_ for _ in ()).throw(ValueError("fail")))

        # Wait for half-open
        time.sleep(0.15)

        # Failure should reopen circuit
        with pytest.raises(ValueError):
            breaker.execute(lambda: (_ for _ in ()).throw(ValueError("fail again")))

        assert breaker.is_open()

    def test_manual_reset(self):
        """Manual reset closes circuit."""
        breaker = CircuitBreaker("test", failure_threshold=1)

        # Open circuit
        with pytest.raises(ValueError):
            breaker.execute(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.is_open()

        # Manual reset
        breaker.reset()

        assert breaker.is_closed()

    def test_stats_tracking(self):
        """Stats are tracked correctly."""
        breaker = CircuitBreaker("test", failure_threshold=3)

        # Some successes
        for _ in range(5):
            breaker.execute(lambda: "ok")

        # Some failures
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.execute(lambda: (_ for _ in ()).throw(ValueError("fail")))

        stats = breaker.get_stats()
        assert stats["name"] == "test"
        assert stats["stats"]["successful_calls"] == 5
        assert stats["stats"]["failed_calls"] == 2
        assert stats["failure_count"] == 2

    def test_excluded_exceptions_not_counted(self):
        """Excluded exceptions don't count as failures."""
        breaker = CircuitBreaker(
            "test",
            failure_threshold=1,
            excluded_exceptions=(KeyError,),
        )

        # KeyError should not count as failure
        for _ in range(5):
            with pytest.raises(KeyError):
                breaker.execute(lambda: (_ for _ in ()).throw(KeyError("excluded")))

        # Circuit should still be closed
        assert breaker.is_closed()

    def test_thread_safety(self):
        """Circuit breaker is thread-safe."""
        breaker = CircuitBreaker("test", failure_threshold=10)
        success_count = [0]

        def increment():
            result = breaker.execute(lambda: 1)
            success_count[0] += result

        threads = [Thread(target=increment) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert success_count[0] == 100
        stats = breaker.get_stats()
        assert stats["stats"]["successful_calls"] == 100


class TestCircuitBreakerRegistry:
    """Test CircuitBreakerRegistry singleton."""

    def test_singleton_pattern(self):
        """Registry is a singleton."""
        reg1 = CircuitBreakerRegistry()
        reg2 = CircuitBreakerRegistry()
        assert reg1 is reg2

    def test_get_or_create(self):
        """get_or_create returns same breaker for same name."""
        registry = CircuitBreakerRegistry()

        breaker1 = registry.get_or_create("test_service", failure_threshold=5)
        breaker2 = registry.get_or_create("test_service", failure_threshold=10)

        # Should return the same instance
        assert breaker1 is breaker2
        # Parameters from first call should be used
        assert breaker1.failure_threshold == 5

    def test_get_all_stats(self):
        """get_all_stats returns stats for all breakers."""
        registry = CircuitBreakerRegistry()

        registry.get_or_create("service_a")
        registry.get_or_create("service_b")

        all_stats = registry.get_all_stats()
        assert "service_a" in all_stats
        assert "service_b" in all_stats

    def test_reset_all(self):
        """reset_all resets all breakers."""
        registry = CircuitBreakerRegistry()

        breaker = registry.get_or_create("reset_test", failure_threshold=1)

        # Open circuit
        with pytest.raises(ValueError):
            breaker.execute(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.is_open()

        # Reset all
        registry.reset_all()

        assert breaker.is_closed()
