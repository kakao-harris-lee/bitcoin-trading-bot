"""Integration tests for volatility-based position sizing in CompositeStrategyTask."""

import pytest
from unittest.mock import MagicMock

from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.strategies.components.models import (
    MarketContext,
    MarketData,
    Position,
    TradingContext,
    build_market_context,
)


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

    def test_entry_fallback_config_reads_for_backtest_adapter(self):
        """Backtest adapter should load the same entry fallback used by live tasks."""
        adapter = self._make_adapter(
            extra_config={
                "entry_fallback": {
                    "enabled": True,
                    "class": "RegimeLongV2EntryStrategy",
                    "on_non_buy": True,
                    "max_hold_confidence": 0.6,
                    "params": {"position_size": 0.12},
                }
            }
        )

        assert adapter._entry_fallback_enabled is True
        assert adapter._entry_fallback_on_non_buy is True
        assert adapter._entry_fallback_max_hold_confidence == pytest.approx(0.6)
        assert adapter._fallback_entry_strategy is not None

    def test_bear_moderate_exit_partially_de_risks_once(self):
        """BEAR_MODERATE should reduce exposure once instead of full cash-out."""
        adapter = self._make_adapter(
            extra_config={
                "exit_on_bear_regime": True,
                "protective_partial_exit_enabled": True,
                "protective_partial_exit_fraction": 0.5,
                "protective_partial_regimes": ["BEAR_MODERATE"],
            }
        )
        adapter.current_position = Position(
            symbol="BTC",
            entry_price=100.0,
            quantity=1.0,
            strategy="llm_direction",
            market="spot",
            timestamp=1,
        )
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_MODERATE",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=20.0,
        )

        market_data = MarketData(
            symbol="BTC", close=99.0, timestamp=1, mfi=40.0, adx=20.0, rsi=45.0, ema_200=90.0
        )

        first = adapter._check_bear_regime_exit_action(context, market_data, is_long=True)
        second = adapter._check_bear_regime_exit_action(context, market_data, is_long=True)

        assert first["action"] == "sell"
        assert first["fraction"] == pytest.approx(0.5)
        assert adapter.current_position.quantity == pytest.approx(0.5)
        assert second is None

    def test_bear_strong_exit_remains_full_exit(self):
        """BEAR_STRONG should still fully close the position."""
        adapter = self._make_adapter(
            extra_config={
                "exit_on_bear_regime": True,
                "protective_partial_exit_enabled": True,
                "protective_partial_exit_fraction": 0.5,
                "protective_partial_regimes": ["BEAR_MODERATE"],
            }
        )
        adapter.current_position = Position(
            symbol="BTC",
            entry_price=100.0,
            quantity=1.0,
            strategy="llm_direction",
            market="spot",
            timestamp=1,
        )
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_STRONG",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=30.0,
        )

        market_data = MarketData(
            symbol="BTC", close=99.0, timestamp=1, mfi=30.0, adx=30.0, rsi=40.0, ema_200=90.0
        )

        action = adapter._check_bear_regime_exit_action(context, market_data, is_long=True)

        assert action["action"] == "sell"
        assert action["fraction"] == pytest.approx(1.0)
        assert adapter.current_position is None

    def test_trend_hold_guard_suppresses_bear_moderate_exit_above_ema200(self):
        """Trend hold guard should avoid weak bear cash-outs above EMA200."""
        adapter = self._make_adapter(
            extra_config={
                "exit_on_bear_regime": True,
                "trend_hold_exit_guard_enabled": True,
                "trend_hold_guard_require_above_ema200": True,
            }
        )
        adapter.current_position = Position(
            symbol="BTC",
            entry_price=100.0,
            quantity=1.0,
            strategy="llm_direction",
            market="spot",
            timestamp=1,
        )
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_MODERATE",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=20.0,
        )
        market_data = MarketData(
            symbol="BTC", close=105.0, timestamp=1, mfi=35.0, adx=20.0, rsi=45.0, ema_200=100.0
        )

        action = adapter._check_bear_regime_exit_action(context, market_data, is_long=True)

        assert action is None
        assert adapter.current_position.quantity == pytest.approx(1.0)

    def test_trend_hold_guard_does_not_suppress_bear_strong_exit(self):
        """Hard bear regime exits should remain active."""
        adapter = self._make_adapter(
            extra_config={
                "exit_on_bear_regime": True,
                "trend_hold_exit_guard_enabled": True,
                "trend_hold_guard_require_above_ema200": True,
            }
        )
        adapter.current_position = Position(
            symbol="BTC",
            entry_price=100.0,
            quantity=1.0,
            strategy="llm_direction",
            market="spot",
            timestamp=1,
        )
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_STRONG",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=30.0,
        )
        market_data = MarketData(
            symbol="BTC", close=105.0, timestamp=1, mfi=30.0, adx=30.0, rsi=40.0, ema_200=100.0
        )

        action = adapter._check_bear_regime_exit_action(context, market_data, is_long=True)

        assert action is not None
        assert action["fraction"] == pytest.approx(1.0)

    def test_trend_floor_signal_uses_configured_floor_size(self):
        """Trend floor entries should use their own smaller sizing."""
        adapter = self._make_adapter(
            extra_config={
                "trend_floor_entry_enabled": True,
                "trend_floor_position_size": 0.08,
                "trend_floor_min_adx": 12.0,
                "trend_floor_min_mfi": 45.0,
            }
        )
        ctx = TradingContext(
            symbol="BTC",
            timestamp=1,
            market=MarketData(
                symbol="BTC",
                close=105.0,
                mfi=55.0,
                adx=20.0,
                rsi=55.0,
                timestamp=1,
                ema_20=100.0,
                ema_120=95.0,
            ),
            regime=MarketContext(
                trend="BULL",
                regime="SIDEWAYS_UP",
                volatility_score=0.01,
                is_extreme_volatility=False,
                adx=20.0,
            ),
            positions={},
        )

        signal = adapter._maybe_build_trend_floor_signal(ctx, "LLM predicted HOLD")
        fraction, reason = adapter._resolve_entry_fraction(signal, atr=0.0, close=105.0)

        assert signal is not None
        assert signal.reason.startswith("TrendFloor entry")
        assert fraction == pytest.approx(0.08)
        assert "trend_floor_size:0.08" in reason

    def test_trend_floor_signal_blocks_until_required_ema_is_ready(self):
        """Trend floor readiness guard should block NaN EMA warmup periods."""
        adapter = self._make_adapter(
            extra_config={
                "trend_floor_entry_enabled": True,
                "trend_floor_position_size": 0.08,
                "trend_floor_min_adx": 12.0,
                "trend_floor_min_mfi": 45.0,
                "trend_floor_require_ema120_ready": True,
            }
        )
        ctx = TradingContext(
            symbol="BTC",
            timestamp=1,
            market=MarketData(
                symbol="BTC",
                close=105.0,
                mfi=55.0,
                adx=20.0,
                rsi=55.0,
                timestamp=1,
                ema_20=100.0,
                ema_120=float("nan"),
            ),
            regime=MarketContext(
                trend="BULL",
                regime="SIDEWAYS_UP",
                volatility_score=0.01,
                is_extreme_volatility=False,
                adx=20.0,
            ),
            positions={},
        )

        signal = adapter._maybe_build_trend_floor_signal(ctx, "LLM predicted HOLD")

        assert signal is None

    def test_entry_fallback_applies_to_low_confidence_hold(self):
        """A low-confidence HOLD reason should be eligible for configured fallback."""
        adapter = self._make_adapter(
            extra_config={
                "entry_fallback": {
                    "enabled": True,
                    "class": "RegimeLongV2EntryStrategy",
                    "on_non_buy": True,
                    "max_hold_confidence": 0.6,
                }
            }
        )

        assert adapter._should_apply_entry_fallback(
            "LLM predicted HOLD (conf=0.50): mixed signals"
        )

    def test_backtest_force_fallback_caches_offline_hold_decision(self):
        """Backtests can avoid live LLM calls and route into fallback deterministically."""
        adapter = self._make_adapter(extra_config={"backtest_force_entry_fallback": True})
        context = build_market_context(mfi=60.0, adx=25.0, atr=1.0, close=100.0)
        market_data = MagicMock()
        market_data.symbol = "BTC"
        market_data.timestamp = 123
        ctx = adapter._build_trading_context(market_data, context, with_position=False)

        assert adapter._cache_forced_fallback_decision(ctx) is True
        decision = adapter.entry_strategy.get_last_decision("BTC")
        assert decision is not None
        assert decision.provider == "offline"
        assert decision.reason == "Backtest forced fallback"


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
