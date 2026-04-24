"""Tests for metrics collection module."""

import pytest
import time
from unittest.mock import patch

from trading.core.metrics import (
    LatencyHistogram,
    MetricsCollector,
    TradingMetrics,
    metrics_collector,
)


class TestLatencyHistogram:
    """Test LatencyHistogram class."""

    def test_empty_histogram(self):
        """Empty histogram returns zeros."""
        hist = LatencyHistogram()
        assert hist.mean() == 0.0
        assert hist.percentile(50) == 0.0

    def test_record_values(self):
        """Values are recorded correctly."""
        hist = LatencyHistogram()
        hist.record(10.0)
        hist.record(20.0)
        hist.record(30.0)

        assert len(hist.values) == 3
        assert hist.mean() == 20.0

    def test_percentiles(self):
        """Percentiles are calculated correctly."""
        hist = LatencyHistogram()
        for i in range(1, 101):
            hist.record(float(i))

        # Allow small margin for percentile calculation method variations
        assert 50 <= hist.percentile(50) <= 51
        assert 90 <= hist.percentile(90) <= 91
        assert 99 <= hist.percentile(99) <= 100

    def test_max_samples_limit(self):
        """Histogram respects max_samples limit."""
        hist = LatencyHistogram(max_samples=10)

        for i in range(20):
            hist.record(float(i))

        # Should only keep last 10 samples
        assert len(hist.values) == 10
        assert hist.values[0] == 10.0  # First kept value

    def test_to_dict(self):
        """to_dict returns expected format."""
        hist = LatencyHistogram()
        hist.record(10.0)
        hist.record(20.0)

        result = hist.to_dict()

        assert "count" in result
        assert "mean" in result
        assert "p50" in result
        assert "p90" in result
        assert "p99" in result
        assert result["count"] == 2

    def test_reset(self):
        """Reset clears all values."""
        hist = LatencyHistogram()
        hist.record(10.0)
        hist.reset()

        assert len(hist.values) == 0


class TestTradingMetrics:
    """Test TradingMetrics dataclass."""

    def test_to_dict_structure(self):
        """to_dict returns expected structure."""
        metrics = TradingMetrics()
        result = metrics.to_dict()

        assert "counters" in result
        assert "gauges" in result
        assert "histograms" in result
        assert "metadata" in result

    def test_reset_counters(self):
        """reset_counters clears counter values."""
        metrics = TradingMetrics()
        metrics.signals_generated["BTC:short"] = 10
        metrics.trades_executed["BTC:buy"] = 5

        metrics.reset_counters()

        assert len(metrics.signals_generated) == 0
        assert len(metrics.trades_executed) == 0


class TestMetricsCollector:
    """Test MetricsCollector singleton."""

    def test_singleton_pattern(self):
        """MetricsCollector is a singleton."""
        collector1 = MetricsCollector()
        collector2 = MetricsCollector()
        assert collector1 is collector2

    def test_record_signal(self):
        """Signals are recorded correctly."""
        collector = MetricsCollector()
        collector.metrics.signals_generated.clear()

        collector.record_signal("BTC", "mlp_direction_btc")
        collector.record_signal("BTC", "mlp_direction_btc")
        collector.record_signal("ETH", "mlp_direction_btc")

        metrics = collector.get_metrics()
        assert metrics["counters"]["signals_generated"]["BTC:mlp_direction_btc"] == 2
        assert metrics["counters"]["signals_generated"]["ETH:mlp_direction_btc"] == 1

    def test_record_trade(self):
        """Trades are recorded correctly."""
        collector = MetricsCollector()
        collector.metrics.trades_executed.clear()

        collector.record_trade("BTC", "buy", 1000000)
        collector.record_trade("BTC", "sell", 1000000)

        metrics = collector.get_metrics()
        assert metrics["counters"]["trades_executed"]["BTC:buy"] == 1
        assert metrics["counters"]["trades_executed"]["BTC:sell"] == 1

    def test_record_error(self):
        """Errors are recorded correctly."""
        collector = MetricsCollector()
        collector.metrics.errors_by_type.clear()

        collector.record_error("connection_timeout")
        collector.record_error("connection_timeout")
        collector.record_error("api_error")

        metrics = collector.get_metrics()
        assert metrics["counters"]["errors_by_type"]["connection_timeout"] == 2
        assert metrics["counters"]["errors_by_type"]["api_error"] == 1

    def test_set_exposure(self):
        """Exposure gauges are set correctly."""
        collector = MetricsCollector()

        collector.set_exposure(1000000)

        metrics = collector.get_metrics()
        assert metrics["gauges"]["current_exposure_krw"] == 1000000

    def test_time_evaluation_context_manager(self):
        """time_evaluation context manager records latency."""
        collector = MetricsCollector()
        collector.metrics.evaluation_latency_ms.reset()

        with collector.time_evaluation():
            time.sleep(0.01)  # 10ms

        metrics = collector.get_metrics()
        # Should have recorded at least ~10ms
        assert metrics["histograms"]["evaluation_latency_ms"]["count"] >= 1

    def test_time_api_call_context_manager(self):
        """time_api_call context manager records API latency."""
        collector = MetricsCollector()
        collector.metrics.api_latency_ms.clear()
        collector.metrics.api_calls.clear()

        with collector.time_api_call("binance"):
            time.sleep(0.01)

        metrics = collector.get_metrics()
        assert "binance" in metrics["counters"]["api_calls"]
        assert "binance" in metrics["histograms"]["api_latency_ms"]

    def test_get_summary(self):
        """get_summary returns expected format."""
        collector = MetricsCollector()

        summary = collector.get_summary()

        assert "uptime_seconds" in summary
        assert "total_signals" in summary
        assert "total_trades" in summary
        assert "total_errors" in summary
        assert "exposure_krw" in summary

    def test_reset(self):
        """reset clears appropriate metrics."""
        collector = MetricsCollector()

        collector.record_signal("BTC", "test")
        collector.record_error("test")

        collector.reset(counters=True)

        metrics = collector.get_metrics()
        assert sum(metrics["counters"]["signals_generated"].values()) == 0
        assert sum(metrics["counters"]["errors_by_type"].values()) == 0
