# tests/trading/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.orchestrator import TradingOrchestrator
from trading.core.config import Config


class TestTradingOrchestrator:
    @pytest.fixture
    def config(self):
        config = Config()
        config.telegram.enabled = False  # Disable telegram for tests
        return config

    @pytest.fixture
    def orchestrator(self, config):
        return TradingOrchestrator(config)

    def test_orchestrator_init(self, orchestrator):
        assert orchestrator.running is True
        assert orchestrator.tasks == {}
        assert orchestrator.notifier is None

    def test_handle_shutdown(self, orchestrator):
        # Add a mock task
        mock_task = MagicMock()
        orchestrator.tasks["test"] = mock_task

        orchestrator._handle_shutdown()

        assert orchestrator.running is False
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup(self, orchestrator):
        # Setup mock task
        mock_task = AsyncMock()
        mock_task.done.return_value = False
        orchestrator.tasks["test"] = mock_task

        # Setup mock redis
        orchestrator.redis = AsyncMock()
        orchestrator.redis.disconnect = AsyncMock()

        await orchestrator._cleanup()

        orchestrator.redis.disconnect.assert_called_once()


class TestOrchestratorComponents:
    """Test that all components can be instantiated."""

    def test_all_strategy_imports(self):
        from trading.strategies import (
            V35Strategy,
            ShortV1Strategy,
            SidewaysV2Strategy,
            H4Strategy,
            PremiumStrategy,
        )
        assert V35Strategy is not None
        assert ShortV1Strategy is not None
        assert SidewaysV2Strategy is not None
        assert H4Strategy is not None
        assert PremiumStrategy is not None

    def test_publisher_imports(self):
        from trading.publishers import FeedPublisher, RegimePublisher
        assert FeedPublisher is not None
        assert RegimePublisher is not None

    def test_executor_imports(self):
        from trading.executor import TradeExecutor, RiskControls
        assert TradeExecutor is not None
        assert RiskControls is not None
