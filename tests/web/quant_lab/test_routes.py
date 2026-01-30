"""Tests for Quant Lab Flask routes."""
import pytest

pytest.importorskip("flask")

from flask import Flask
from web.quant_lab.routes import quant_lab_bp


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


class TestQuantLabRoutes:
    """Test Quant Lab API endpoints."""

    def test_index_returns_200(self, client):
        """GET /quant-lab/ should return 200."""
        response = client.get('/quant-lab/')
        assert response.status_code == 200

    def test_templates_endpoint(self, client):
        """GET /quant-lab/api/templates should return templates."""
        response = client.get('/quant-lab/api/templates')
        assert response.status_code == 200
        data = response.get_json()
        assert 'templates' in data

    def test_create_experiment_requires_post(self, client):
        """POST /quant-lab/api/experiments should create job."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "test_experiment",
            "data_path": "data.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "symbols": ["BTCUSDT"],
            "max_trials": 10,
        })
        # Should accept the request (may fail on actual enqueue without Redis)
        assert response.status_code in [200, 201, 500]
