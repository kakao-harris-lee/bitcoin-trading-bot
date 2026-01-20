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


class TestJobStatus:
    """Test job status enum."""

    def test_status_values(self):
        """JobStatus should have expected values."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
