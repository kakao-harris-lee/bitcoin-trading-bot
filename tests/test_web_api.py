"""
Test dashboard API endpoints.
"""

import pytest
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from web.app import app


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_multi_asset_status():
    """Sample multi-asset engine status."""
    return {
        'timestamp': '2025-01-03T10:00:00',
        'mode': 'paper',
        'engine': 'multi-asset',
        'iteration_count': 100,
        'signal_count': 5,
        'assets': {
            'BTC': {
                'regime': 'BULL',
                'binance_price': 100000,
                'position_active': True,
                'position_qty': 0.1,
            },
            'ETH': {
                'regime': 'SIDEWAYS',
                'binance_price': 3500,
                'position_active': False,
                'position_qty': 0,
            },
        },
        'portfolio': {
            'total_capital_usdt': 10000,
            'total_value_usdt': 10500,
            'cash_usdt': 5000,
            'exposure_pct': 50,
            'total_unrealized_pnl': 500,
            'assets': {
                'BTC': {
                    'allocated_usdt': 4000,
                    'position_value_usdt': 4200,
                },
                'ETH': {
                    'allocated_usdt': 1000,
                    'position_value_usdt': 0,
                },
            },
        },
    }


@pytest.fixture
def mock_trading_log():
    """Sample trading log."""
    return {
        'trades': [
            {
                'timestamp': '2025-01-03T09:00:00',
                'action': 'BUY',
                'price': 100000,
                'quantity': 0.1,
                'pnl': 0,
            },
            {
                'timestamp': '2025-01-03T10:00:00',
                'action': 'SELL',
                'price': 102000,
                'quantity': 0.1,
                'pnl': 200,
            },
        ],
        'signals': [
            {
                'timestamp': '2025-01-03T09:00:00',
                'signal': 'LONG',
                'regime': 'BULL',
                'confidence': 0.8,
            },
        ],
        'statistics': {
            'return_pct': 5.2,
            'total_trades': 10,
            'win_rate': 0.6,
        },
    }


class TestRootEndpoints:
    """Test root and common file endpoints."""

    def test_root_returns_404(self, client):
        """Root path should return 404 for security."""
        response = client.get('/')
        assert response.status_code == 404

    def test_common_files_blocked(self, client):
        """Common file names should be blocked."""
        for path in ['/index.html', '/default.html', '/dashboard.html']:
            response = client.get(path)
            assert response.status_code == 404, f"{path} should return 404"


class TestDashboardAuth:
    """Test dashboard authentication."""

    def test_dashboard_requires_totp(self, client):
        """Dashboard should require TOTP authentication."""
        response = client.get('/btc-dashboard')
        # Should return TOTP form (200) or redirect
        assert response.status_code == 200
        assert b'Dashboard Access' in response.data or b'TOTP' in response.data

    @patch('web.app.verify_totp')
    def test_dashboard_with_valid_totp(self, mock_verify, client):
        """Dashboard should load with valid TOTP."""
        mock_verify.return_value = True
        response = client.get('/btc-dashboard?code=123456')
        # Should either render dashboard or return form
        assert response.status_code == 200


class TestStatusAPI:
    """Test /api/status endpoint."""

    @patch('web.app.load_multi_asset_status')
    @patch('web.app.load_allocation_config')
    def test_status_no_data(self, mock_alloc, mock_status, client):
        """Status should return 404 when no engine status."""
        mock_status.return_value = None
        mock_alloc.return_value = {}

        response = client.get('/api/status')
        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data

    @patch('web.app.load_multi_asset_status')
    @patch('web.app.load_allocation_config')
    def test_status_with_data(self, mock_alloc, mock_status, client, mock_multi_asset_status):
        """Status should return proper data when available."""
        mock_status.return_value = mock_multi_asset_status
        mock_alloc.return_value = {
            'assets': {
                'BTC': {'enabled': True, 'alpha_ratio': 0.7},
                'ETH': {'enabled': True, 'alpha_ratio': 0.3},
            }
        }

        response = client.get('/api/status')
        assert response.status_code == 200
        data = json.loads(response.data)

        # Check structure
        assert 'timestamp' in data
        assert 'mode' in data
        assert 'assets' in data
        assert 'portfolio' in data

        # Check assets (API returns keys like "BTC_binance")
        assert 'BTC_binance' in data['assets']
        assert data['assets']['BTC_binance']['regime'] == 'BULL'
        assert data['assets']['BTC_binance']['exchange'] == 'binance'


class TestKillSwitchAPI:
    """Test /api/kill_switch endpoints."""

    @patch('web.app.KILL_SWITCH_FILE')
    def test_kill_switch_status_inactive(self, mock_file, client):
        """Kill switch status when inactive."""
        mock_file.exists.return_value = False
        mock_file.__str__ = lambda self: '/data/KILL_SWITCH'

        response = client.get('/api/kill_switch/status')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['active'] == False

    @patch('web.app.KILL_SWITCH_FILE')
    def test_kill_switch_status_active(self, mock_file, client):
        """Kill switch status when active."""
        mock_file.exists.return_value = True
        mock_file.__str__ = lambda self: '/data/KILL_SWITCH'

        response = client.get('/api/kill_switch/status')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['active'] == True

    def test_kill_switch_on_requires_token(self, client):
        """Kill switch on should require admin token."""
        response = client.post('/api/kill_switch/on')
        assert response.status_code == 403
        data = json.loads(response.data)
        assert data['error'] == 'forbidden'

    def test_kill_switch_off_requires_token(self, client):
        """Kill switch off should require admin token."""
        response = client.post('/api/kill_switch/off')
        assert response.status_code == 403


class TestTradesAPI:
    """Test /api/trades/<exchange> endpoint."""

    @patch('web.app.load_trading_log')
    def test_trades_no_data(self, mock_load, client):
        """Trades should return 404 when no log."""
        mock_load.return_value = None

        response = client.get('/api/trades/binance')
        assert response.status_code == 404

    @patch('web.app.load_trading_log')
    def test_trades_with_data(self, mock_load, client, mock_trading_log):
        """Trades should return trade data."""
        mock_load.return_value = mock_trading_log

        response = client.get('/api/trades/binance')
        assert response.status_code == 200
        data = json.loads(response.data)

        assert data['exchange'] == 'binance'
        assert 'trades' in data
        assert len(data['trades']) == 2
        assert data['total_count'] == 2


class TestSignalsAPI:
    """Test /api/signals/<exchange> endpoint."""

    @patch('web.app.load_trading_log')
    def test_signals_no_data(self, mock_load, client):
        """Signals should return 404 when no log."""
        mock_load.return_value = None

        response = client.get('/api/signals/binance')
        assert response.status_code == 404

    @patch('web.app.load_trading_log')
    def test_signals_with_data(self, mock_load, client, mock_trading_log):
        """Signals should return signal data."""
        mock_load.return_value = mock_trading_log

        response = client.get('/api/signals/binance')
        assert response.status_code == 200
        data = json.loads(response.data)

        assert data['exchange'] == 'binance'
        assert 'signals' in data
        assert len(data['signals']) == 1


class TestStatisticsAPI:
    """Test /api/statistics endpoint."""

    @patch('web.app.load_trading_log')
    def test_statistics_with_data(self, mock_load, client, mock_trading_log):
        """Statistics should return binance stats."""
        mock_load.return_value = mock_trading_log

        response = client.get('/api/statistics')
        assert response.status_code == 200
        data = json.loads(response.data)

        assert 'binance' in data
        assert data['binance']['return_pct'] == 5.2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
