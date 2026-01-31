# tests/web/test_events_api.py
"""
MetricsService event methods and API endpoint tests.

Tests cover:
- MetricsService.get_entry_events()
- MetricsService.get_exit_events()
- MetricsService.get_hwm_timeline()
- MetricsService.get_safety_rejections()
- API endpoints: /api/events/*
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import json

pytest.importorskip("flask")


class TestMetricsServiceEventMethods:
    """Test MetricsService event reading methods."""

    def test_get_entry_events_returns_list(self):
        """Test get_entry_events returns a list of events."""
        from web.services.metrics_service import MetricsService

        service = MetricsService()

        # Mock Redis client
        mock_redis = MagicMock()
        mock_redis.xrevrange = MagicMock(return_value=[
            ("1234567890-0", {
                "timestamp": "2026-01-20T12:00:00",
                "strategy": "v35_long",
                "symbol": "BTC",
                "market": "futures",
                "adx": "25.5",
                "mfi": "55.0",
                "regime": "BULL_STRONG",
                "signal_generated": "true",
            }),
        ])
        service._redis = mock_redis

        events = service.get_entry_events(hours=24, limit=50)

        assert isinstance(events, list)
        assert len(events) == 1
        assert events[0]["strategy"] == "v35_long"

    def test_get_entry_events_filters_by_symbol(self):
        """Test get_entry_events filters by symbol."""
        from web.services.metrics_service import MetricsService

        service = MetricsService()

        mock_redis = MagicMock()
        mock_redis.xrevrange = MagicMock(return_value=[
            ("1234567890-0", {
                "timestamp": "2026-01-20T12:00:00",
                "strategy": "v35_long",
                "symbol": "BTC",
                "market": "futures",
            }),
            ("1234567891-0", {
                "timestamp": "2026-01-20T12:01:00",
                "strategy": "v35_long",
                "symbol": "ETH",
                "market": "futures",
            }),
        ])
        service._redis = mock_redis

        events = service.get_entry_events(hours=24, limit=50, symbol="BTC")

        assert len(events) == 1
        assert events[0]["symbol"] == "BTC"

    def test_get_entry_events_filters_by_strategy(self):
        """Test get_entry_events filters by strategy."""
        from web.services.metrics_service import MetricsService

        service = MetricsService()

        mock_redis = MagicMock()
        mock_redis.xrevrange = MagicMock(return_value=[
            ("1234567890-0", {
                "timestamp": "2026-01-20T12:00:00",
                "strategy": "v35_long",
                "symbol": "BTC",
            }),
            ("1234567891-0", {
                "timestamp": "2026-01-20T12:01:00",
                "strategy": "short_v1",
                "symbol": "BTC",
            }),
        ])
        service._redis = mock_redis

        events = service.get_entry_events(hours=24, limit=50, strategy="v35_long")

        assert len(events) == 1
        assert events[0]["strategy"] == "v35_long"

    def test_get_exit_events_returns_list(self):
        """Test get_exit_events returns a list of events."""
        from web.services.metrics_service import MetricsService

        service = MetricsService()

        mock_redis = MagicMock()
        mock_redis.xrevrange = MagicMock(return_value=[
            ("1234567890-0", {
                "timestamp": "2026-01-20T12:00:00",
                "strategy": "v35_long",
                "symbol": "BTC",
                "entry_price": "43000.0",
                "current_price": "44000.0",
                "unrealized_pnl_pct": "2.33",
                "signal_generated": "false",
            }),
        ])
        service._redis = mock_redis

        events = service.get_exit_events(hours=24, limit=50)

        assert isinstance(events, list)
        assert len(events) == 1

    def test_get_hwm_timeline_returns_ordered_list(self):
        """Test get_hwm_timeline returns chronologically ordered HWM updates."""
        from web.services.metrics_service import MetricsService

        service = MetricsService()

        mock_redis = MagicMock()
        mock_redis.xrange = MagicMock(return_value=[
            ("1234567890-0", {
                "timestamp": "2026-01-20T12:00:00",
                "strategy": "v35_long",
                "symbol": "BTC",
                "old_hwm": "43000.0",
                "new_hwm": "43500.0",
            }),
            ("1234567891-0", {
                "timestamp": "2026-01-20T12:30:00",
                "strategy": "v35_long",
                "symbol": "BTC",
                "old_hwm": "43500.0",
                "new_hwm": "44000.0",
            }),
        ])
        service._redis = mock_redis

        timeline = service.get_hwm_timeline(symbol="BTC", strategy="v35_long", hours=24)

        assert isinstance(timeline, list)
        assert len(timeline) == 2
        # Verify chronological order (oldest first for timeline)
        assert timeline[0]["old_hwm"] == "43000.0"
        assert timeline[1]["old_hwm"] == "43500.0"

    def test_get_safety_rejections_returns_list(self):
        """Test get_safety_rejections returns a list of rejection events."""
        from web.services.metrics_service import MetricsService

        service = MetricsService()

        mock_redis = MagicMock()
        mock_redis.xrevrange = MagicMock(return_value=[
            ("1234567890-0", {
                "timestamp": "2026-01-20T12:00:00",
                "strategy": "v35_long",
                "symbol": "BTC",
                "rejection_type": "weak_trend",
                "reason": "ADX=15.0 < 20.0 threshold",
            }),
        ])
        service._redis = mock_redis

        rejections = service.get_safety_rejections(hours=24, limit=50)

        assert isinstance(rejections, list)
        assert len(rejections) == 1
        assert rejections[0]["rejection_type"] == "weak_trend"

    def test_get_safety_rejections_filters_by_type(self):
        """Test get_safety_rejections filters by rejection_type."""
        from web.services.metrics_service import MetricsService

        service = MetricsService()

        mock_redis = MagicMock()
        mock_redis.xrevrange = MagicMock(return_value=[
            ("1234567890-0", {
                "rejection_type": "weak_trend",
                "strategy": "v35_long",
                "symbol": "BTC",
            }),
            ("1234567891-0", {
                "rejection_type": "wrong_regime",
                "strategy": "v35_long",
                "symbol": "ETH",
            }),
        ])
        service._redis = mock_redis

        rejections = service.get_safety_rejections(
            hours=24, limit=50, rejection_type="weak_trend"
        )

        assert len(rejections) == 1
        assert rejections[0]["rejection_type"] == "weak_trend"


class TestEventsAPIEndpoints:
    """Test API endpoints for events."""

    @pytest.fixture(autouse=True)
    def patch_auth(self):
        """Patch auth credentials for all tests."""
        with patch('web.app.DASHBOARD_PASSWORD', 'test_password'), \
             patch('web.app.DASHBOARD_USERNAME', 'admin'):
            yield

    @pytest.fixture
    def client(self, patch_auth):
        """Create Flask test client with auth credentials."""
        import base64
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            # Add auth header helper
            credentials = base64.b64encode(b"admin:test_password").decode("utf-8")
            client.auth_header = {"Authorization": f"Basic {credentials}"}
            yield client

    def test_get_entry_events_endpoint(self, client):
        """Test GET /api/events/entry endpoint."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_entry_events.return_value = [
                {
                    "timestamp": "2026-01-20T12:00:00",
                    "strategy": "v35_long",
                    "symbol": "BTC",
                }
            ]

            response = client.get('/api/events/entry', headers=client.auth_header)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "events" in data
            assert len(data["events"]) == 1

    def test_get_entry_events_with_filters(self, client):
        """Test GET /api/events/entry with query params."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_entry_events.return_value = []

            response = client.get('/api/events/entry?symbol=BTC&strategy=v35_long&hours=12&limit=100', headers=client.auth_header)

            assert response.status_code == 200
            mock_service.get_entry_events.assert_called_once_with(
                hours=12, limit=100, symbol="BTC", strategy="v35_long"
            )

    def test_get_exit_events_endpoint(self, client):
        """Test GET /api/events/exit endpoint."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_exit_events.return_value = [
                {
                    "timestamp": "2026-01-20T12:00:00",
                    "strategy": "v35_long",
                    "symbol": "BTC",
                    "unrealized_pnl_pct": "2.33",
                }
            ]

            response = client.get('/api/events/exit', headers=client.auth_header)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "events" in data

    def test_get_hwm_timeline_endpoint(self, client):
        """Test GET /api/events/hwm/<symbol>/<strategy> endpoint."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_hwm_timeline.return_value = [
                {
                    "timestamp": "2026-01-20T12:00:00",
                    "old_hwm": "43000.0",
                    "new_hwm": "43500.0",
                }
            ]

            response = client.get('/api/events/hwm/BTC/v35_long', headers=client.auth_header)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "timeline" in data
            mock_service.get_hwm_timeline.assert_called_once()

    def test_get_safety_rejections_endpoint(self, client):
        """Test GET /api/events/safety endpoint."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_safety_rejections.return_value = [
                {
                    "timestamp": "2026-01-20T12:00:00",
                    "rejection_type": "weak_trend",
                    "strategy": "v35_long",
                }
            ]

            response = client.get('/api/events/safety', headers=client.auth_header)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "rejections" in data

    def test_get_events_summary_endpoint(self, client):
        """Test GET /api/events/summary endpoint."""
        with patch('web.app.metrics_service') as mock_service:
            mock_service.get_entry_events.return_value = [{"id": 1}, {"id": 2}]
            mock_service.get_exit_events.return_value = [{"id": 1}]
            mock_service.get_safety_rejections.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

            response = client.get('/api/events/summary', headers=client.auth_header)

            assert response.status_code == 200
            data = json.loads(response.data)
            assert "entry_events_count" in data
            assert "exit_events_count" in data
            assert "safety_rejections_count" in data
