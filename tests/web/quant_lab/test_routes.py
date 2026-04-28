"""Tests for Quant Lab Flask routes."""
import base64
import re
import os
import json
import pytest
from unittest.mock import MagicMock, patch

pytest.importorskip("flask")

from flask import Flask
from web.quant_lab.routes import quant_lab_bp, build_suggested_study_name


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

    def test_index_requires_auth(self, client):
        """GET /quant-lab/ should require auth."""
        response = client.get('/quant-lab/')
        assert response.status_code == 401

    def test_index_returns_200_with_auth(self, client, auth_headers):
        """GET /quant-lab/ should return 200 with auth."""
        response = client.get('/quant-lab/', headers=auth_headers)
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

    def test_search_space_is_regime_only(self, client, auth_headers):
        """GET /quant-lab/api/search-space should expose regime-only options."""
        response = client.get('/quant-lab/api/search-space', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data['strategy_types'] == ['regime']
        assert data['llm_optimization_supported'] is False
        assert 'llm_direction' not in data

    def test_create_non_regime_experiment_rejected(self, client, auth_headers):
        """POST /quant-lab/api/experiments rejects removed strategy types."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "llm_btc_tune",
            "strategy_type": "llm_direction",
            "symbols": ["BTC"],
            "data_path": "data/binance_bitcoin.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "max_trials": 10,
        }, headers=auth_headers)
        assert response.status_code == 400
        data = response.get_json()
        assert 'regime optimization' in data['error'].lower()

    def test_create_regime_experiment_without_asset_is_allowed(self, client, auth_headers):
        """Regime experiment should not require asset."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "regime_no_asset",
            "strategy_type": "regime",
            "data_path": "data/binance_bitcoin.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "symbols": ["BTC"],
            "max_trials": 10,
        }, headers=auth_headers)
        assert response.status_code in [200, 201, 500]

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
            "strategy_type": "regime",
            "asset": "DOGE",
            "data_path": "data/binance_bitcoin.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "max_trials": 10,
        }, headers=auth_headers)
        assert response.status_code == 400

    def test_build_suggested_study_name_ignores_removed_strategy_type(self):
        """Study name suggestions should now normalize to regime-only naming."""
        study_name = build_suggested_study_name("llm_direction", "ETH")
        assert re.match(r"^regime_\d{8}_\d{6}$", study_name)

    def test_build_suggested_study_name_regime(self):
        """Regime study names should include datetime postfix."""
        study_name = build_suggested_study_name("regime")
        assert re.match(r"^regime_\d{8}_\d{6}$", study_name)

    @patch("rq.Queue")
    @patch("redis.Redis.from_url")
    def test_create_experiment_auto_suggests_study_name_when_missing(
        self,
        mock_redis_from_url,
        mock_queue_cls,
        client,
        auth_headers,
    ):
        """Missing study_name should be auto-generated with datetime postfix."""
        redis_conn = MagicMock()
        mock_redis_from_url.return_value = redis_conn

        queue = MagicMock()
        rq_job = MagicMock()
        rq_job.id = "rq-job-1"
        queue.enqueue.return_value = rq_job
        queue.job_ids = []
        mock_queue_cls.return_value = queue

        response = client.post('/quant-lab/api/experiments', json={
            "strategy_type": "regime",
            "symbols": ["BTC"],
            "data_path": "data/binance_bitcoin.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "max_trials": 10,
        }, headers=auth_headers)

        assert response.status_code == 201
        hset_mapping = redis_conn.hset.call_args.kwargs["mapping"]
        suggested_name = json.loads(hset_mapping["study_name"])
        assert re.match(r"^regime_\d{8}_\d{6}$", suggested_name)

    @patch("rq.Queue")
    @patch("redis.Redis.from_url")
    def test_active_jobs_moves_failed_to_completed_jobs(
        self,
        mock_redis_from_url,
        mock_queue_cls,
        client,
        auth_headers,
    ):
        """Failed jobs should move to completed_jobs and leave active_jobs."""
        redis_conn = MagicMock()
        redis_conn.keys.return_value = [b"quant_lab:job:test-job-1"]
        redis_conn.hgetall.return_value = {
            b"status": b"\"failed\"",
            b"study_name": b"\"test_0213\"",
            b"error": b"\"boom\"",
            b"updated_at": b"\"2026-02-13T10:00:00\"",
        }
        mock_redis_from_url.return_value = redis_conn

        queue = MagicMock()
        queue.job_ids = []
        mock_queue_cls.return_value = queue

        response = client.get("/quant-lab/api/active-jobs", headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("active_jobs", []) == []
        completed = data.get("completed_jobs", [])
        assert len(completed) == 1
        assert completed[0]["status"] == "failed"
        assert completed[0]["study_name"] == "test_0213"
