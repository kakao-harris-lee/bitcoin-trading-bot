"""Tests for V35 API endpoints."""
import pytest
from flask import Flask
from unittest.mock import patch, MagicMock

from web.quant_lab.routes import quant_lab_bp


@pytest.fixture
def client():
    """Create Flask test client."""
    app = Flask(__name__)
    app.register_blueprint(quant_lab_bp, url_prefix="/quant-lab")
    app.config["TESTING"] = True
    return app.test_client()


class TestV35StrategiesEndpoint:
    """Tests for /api/v35/strategies endpoint."""

    def test_returns_200(self, client):
        """Endpoint returns 200 OK."""
        response = client.get("/quant-lab/api/v35/strategies")
        assert response.status_code == 200

    def test_returns_strategy_list(self, client):
        """Response contains list of strategies."""
        response = client.get("/quant-lab/api/v35/strategies")
        data = response.get_json()

        assert "strategies" in data
        assert isinstance(data["strategies"], list)
        assert len(data["strategies"]) == 6

    def test_contains_all_v35_variants(self, client):
        """All V35 variants are listed."""
        response = client.get("/quant-lab/api/v35/strategies")
        data = response.get_json()

        expected = [
            "v35_long",
            "v35_long_v2",
            "tuned_v35_long_v2_growth",
            "tuned_v35_long_v2_hold",
            "tuned_v35_long_v2_core_overlay",
            "tuned_v35_long_v2_core_overlay_v2",
        ]
        for strategy in expected:
            assert strategy in data["strategies"]

    def test_includes_default_strategy(self, client):
        """Response includes default strategy recommendation."""
        response = client.get("/quant-lab/api/v35/strategies")
        data = response.get_json()

        assert "default" in data
        assert data["default"] == "v35_long_v2"


class TestV35ParamGroupsEndpoint:
    """Tests for /api/v35/param-groups/<strategy> endpoint."""

    def test_returns_200_for_valid_strategy(self, client):
        """Endpoint returns 200 for valid strategy."""
        response = client.get("/quant-lab/api/v35/param-groups/v35_long_v2")
        assert response.status_code == 200

    def test_returns_404_for_invalid_strategy(self, client):
        """Endpoint returns 404 for unknown strategy."""
        response = client.get("/quant-lab/api/v35/param-groups/unknown_strategy")
        assert response.status_code == 404

    def test_returns_correct_groups(self, client):
        """Response contains correct parameter groups."""
        response = client.get("/quant-lab/api/v35/param-groups/v35_long_v2")
        data = response.get_json()

        assert "groups" in data
        assert "risk" in data["groups"]
        assert "sizing" in data["groups"]
        assert "trailing" in data["groups"]

    def test_returns_param_definitions(self, client):
        """Response contains parameter definitions."""
        response = client.get("/quant-lab/api/v35/param-groups/v35_long_v2")
        data = response.get_json()

        assert "params" in data
        assert "risk" in data["params"]
        assert "stop_loss_pct" in data["params"]["risk"]

    def test_core_overlay_strategy_includes_core_group(self, client):
        """Core overlay strategy includes core_overlay group."""
        response = client.get("/quant-lab/api/v35/param-groups/tuned_v35_long_v2_core_overlay")
        data = response.get_json()

        assert "core_overlay" in data["groups"]


class TestV35SearchSpaceEndpoint:
    """Tests for /api/v35/search-space/<strategy> endpoint."""

    def test_returns_200_for_valid_strategy(self, client):
        """Endpoint returns 200 for valid strategy."""
        response = client.get("/quant-lab/api/v35/search-space/v35_long_v2")
        assert response.status_code == 200

    def test_returns_search_space(self, client):
        """Response contains search space definition."""
        response = client.get("/quant-lab/api/v35/search-space/v35_long_v2")
        data = response.get_json()

        assert "search_space" in data
        assert "risk" in data["search_space"]
        assert "stop_loss_pct" in data["search_space"]["risk"]


class TestV35OptimizeEndpoint:
    """Tests for /api/v35/optimize endpoint."""

    def test_requires_strategy(self, client):
        """Endpoint requires strategy parameter."""
        response = client.post(
            "/quant-lab/api/v35/optimize",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_rejects_invalid_strategy(self, client):
        """Endpoint rejects unknown strategy."""
        response = client.post(
            "/quant-lab/api/v35/optimize",
            json={"strategy": "unknown_strategy"},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "available" in data

    @patch("redis.Redis")
    @patch("rq.Queue")
    def test_queues_job_for_valid_request(self, mock_queue_cls, mock_redis_cls, client):
        """Valid request queues optimization job."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_queue.enqueue.return_value = mock_job
        mock_queue_cls.return_value = mock_queue

        response = client.post(
            "/quant-lab/api/v35/optimize",
            json={
                "strategy": "v35_long_v2",
                "param_groups": ["risk", "sizing"],
                "n_trials": 50,
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["job_id"] == "test-job-id"
        assert data["strategy"] == "v35_long_v2"
        assert data["status"] == "queued"

    @patch("redis.Redis")
    @patch("rq.Queue")
    def test_uses_default_param_groups(self, mock_queue_cls, mock_redis_cls, client):
        """Uses strategy default param groups if not specified."""
        mock_queue = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_queue.enqueue.return_value = mock_job
        mock_queue_cls.return_value = mock_queue

        response = client.post(
            "/quant-lab/api/v35/optimize",
            json={"strategy": "v35_long_v2"},
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "param_groups" in data
        assert len(data["param_groups"]) > 0
