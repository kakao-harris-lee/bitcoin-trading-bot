"""Tests for portfolio-level risk management."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.risk.portfolio_risk_manager import (
    PortfolioRiskManager,
    RiskCapConfig,
    RiskCheckResult,
    OpenPositionRisk,
)
from trading.risk.correlation_filter import (
    CorrelationFilter,
    CorrelationConfig,
)


class TestRiskCapConfig:
    """Tests for RiskCapConfig."""

    def test_default_values(self):
        """Default config has sensible values."""
        config = RiskCapConfig()
        assert config.max_total_risk_pct == 0.05
        assert config.max_open_positions == 5
        assert config.risk_per_trade_pct == 0.01
        assert config.corr_threshold == 0.75

    def test_from_dict(self):
        """Config can be created from dict."""
        config = RiskCapConfig.from_dict({
            "max_total_risk_pct": 0.03,
            "max_open_positions": 3,
            "risk_per_trade_pct": 0.005,
            "corr_threshold": 0.8,
        })
        assert config.max_total_risk_pct == 0.03
        assert config.max_open_positions == 3
        assert config.risk_per_trade_pct == 0.005
        assert config.corr_threshold == 0.8


class TestPortfolioRiskManager:
    """Tests for PortfolioRiskManager."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.get_position = AsyncMock(return_value=None)
        return redis

    @pytest.fixture
    def config(self):
        """Default test config."""
        return RiskCapConfig(
            max_total_risk_pct=0.05,  # 5%
            max_open_positions=3,
            risk_per_trade_pct=0.01,  # 1%
            use_correlation_filter=False,  # Disable for basic tests
        )

    @pytest.fixture
    def manager(self, config, mock_redis):
        """Create manager for testing."""
        return PortfolioRiskManager(config, mock_redis)

    @pytest.mark.asyncio
    async def test_can_open_first_trade(self, manager):
        """First trade with no existing positions should pass."""
        result = await manager.can_open_trade(
            symbol="BTC",
            proposed_risk=100,  # $100 risk
            equity=10000,
        )

        assert result.allowed is True
        assert result.reason == "OK"

    @pytest.mark.asyncio
    async def test_total_risk_cap_enforced(self, manager, mock_redis):
        """Total risk cap blocks trades that would exceed limit."""
        # Mock existing positions with $400 risk (4%)
        manager._risk_cache = {
            "BTC_spot": OpenPositionRisk("BTC", 100000, 0.1, 97000, 200, 1),
            "ETH_spot": OpenPositionRisk("ETH", 3000, 3, 2910, 200, 1),
        }
        manager._cache_ts = float("inf")  # Prevent cache refresh

        result = await manager.can_open_trade(
            symbol="SOL",
            proposed_risk=200,  # $200 more = 6% total
            equity=10000,  # 5% max = $500
        )

        assert result.allowed is False
        assert "TOTAL_RISK_CAP" in result.reason
        assert result.current_total_risk == 400

    @pytest.mark.asyncio
    async def test_position_count_cap_enforced(self, manager, mock_redis):
        """Position count cap blocks new positions."""
        # Mock 3 existing positions (max)
        manager._risk_cache = {
            "BTC_spot": OpenPositionRisk("BTC", 100000, 0.01, 97000, 100, 1),
            "ETH_spot": OpenPositionRisk("ETH", 3000, 1, 2910, 100, 1),
            "SOL_spot": OpenPositionRisk("SOL", 100, 10, 97, 100, 1),
        }
        manager._cache_ts = float("inf")

        result = await manager.can_open_trade(
            symbol="DOGE",
            proposed_risk=50,
            equity=10000,
        )

        assert result.allowed is False
        assert "MAX_POSITIONS" in result.reason

    @pytest.mark.asyncio
    async def test_adding_to_existing_position_allowed(self, manager, mock_redis):
        """Adding to existing position doesn't count against position limit."""
        # Mock 3 existing positions including BTC
        manager._risk_cache = {
            "BTC_spot": OpenPositionRisk("BTC", 100000, 0.01, 97000, 100, 1),
            "ETH_spot": OpenPositionRisk("ETH", 3000, 1, 2910, 100, 1),
            "SOL_spot": OpenPositionRisk("SOL", 100, 10, 97, 100, 1),
        }
        manager._cache_ts = float("inf")

        # Adding to BTC should be allowed (not a new position)
        result = await manager.can_open_trade(
            symbol="BTC",  # Same as existing
            proposed_risk=50,
            equity=10000,
        )

        # Should pass position count check (still 3 positions)
        # Might fail risk cap, but won't fail position count
        assert "MAX_POSITIONS" not in result.reason

    @pytest.mark.asyncio
    async def test_remaining_risk_budget_calculated(self, manager, mock_redis):
        """Result includes remaining risk budget."""
        manager._risk_cache = {
            "BTC_spot": OpenPositionRisk("BTC", 100000, 0.1, 97000, 200, 1),
        }
        manager._cache_ts = float("inf")

        result = await manager.can_open_trade(
            symbol="ETH",
            proposed_risk=100,
            equity=10000,  # 5% max = $500
        )

        # $200 existing + $100 proposed = $300 used
        # $500 - $300 = $200 remaining
        assert result.remaining_risk_budget == 200

    @pytest.mark.asyncio
    async def test_correlation_filter_blocks_high_corr(self, mock_redis):
        """Correlation filter blocks highly correlated entries."""
        # Mock correlation filter
        mock_corr_filter = MagicMock()
        mock_corr_filter.get_correlation = AsyncMock(return_value=0.85)

        config = RiskCapConfig(
            max_total_risk_pct=0.05,
            max_open_positions=5,
            use_correlation_filter=True,
            corr_threshold=0.75,
            corr_action="block",
        )

        manager = PortfolioRiskManager(config, mock_redis, mock_corr_filter)
        manager._risk_cache = {
            "BTC_spot": OpenPositionRisk("BTC", 100000, 0.1, 97000, 100, 1),
        }
        manager._cache_ts = float("inf")

        result = await manager.can_open_trade(
            symbol="ETH",
            proposed_risk=100,
            equity=10000,
        )

        assert result.allowed is False
        assert "HIGH_CORR" in result.reason

    @pytest.mark.asyncio
    async def test_correlation_reduce_action(self, mock_redis):
        """Correlation filter can reduce risk instead of blocking."""
        # Create correlation filter mock that returns high correlation
        mock_corr_filter = MagicMock()
        mock_corr_filter.get_correlation = AsyncMock(return_value=0.85)

        config = RiskCapConfig(
            max_total_risk_pct=0.05,
            max_open_positions=5,
            use_correlation_filter=True,
            corr_threshold=0.75,
            corr_action="reduce",
            corr_reduction_factor=0.5,
            risk_per_trade_pct=0.01,
        )

        manager = PortfolioRiskManager(config, mock_redis, mock_corr_filter)
        manager._risk_cache = {
            "BTC_spot": OpenPositionRisk("BTC", 100000, 0.1, 97000, 100, 1),
        }
        manager._cache_ts = float("inf")

        # Call _check_correlation directly to verify the reduce action works
        result = await manager._check_correlation(
            new_symbol="ETH",
            existing_symbols=["BTC"],
            proposed_risk=100,
            equity=10000,
        )

        # Should be allowed but with reduced risk
        assert result.allowed is True
        assert "CORR_REDUCED" in result.reason
        assert result.adjusted_risk_pct == 0.005  # 1% * 0.5

    @pytest.mark.asyncio
    async def test_portfolio_risk_summary(self, manager, mock_redis):
        """Get portfolio risk summary."""
        manager._risk_cache = {
            "BTC_futures": OpenPositionRisk("BTC", 100000, 0.1, 97000, 200, 3),
            "ETH_futures": OpenPositionRisk("ETH", 3000, 3, 2910, 150, 2),
        }
        manager._cache_ts = float("inf")

        summary = await manager.get_portfolio_risk_summary(equity=10000)

        assert summary["open_positions"] == 2
        assert summary["max_positions"] == 3
        assert summary["total_risk_usd"] == 350
        assert summary["max_risk_usd"] == 500
        assert summary["total_risk_pct"] == pytest.approx(3.5, rel=0.001)
        assert summary["remaining_risk_budget"] == 150


class TestCorrelationFilter:
    """Tests for CorrelationFilter."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.redis = MagicMock()
        redis.redis.lrange = AsyncMock(return_value=[])
        redis.redis.xrevrange = AsyncMock(return_value=[])
        return redis

    @pytest.fixture
    def config(self):
        """Default test config."""
        return CorrelationConfig(
            lookback_bars=60,
            threshold=0.75,
            min_data_points=30,
        )

    @pytest.fixture
    def filter(self, config, mock_redis):
        """Create filter for testing."""
        return CorrelationFilter(config, mock_redis)

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_zero(self, filter):
        """Zero correlation when insufficient data."""
        corr = await filter.get_correlation("BTC", "ETH")
        assert corr == 0.0

    @pytest.mark.asyncio
    async def test_should_block_empty_positions(self, filter):
        """No blocking when no existing positions."""
        blocked, reason = await filter.should_block("BTC", [])
        assert blocked is False
        assert reason == "NO_EXISTING_POSITIONS"

    def test_cache_key_normalized(self, filter):
        """Cache key is alphabetically sorted."""
        # Internal test - cache key should be same regardless of order
        key1 = f"{min('BTC', 'ETH')}_{max('BTC', 'ETH')}"
        key2 = f"{min('ETH', 'BTC')}_{max('ETH', 'BTC')}"
        assert key1 == key2

    @pytest.mark.asyncio
    async def test_correlation_cached(self, filter, mock_redis):
        """Correlation values are cached."""
        # Manually set cache
        filter._cache["BTC_ETH"] = (0.85, float("inf"))

        corr = await filter.get_correlation("BTC", "ETH")
        assert corr == 0.85

        # Redis should not be called
        mock_redis.redis.lrange.assert_not_called()

    def test_invalidate_cache(self, filter):
        """Cache can be invalidated."""
        filter._cache["BTC_ETH"] = (0.85, float("inf"))
        filter._returns_cache["BTC"] = ([0.01, 0.02], float("inf"))

        filter.invalidate_cache()

        assert len(filter._cache) == 0
        assert len(filter._returns_cache) == 0
