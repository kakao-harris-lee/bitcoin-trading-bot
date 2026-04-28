"""Integration tests for volatility-based position sizing in CompositeStrategyTask."""

import pytest
from unittest.mock import MagicMock

from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.strategies.components.models import build_market_context


class TestComponentAdapterVolSizing:
    """Test volatility sizing integration in ComponentStrategyAdapter (backtester)."""

    def _make_adapter(
        self,
        vol_sizing_config: dict | None = None,
        extra_config: dict | None = None,
    ) -> ComponentStrategyAdapter:
        """Create a minimal adapter with vol sizing config."""
        config = {
            "market": "spot",
            "position_pct": 0.90,
            "position_size": 0.90,
            "drawdown_enabled": False,
            "stop_loss_cooldown": 0,
            "drawdown_bear_threshold": 1.0,
            "entry": {
                "class": "LLMDecisionEntryStrategy",
                "params": {
                    "confidence_threshold": 0.0,
                    "position_size": 0.9,
                    "market": "spot",
                },
            },
            "exit": {
                "class": "LLMHybridExitStrategy",
                "params": {
                    "stop_loss_pct": 10.0,
                    "market": "spot",
                },
            },
        }
        if vol_sizing_config is not None:
            config["volatility_sizing"] = vol_sizing_config
        if extra_config is not None:
            config.update(extra_config)

        factory = StrategyFactory(redis=None)
        adapter = ComponentStrategyAdapter(
            factory=factory,
            strategy_name="llm_direction",
            config=config,
        )
        adapter.symbol = "BTC"
        return adapter

    def test_vol_sizing_disabled_by_default(self):
        """When no volatility_sizing config, feature should be disabled."""
        adapter = self._make_adapter()
        assert adapter._vol_sizing_enabled is False

    def test_vol_sizing_config_reads(self):
        """Config values should be read correctly."""
        adapter = self._make_adapter({
            "enabled": True,
            "target_vol": 0.03,
            "min_scale": 0.10,
            "max_scale": 1.5,
        })
        assert adapter._vol_sizing_enabled is True
        assert adapter._vol_target == 0.03
        assert adapter._vol_min_scale == 0.10
        assert adapter._vol_max_scale == 1.5

    def test_vol_sizing_disabled_explicit(self):
        """Explicitly disabled vol sizing should not scale."""
        adapter = self._make_adapter({
            "enabled": False,
            "target_vol": 0.02,
        })
        assert adapter._vol_sizing_enabled is False

    def test_period_risk_config_reads(self):
        """Period risk throttle config should be loaded into adapter."""
        adapter = self._make_adapter(
            extra_config={
                "period_risk_enabled": True,
                "period_reduce_threshold_pct": 7.5,
                "period_reduce_scale": 0.65,
                "period_loss_limit_pct": 10.0,
            },
        )
        assert adapter._period_risk_enabled is True
        assert adapter._period_reduce_threshold_pct == 7.5
        assert adapter._period_reduce_scale == 0.65
        assert adapter._period_loss_limit_pct == 10.0

    def test_period_loss_guard_blocks_new_entries(self):
        """When period loss exceeds limit, entry hold reason should block new entries."""
        adapter = self._make_adapter(extra_config={"period_risk_enabled": True, "period_loss_limit_pct": 5.0})
        adapter._period_return_pct = -6.0
        context = build_market_context(mfi=60.0, adx=25.0, atr=1.0, close=100.0)
        row = MagicMock()
        row.get = lambda k, d=None: {"ema_200": 0.0}.get(k, d)

        reason = adapter._entry_hold_reason(row, context, {"close": 100.0, "mfi": 60.0})
        assert reason is not None
        assert reason.startswith("period_loss_guard:")

    def test_period_drawdown_scales_entry_fraction(self):
        """Period drawdown warning should downscale position size."""
        adapter = self._make_adapter(
            extra_config={
                "period_risk_enabled": True,
                "period_reduce_threshold_pct": 8.0,
                "period_reduce_scale": 0.6,
            },
        )
        adapter._period_drawdown_pct = 10.0

        signal = MagicMock()
        signal.quantity = None

        fraction, reason = adapter._resolve_entry_fraction(signal, atr=0.0, close=100.0)
        assert fraction == pytest.approx(0.90 * 0.60, rel=1e-9)
        assert "period_scale:0.60" in reason

    def test_entry_fraction_uses_position_pct_by_default(self):
        """Without use_signal_quantity, entry fraction should follow position_pct."""
        adapter = self._make_adapter(extra_config={"position_pct": 0.9})
        signal = MagicMock()
        signal.quantity = 0.25

        fraction, reason = adapter._resolve_entry_fraction(signal, atr=0.0, close=100.0)
        assert fraction == pytest.approx(0.9, rel=1e-9)
        assert "config_pct:0.90" in reason

    def test_entry_fraction_can_use_signal_quantity_when_enabled(self):
        """When use_signal_quantity is enabled, signal quantity should be used."""
        adapter = self._make_adapter(
            extra_config={
                "position_pct": 0.9,
                "use_signal_quantity": True,
            },
        )
        signal = MagicMock()
        signal.quantity = 0.25

        fraction, reason = adapter._resolve_entry_fraction(signal, atr=0.0, close=100.0)
        assert fraction == pytest.approx(0.25, rel=1e-9)
        assert "regime_size:0.25" in reason


class TestCompositeTaskVolSizingConfig:
    """Test volatility sizing config reads in CompositeStrategyTask."""

    def _make_task(self, config: dict | None = None):
        """Create a minimal CompositeStrategyTask with given config."""
        from trading.strategies.components.composite_task import CompositeStrategyTask

        redis = MagicMock()
        redis.publish_event = MagicMock()
        redis._client = MagicMock()

        entry = MagicMock()
        entry.params = MagicMock()
        entry.params.mfi_bull = 52.0
        entry.params.mfi_bear = 48.0
        entry.params.adx_trend = 20.0

        exit_strat = MagicMock()
        exit_strat.params = MagicMock()

        task = CompositeStrategyTask(
            name="test_llm",
            symbols=["BTC"],
            redis=redis,
            entry_strategy=entry,
            exit_strategy=exit_strat,
            market="spot",
            config=config or {},
        )
        return task

    def test_vol_sizing_disabled_by_default(self):
        """Default config should have vol sizing disabled."""
        task = self._make_task()
        assert task._vol_sizing_enabled is False

    def test_vol_sizing_config_reads(self):
        """Config values should be read correctly into task."""
        task = self._make_task({
            "volatility_sizing": {
                "enabled": True,
                "target_vol": 0.025,
                "min_scale": 0.15,
                "max_scale": 0.95,
            },
        })
        assert task._vol_sizing_enabled is True
        assert task._vol_target == 0.025
        assert task._vol_min_scale == 0.15
        assert task._vol_max_scale == 0.95

    def test_vol_sizing_defaults(self):
        """Empty volatility_sizing block should use defaults."""
        task = self._make_task({
            "volatility_sizing": {},
        })
        assert task._vol_sizing_enabled is False
        assert task._vol_target == 0.02
        assert task._vol_min_scale == 0.25
        assert task._vol_max_scale == 1.0
