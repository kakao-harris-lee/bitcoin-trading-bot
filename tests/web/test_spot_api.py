"""
Test spot trading API endpoints.
"""
import pytest
import json
import os
import base64
import sys
import importlib
from pathlib import Path
from unittest.mock import Mock, patch

# Skip this module when Flask is unavailable.
flask = pytest.importorskip("flask")

# Ensure project root (with local `web` package) is importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Ensure `patch("web.app.*")` resolves to the local dashboard module.
import web as web_pkg  # type: ignore
dashboard_app_module = importlib.import_module("web.app")
setattr(web_pkg, "app", dashboard_app_module)


@pytest.fixture(autouse=True)
def patch_auth():
    """Patch auth credentials for all tests."""
    with patch('web.app.DASHBOARD_PASSWORD', 'test'), \
         patch('web.app.DASHBOARD_USERNAME', 'admin'):
        yield


@pytest.fixture
def client(patch_auth):
    """Flask test client with auth."""
    from web.app import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_headers():
    """Basic auth headers."""
    import base64
    credentials = base64.b64encode(b'admin:test').decode('utf-8')
    return {'Authorization': f'Basic {credentials}'}


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis_mock = Mock()
    with patch('web.app.get_redis', return_value=redis_mock):
        yield redis_mock


class TestSummaryAPI:
    """Test /api/summary endpoint."""

    def test_get_summary_paper_mode(self, client, auth_headers, mock_redis):
        """Test summary endpoint in paper mode."""
        # Mock Redis responses
        mock_redis.hgetall.side_effect = lambda key: {
            'risk': {'mode': 'paper'},
            'account:paper': {'spot_balance': '10000'},
            'positions:BTC:spot': {'quantity': '0.1', 'entry_price': '100000', 'strategy': 'llm_spot'},
        }.get(key, {})

        # Mock price stream
        with patch('web.app.get_latest_prices') as mock_prices:
            mock_prices.return_value = {
                'BTCUSDT': 102000,
                'ETHUSDT': 4000,
                'SOLUSDT': 100,
            }

            response = client.get('/api/summary', headers=auth_headers)
            assert response.status_code == 200

            data = response.get_json()
            assert data['mode'] == 'paper'
            assert data['spot']['balance'] == 10000
            assert data['total_equity'] > 0
            assert isinstance(data['positions'], list)

    def test_get_summary_no_positions(self, client, auth_headers, mock_redis):
        """Test summary with no positions."""
        mock_redis.hgetall.side_effect = lambda key: {
            'risk': {'mode': 'paper'},
            'account:paper': {'spot_balance': '10000'},
        }.get(key, {})

        with patch('web.app.get_latest_prices') as mock_prices:
            mock_prices.return_value = {}

            response = client.get('/api/summary', headers=auth_headers)
            assert response.status_code == 200

            data = response.get_json()
            assert data['spot']['positions'] == 0
            assert len(data['positions']) == 0

    def test_get_summary_includes_dynamic_spot_symbol(self, client, auth_headers, mock_redis):
        """Summary should count spot positions outside default BTC/ETH/SOL symbols."""
        mock_redis.keys.return_value = ['positions:GRT:spot']
        mock_redis.hgetall.side_effect = lambda key: {
            'risk': {'mode': 'paper'},
            'account:paper': {'spot_balance': '191.09'},
            'positions:GRT:spot': {
                'quantity': '26935.24799083962',
                'entry_price': '0.028271304',
                'strategy': 'llm_direction_btc',
            },
        }.get(key, {})

        with patch('web.app.get_latest_prices') as mock_prices:
            mock_prices.return_value = {
                'GRTUSDT': 0.02827,
            }

            response = client.get('/api/summary', headers=auth_headers)
            assert response.status_code == 200

            data = response.get_json()
            assert data['spot']['positions'] == 1
            assert any(
                p['symbol'] == 'GRTUSDT' and p['market'] == 'spot'
                for p in data['positions']
            )


class TestSpotPositionsAPI:
    """Test /api/spot/positions endpoint."""

    def test_get_spot_positions_empty(self, client, auth_headers, mock_redis):
        """Test getting spot positions when none exist."""
        mock_redis.hgetall.return_value = {}

        with patch('web.app.get_latest_prices') as mock_prices:
            mock_prices.return_value = {}

            response = client.get('/api/spot/positions', headers=auth_headers)
            assert response.status_code == 200

            data = response.get_json()
            assert data['count'] == 0
            assert data['positions'] == []

    def test_get_spot_positions_with_data(self, client, auth_headers, mock_redis):
        """Test getting spot positions with data."""
        mock_redis.hgetall.side_effect = lambda key: {
            'positions:BTC:spot': {
                'quantity': '0.1',
                'entry_price': '100000',
                'strategy': 'llm_spot',
                'entry_time': '1700000000',
            },
            'positions:ETH:spot': {
                'quantity': '2.5',
                'entry_price': '3900',
                'strategy': 'short_spot',
                'entry_time': '1700000100',
            },
        }.get(key, {})

        with patch('web.app.get_latest_prices') as mock_prices:
            mock_prices.return_value = {
                'BTCUSDT': 102000,
                'ETHUSDT': 4000,
                'SOLUSDT': 100,
            }

            response = client.get('/api/spot/positions', headers=auth_headers)
            assert response.status_code == 200

            data = response.get_json()
            assert data['count'] == 2
            assert len(data['positions']) == 2

            # Check BTC position
            btc_pos = next((p for p in data['positions'] if p['symbol'] == 'BTCUSDT'), None)
            assert btc_pos is not None
            assert btc_pos['market'] == 'spot'
            assert btc_pos['quantity'] == 0.1
            assert btc_pos['entry_price'] == 100000
            assert btc_pos['current_price'] == 102000
            assert btc_pos['unrealized_pnl'] > 0  # Profit
            assert btc_pos['strategy'] == 'llm_spot'

            # Check ETH position
            eth_pos = next((p for p in data['positions'] if p['symbol'] == 'ETHUSDT'), None)
            assert eth_pos is not None
            assert eth_pos['quantity'] == 2.5
            assert eth_pos['unrealized_pnl'] > 0  # Profit

    def test_get_spot_positions_includes_dynamic_symbol(self, client, auth_headers, mock_redis):
        """Spot positions endpoint should include non-default symbols from Redis keys."""
        mock_redis.keys.return_value = ['positions:GRT:spot']
        mock_redis.hgetall.side_effect = lambda key: {
            'positions:GRT:spot': {
                'quantity': '26935.24799083962',
                'entry_price': '0.028271304',
                'strategy': 'llm_direction_btc',
                'entry_time': '1771696808878',
            },
        }.get(key, {})

        with patch('web.app.get_latest_prices') as mock_prices:
            mock_prices.return_value = {
                'GRTUSDT': 0.02827,
            }

            response = client.get('/api/spot/positions', headers=auth_headers)
            assert response.status_code == 200

            data = response.get_json()
            assert data['count'] == 1
            assert len(data['positions']) == 1
            assert data['positions'][0]['symbol'] == 'GRTUSDT'


class TestSpotBalanceAPI:
    """Test /api/spot/balance endpoint."""

    def test_get_spot_balance_paper_mode(self, client, auth_headers, mock_redis):
        """Test getting spot balance in paper mode."""
        mock_redis.hgetall.side_effect = lambda key: {
            'risk': {'mode': 'paper'},
            'account:paper': {'spot_balance': '12345.67'},
        }.get(key, {})

        response = client.get('/api/spot/balance', headers=auth_headers)
        assert response.status_code == 200

        data = response.get_json()
        assert data['mode'] == 'paper'
        assert data['balance'] == 12345.67

    def test_get_spot_balance_default(self, client, auth_headers, mock_redis):
        """Test getting spot balance with default value."""
        mock_redis.hgetall.side_effect = lambda key: {
            'risk': {},
            'account:paper': {},
        }.get(key, {})

        response = client.get('/api/spot/balance', headers=auth_headers)
        assert response.status_code == 200

        data = response.get_json()
        assert data['mode'] == 'paper'
        assert data['balance'] == 10000  # Default


class TestAuth:
    """Test authentication."""

    def test_summary_requires_auth(self, client):
        """Test that summary requires authentication."""
        response = client.get('/api/summary')
        assert response.status_code == 401

    def test_spot_positions_requires_auth(self, client):
        """Test that spot positions requires authentication."""
        response = client.get('/api/spot/positions')
        assert response.status_code == 401

    def test_spot_balance_requires_auth(self, client):
        """Test that spot balance requires authentication."""
        response = client.get('/api/spot/balance')
        assert response.status_code == 401

    def test_valid_auth(self, client, auth_headers, mock_redis):
        """Test that valid auth works."""
        mock_redis.hgetall.return_value = {'mode': 'paper'}

        with patch('web.app.get_latest_prices') as mock_prices:
            mock_prices.return_value = {}

            response = client.get('/api/spot/positions', headers=auth_headers)
            assert response.status_code == 200


class TestErrorHandling:
    """Test error handling."""

    def test_redis_error(self, client, auth_headers):
        """Test handling of Redis connection errors."""
        with patch('web.app.get_redis') as mock:
            mock.side_effect = Exception('Redis connection failed')

            response = client.get('/api/spot/balance', headers=auth_headers)
            assert response.status_code == 500

            data = response.get_json()
            assert 'error' in data
