"""Integration tests for volatility-based position sizing in CompositeStrategyTask."""

import pytest
from unittest.mock import MagicMock

from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory


class TestComponentAdapterVolSizing:
    """Test volatility sizing integration in ComponentStrategyAdapter (backtester)."""

    def _make_adapter(self, vol_sizing_config: dict | None = None) -> ComponentStrategyAdapter:
        """Create a minimal adapter with vol sizing config."""
        config = {
            "market": "spot",
            "position_pct": 0.90,
            "position_size": 0.90,
            "drawdown_enabled": False,
            "stop_loss_cooldown": 0,
            "drawdown_bear_threshold": 1.0,
            "entry": {
                "class": "MLPDirectionEntryStrategy",
                "params": {
                    "model_path": "models/mlp_direction/btc_bwin5_fwin2/model_final.pt",
                    "buy_confidence_threshold": 0.0,
                    "position_size": 0.9,
                    "market": "spot",
                    "mlp_feature_set": "paper_36",
                },
            },
            "exit": {
                "class": "MLPDirectionExitStrategy",
                "params": {
                    "stop_loss_pct": 10.0,
                    "use_mlp_sell_exit": True,
                    "sell_confidence_threshold": 0.0,
                    "model_path": "models/mlp_direction/btc_bwin5_fwin2/model_final.pt",
                    "market": "spot",
                    "mlp_feature_set": "paper_36",
                },
            },
        }
        if vol_sizing_config is not None:
            config["volatility_sizing"] = vol_sizing_config

        factory = StrategyFactory(redis=None)
        adapter = ComponentStrategyAdapter(
            factory=factory,
            strategy_name="mlp_direction",
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
            name="test_mlp",
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
