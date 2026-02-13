"""Tests for Quant Lab Flask routes."""
import base64
import os
import pytest

pytest.importorskip("flask")

from flask import Flask
from web.quant_lab.routes import quant_lab_bp


@pytest.fixture(autouse=True)
def setup_env():
    """Set up environment variables for tests."""
    # Save original values
    orig_password = os.environ.get("DASHBOARD_PASSWORD")
    orig_username = os.environ.get("DASHBOARD_USERNAME")

    # Set test values
    os.environ["DASHBOARD_PASSWORD"] = "testpass"
    os.environ["DASHBOARD_USERNAME"] = "admin"
    yield

    # Restore original values
    if orig_password is not None:
        os.environ["DASHBOARD_PASSWORD"] = orig_password
    elif "DASHBOARD_PASSWORD" in os.environ:
        del os.environ["DASHBOARD_PASSWORD"]

    if orig_username is not None:
        os.environ["DASHBOARD_USERNAME"] = orig_username
    elif "DASHBOARD_USERNAME" in os.environ:
        del os.environ["DASHBOARD_USERNAME"]


@pytest.fixture
def app():
    """Create test Flask app."""
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(quant_lab_bp, url_prefix='/quant-lab')
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def auth_headers():
    """Create authentication headers."""
    credentials = base64.b64encode(b"admin:testpass").decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}


class TestQuantLabRoutes:
    """Test Quant Lab API endpoints."""

    def test_index_returns_200(self, client):
        """GET /quant-lab/ should return 200."""
        response = client.get('/quant-lab/')
        assert response.status_code == 200

    def test_templates_endpoint(self, client, auth_headers):
        """GET /quant-lab/api/templates should return templates."""
        response = client.get('/quant-lab/api/templates', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert 'templates' in data

    def test_create_experiment_requires_post(self, client, auth_headers):
        """POST /quant-lab/api/experiments should create job."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "test_experiment",
            "data_path": "data/binance_bitcoin.db",  # Valid path within data/
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "symbols": ["BTCUSDT"],
            "max_trials": 10,
        }, headers=auth_headers)
        # Should accept the request (may fail on actual enqueue without Redis)
        assert response.status_code in [200, 201, 500]

    def test_search_space_includes_mlp(self, client, auth_headers):
        """GET /quant-lab/api/search-space should include mlp_direction params."""
        response = client.get('/quant-lab/api/search-space', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert 'mlp_direction' in data
        mlp = data['mlp_direction']
        assert 'entry_params' in mlp
        assert 'exit_params' in mlp
        assert 'ensemble_params' in mlp
        assert 'adapter_params' in mlp

    def test_create_mlp_experiment(self, client, auth_headers):
        """POST /quant-lab/api/experiments with mlp_direction type."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "mlp_btc_tune",
            "strategy_type": "mlp_direction",
            "asset": "BTC",
            "data_path": "data/binance_bitcoin.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "max_trials": 10,
        }, headers=auth_headers)
        # Should accept (may fail on Redis enqueue)
        assert response.status_code in [200, 201, 500]

    def test_create_mlp_experiment_requires_asset(self, client, auth_headers):
        """MLP experiment without asset should return 400."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "mlp_no_asset",
            "strategy_type": "mlp_direction",
            "data_path": "data/binance_bitcoin.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "max_trials": 10,
        }, headers=auth_headers)
        assert response.status_code == 400
        data = response.get_json()
        assert "asset" in data["error"].lower()

    def test_create_experiment_invalid_strategy_type(self, client, auth_headers):
        """Invalid strategy_type should return 400."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "invalid_type",
            "strategy_type": "invalid",
            "data_path": "data/binance_bitcoin.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "symbols": ["BTC"],
            "max_trials": 10,
        }, headers=auth_headers)
        assert response.status_code == 400

    def test_create_experiment_invalid_asset(self, client, auth_headers):
        """Invalid asset should return 400."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "invalid_asset",
            "strategy_type": "mlp_direction",
            "asset": "DOGE",
            "data_path": "data/binance_bitcoin.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "max_trials": 10,
        }, headers=auth_headers)
        assert response.status_code == 400
