"""
test_metrics_api.py
Tests for the real-time trading metrics dashboard API endpoints.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Skip entire module if Flask is not installed
pytest.importorskip("flask")

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
        'binance': {
            'exchange': 'binance',
            'mode': 'paper',
            'strategy': 'llm_direction_btc',
            'regime': 'BULL',
            'market_state': 'BULL_STRONG',
            'current_price': 95000.0,
            'position_active': True,
            'position_qty': 0.01,
            'entry_price': 94500.0,
            'unrealized_pnl': 50.0,
            'unrealized_pnl_pct': 0.53,
            'total_value': 10000.0,
            'last_updated': datetime.now().isoformat(),
            'last_decision': {
                'timestamp': datetime.now().isoformat(),
                'strategy': 'llm_direction_btc',
                'action': 'hold',
                'reason': 'HOLDING',
                'regime': 'BULL',
                'market_state': 'BULL_STRONG',
                'indicators': {
                    'rsi': 55.5,
                    'mfi': 58.9,
                    'adx': 28.4,
                    'close': 95000.0,
                    'score': 72,
                    'tier': 'A'
                }
            }
        },
        'recent_decisions': [
            {
                'timestamp': datetime.now().isoformat(),
                'strategy': 'llm_direction_btc',
                'action': 'hold',
                'reason': 'HOLDING',
                'exchange': 'binance'
            }
        ],
        'connection_status': [
            {
                'exchange': 'binance',
                'connected': True,
                'last_heartbeat': datetime.now().isoformat(),
                'is_stale': False,
                'stale_seconds': 5
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
            assert 'binance' in data
            assert 'connection_status' in data

    def test_realtime_endpoint_returns_404_when_no_data(self, client):
        """Test that the endpoint returns 404 when no trading data available."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_dashboard_state.return_value = {
                'timestamp': datetime.now().isoformat(),
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

            binance = data.get('binance')
            assert binance is not None
            assert binance['position_active'] is True
            assert binance['position_qty'] > 0
            assert 'unrealized_pnl' in binance
            assert 'unrealized_pnl_pct' in binance

    def test_realtime_endpoint_returns_regime_data(self, client, mock_metrics_service):
        """Test that market regime data is correctly returned."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_dashboard_state.return_value = mock_metrics_service

            response = client.get('/api/metrics/realtime')

            assert response.status_code == 200
            data = json.loads(response.data)

            binance = data.get('binance')
            assert binance is not None
            assert binance['regime'] == 'BULL'
            assert binance['market_state'] == 'BULL_STRONG'


class TestDecisionHistoryEndpoint:
    """Tests for /api/metrics/decisions endpoint."""

    def test_decisions_endpoint_returns_list(self, client):
        """Test that the endpoint returns a list of decisions."""
        sample_decisions = [
            {
                'timestamp': datetime.now().isoformat(),
                'strategy': 'llm_direction_btc',
                'action': 'hold',
                'reason': 'HOLDING',
                'exchange': 'binance'
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

            response = client.get('/api/metrics/decisions?exchange=binance')

            assert response.status_code == 200
            mock_service.get_recent_decisions.assert_called_once()
            call_kwargs = mock_service.get_recent_decisions.call_args[1]
            assert call_kwargs['exchange'] == 'binance'

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


class TestSignalsEndpoint:
    """Tests for /api/signals endpoint (market-analysis decisions)."""

    def test_signals_endpoint_returns_decision_based_signals(self, client):
        """Signals should be built from decision history with regime/indicator fields."""
        sample_decisions = [
            {
                'timestamp': datetime.now().isoformat(),
                'exchange': 'binance',
                'symbol': 'BTC',
                'market': 'spot',
                'strategy': 'llm_direction_btc',
                'decision': 'BUY',
                'reason': 'Entry signal',
                'regime': 'BULL_STRONG',
                'indicators': {'price': 95000.0, 'mfi': 55.0, 'adx': 30.0},
            }
        ]

        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_recent_decisions.return_value = sample_decisions

            response = client.get('/api/signals?hours=24&limit=50')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['total_count'] == 1
            assert data['signals'][0]['decision'] == 'BUY'
            assert data['signals'][0]['action'] == 'buy'
            assert data['signals'][0]['regime'] == 'BULL_STRONG'
            assert data['signals'][0]['market_state'] == 'STRONG'
            assert data['signals'][0]['indicators']['mfi'] == 55.0
            assert data['signals'][0]['acted'] is False

    def test_signals_endpoint_applies_action_filter(self, client):
        """Action filter should apply to decision-derived actions."""
        sample_decisions = [
            {
                'timestamp': datetime.now().isoformat(),
                'exchange': 'binance',
                'symbol': 'BTC',
                'market': 'spot',
                'strategy': 's1',
                'decision': 'BUY',
                'reason': 'Entry',
                'regime': 'BULL_MODERATE',
                'indicators': {'price': 1},
            },
            {
                'timestamp': datetime.now().isoformat(),
                'exchange': 'binance',
                'symbol': 'ETH',
                'market': 'spot',
                'strategy': 's1',
                'decision': 'WAIT',
                'reason': 'No setup',
                'regime': 'SIDEWAYS_FLAT',
                'indicators': {'price': 1},
            },
        ]

        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_recent_decisions.return_value = sample_decisions

            response = client.get('/api/signals?action=buy')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['total_count'] == 1
            assert data['signals'][0]['symbol'] == 'BTC'

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
