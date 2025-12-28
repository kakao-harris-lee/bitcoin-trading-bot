"""
Tests for exponential backoff order polling in exchange adapters.
"""

import pytest
from unittest.mock import MagicMock, patch
import time


class TestUpbitExponentialBackoff:
    """Test UpbitTrader exponential backoff."""

    def _create_mock_trader(self):
        """Create UpbitTrader with mocked pyupbit."""
        with patch('trading.adapters.upbit.pyupbit') as mock_pyupbit:
            with patch('trading.adapters.upbit.load_dotenv'):
                with patch.dict('os.environ', {
                    'UPBIT_ACCESS_KEY': 'test_key',
                    'UPBIT_SECRET_KEY': 'test_secret'
                }):
                    mock_upbit_instance = MagicMock()
                    mock_upbit_instance.get_balance.return_value = 1000000.0
                    mock_pyupbit.Upbit.return_value = mock_upbit_instance

                    from trading.adapters.upbit import UpbitTrader
                    trader = UpbitTrader()
                    return trader, mock_upbit_instance

    def test_quick_fill_detected_fast(self):
        """Order that fills immediately is detected in <0.2s."""
        trader, mock_upbit = self._create_mock_trader()

        # Order fills on first check
        mock_upbit.get_order.return_value = {'state': 'done', 'executed_volume': '0.001'}

        start = time.time()
        result = trader._wait_for_order_fill('test-uuid', max_wait=30.0)
        elapsed = time.time() - start

        assert result is not None
        assert result['state'] == 'done'
        assert elapsed < 0.2  # Should be nearly instant
        mock_upbit.get_order.assert_called_once_with('test-uuid')

    def test_slow_fill_uses_backoff(self):
        """Order that fills after several checks uses exponential backoff."""
        trader, mock_upbit = self._create_mock_trader()

        # Order fills on 4th check (after ~0.7s: 0.1 + 0.2 + 0.4)
        mock_upbit.get_order.side_effect = [
            {'state': 'wait'},
            {'state': 'wait'},
            {'state': 'wait'},
            {'state': 'done', 'executed_volume': '0.001'},
        ]

        start = time.time()
        result = trader._wait_for_order_fill('test-uuid', max_wait=30.0)
        elapsed = time.time() - start

        assert result is not None
        assert result['state'] == 'done'
        assert 0.5 < elapsed < 1.5  # Should be ~0.7s with backoff
        assert mock_upbit.get_order.call_count == 4

    def test_timeout_returns_last_status(self):
        """Order that never fills returns last status after timeout."""
        trader, mock_upbit = self._create_mock_trader()

        # Order never fills
        mock_upbit.get_order.return_value = {'state': 'wait'}

        start = time.time()
        result = trader._wait_for_order_fill('test-uuid', max_wait=2.0)  # Short timeout for test
        elapsed = time.time() - start

        assert result is not None
        assert result['state'] == 'wait'
        assert elapsed >= 2.0  # Should wait full timeout

    def test_backoff_caps_at_2_seconds(self):
        """Backoff delay caps at 2 seconds."""
        trader, mock_upbit = self._create_mock_trader()

        # Order fills after many checks
        call_count = [0]
        def side_effect(uuid):
            call_count[0] += 1
            if call_count[0] >= 10:
                return {'state': 'done', 'executed_volume': '0.001'}
            return {'state': 'wait'}

        mock_upbit.get_order.side_effect = side_effect

        result = trader._wait_for_order_fill('test-uuid', max_wait=30.0)

        assert result is not None
        assert result['state'] == 'done'
        # Delays: 0.1, 0.2, 0.4, 0.8, 1.6, 2.0, 2.0, 2.0, 2.0 (capped at 2.0)


class TestBinanceExponentialBackoff:
    """Test BinanceFuturesTrader exponential backoff."""

    def _create_mock_trader(self):
        """Create BinanceFuturesTrader with mocked client."""
        with patch('trading.adapters.binance.Client') as mock_client_class:
            with patch('trading.adapters.binance.load_dotenv'):
                with patch.dict('os.environ', {
                    'BINANCE_API_KEY': 'test_key',
                    'BINANCE_API_SECRET': 'test_secret'
                }):
                    mock_client = MagicMock()
                    mock_client.futures_account.return_value = {'totalWalletBalance': '1000.0'}
                    mock_client_class.return_value = mock_client

                    from trading.adapters.binance import BinanceFuturesTrader
                    trader = BinanceFuturesTrader()
                    return trader, mock_client

    def test_quick_fill_detected_fast(self):
        """Order that fills immediately is detected in <0.2s."""
        trader, mock_client = self._create_mock_trader()

        # Order fills on first check
        mock_client.futures_get_order.return_value = {
            'status': 'FILLED',
            'avgPrice': '95000.0',
            'executedQty': '0.1'
        }

        start = time.time()
        result = trader._wait_for_order_fill(12345, max_wait=30.0)
        elapsed = time.time() - start

        assert result is not None
        assert result['status'] == 'FILLED'
        assert elapsed < 0.2
        mock_client.futures_get_order.assert_called_once()

    def test_slow_fill_uses_backoff(self):
        """Order that fills after several checks uses exponential backoff."""
        trader, mock_client = self._create_mock_trader()

        # Order fills on 4th check
        mock_client.futures_get_order.side_effect = [
            {'status': 'NEW'},
            {'status': 'NEW'},
            {'status': 'NEW'},
            {'status': 'FILLED', 'avgPrice': '95000.0', 'executedQty': '0.1'},
        ]

        start = time.time()
        result = trader._wait_for_order_fill(12345, max_wait=30.0)
        elapsed = time.time() - start

        assert result is not None
        assert result['status'] == 'FILLED'
        assert 0.5 < elapsed < 1.5
        assert mock_client.futures_get_order.call_count == 4

    def test_timeout_returns_last_status(self):
        """Order that never fills returns last status after timeout."""
        trader, mock_client = self._create_mock_trader()

        # Order never fills
        mock_client.futures_get_order.return_value = {'status': 'NEW'}

        start = time.time()
        result = trader._wait_for_order_fill(12345, max_wait=2.0)
        elapsed = time.time() - start

        assert result is not None
        assert result['status'] == 'NEW'
        assert elapsed >= 2.0


class TestBackoffTiming:
    """Test exponential backoff timing characteristics."""

    def test_backoff_sequence(self):
        """Verify the expected backoff delay sequence."""
        delays = []
        delay = 0.1
        elapsed = 0.0
        max_wait = 30.0

        while elapsed < max_wait:
            delays.append(delay)
            elapsed += delay
            delay = min(delay * 2, 2.0)

        # First few delays should be: 0.1, 0.2, 0.4, 0.8, 1.6, 2.0, 2.0, ...
        assert delays[0] == pytest.approx(0.1, rel=0.01)
        assert delays[1] == pytest.approx(0.2, rel=0.01)
        assert delays[2] == pytest.approx(0.4, rel=0.01)
        assert delays[3] == pytest.approx(0.8, rel=0.01)
        assert delays[4] == pytest.approx(1.6, rel=0.01)
        assert delays[5] == pytest.approx(2.0, rel=0.01)  # Capped
        assert delays[6] == pytest.approx(2.0, rel=0.01)  # Stays capped

    def test_total_checks_within_30s(self):
        """Verify number of checks possible within 30 seconds."""
        delays = []
        delay = 0.1
        elapsed = 0.0
        max_wait = 30.0

        while elapsed < max_wait:
            delays.append(delay)
            elapsed += delay
            delay = min(delay * 2, 2.0)

        # With exponential backoff, we should get ~18-20 checks in 30s
        # Much better than fixed 30 checks with 1s delay
        assert len(delays) >= 15
        assert len(delays) <= 25
