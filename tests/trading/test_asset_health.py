"""Tests for asset health tracking."""

import pytest
import time
from unittest.mock import Mock

from trading.core.asset_health import (
    AssetHealth,
    AssetHealthTracker,
    ErrorCategory,
    classify_error,
)


class TestErrorClassification:
    """Test error classification."""

    def test_classify_transient_timeout(self):
        """Timeout errors are transient."""
        e = TimeoutError("Connection timed out")
        assert classify_error(e) == ErrorCategory.TRANSIENT

    def test_classify_transient_rate_limit(self):
        """Rate limit errors are transient."""
        e = Exception("429 Too Many Requests")
        assert classify_error(e) == ErrorCategory.TRANSIENT

    def test_classify_transient_connection(self):
        """Connection errors are transient."""
        e = ConnectionError("Network unreachable")
        assert classify_error(e) == ErrorCategory.TRANSIENT

    def test_classify_permanent_auth(self):
        """Auth errors are permanent."""
        e = Exception("401 Unauthorized - Invalid API key")
        assert classify_error(e) == ErrorCategory.PERMANENT

    def test_classify_permanent_not_found(self):
        """Not found errors are permanent."""
        e = Exception("404 Resource not found")
        assert classify_error(e) == ErrorCategory.PERMANENT

    def test_classify_data_parse(self):
        """Parse errors are data category."""
        e = ValueError("JSON decode error")
        assert classify_error(e) == ErrorCategory.DATA

    def test_classify_unknown(self):
        """Unclassified errors are unknown."""
        e = Exception("Some random error")
        assert classify_error(e) == ErrorCategory.UNKNOWN


class TestAssetHealthTracker:
    """Test AssetHealthTracker class."""

    def test_initial_state_healthy(self):
        """All assets start healthy."""
        tracker = AssetHealthTracker(["BTC", "ETH", "XRP"])

        assert tracker.is_healthy("BTC")
        assert tracker.is_healthy("ETH")
        assert tracker.is_healthy("XRP")
        assert len(tracker.get_healthy_symbols()) == 3
        assert len(tracker.get_disabled_symbols()) == 0

    def test_record_success(self):
        """Success resets failure count."""
        tracker = AssetHealthTracker(["BTC"], max_failures=3)

        # Record some failures
        tracker.record_failure("BTC", Exception("error 1"))
        tracker.record_failure("BTC", Exception("error 2"))

        health = tracker.get_health("BTC")
        assert health.consecutive_failures == 2

        # Success resets counter
        tracker.record_success("BTC")

        health = tracker.get_health("BTC")
        assert health.consecutive_failures == 0
        assert health.total_successes == 1

    def test_failures_disable_asset(self):
        """Consecutive failures disable an asset."""
        tracker = AssetHealthTracker(["BTC"], max_failures=3)

        # Record failures up to threshold
        for i in range(3):
            tracker.record_failure("BTC", Exception(f"error {i}"))

        # Asset should be disabled
        assert not tracker.is_healthy("BTC")
        assert "BTC" in tracker.get_disabled_symbols()

        health = tracker.get_health("BTC")
        assert not health.enabled
        assert health.disable_reason is not None

    def test_success_clears_failures(self):
        """Success before threshold clears failures."""
        tracker = AssetHealthTracker(["BTC"], max_failures=5)

        # Some failures
        tracker.record_failure("BTC", Exception("error 1"))
        tracker.record_failure("BTC", Exception("error 2"))

        assert tracker.is_healthy("BTC")

        # Success clears failures
        tracker.record_success("BTC")

        health = tracker.get_health("BTC")
        assert health.consecutive_failures == 0

    def test_recovery_after_timeout(self):
        """Asset becomes eligible for recovery after timeout."""
        tracker = AssetHealthTracker(
            ["BTC"],
            max_failures=1,
            disable_duration_sec=0.1,  # 100ms for testing
        )

        # Disable asset
        tracker.record_failure("BTC", Exception("error"))
        assert not tracker.is_healthy("BTC")

        # Wait for recovery period
        time.sleep(0.15)

        # Should be eligible for recovery
        assert tracker.check_recovery("BTC")
        assert tracker.is_healthy("BTC")  # Eligible for recovery attempt

    def test_callbacks_on_disable(self):
        """on_disable callback is called when asset is disabled."""
        callback = Mock()
        tracker = AssetHealthTracker(
            ["BTC"],
            max_failures=2,
            on_disable=callback,
        )

        # Trigger disable
        tracker.record_failure("BTC", Exception("error 1"))
        tracker.record_failure("BTC", Exception("error 2"))

        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][0] == "BTC"  # symbol
        assert "error 2" in call_args[0][1]  # reason

    def test_callbacks_on_recovery(self):
        """on_recovery callback is called when asset recovers."""
        callback = Mock()
        tracker = AssetHealthTracker(
            ["BTC"],
            max_failures=1,
            disable_duration_sec=0.1,
            on_recovery=callback,
        )

        # Disable then recover
        tracker.record_failure("BTC", Exception("error"))
        time.sleep(0.15)
        tracker.record_success("BTC")

        callback.assert_called_once_with("BTC")

    def test_get_summary(self):
        """get_summary returns correct statistics."""
        tracker = AssetHealthTracker(["BTC", "ETH"], max_failures=2)

        tracker.record_success("BTC")
        tracker.record_failure("ETH", Exception("error 1"))
        tracker.record_failure("ETH", Exception("error 2"))

        summary = tracker.get_summary()

        assert summary["total_assets"] == 2
        assert summary["healthy_assets"] == 1
        assert summary["disabled_assets"] == 1
        assert summary["assets"]["BTC"]["total_successes"] == 1
        assert summary["assets"]["ETH"]["total_failures"] == 2

    def test_reset_single_asset(self):
        """reset() can reset a single asset."""
        tracker = AssetHealthTracker(["BTC", "ETH"], max_failures=1)

        tracker.record_failure("BTC", Exception("error"))
        tracker.record_failure("ETH", Exception("error"))

        # Reset only BTC
        tracker.reset("BTC")

        assert tracker.is_healthy("BTC")
        assert not tracker.is_healthy("ETH")

    def test_reset_all_assets(self):
        """reset() without argument resets all assets."""
        tracker = AssetHealthTracker(["BTC", "ETH"], max_failures=1)

        tracker.record_failure("BTC", Exception("error"))
        tracker.record_failure("ETH", Exception("error"))

        # Reset all
        tracker.reset()

        assert tracker.is_healthy("BTC")
        assert tracker.is_healthy("ETH")

    def test_add_remove_symbol(self):
        """Symbols can be added and removed dynamically."""
        tracker = AssetHealthTracker(["BTC"])

        tracker.add_symbol("ETH")
        assert tracker.is_healthy("ETH")
        assert len(tracker.get_healthy_symbols()) == 2

        tracker.remove_symbol("ETH")
        assert len(tracker.get_healthy_symbols()) == 1
        assert tracker.get_health("ETH") is None
