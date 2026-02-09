"""Tests for RQ worker tasks."""
import pytest
from unittest.mock import MagicMock, patch
from web.quant_lab.worker.tasks import (
    run_optimization,
    OptimizationJob,
    JobStatus,
)


class TestOptimizationJob:
    """Test optimization job dataclass."""

    def test_job_creation(self):
        """Job should store all configuration."""
        job = OptimizationJob(
            job_id="test-123",
            study_name="my_experiment",
            data_path="data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["BTCUSDT"],
            max_trials=100,
        )

        assert job.job_id == "test-123"
        assert job.max_trials == 100

    def test_job_to_dict(self):
        """Job should serialize to dict."""
        job = OptimizationJob(
            job_id="test-456",
            study_name="test_study",
            data_path="data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["BTCUSDT", "ETHUSDT"],
        )

        data = job.to_dict()
        assert data["job_id"] == "test-456"
        assert data["symbols"] == ["BTCUSDT", "ETHUSDT"]

    def test_job_from_dict(self):
        """Job should deserialize from dict."""
        data = {
            "job_id": "test-789",
            "study_name": "from_dict_study",
            "data_path": "data.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "symbols": ["BTCUSDT"],
        }

        job = OptimizationJob.from_dict(data)
        assert job.job_id == "test-789"
        assert job.study_name == "from_dict_study"


    def test_job_mlp_fields(self):
        """Job should support MLP-specific fields."""
        job = OptimizationJob(
            job_id="mlp-001",
            study_name="mlp_tune_btc",
            data_path="data/binance_bitcoin.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["BTC"],
            strategy_type="mlp_direction",
            asset="BTC",
            config_path="config/strategies/allocation.json",
        )

        assert job.strategy_type == "mlp_direction"
        assert job.asset == "BTC"
        assert job.config_path == "config/strategies/allocation.json"

    def test_job_default_strategy_type(self):
        """Job should default to regime strategy type."""
        job = OptimizationJob(
            job_id="test-default",
            study_name="test",
            data_path="data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["BTCUSDT"],
        )

        assert job.strategy_type == "regime"
        assert job.asset is None
        assert job.config_path is None

    def test_job_to_dict_includes_mlp_fields(self):
        """to_dict should include strategy_type, asset, config_path."""
        job = OptimizationJob(
            job_id="mlp-dict",
            study_name="mlp_tune",
            data_path="data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["ETH"],
            strategy_type="mlp_direction",
            asset="ETH",
            config_path="config/strategies/allocation.json",
        )

        data = job.to_dict()
        assert data["strategy_type"] == "mlp_direction"
        assert data["asset"] == "ETH"
        assert data["config_path"] == "config/strategies/allocation.json"

    def test_job_from_dict_with_mlp_fields(self):
        """from_dict should handle MLP fields."""
        data = {
            "job_id": "mlp-from",
            "study_name": "mlp_test",
            "data_path": "data.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "symbols": ["SOL"],
            "strategy_type": "mlp_direction",
            "asset": "SOL",
            "config_path": "config/strategies/allocation.json",
        }

        job = OptimizationJob.from_dict(data)
        assert job.strategy_type == "mlp_direction"
        assert job.asset == "SOL"


class TestJobStatus:
    """Test job status enum."""

    def test_status_values(self):
        """JobStatus should have expected values."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
