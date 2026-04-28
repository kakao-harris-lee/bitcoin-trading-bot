"""
Trading Metrics Collection for observability.

Collects and exposes metrics about trading system behavior
for monitoring and debugging.
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LatencyHistogram:
    """Simple histogram for latency tracking."""
    values: List[float] = field(default_factory=list)
    max_samples: int = 1000

    def record(self, value_ms: float) -> None:
        """Record a latency value in milliseconds."""
        self.values.append(value_ms)
        # Keep only recent samples
        if len(self.values) > self.max_samples:
            self.values = self.values[-self.max_samples:]

    def percentile(self, p: float) -> float:
        """Get percentile value (0-100)."""
        if not self.values:
            return 0.0
        sorted_vals = sorted(self.values)
        idx = int(len(sorted_vals) * p / 100)
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    def mean(self) -> float:
        """Get mean value."""
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)

    def to_dict(self) -> Dict[str, float]:
        """Export as dictionary."""
        return {
            "count": len(self.values),
            "mean": round(self.mean(), 2),
            "p50": round(self.percentile(50), 2),
            "p90": round(self.percentile(90), 2),
            "p99": round(self.percentile(99), 2),
        }

    def reset(self) -> None:
        """Clear all values."""
        self.values.clear()


@dataclass
class TradingMetrics:
    """
    Structured metrics for trading system observability.

    Tracks:
    - Counters: signals, trades, errors (monotonic)
    - Gauges: current exposure, positions (point-in-time)
    - Histograms: latencies (distributions)
    """
    # Counters (monotonically increasing)
    signals_generated: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    trades_executed: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    api_calls: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    circuit_breaker_trips: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Gauges (current values)
    current_exposure_krw: float = 0.0
    position_values: Dict[str, float] = field(default_factory=dict)

    # Histograms (distributions)
    evaluation_latency_ms: LatencyHistogram = field(default_factory=LatencyHistogram)
    execution_latency_ms: LatencyHistogram = field(default_factory=LatencyHistogram)
    api_latency_ms: Dict[str, LatencyHistogram] = field(default_factory=dict)

    # Metadata
    start_time: datetime = field(default_factory=datetime.now)
    last_reset: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Export all metrics as dictionary."""
        return {
            "counters": {
                "signals_generated": dict(self.signals_generated),
                "trades_executed": dict(self.trades_executed),
                "errors_by_type": dict(self.errors_by_type),
                "api_calls": dict(self.api_calls),
                "circuit_breaker_trips": dict(self.circuit_breaker_trips),
            },
            "gauges": {
                "current_exposure_krw": self.current_exposure_krw,
                "position_values": self.position_values,
            },
            "histograms": {
                "evaluation_latency_ms": self.evaluation_latency_ms.to_dict(),
                "execution_latency_ms": self.execution_latency_ms.to_dict(),
                "api_latency_ms": {
                    name: hist.to_dict()
                    for name, hist in self.api_latency_ms.items()
                },
            },
            "metadata": {
                "start_time": self.start_time.isoformat(),
                "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
                "last_reset": self.last_reset.isoformat() if self.last_reset else None,
            },
        }

    def reset_counters(self) -> None:
        """Reset all counters (for periodic reset if needed)."""
        self.signals_generated.clear()
        self.trades_executed.clear()
        self.errors_by_type.clear()
        self.api_calls.clear()
        self.circuit_breaker_trips.clear()
        self.last_reset = datetime.now()

    def reset_histograms(self) -> None:
        """Reset all histograms."""
        self.evaluation_latency_ms.reset()
        self.execution_latency_ms.reset()
        for hist in self.api_latency_ms.values():
            hist.reset()


class MetricsCollector:
    """
    Thread-safe metrics collector singleton.

    Usage:
        metrics = MetricsCollector()

        # Record signal
        metrics.record_signal("BTC", "llm_direction_btc")

        # Record trade
        metrics.record_trade("BTC", "buy", 100000)

        # Time an operation
        with metrics.time_evaluation():
            await evaluate_strategies()

        # Get all metrics
        data = metrics.get_metrics()
    """

    _instance: Optional["MetricsCollector"] = None
    _lock = threading.Lock()
    _metrics: TradingMetrics
    _metrics_lock: threading.RLock

    def __new__(cls) -> "MetricsCollector":
        """Singleton pattern."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._metrics = TradingMetrics()
                cls._instance._metrics_lock = threading.RLock()
            return cls._instance

    @property
    def metrics(self) -> TradingMetrics:
        """Get the underlying metrics object."""
        return self._metrics

    # Counter methods
    def record_signal(self, symbol: str, strategy: str) -> None:
        """Record a signal generation."""
        with self._metrics_lock:
            self._metrics.signals_generated[f"{symbol}:{strategy}"] += 1

    def record_trade(self, symbol: str, action: str, amount: float = 0) -> None:
        """Record a trade execution."""
        _ = amount
        with self._metrics_lock:
            self._metrics.trades_executed[f"{symbol}:{action}"] += 1

    def record_error(self, error_type: str) -> None:
        """Record an error occurrence."""
        with self._metrics_lock:
            self._metrics.errors_by_type[error_type] += 1

    def record_api_call(self, service: str) -> None:
        """Record an API call."""
        with self._metrics_lock:
            self._metrics.api_calls[service] += 1

    def record_circuit_breaker_trip(self, breaker_name: str) -> None:
        """Record a circuit breaker trip."""
        with self._metrics_lock:
            self._metrics.circuit_breaker_trips[breaker_name] += 1

    # Gauge methods
    def set_exposure(self, krw: float) -> None:
        """Set current exposure values."""
        with self._metrics_lock:
            self._metrics.current_exposure_krw = krw

    def set_position_value(self, symbol: str, value: float) -> None:
        """Set current position value for a symbol."""
        with self._metrics_lock:
            self._metrics.position_values[symbol] = value

    # Latency recording
    def record_evaluation_latency(self, latency_ms: float) -> None:
        """Record strategy evaluation latency."""
        with self._metrics_lock:
            self._metrics.evaluation_latency_ms.record(latency_ms)

    def record_execution_latency(self, latency_ms: float) -> None:
        """Record trade execution latency."""
        with self._metrics_lock:
            self._metrics.execution_latency_ms.record(latency_ms)

    def record_api_latency(self, service: str, latency_ms: float) -> None:
        """Record API call latency for a service."""
        with self._metrics_lock:
            if service not in self._metrics.api_latency_ms:
                self._metrics.api_latency_ms[service] = LatencyHistogram()
            self._metrics.api_latency_ms[service].record(latency_ms)

    # Context managers for timing
    class _Timer:
        """Context manager for timing operations."""
        def __init__(self, callback):
            self.callback = callback
            self.start = None

        def __enter__(self):
            self.start = time.perf_counter()
            return self

        def __exit__(self, *args):
            elapsed_ms = (time.perf_counter() - self.start) * 1000
            self.callback(elapsed_ms)

    def time_evaluation(self) -> _Timer:
        """Context manager to time evaluation."""
        return self._Timer(self.record_evaluation_latency)

    def time_execution(self) -> _Timer:
        """Context manager to time execution."""
        return self._Timer(self.record_execution_latency)

    def time_api_call(self, service: str) -> _Timer:
        """Context manager to time API calls."""
        def record(latency_ms):
            self.record_api_call(service)
            self.record_api_latency(service, latency_ms)
        return self._Timer(record)

    # Export methods
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics as dictionary."""
        with self._metrics_lock:
            return self._metrics.to_dict()

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of key metrics."""
        with self._metrics_lock:
            m = self._metrics
            return {
                "uptime_seconds": (datetime.now() - m.start_time).total_seconds(),
                "total_signals": sum(m.signals_generated.values()),
                "total_trades": sum(m.trades_executed.values()),
                "total_errors": sum(m.errors_by_type.values()),
                "exposure_krw": m.current_exposure_krw,
                "eval_latency_p50": m.evaluation_latency_ms.percentile(50),
                "exec_latency_p50": m.execution_latency_ms.percentile(50),
            }

    def reset(self, counters: bool = True, histograms: bool = False) -> None:
        """Reset metrics."""
        with self._metrics_lock:
            if counters:
                self._metrics.reset_counters()
            if histograms:
                self._metrics.reset_histograms()


# Global metrics collector instance
metrics_collector = MetricsCollector()
