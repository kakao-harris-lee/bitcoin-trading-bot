"""Tests for V35 API endpoints."""
import base64
import os
import pytest
from flask import Flask
from unittest.mock import patch, MagicMock

from web.quant_lab.routes import quant_lab_bp


@pytest.fixture(autouse=True)
def setup_env():
    """Set up environment variables for tests."""
    os.environ["DASHBOARD_PASSWORD"] = "testpass"
    os.environ["DASHBOARD_USERNAME"] = "admin"
    yield
    # Cleanup is handled by pytest


@pytest.fixture
def client():
    """Create Flask test client."""
    app = Flask(__name__)
    app.register_blueprint(quant_lab_bp, url_prefix="/quant-lab")
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def auth_headers():
    """Create authentication headers."""
    credentials = base64.b64encode(b"admin:testpass").decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}


class TestV35StrategiesEndpoint:
    """Tests for /api/v35/strategies endpoint."""

    def test_returns_401_without_auth(self, client):
        """Endpoint requires authentication."""
        response = client.get("/quant-lab/api/v35/strategies")
        assert response.status_code == 401

    def test_returns_200(self, client, auth_headers):
        """Endpoint returns 200 OK with auth."""
        response = client.get("/quant-lab/api/v35/strategies", headers=auth_headers)
        assert response.status_code == 200

    def test_returns_strategy_list(self, client, auth_headers):
        """Response contains list of strategies."""
        response = client.get("/quant-lab/api/v35/strategies", headers=auth_headers)
        data = response.get_json()

        assert "strategies" in data
        assert isinstance(data["strategies"], list)
        assert len(data["strategies"]) == 6

    def test_contains_all_v35_variants(self, client, auth_headers):
        """All V35 variants are listed."""
        response = client.get("/quant-lab/api/v35/strategies", headers=auth_headers)
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

    def test_includes_default_strategy(self, client, auth_headers):
        """Response includes default strategy recommendation."""
        response = client.get("/quant-lab/api/v35/strategies", headers=auth_headers)
        data = response.get_json()

        assert "default" in data
        assert data["default"] == "v35_long_v2"


class TestV35ParamGroupsEndpoint:
    """Tests for /api/v35/param-groups/<strategy> endpoint."""

    def test_returns_200_for_valid_strategy(self, client, auth_headers):
        """Endpoint returns 200 for valid strategy."""
        response = client.get("/quant-lab/api/v35/param-groups/v35_long_v2", headers=auth_headers)
        assert response.status_code == 200

    def test_returns_404_for_invalid_strategy(self, client, auth_headers):
        """Endpoint returns 404 for unknown strategy."""
        response = client.get("/quant-lab/api/v35/param-groups/unknown_strategy", headers=auth_headers)
        assert response.status_code == 404

    def test_returns_correct_groups(self, client, auth_headers):
        """Response contains correct parameter groups."""
        response = client.get("/quant-lab/api/v35/param-groups/v35_long_v2", headers=auth_headers)
        data = response.get_json()

        assert "groups" in data
        assert "risk" in data["groups"]
        assert "sizing" in data["groups"]
        assert "trailing" in data["groups"]

    def test_returns_param_definitions(self, client, auth_headers):
        """Response contains parameter definitions."""
        response = client.get("/quant-lab/api/v35/param-groups/v35_long_v2", headers=auth_headers)
        data = response.get_json()

        assert "params" in data
        assert "risk" in data["params"]
        assert "stop_loss_pct" in data["params"]["risk"]

    def test_core_overlay_strategy_includes_core_group(self, client, auth_headers):
        """Core overlay strategy includes core_overlay group."""
        response = client.get("/quant-lab/api/v35/param-groups/tuned_v35_long_v2_core_overlay", headers=auth_headers)
        data = response.get_json()

        assert "core_overlay" in data["groups"]


class TestV35SearchSpaceEndpoint:
    """Tests for /api/v35/search-space/<strategy> endpoint."""

    def test_returns_200_for_valid_strategy(self, client, auth_headers):
        """Endpoint returns 200 for valid strategy."""
        response = client.get("/quant-lab/api/v35/search-space/v35_long_v2", headers=auth_headers)
        assert response.status_code == 200

    def test_returns_search_space(self, client, auth_headers):
        """Response contains search space definition."""
        response = client.get("/quant-lab/api/v35/search-space/v35_long_v2", headers=auth_headers)
        data = response.get_json()

        assert "search_space" in data
        assert "risk" in data["search_space"]
        assert "stop_loss_pct" in data["search_space"]["risk"]


class TestV35OptimizeEndpoint:
    """Tests for /api/v35/optimize endpoint."""

    def test_requires_strategy(self, client, auth_headers):
        """Endpoint requires strategy parameter."""
        response = client.post(
            "/quant-lab/api/v35/optimize",
            json={},
            content_type="application/json",
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_rejects_invalid_strategy(self, client, auth_headers):
        """Endpoint rejects unknown strategy."""
        response = client.post(
            "/quant-lab/api/v35/optimize",
            json={"strategy": "unknown_strategy"},
            content_type="application/json",
            headers=auth_headers,
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "available" in data

    @patch("redis.Redis")
    @patch("rq.Queue")
    def test_queues_job_for_valid_request(self, mock_queue_cls, mock_redis_cls, client, auth_headers):
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
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["job_id"] == "test-job-id"
        assert data["strategy"] == "v35_long_v2"
        assert data["status"] == "queued"

    @patch("redis.Redis")
    @patch("rq.Queue")
    def test_uses_default_param_groups(self, mock_queue_cls, mock_redis_cls, client, auth_headers):
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
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "param_groups" in data
        assert len(data["param_groups"]) > 0


class TestSecurityValidation:
    """Tests for security validation functions."""

    def test_sanitize_strategy_name_rejects_path_traversal(self, client, auth_headers):
        """Sanitize rejects path traversal attempts."""
        from web.quant_lab.routes import sanitize_strategy_name
        import pytest

        with pytest.raises(ValueError):
            sanitize_strategy_name("../../../etc/passwd")

        with pytest.raises(ValueError):
            sanitize_strategy_name("strategy/name")

        with pytest.raises(ValueError):
            sanitize_strategy_name(".hidden")

    def test_sanitize_strategy_name_accepts_valid_names(self, client, auth_headers):
        """Sanitize accepts valid strategy names."""
        from web.quant_lab.routes import sanitize_strategy_name

        assert sanitize_strategy_name("v35_long_v2") == "v35_long_v2"
        assert sanitize_strategy_name("tuned-strategy-1") == "tuned-strategy-1"
        assert sanitize_strategy_name("MyStrategy123") == "MyStrategy123"

    def test_validate_data_path_rejects_traversal(self, client, auth_headers):
        """Validate data path rejects path traversal."""
        from web.quant_lab.routes import validate_data_path
        import pytest

        with pytest.raises(ValueError):
            validate_data_path("../../../etc/passwd")

        with pytest.raises(ValueError):
            validate_data_path("/etc/passwd")

    def test_n_trials_limited_to_max(self, client, auth_headers):
        """n_trials is capped at MAX_TRIALS."""
        from web.quant_lab.routes import MAX_TRIALS

        with patch("redis.Redis"), patch("rq.Queue") as mock_queue:
            mock_job = MagicMock()
            mock_job.id = "test-job-id"
            mock_queue.return_value.enqueue.return_value = mock_job

            response = client.post(
                "/quant-lab/api/v35/optimize",
                json={
                    "strategy": "v35_long_v2",
                    "n_trials": 999999,  # Way over limit
                },
                content_type="application/json",
                headers=auth_headers,
            )

            assert response.status_code == 201
            data = response.get_json()
            # n_trials should be capped
            assert data["n_trials"] <= MAX_TRIALS
