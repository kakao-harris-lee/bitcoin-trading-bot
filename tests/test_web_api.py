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

# Skip entire module if Flask is not installed
flask = pytest.importorskip("flask")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from web.app import app
import web.app as web_app


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


class TestStatusAPI:
    """Test /api/status endpoint."""

    @patch('web.app.metrics_service', None)
    @patch('web.app.load_multi_asset_status')
    @patch('web.app.load_allocation_config')
    def test_status_no_data(self, mock_alloc, mock_status, client):
        """Status should return minimal data when no engine status."""
        mock_status.return_value = None
        mock_alloc.return_value = {}

        response = client.get('/api/status')
        # API returns 200 with minimal status (prices/risk from Redis)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'timestamp' in data

    @patch('web.app.metrics_service', None)
    @patch('web.app.load_multi_asset_status')
    @patch('web.app.load_allocation_config')
    def test_status_with_data(self, mock_alloc, mock_status, client, mock_multi_asset_status):
        """Status should return proper data when available (legacy path)."""
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

        # Legacy path uses symbol as key
        assert 'BTC' in data['assets']

    def test_fallback_assets_use_selector_symbols_only(self):
        """Fallback assets should prioritize selector symbols, not full regime universe."""
        prices = {
            'BTC': 90000,
            'ETH': 3000,
            'SOL': 180,
            'ADA': 0.8,
            'XRP': 0.6,
            'DOGE': 0.2,
        }
        regime_status = {
            'BTC': {'regime': 'BULL_STRONG'},
            'ETH': {'regime': 'BULL_STRONG'},
            'SOL': {'regime': 'SIDEWAYS_FLAT'},
            'ADA': {'regime': 'BULL_MODERATE'},
            'XRP': {'regime': 'SIDEWAYS_UP'},
            'DOGE': {'regime': 'BEAR_STRONG'},
            'AVAX': {'regime': 'BULL_MODERATE'},
        }

        assets = web_app._build_status_fallback_assets(
            prices,
            regime_status,
            selector_symbols=['ADA', 'XRP'],
        )

        assert 'BTC_futures' in assets
        assert 'ETH_futures' in assets
        assert 'SOL_futures' in assets
        assert 'ADA_futures' in assets
        assert 'XRP_futures' in assets
        assert 'DOGE_futures' not in assets
        assert 'AVAX_futures' not in assets
        assert all(a.get('strategy') == '-' for a in assets.values())

    @patch('web.app.get_redis')
    def test_load_selector_fallback_symbols(self, mock_get_redis):
        """Selector fallback symbol loader should parse latest selector state."""
        mock_redis = MagicMock()
        mock_redis.keys.return_value = [
            'strategy:selector:latest:mlp_direction_bnb',
        ]
        mock_redis.hgetall.return_value = {
            'selected_symbols': '["ADA","XRP","DOGE"]',
        }
        mock_get_redis.return_value = mock_redis

        symbols = web_app._load_selector_fallback_symbols(mock_get_redis.return_value, limit=5)
        assert symbols == ['ADA', 'XRP', 'DOGE']

    def test_load_selector_symbols_from_stream_uses_latest_snapshot_per_strategy(self):
        """Stream fallback should ignore stale symbols from older snapshots."""
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = [
            (
                '3-0',
                {
                    'strategy': 'mlp_direction_a',
                    'fields': json.dumps({
                        'strategy': 'mlp_direction_a',
                        'selected_symbols': '["ADA","XRP"]',
                    }),
                },
            ),
            (
                '2-0',
                {
                    'strategy': 'mlp_direction_a',
                    'fields': json.dumps({
                        'strategy': 'mlp_direction_a',
                        'selected_symbols': '["BTC","ETH"]',
                    }),
                },
            ),
            (
                '1-0',
                {
                    'strategy': 'mlp_direction_b',
                    'fields': json.dumps({
                        'strategy': 'mlp_direction_b',
                        'selected_symbols': '["SOL"]',
                    }),
                },
            ),
        ]

        symbols = web_app._load_selector_symbols_from_stream(mock_redis, limit=5)

        assert symbols == ['ADA', 'XRP', 'SOL']

    def test_load_strategy_live_state_prefers_index_over_event_mirror(self):
        """Indexed Redis state should override stale best-effort stream values."""
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = [
            (
                '1-0',
                {
                    'strategy': 'mlp_direction',
                    'symbol': 'BTC',
                    'variable': 'hwm',
                    'value': '100.0',
                },
            ),
        ]
        mock_redis.smembers.return_value = {'hwm'}
        mock_redis.get.return_value = '125.0'

        live_state = web_app._load_strategy_live_state(mock_redis, 'mlp_direction', ['BTC'])

        assert live_state == {'BTC': {'hwm': 125.0}}


class TestPositionsAPI:
    """Test /api/positions endpoint."""

    @patch('web.app._load_dashboard_symbols')
    def test_discover_position_symbols_scans_hashes_when_stream_misses_symbol(self, mock_dashboard_symbols):
        """Active position hashes should still surface symbols after stream loss/trim."""
        mock_dashboard_symbols.return_value = ['BTC']
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = []
        mock_redis.scan_iter.side_effect = lambda match: [b'positions:GRT:spot'] if match == 'positions:*:spot' else []
        mock_redis.hgetall.side_effect = lambda key: {
            'positions:GRT:spot': {'quantity': '3.5'},
        }.get(key, {})

        symbols = web_app._discover_position_symbols(mock_redis)

        assert symbols == ['BTC', 'GRT']

    @patch('web.app.get_latest_prices')
    @patch('web.app.get_redis')
    def test_positions_include_dynamic_symbol_in_paper_mode(self, mock_get_redis, mock_get_prices, client):
        """Paper positions should include Redis-tracked symbols outside defaults."""
        mock_redis = MagicMock()
        mock_redis.keys.return_value = ['positions:GRT:spot']
        mock_redis.hgetall.side_effect = lambda key: {
            'risk': {'mode': 'paper'},
            'positions:GRT:spot': {
                'quantity': '26935.24799083962',
                'entry_price': '0.028271304',
                'strategy': 'mlp_direction_bnb',
                'entry_time': '1771696808878',
            },
        }.get(key, {})
        mock_get_redis.return_value = mock_redis
        mock_get_prices.return_value = {'GRTUSDT': 0.02827}

        response = client.get('/api/positions')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['positions']) == 1
        assert data['positions'][0]['symbol'] == 'GRTUSDT'
        assert data['positions'][0]['market'] == 'spot'


class TestKillSwitchAPI:
    """Test /api/kill_switch endpoints."""

    @patch('web.app.get_redis')
    @patch('web.app.KILL_SWITCH_FILE')
    def test_kill_switch_status_inactive(self, mock_file, mock_get_redis, client):
        """Kill switch status when inactive."""
        mock_get_redis.return_value.hgetall.return_value = {}
        mock_file.exists.return_value = False
        mock_file.__str__ = lambda self: '/data/KILL_SWITCH'

        response = client.get('/api/kill_switch/status')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['active'] == False

    @patch('web.app.get_redis')
    @patch('web.app.KILL_SWITCH_FILE')
    def test_kill_switch_status_active(self, mock_file, mock_get_redis, client):
        """Kill switch status when active."""
        mock_get_redis.return_value.hgetall.return_value = {}
        mock_file.exists.return_value = True
        mock_file.__str__ = lambda self: '/data/KILL_SWITCH'

        response = client.get('/api/kill_switch/status')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['active'] == True

    @patch('web.app.get_redis')
    @patch('web.app.KILL_SWITCH_FILE')
    def test_kill_switch_status_prefers_redis_state(self, mock_file, mock_get_redis, client):
        """When Redis is available, status should reflect runtime risk state."""
        mock_file.exists.return_value = False
        mock_get_redis.return_value.hgetall.return_value = {"kill_switch": "true"}

        response = client.get('/api/kill_switch/status')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['active'] == True
        assert data['source'] == 'redis'

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

    @patch('web.app.get_redis')
    @patch('web.app.KILL_SWITCH_FILE')
    def test_kill_switch_on_sets_redis(self, mock_file, mock_get_redis, client):
        """Kill switch on should update both file and Redis."""
        mock_file.exists.return_value = True
        mock_get_redis.return_value.hgetall.return_value = {"kill_switch": "true"}

        with patch.dict(os.environ, {"WEB_ADMIN_TOKEN": "secret"}):
            response = client.post('/api/kill_switch/on', headers={"X-Admin-Token": "secret"})

        assert response.status_code == 200
        mock_file.touch.assert_called_once()
        mock_get_redis.return_value.hset.assert_called_with("risk", "kill_switch", "true")

    @patch('web.app.get_redis')
    @patch('web.app.KILL_SWITCH_FILE')
    def test_kill_switch_off_sets_redis(self, mock_file, mock_get_redis, client):
        """Kill switch off should update both file and Redis."""
        mock_file.exists.return_value = False
        mock_get_redis.return_value.hgetall.return_value = {"kill_switch": "false"}

        with patch.dict(os.environ, {"WEB_ADMIN_TOKEN": "secret"}):
            response = client.post('/api/kill_switch/off', headers={"X-Admin-Token": "secret"})

        assert response.status_code == 200
        mock_get_redis.return_value.hset.assert_called_with("risk", "kill_switch", "false")


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


class TestTradesHistoryAPI:
    """Test /api/trades paginated history endpoint."""

    @patch('web.app.get_redis')
    @patch('web.app.read_redis_trades')
    def test_trades_history_returns_summary(self, mock_read_trades, mock_get_redis, client):
        """Trades history should return paginated trades and summary metrics."""
        mock_get_redis.return_value.hgetall.return_value = {'mode': 'paper'}
        mock_read_trades.return_value = [
            {
                'id': '1',
                'timestamp': '2026-02-08T10:00:00',
                'action': 'BUY',
                'symbol': 'BTC',
                'price': 100000,
                'volume': 0.01,
                'market': 'spot',
                'exchange': 'binance',
                'strategy': 's1',
                'paper': True,
                'profit': None,
                'profit_pct': None,
                'reason': 'entry',
            },
            {
                'id': '2',
                'timestamp': '2026-02-08T11:00:00',
                'action': 'SELL',
                'symbol': 'BTC',
                'price': 101000,
                'volume': 0.01,
                'market': 'futures',
                'exchange': 'binance',
                'strategy': 's1',
                'paper': True,
                'profit': 10.0,
                'profit_pct': 1.0,
                'reason': 'exit',
            },
        ]

        response = client.get('/api/trades?page=1&limit=50')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['total_count'] == 2
        assert len(data['trades']) == 2
        assert 'summary' in data
        assert data['summary']['buy_count'] == 1
        assert data['summary']['sell_count'] == 1
        assert data['summary']['spot_count'] == 1
        assert data['summary']['futures_count'] == 1
        assert data['summary']['realized_trade_count'] == 1
        assert data['summary']['realized_pnl'] == 10.0
        assert data['summary']['win_rate'] == 100.0


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
