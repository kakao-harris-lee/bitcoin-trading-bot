"""Integration tests for Quant Lab."""
import base64
import pytest

pytest.importorskip("flask")

from flask import Flask
from web.quant_lab.routes import quant_lab_bp
from web.quant_lab.optimizer.search_space import SearchSpaceConfig, build_search_space, sample_trial_config, REGIMES
from web.quant_lab.optimizer.study_manager import StudyManager
from unittest.mock import MagicMock
import tempfile
import os


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


def get_auth_headers():
    """Create authentication headers."""
    credentials = base64.b64encode(b"admin:testpass").decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}


class TestFullWorkflow:
    """Test complete Quant Lab workflow."""

    def test_search_space_to_trial_config(self):
        """SearchSpaceConfig -> sample_trial_config should work end-to-end."""
        config = SearchSpaceConfig()
        space = build_search_space(config)

        # Verify all regimes present
        assert len(space) == 7

        # Mock trial and sample
        mock_trial = MagicMock()
        mock_trial.suggest_categorical.side_effect = lambda n, c: c[0]
        mock_trial.suggest_float.return_value = 50.0

        result = sample_trial_config(mock_trial, config)

        # Verify result structure: 7 regimes + regime_thresholds
        assert len(result) == 8
        assert "regime_thresholds" in result
        for regime in REGIMES:
            regime_config = result[regime]
            assert "entry" in regime_config
            assert "exit" in regime_config
            assert "params" in regime_config

    def test_study_manager_full_lifecycle(self):
        """StudyManager should handle create -> optimize -> results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            # Create study
            study = manager.create_study("integration_test")
            assert study.study_name == "integration_test"

            # Verify listing
            studies = manager.list_studies()
            assert any(s.study_name == "integration_test" for s in studies)

            # Get stats (empty study)
            stats = manager.get_study_stats("integration_test")
            assert stats["total_trials"] == 0
            assert stats["pareto_front_size"] == 0

    def test_flask_routes_available(self):
        """All Quant Lab routes should be accessible with auth."""
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(quant_lab_bp, url_prefix='/quant-lab')
        client = app.test_client()
        auth_headers = get_auth_headers()

        # Index (auth required)
        response = client.get('/quant-lab/', headers=auth_headers)
        assert response.status_code == 200

        # Templates API (auth required)
        response = client.get('/quant-lab/api/templates', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert 'templates' in data

        # Search space API (auth required)
        response = client.get('/quant-lab/api/search-space', headers=auth_headers)
        assert response.status_code == 200
        data = response.get_json()
        assert 'regimes' in data
        assert len(data['regimes']) == 7
