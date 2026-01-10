"""
test_metrics_api.py
Tests for the real-time trading metrics dashboard API endpoints.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from web.app import app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_metrics_service():
    """Mock the metrics service with sample data."""
    sample_data = {
        'timestamp': datetime.now().isoformat(),
        'upbit': {
            'exchange': 'upbit',
            'mode': 'paper',
            'strategy': 'va02',
            'regime': 'BEAR',
            'market_state': 'BEAR_STRONG',
            'current_price': 128000000.0,
            'position_active': True,
            'position_qty': 0.019,
            'entry_price': 128073000.0,
            'unrealized_pnl': -15000.0,
            'unrealized_pnl_pct': -0.06,
            'total_value': 10000000.0,
            'last_updated': datetime.now().isoformat(),
            'last_decision': {
                'timestamp': datetime.now().isoformat(),
                'strategy': 'va02',
                'action': 'hold',
                'reason': 'VA02_HOLDING_S',
                'regime': 'BEAR',
                'market_state': 'BEAR_STRONG',
                'indicators': {
                    'rsi': 36.5,
                    'mfi': 35.9,
                    'adx': 34.4,
                    'close': 128000000.0,
                    'score': 32,
                    'tier': 'S'
                }
            }
        },
        'binance': None,
        'recent_decisions': [
            {
                'timestamp': datetime.now().isoformat(),
                'strategy': 'va02',
                'action': 'hold',
                'reason': 'VA02_HOLDING_S',
                'exchange': 'upbit'
            }
        ],
        'connection_status': [
            {
                'exchange': 'upbit',
                'connected': True,
                'last_heartbeat': datetime.now().isoformat(),
                'is_stale': False,
                'stale_seconds': 5
            },
            {
                'exchange': 'binance',
                'connected': False,
                'last_heartbeat': None,
                'is_stale': True,
                'stale_seconds': None
            }
        ]
    }
    return sample_data


class TestMetricsRealtimeEndpoint:
    """Tests for /api/metrics/realtime endpoint."""

    def test_realtime_endpoint_returns_data(self, client, mock_metrics_service):
        """Test that the endpoint returns dashboard state when data is available."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_dashboard_state.return_value = mock_metrics_service

            response = client.get('/api/metrics/realtime')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'timestamp' in data
            assert 'upbit' in data
            assert 'connection_status' in data

    def test_realtime_endpoint_returns_404_when_no_data(self, client):
        """Test that the endpoint returns 404 when no trading data available."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_dashboard_state.return_value = {
                'timestamp': datetime.now().isoformat(),
                'upbit': None,
                'binance': None,
                'recent_decisions': [],
                'connection_status': []
            }

            response = client.get('/api/metrics/realtime')

            assert response.status_code == 404
            data = json.loads(response.data)
            assert 'error' in data

    def test_realtime_endpoint_handles_service_error(self, client):
        """Test that the endpoint handles service errors gracefully."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_dashboard_state.side_effect = Exception('Service error')

            response = client.get('/api/metrics/realtime')

            assert response.status_code == 500
            data = json.loads(response.data)
            assert 'error' in data

    def test_realtime_endpoint_returns_position_data(self, client, mock_metrics_service):
        """Test that position data is correctly returned."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_dashboard_state.return_value = mock_metrics_service

            response = client.get('/api/metrics/realtime')

            assert response.status_code == 200
            data = json.loads(response.data)

            upbit = data.get('upbit')
            assert upbit is not None
            assert upbit['position_active'] is True
            assert upbit['position_qty'] > 0
            assert 'unrealized_pnl' in upbit
            assert 'unrealized_pnl_pct' in upbit

    def test_realtime_endpoint_returns_regime_data(self, client, mock_metrics_service):
        """Test that market regime data is correctly returned."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_dashboard_state.return_value = mock_metrics_service

            response = client.get('/api/metrics/realtime')

            assert response.status_code == 200
            data = json.loads(response.data)

            upbit = data.get('upbit')
            assert upbit is not None
            assert upbit['regime'] == 'BEAR'
            assert upbit['market_state'] == 'BEAR_STRONG'


class TestDecisionHistoryEndpoint:
    """Tests for /api/metrics/decisions endpoint."""

    def test_decisions_endpoint_returns_list(self, client):
        """Test that the endpoint returns a list of decisions."""
        sample_decisions = [
            {
                'timestamp': datetime.now().isoformat(),
                'strategy': 'va02',
                'action': 'hold',
                'reason': 'VA02_HOLDING_S',
                'exchange': 'upbit'
            }
        ]

        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_recent_decisions.return_value = sample_decisions

            response = client.get('/api/metrics/decisions')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'decisions' in data
            assert 'total_count' in data
            assert len(data['decisions']) == 1

    def test_decisions_endpoint_with_exchange_filter(self, client):
        """Test filtering by exchange."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_recent_decisions.return_value = []

            response = client.get('/api/metrics/decisions?exchange=upbit')

            assert response.status_code == 200
            mock_service.get_recent_decisions.assert_called_once()
            call_kwargs = mock_service.get_recent_decisions.call_args[1]
            assert call_kwargs['exchange'] == 'upbit'

    def test_decisions_endpoint_with_hours_filter(self, client):
        """Test filtering by hours."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_recent_decisions.return_value = []

            response = client.get('/api/metrics/decisions?hours=48')

            assert response.status_code == 200
            mock_service.get_recent_decisions.assert_called_once()
            call_kwargs = mock_service.get_recent_decisions.call_args[1]
            assert call_kwargs['hours'] == 48

    def test_decisions_endpoint_caps_hours_at_72(self, client):
        """Test that hours parameter is capped at 72."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_recent_decisions.return_value = []

            response = client.get('/api/metrics/decisions?hours=100')

            assert response.status_code == 200
            call_kwargs = mock_service.get_recent_decisions.call_args[1]
            assert call_kwargs['hours'] == 72

    def test_decisions_endpoint_caps_limit_at_200(self, client):
        """Test that limit parameter is capped at 200."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_recent_decisions.return_value = []

            response = client.get('/api/metrics/decisions?limit=500')

            assert response.status_code == 200
            call_kwargs = mock_service.get_recent_decisions.call_args[1]
            assert call_kwargs['limit'] == 200

    def test_decisions_endpoint_invalid_exchange(self, client):
        """Test that invalid exchange returns error."""
        response = client.get('/api/metrics/decisions?exchange=invalid')

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data


class TestMetricsPage:
    """Tests for /metrics page route."""

    def test_metrics_page_renders(self, client):
        """Test that the metrics page renders without error."""
        # Note: This test may require auth depending on configuration
        response = client.get('/metrics')

        # Should return either 200 (OK) or 401 (auth required)
        assert response.status_code in [200, 401]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
