"""Adapter to bridge Component-based Strategies with the Functional Backtester.

This allows the historical backtester to run the exact same logic as live trading.

Supports regime filtering:
- v1: Basic regime classification (default)
- v2: EnhancedRegimeRouter with BBW + Volume + MTF filters
"""
# pylint: disable=logging-fstring-interpolation,broad-exception-caught,protected-access

from dataclasses import replace
import logging
from types import MappingProxyType
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd
from trading.strategies.components.models import MarketData, Position, Signal, MarketContext, TradingContext, build_market_context

logger = logging.getLogger(__name__)
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.strategies.volatility_tracker import VolatilityTracker
from trading.strategies.components.regime_filter import EnhancedRegimeRouter, MTFCandle

class ComponentStrategyAdapter:
    """Adapts a StrategyFactory strategy into a Backtester-compatible function.

    Supports regime filtering via config:
    - regime_version: "v2" (default, EnhancedRegimeRouter)
    - bbw_block_threshold: BBW percentile below which to block (default 25)
    - bbw_confirm_threshold: BBW percentile requiring confirmation (default 50)
    - volume_block_ratio: Volume ratio below which to block (default 0.8)
    - volume_boost_ratio: Volume ratio above which to boost confidence (default 1.2)
    - mtf_enabled: Whether to check 4h direction alignment (default True)
    """

    def __init__(
        self,
        factory: StrategyFactory,
        strategy_name: str,
        config: Dict[str, Any],
        entry_overrides: Dict[str, Any] | None = None,
        exit_overrides: Dict[str, Any] | None = None,
    ):
        """
        Args:
            factory: Initialized StrategyFactory
            strategy_name: Name of the strategy to run (e.g., "mlp_direction_btc")
            config: Configuration dictionary for the strategy
            entry_overrides: Parameter overrides for entry strategy
            exit_overrides: Parameter overrides for exit strategy
        """
        self.strategy_name = strategy_name
        self.config = config
        self.entry_strategy, self.exit_strategy = factory.create_components(
            strategy_name=strategy_name,
            config=config,
            persistent=False,  # Backtesting is always non-persistent (stateless run)
            entry_overrides=entry_overrides,
            exit_overrides=exit_overrides,
        )
        self.market = factory.get_market(strategy_name, config)
        self.current_position: Optional[Position] = None
        self.high_water_mark: Optional[float] = None
        self.symbol = "BTC" # Default, will be updated if possible
        self.vol_tracker = VolatilityTracker(window=20)
        entry_params_cfg = config.get("entry", {}).get("params", {}) if isinstance(config.get("entry"), dict) else {}
        def _cfg_value(key: str, default: Any) -> Any:
            if key in config:
                return config.get(key)
            return entry_params_cfg.get(key, default)

        # Initialize regime filter based on regime_version config
        self._regime_router: Optional[EnhancedRegimeRouter] = None
        self._v2_entry_allowed: bool = True  # Default: allow entry
        regime_version = config.get('regime_version', 'v2')
        if regime_version == 'v2':
            self._regime_router = EnhancedRegimeRouter(
                bbw_block_threshold=config.get('bbw_block_threshold', 25),
                bbw_confirm_threshold=config.get('bbw_confirm_threshold', 50),
                bbw_window=config.get('bbw_window', 100),
                volume_block_ratio=config.get('volume_block_ratio', 0.8),
                volume_boost_ratio=config.get('volume_boost_ratio', 1.2),
                mtf_enabled=config.get('mtf_enabled', True),
                bbw_enabled=config.get('bbw_enabled', True),
                volume_filter_enabled=config.get('volume_filter_enabled', True),
            )

        # Stop loss cooldown: prevent rapid re-entry after stop loss
        # Default: 24 candles (1 day for hourly data)
        self._cooldown_candles: int = config.get('stop_loss_cooldown', 24)
        self._cooldown_remaining: int = 0  # Candles remaining in cooldown

        # Dynamic leverage based on regime confidence
        # BULL_STRONG = max leverage, BEAR = no trade (cash)
        self._dynamic_leverage_enabled: bool = config.get('dynamic_leverage', False)
        self._leverage_bull_strong: float = config.get('leverage_bull_strong', 3.0)
        self._leverage_bull_moderate: float = config.get('leverage_bull_moderate', 2.0)
        self._leverage_sideways: float = config.get('leverage_sideways', 1.0)
        self._leverage_bear: float = config.get('leverage_bear', 0.0)  # 0 = no trade

        # Cash strategy: block entries in unfavorable conditions
        self._cash_in_bear: bool = config.get('cash_in_bear', False)  # No entry in BEAR
        self._cash_below_ema200: bool = config.get('cash_below_ema200', False)  # No entry below EMA200
        self._exit_on_bear_regime: bool = bool(_cfg_value("exit_on_bear_regime", False))
        # Spot-only default leverage.
        self._default_leverage: float = 1.0
        self._current_leverage: float = self._default_leverage

        # === NEW: Consecutive Loss Prevention ===
        # Track recent trade outcomes to pause after consecutive losses
        self._consecutive_losses: int = 0
        self._max_consecutive_losses: int = config.get('max_consecutive_losses', 3)
        self._loss_pause_candles: int = config.get('loss_pause_candles', 48)  # 48h pause after 3 losses
        self._loss_pause_remaining: int = 0

        # === Dynamic Drawdown Response ===
        # Graduated response to portfolio drawdown (not just price drawdown)
        self._drawdown_warning_pct: float = config.get('drawdown_warning_pct', 8.0)  # 8%: reduce leverage
        self._drawdown_reduce_pct: float = config.get('drawdown_reduce_pct', 10.0)   # 10%: exit 50%
        self._drawdown_exit_pct: float = config.get('drawdown_exit_pct', 12.0)       # 12%: full exit
        self._drawdown_enabled: bool = config.get('drawdown_enabled', True)  # Enable drawdown protection
        self._peak_equity: float = 0.0  # Track peak for drawdown calculation
        self._current_equity: float = 0.0
        self._current_drawdown_pct: float = 0.0  # Current drawdown percentage
        self._partial_exit_done: bool = False  # Track if 50% exit was triggered
        self._drawdown_partial_exit_fraction: float = float(
            config.get('drawdown_partial_exit_fraction', 0.5)
        )
        if self._drawdown_partial_exit_fraction <= 0:
            self._drawdown_partial_exit_fraction = 0.5
        elif self._drawdown_partial_exit_fraction > 1:
            self._drawdown_partial_exit_fraction = 1.0
        self._drawdown_leverage_reduction: float = float(
            config.get('drawdown_leverage_reduction', 0.5)
        )  # Reduce leverage by 50% at warning

        # === NEW: V2 Filter Exit for Existing Positions ===
        self._v2_exit_on_filter: bool = _cfg_value('v2_exit_on_filter', False)  # Exit when v2 blocks
        # P0: protective de-risk ladder to reduce tail loss
        self._protective_de_risk_enabled: bool = bool(_cfg_value("protective_de_risk_enabled", True))
        self._protective_de_risk_fraction: float = float(_cfg_value("protective_de_risk_fraction", 0.5))
        if self._protective_de_risk_fraction <= 0 or self._protective_de_risk_fraction >= 1:
            self._protective_de_risk_fraction = 0.5
        self._protective_de_risk_loss_pct: float = float(_cfg_value("protective_de_risk_loss_pct", 5.0))
        self._protective_force_exit_bars: int = int(_cfg_value("protective_force_exit_bars", 1))
        if self._protective_force_exit_bars < 1:
            self._protective_force_exit_bars = 1
        self._protective_force_exit_remaining: int = 0
        self._protective_ladder_active: bool = False

        # === NEW: Regime Probability Filter ===
        # Use RF confidence (if available) or MFI proxy for bullish probability
        # Block entry if bull probability < threshold
        self._bull_prob_threshold: float = config.get('bull_prob_threshold', 0.0)  # 0 = disabled
        self._bull_prob_enabled: bool = self._bull_prob_threshold > 0

        # MLP Direction prediction cache for backtesting
        # Populated by precompute_mlp_predictions()
        self._mlp_cache: dict[int, dict] | None = None
        self._mlp_model = None
        self._mlp_ensemble = None  # MLPEnsemblePredictor if configured
        self._mlp_available: bool | None = None
        self._uses_mlp_direction = (
            self.strategy_name.startswith("mlp_direction")
            or self.config.get("entry", {}).get("class") == "MLPDirectionEntryStrategy"
            or self.config.get("exit", {}).get("class") == "MLPDirectionExitStrategy"
            or self.entry_strategy.__class__.__name__ == "MLPDirectionEntryStrategy"
            or self.exit_strategy.__class__.__name__ == "MLPDirectionExitStrategy"
        )

        # === NEW: Dynamic Position Sizing based on RF Confidence ===
        # Scale position size based on model confidence:
        # High confidence (>70%) → large position, Low confidence (<50%) → small position

        # === NEW: Probability-based Leverage ===
        # Adjust leverage based on MFI (bull probability proxy)
        # Higher MFI = higher confidence = higher leverage
        self._prob_leverage_enabled: bool = config.get('prob_leverage_enabled', False)
        self._prob_leverage_max: float = config.get('prob_leverage_max', 3.0)      # MFI >= 70
        self._prob_leverage_high: float = config.get('prob_leverage_high', 2.5)    # MFI 60-70
        self._prob_leverage_mid: float = config.get('prob_leverage_mid', 2.0)      # MFI 50-60
        self._prob_leverage_low: float = config.get('prob_leverage_low', 1.0)      # MFI 40-50
        self._prob_leverage_min: float = config.get('prob_leverage_min', 0.5)      # MFI 30-40
        # MFI < 30 = no entry (leverage 0)

        # === NEW: MA120 Panic Sell ===
        # Force exit all positions when price drops below EMA120
        # More aggressive than EMA200 filter for MDD defense
        self._panic_sell_below_ma120: bool = config.get('panic_sell_below_ma120', False)

        # === Configurable Drawdown BEAR Threshold ===
        # Override regime to BEAR when price drops below this % from 30-day high
        # Default 0.15 (15%) can be too aggressive for bear markets
        # Set to 1.0 to effectively disable drawdown-based BEAR override
        self._drawdown_bear_threshold: float = config.get('drawdown_bear_threshold', 0.15)

        # Volatility-based position scaling (CTA vol-targeting)
        vol_cfg = config.get("volatility_sizing", {})
        self._vol_sizing_enabled: bool = vol_cfg.get("enabled", False)
        self._vol_target: float = vol_cfg.get("target_vol", 0.02)
        self._vol_min_scale: float = vol_cfg.get("min_scale", 0.25)
        self._vol_max_scale: float = vol_cfg.get("max_scale", 1.0)

        # P2: period-aware risk throttle (monthly)
        self._period_risk_enabled: bool = bool(_cfg_value("period_risk_enabled", False))
        self._period_reduce_threshold_pct: float = float(_cfg_value("period_reduce_threshold_pct", 8.0))
        self._period_reduce_scale: float = float(_cfg_value("period_reduce_scale", 0.7))
        if self._period_reduce_scale <= 0:
            self._period_reduce_scale = 0.5
        elif self._period_reduce_scale > 1:
            self._period_reduce_scale = 1.0
        self._period_loss_limit_pct: float = float(_cfg_value("period_loss_limit_pct", 12.0))
        if self._period_loss_limit_pct <= 0:
            self._period_loss_limit_pct = 12.0
        self._period_key: str | None = None
        self._period_start_equity: float = 0.0
        self._period_peak_equity: float = 0.0
        self._period_return_pct: float = 0.0
        self._period_drawdown_pct: float = 0.0

        # Regime classification thresholds (externalised for optimisation)
        self._regime_thresholds: Dict[str, float] = dict(config.get("regime_thresholds", {}))

    def update_equity(self, equity: float) -> None:
        """Update portfolio equity tracking for drawdown protection.

        Call this at the START of each candle BEFORE calling __call__().
        Tracks peak equity and calculates current drawdown percentage.

        Args:
            equity: Current portfolio equity (capital + unrealized PnL)
        """
        self._current_equity = equity

        # Update peak (only when equity increases)
        if equity > self._peak_equity:
            self._peak_equity = equity
            self._partial_exit_done = False  # Reset partial exit flag on new peak

        # Calculate current drawdown
        if self._peak_equity > 0:
            self._current_drawdown_pct = (self._peak_equity - equity) / self._peak_equity * 100
        else:
            self._current_drawdown_pct = 0.0

    def precompute_mlp_predictions(self, df: pd.DataFrame) -> None:
        """Pre-compute MLP Direction predictions for entire DataFrame (backtest optimization).

        Call this BEFORE running backtest loop to cache all MLP predictions.
        Supports both single model and ensemble prediction.

        Args:
            df: Full DataFrame with OHLCV and indicators for backtest.
        """
        # Only precompute for MLP Direction strategies
        if not self._uses_mlp_direction:
            return

        try:
            if not self._ensure_mlp_predictor():
                return
            valid_indices, features, use_ensemble = self._prepare_mlp_features(df)
            if len(valid_indices) == 0:
                return
            predictions, confidences, probs = self._predict_mlp_batch(features, use_ensemble)
            self._store_mlp_cache(df, valid_indices, predictions, confidences, probs)
        except Exception as e:
            logger.warning("MLP precompute failed: %s", e)
            self._mlp_available = False

    def _ensure_mlp_predictor(self) -> bool:
        from pathlib import Path

        ensemble_configs = self.config.get("ensemble_models", None)
        use_ensemble = bool(ensemble_configs and len(ensemble_configs) > 0)
        if use_ensemble:
            from trading.strategies.components.mlp_ensemble import MLPEnsemblePredictor

            if self._mlp_ensemble is None:
                self._mlp_ensemble = MLPEnsemblePredictor(ensemble_configs)
                self._mlp_available = self._mlp_ensemble.load(device="cpu")
            return self._mlp_available

        from mlp_trainer.src.mlp_model import MLPDirectionClassifier

        model_path = Path(self.config.get("model_path", "models/mlp_direction/model_final.pt"))
        if not model_path.exists():
            return False
        if self._mlp_model is None:
            self._mlp_model = MLPDirectionClassifier.load(str(model_path), device="cpu")
            self._mlp_model.eval()
            self._mlp_available = True
        return self._mlp_available

    def _prepare_mlp_features(self, df: pd.DataFrame) -> tuple[pd.Index, Any, bool]:
        from trading.indicators.mlp_features import FEATURE_SET_PAPER, calculate_mlp_features

        feature_set = self.config.get("mlp_feature_set", FEATURE_SET_PAPER)
        mlp_features = calculate_mlp_features(
            df,
            bwin=self.config.get("bwin", 5),
            include_temporal=True,
            feature_set=feature_set,
        )
        valid_indices = mlp_features.dropna().index
        features = mlp_features.loc[valid_indices].values if len(valid_indices) > 0 else mlp_features.iloc[0:0].values
        ensemble_configs = self.config.get("ensemble_models", None)
        use_ensemble = bool(ensemble_configs and len(ensemble_configs) > 0)
        return valid_indices, features, use_ensemble

    def _predict_mlp_batch(self, features: Any, use_ensemble: bool):
        if use_ensemble and self._mlp_ensemble is not None:
            return self._mlp_ensemble.predict_batch(features)
        probs = self._predict_single_model_probs(features)
        predictions = probs.argmax(axis=1)
        confidences = probs[np.arange(len(probs)), predictions]
        return predictions, confidences, probs

    def _predict_single_model_probs(self, features: Any):
        import torch

        X_tensor = torch.FloatTensor(features)
        with torch.no_grad():
            return self._mlp_model.predict_proba(X_tensor).cpu().numpy()

    def _store_mlp_cache(
        self,
        df: pd.DataFrame,
        valid_indices: pd.Index,
        predictions: Any,
        confidences: Any,
        probs: Any,
    ) -> None:
        self._mlp_cache = {}
        for df_idx, pred, conf, prob in zip(valid_indices, predictions, confidences, probs):
            iloc_pos = df.index.get_loc(df_idx)
            self._mlp_cache[iloc_pos] = {
                "prediction": int(pred),
                "confidence": float(conf),
                "probs": prob.tolist() if hasattr(prob, 'tolist') else list(prob),
            }

    def _determine_regime(self, mfi: float, adx: float) -> str:
        """Determine market regime using strategy-specific logic if available."""
        # Try to use the component's internal classification logic
        if hasattr(self.entry_strategy, '_classify_regime'):
            return self.entry_strategy._classify_regime(mfi, adx)

        # Fallback: Simple classification (should match default expectation)
        return "UNKNOWN"

    def __call__(self, df: pd.DataFrame, i: int, params: Dict = None) -> Dict[str, Any]:
        """Callable interface for Backtester.run(strategy_func)."""
        row = df.iloc[i]
        self._decrement_timers()
        self._update_period_risk_state(row)
        values = self._extract_row_values(row)
        mlp_prediction, mlp_confidence = self._get_cached_mlp_prediction(i)
        context = self._build_context(row, values)
        indicators = self._extract_indicators(row)
        market_data = self._build_market_data(row, values, indicators)

        if self.current_position:
            return self._evaluate_exit(
                row=row,
                market_data=market_data,
                context=context,
                mlp_prediction=mlp_prediction,
                mlp_confidence=mlp_confidence,
                values=values,
            )

        return self._evaluate_entry(
            row=row,
            market_data=market_data,
            context=context,
            mlp_prediction=mlp_prediction,
            mlp_confidence=mlp_confidence,
            values=values,
        )

    def _decrement_timers(self) -> None:
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
        if self._loss_pause_remaining > 0:
            self._loss_pause_remaining -= 1
        if self._protective_force_exit_remaining > 0:
            self._protective_force_exit_remaining -= 1

    def _update_period_risk_state(self, row: pd.Series) -> None:
        if not self._period_risk_enabled:
            return
        ts = row.get("timestamp")
        if ts is None:
            return
        try:
            ts_dt = pd.to_datetime(ts)
        except Exception:
            return
        period_key = ts_dt.strftime("%Y-%m")
        equity = float(self._current_equity) if self._current_equity > 0 else 0.0
        if equity <= 0:
            return

        if period_key != self._period_key:
            self._period_key = period_key
            self._period_start_equity = equity
            self._period_peak_equity = equity
            self._period_return_pct = 0.0
            self._period_drawdown_pct = 0.0
            return

        if equity > self._period_peak_equity:
            self._period_peak_equity = equity

        if self._period_start_equity > 0:
            self._period_return_pct = ((equity / self._period_start_equity) - 1.0) * 100.0
        else:
            self._period_return_pct = 0.0

        if self._period_peak_equity > 0:
            self._period_drawdown_pct = ((self._period_peak_equity - equity) / self._period_peak_equity) * 100.0
        else:
            self._period_drawdown_pct = 0.0

    def _extract_row_values(self, row: pd.Series) -> Dict[str, Any]:
        mfi = row.get("mfi", 50.0)
        adx = row.get("adx", 20.0)
        atr = row.get("atr", 0.0)
        close = row["close"]
        volume = row.get("volume", 0.0)
        avg_volume = row.get("avg_volume_20", 0.0)
        ts_value = row.get("timestamp", 0)
        if hasattr(ts_value, "timestamp"):
            candle_ts = int(ts_value.timestamp() * 1000)
        else:
            candle_ts = int(ts_value) if ts_value else 0
        return {
            "mfi": mfi,
            "adx": adx,
            "atr": atr,
            "close": close,
            "volume": volume,
            "avg_volume": avg_volume,
            "candle_ts": candle_ts,
        }

    def _get_cached_mlp_prediction(self, i: int) -> tuple[int | None, float | None]:
        if not self._uses_mlp_direction or self._mlp_cache is None or i not in self._mlp_cache:
            return None, None
        cached = self._mlp_cache[i]
        return cached.get("prediction"), cached.get("confidence")

    def _build_context(self, row: pd.Series, values: Dict[str, Any]) -> MarketContext:
        context = build_market_context(
            mfi=values["mfi"],
            adx=values["adx"],
            atr=values["atr"],
            close=values["close"],
            volume=values["volume"],
            avg_volume=values["avg_volume"],
            recent_high=row.get("high_30d", 0.0) or row.get("prev_high_20", 0.0),
            drawdown_bear_threshold=self._drawdown_bear_threshold,
            **self._regime_thresholds,
        )

        self._v2_entry_allowed = True
        volume_ratio = values["volume"] / values["avg_volume"] if values["avg_volume"] > 0 else 1.0
        if self._regime_router is not None:
            context = self._apply_v2_regime_filter(row, values, context, volume_ratio)

        if self._v2_exit_on_filter and self._regime_router is not None and context.regime in ("BULL_STRONG", "BULL_MODERATE"):
            if self._regime_router._volume_filter.should_block(volume_ratio, context.regime):
                self._v2_entry_allowed = False
            bbw_boosted = self._regime_router._volume_filter.is_boosted(volume_ratio)
            if not bbw_boosted and self._regime_router._bbw_filter.should_block():
                self._v2_entry_allowed = False

        return context

    def _apply_v2_regime_filter(
        self,
        row: pd.Series,
        values: Dict[str, Any],
        context: MarketContext,
        volume_ratio: float,
    ) -> MarketContext:
        close = values["close"]
        mfi = values["mfi"]
        adx = values["adx"]
        volume = values["volume"]
        self._regime_router.update_from_lower_candle(
            MTFCandle(
                open=float(row.get("open", close)) if pd.notna(row.get("open", close)) else close,
                high=float(row.get("high", close)) if pd.notna(row.get("high", close)) else close,
                low=float(row.get("low", close)) if pd.notna(row.get("low", close)) else close,
                close=float(close),
                volume=float(volume),
                mfi=float(mfi),
                adx=float(adx),
            ),
            candle_ts=values["candle_ts"],
        )
        filtered_regime = self._regime_router.get_regime(
            mfi=mfi,
            adx=adx,
            bb_upper=row.get("bb_upper", 0.0),
            bb_lower=row.get("bb_lower", 0.0),
            bb_middle=row.get("bb_middle", 0.0),
            volume_ratio=volume_ratio,
        )

        if context.is_drawdown_bear and filtered_regime not in ("BEAR_STRONG", "BEAR_MODERATE"):
            final_regime = "BEAR_STRONG" if context.adx >= 25 else "BEAR_MODERATE"
            final_trend = "BEAR"
        else:
            final_regime = filtered_regime
            if final_regime in ("BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"):
                final_trend = "BULL"
            elif final_regime in ("BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN"):
                final_trend = "BEAR"
            else:
                final_trend = "SIDEWAYS"

        return MarketContext(
            trend=final_trend,
            regime=final_regime,
            volatility_score=context.volatility_score,
            is_extreme_volatility=context.is_extreme_volatility,
            adx=context.adx,
            volume_ratio=context.volume_ratio,
            is_high_volume=context.is_high_volume,
            drawdown=context.drawdown,
            is_drawdown_bear=context.is_drawdown_bear,
        )

    def _extract_indicators(self, row: pd.Series) -> Dict[str, Any]:
        indicators: Dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(k, str) and k.startswith(("ema", "adx", "rsi", "plus", "minus", "bb", "trix")):
                indicators[k] = v
        self._augment_config_indicators(row, indicators)
        return indicators

    def _augment_config_indicators(self, row: pd.Series, indicators: Dict[str, Any]) -> None:
        if not self.config:
            return
        self._add_config_ema_indicator(row, indicators, "ema_fast", self.config.get("ema_fast"))
        self._add_config_ema_indicator(row, indicators, "ema_slow", self.config.get("ema_slow"))
        for key in ("plus_di", "minus_di", "adx_slope"):
            if key in row:
                indicators[key] = row[key]

    def _add_config_ema_indicator(self, row: pd.Series, indicators: Dict[str, Any], output_key: str, ema_len: Any) -> None:
        if not ema_len:
            return
        col = f"ema_{ema_len}"
        if col in row:
            indicators[output_key] = row[col]

    def _build_market_data(self, row: pd.Series, values: Dict[str, Any], indicators: Dict[str, Any]) -> MarketData:
        close = values["close"]
        return MarketData(
            symbol=self.symbol,
            close=close,
            timestamp=values["candle_ts"],
            mfi=values["mfi"],
            adx=values["adx"],
            rsi=row.get("rsi", 50.0),
            open=float(row.get("open", close)) if pd.notna(row.get("open", close)) else close,
            high=row.get("high", 0.0) or 0.0,
            low=row.get("low", 0.0) or 0.0,
            volume=values["volume"],
            macd=row.get("macd", 0.0),
            macd_signal=row.get("macd_signal", 0.0),
            stoch_k=row.get("stoch_k", 50.0),
            stoch_d=row.get("stoch_d", 50.0),
            bb_upper=row.get("bb_upper", 0.0),
            bb_lower=row.get("bb_lower", 0.0),
            bb_middle=row.get("bb_middle", 0.0),
            avg_volume_20=values["avg_volume"],
            prev_high_20=row.get("prev_high_20", 0.0),
            prev_low_20=row.get("prev_low_20", 0.0),
            atr=values["atr"],
            ema_5=row.get("ema_5", 0.0),
            ema_10=row.get("ema_10", 0.0),
            ema_20=row.get("ema_20", 0.0),
            ema_120=row.get("ema_120", 0.0),
            ema_200=row.get("ema_200", 0.0),
            market_stress=row.get("market_stress", 0.0),
            high_30d=row.get("high_30d", 0.0),
            breakout_signal=int(row.get("breakout_signal", 0)) if pd.notna(row.get("breakout_signal")) else 0,
            target_price=float(row.get("target_price", 0.0)) if pd.notna(row.get("target_price")) else 0.0,
            trix=float(row.get("trix", 0.0)) if pd.notna(row.get("trix")) else 0.0,
            trix_signal=float(row.get("trix_signal", 0.0)) if pd.notna(row.get("trix_signal")) else 0.0,
            trix_hist=float(row.get("trix_hist", 0.0)) if pd.notna(row.get("trix_hist")) else 0.0,
            indicators=indicators,
            high_water_mark=self.high_water_mark,
        )

    def _build_trading_context(
        self,
        market_data: MarketData,
        context: MarketContext,
        mlp_prediction: int | None,
        mlp_confidence: float | None,
        with_position: bool,
    ) -> TradingContext:
        positions = MappingProxyType(
            {self.strategy_name: self.current_position} if with_position and self.current_position else {}
        )
        return TradingContext(
            symbol=self.symbol,
            timestamp=market_data.timestamp,
            market=market_data,
            regime=context,
            positions=positions,
            mlp_prediction=mlp_prediction,
            mlp_confidence=mlp_confidence,
        )

    def _close_position(self) -> None:
        self.current_position = None
        self.high_water_mark = None
        self._protective_ladder_active = False
        self._protective_force_exit_remaining = 0
        try:
            self.exit_strategy.on_position_closed(self.symbol)
        except Exception as e:
            logger.debug(f"on_position_closed failed: {e}")

    def _evaluate_exit(
        self,
        row: pd.Series,
        market_data: MarketData,
        context: MarketContext,
        mlp_prediction: int | None,
        mlp_confidence: float | None,
        values: Dict[str, Any],
    ) -> Dict[str, Any]:
        close = values["close"]
        is_long = getattr(self.current_position, "side", "long") == "long"
        market_data = self._update_exit_hwm(market_data, close, is_long)

        force_exit = self._check_protective_force_exit_action(is_long)
        if force_exit is not None:
            return force_exit

        bear_exit = self._check_bear_regime_exit_action(context, close, is_long)
        if bear_exit is not None:
            return bear_exit

        protective_action = self._get_protective_exit_action(row, close, is_long)
        if protective_action is not None:
            return protective_action

        signal = self._run_exit_signal(market_data, context, mlp_prediction, mlp_confidence)
        if not signal:
            return {"action": "hold"}
        return self._finalize_exit_signal(signal, is_long)

    def _update_exit_hwm(self, market_data: MarketData, close: float, is_long: bool) -> MarketData:
        if is_long:
            if self.high_water_mark is None or close > self.high_water_mark:
                self.high_water_mark = close
        else:
            if self.high_water_mark is None or close < self.high_water_mark:
                self.high_water_mark = close
        return replace(market_data, high_water_mark=self.high_water_mark)

    def _get_protective_exit_action(
        self,
        row: pd.Series,
        close: float,
        is_long: bool,
    ) -> Dict[str, Any] | None:
        action = self._check_drawdown_exit_action(close, is_long)
        if action is not None:
            return action
        action = self._check_v2_filter_exit_action(close, is_long)
        if action is not None:
            return action
        return self._check_ma_exit_action(row, close, is_long)

    def _check_v2_filter_exit_action(self, close: float, is_long: bool) -> Dict[str, Any] | None:
        if not (self._v2_exit_on_filter and self._regime_router is not None and not self._v2_entry_allowed):
            return None
        return self._build_protective_exit_action(
            reason="v2_filter_protective_exit",
            close=close,
            is_long=is_long,
        )

    def _check_bear_regime_exit_action(
        self,
        context: MarketContext,
        close: float,
        is_long: bool,
    ) -> Dict[str, Any] | None:
        if not self._exit_on_bear_regime or not is_long:
            return None
        if context.regime not in ("BEAR_STRONG", "BEAR_MODERATE"):
            return None
        return self._build_protective_exit_action(
            reason=f"bear_regime_exit:{context.regime}",
            close=close,
            is_long=True,
        )

    def _check_ma_exit_action(
        self,
        row: pd.Series,
        close: float,
        is_long: bool,
    ) -> Dict[str, Any] | None:
        ema_120 = row.get("ema_120", 0.0)
        if self._panic_sell_below_ma120 and is_long and ema_120 > 0 and close < ema_120:
            return self._build_protective_exit_action(
                reason=f"MA120 panic_sell: close={close:.0f} < ema120={ema_120:.0f}",
                close=close,
                is_long=True,
            )

        ema_200 = row.get("ema_200", 0.0)
        if self._cash_below_ema200 and is_long and ema_200 > 0 and close < ema_200:
            return self._build_protective_exit_action(
                reason=f"EMA200 protective exit: close={close:.0f} < ema200={ema_200:.0f}",
                close=close,
                is_long=True,
            )

        return None

    def _run_exit_signal(
        self,
        market_data: MarketData,
        context: MarketContext,
        mlp_prediction: int | None,
        mlp_confidence: float | None,
    ) -> Signal | None:
        ctx = self._build_trading_context(
            market_data, context, mlp_prediction, mlp_confidence, with_position=True
        )
        return self.exit_strategy.check_exit(ctx, self.current_position)

    def _finalize_exit_signal(self, signal: Signal, is_long: bool) -> Dict[str, Any]:
        action = "close_short" if not is_long else "sell"
        reason = signal.reason or ""
        trigger_price = getattr(signal, "trigger_price", None)
        partial = self._maybe_handle_partial_exit(signal, action, reason, trigger_price)
        if partial is not None:
            return partial
        self._close_position()
        self._update_loss_tracking(reason)
        result = {
            "action": action,
            "fraction": 1.0,
            "reason": reason,
            "consecutive_losses": self._consecutive_losses,
        }
        if trigger_price is not None:
            result["price"] = trigger_price
        return result

    def _check_drawdown_exit_action(self, close: float, is_long: bool) -> Dict[str, Any] | None:
        if not (self._drawdown_enabled and self._current_drawdown_pct > 0):
            return None
        if self._current_drawdown_pct >= self._drawdown_exit_pct:
            self._loss_pause_remaining = self._loss_pause_candles
            return self._build_protective_exit_action(
                reason=f"DRAWDOWN_EXIT: {self._current_drawdown_pct:.1f}% >= {self._drawdown_exit_pct:.1f}%",
                close=close,
                is_long=is_long,
            )
        if self._current_drawdown_pct >= self._drawdown_reduce_pct and not self._partial_exit_done:
            self._partial_exit_done = True
            return {
                "action": "sell" if is_long else "close_short",
                "fraction": self._drawdown_partial_exit_fraction,
                "reason": f"DRAWDOWN_REDUCE: {self._current_drawdown_pct:.1f}% >= {self._drawdown_reduce_pct:.1f}%",
            }
        return None

    def _maybe_handle_partial_exit(
        self,
        signal: Signal,
        action: str,
        reason: str,
        trigger_price: float | None = None,
    ) -> Dict[str, Any] | None:
        exit_qty = getattr(signal, "quantity", None)
        if exit_qty is None or not self.current_position or self.current_position.quantity <= 0:
            return None
        try:
            exit_qty = float(exit_qty)
            current_qty = float(self.current_position.quantity)
        except Exception:
            return None
        if current_qty <= 0:
            return None

        fraction = max(min(exit_qty / current_qty, 1.0), 0.0)
        if fraction >= 1.0:
            return None

        remaining_qty = max(current_qty - exit_qty, 0.0)
        if remaining_qty < 1e-10:
            return None

        self.current_position = replace(self.current_position, quantity=remaining_qty)
        result = {
            "action": action,
            "fraction": fraction,
            "reason": reason,
            "consecutive_losses": self._consecutive_losses,
        }
        if trigger_price is not None:
            result["price"] = trigger_price
        return result

    def _check_protective_force_exit_action(self, is_long: bool) -> Dict[str, Any] | None:
        if not self._protective_ladder_active or self._protective_force_exit_remaining > 0:
            return None
        if self.current_position is None:
            self._protective_ladder_active = False
            return None
        self._close_position()
        return {
            "action": "sell" if is_long else "close_short",
            "fraction": 1.0,
            "reason": "PROTECTIVE_DE_RISK_STEP2_FORCE_EXIT",
        }

    def _build_protective_exit_action(
        self,
        reason: str,
        close: float,
        is_long: bool,
    ) -> Dict[str, Any]:
        action = "sell" if is_long else "close_short"
        should_ladder = self._should_apply_protective_ladder(close, is_long)
        if should_ladder:
            self._protective_ladder_active = True
            self._protective_force_exit_remaining = self._protective_force_exit_bars
            return {
                "action": action,
                "fraction": self._protective_de_risk_fraction,
                "reason": f"{reason} | PROTECTIVE_DE_RISK_STEP1",
            }

        self._close_position()
        return {
            "action": action,
            "fraction": 1.0,
            "reason": reason,
        }

    def _should_apply_protective_ladder(self, close: float, is_long: bool) -> bool:
        if not self._protective_de_risk_enabled or self._protective_ladder_active:
            return False
        if not is_long or self.current_position is None:
            return False
        entry_price = float(getattr(self.current_position, "entry_price", 0.0) or 0.0)
        if entry_price <= 0:
            return False
        loss_pct = ((close / entry_price) - 1.0) * 100.0
        return loss_pct <= -abs(self._protective_de_risk_loss_pct)

    def _update_loss_tracking(self, reason: str) -> None:
        is_stop_loss = "stop loss" in reason.lower() or "stoploss" in reason.lower()
        if is_stop_loss:
            self._cooldown_remaining = self._cooldown_candles
            self._consecutive_losses += 1
            if self._consecutive_losses >= self._max_consecutive_losses:
                self._loss_pause_remaining = self._loss_pause_candles
                self._consecutive_losses = 0
            return
        self._consecutive_losses = 0

    def _evaluate_entry(
        self,
        row: pd.Series,
        market_data: MarketData,
        context: MarketContext,
        mlp_prediction: int | None,
        mlp_confidence: float | None,
        values: Dict[str, Any],
    ) -> Dict[str, Any]:
        hold_reason = self._entry_hold_reason(row, context, values)
        if hold_reason is not None:
            return {"action": "hold", "reason": hold_reason}

        leverage = self._resolve_entry_leverage(context.regime, values["mfi"])
        if leverage is None:
            return {"action": "hold", "reason": "dynamic_lev_zero"}
        self._current_leverage = leverage

        ctx = self._build_trading_context(market_data, context, mlp_prediction, mlp_confidence, with_position=False)
        signal = self.entry_strategy.check_entry(ctx)
        if not signal:
            return {"action": "hold"}
        return self._open_position_from_signal(row, signal, values, context)

    def _entry_hold_reason(self, row: pd.Series, context: MarketContext, values: Dict[str, Any]) -> str | None:
        if self._loss_pause_remaining > 0:
            return f"loss_pause:{self._loss_pause_remaining}"
        if self._cooldown_remaining > 0:
            return f"cooldown:{self._cooldown_remaining}"
        if self._period_risk_enabled and self._period_return_pct <= -abs(self._period_loss_limit_pct):
            return (
                f"period_loss_guard:{self._period_return_pct:.1f}%"
                f"<={-abs(self._period_loss_limit_pct):.1f}%"
            )
        if self._cash_in_bear and context.regime in ("BEAR_STRONG", "BEAR_MODERATE"):
            return "cash_bear_regime"
        ema_200 = row.get("ema_200", 0.0)
        if self._cash_below_ema200 and ema_200 > 0 and values["close"] < ema_200:
            return "cash_below_ema200"
        if self._bull_prob_enabled:
            bull_prob = values["mfi"] / 100.0
            if bull_prob < self._bull_prob_threshold:
                return f"bull_prob_low(mfi):{bull_prob:.2f}<{self._bull_prob_threshold:.2f}"
        return None

    def _resolve_entry_leverage(self, current_regime: str, mfi: float) -> float | None:
        leverage = self._resolve_regime_leverage(current_regime)
        if leverage is None:
            return None
        leverage = self._apply_drawdown_leverage(leverage)
        return self._apply_probability_leverage(leverage, mfi)

    def _resolve_regime_leverage(self, current_regime: str) -> float | None:
        if not self._dynamic_leverage_enabled:
            return self._default_leverage
        if current_regime == "BULL_STRONG":
            return self._leverage_bull_strong
        if current_regime == "BULL_MODERATE":
            return self._leverage_bull_moderate
        if current_regime in ("SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"):
            return self._leverage_sideways
        return None if self._leverage_bear == 0 else self._leverage_bear

    def _apply_drawdown_leverage(self, leverage: float) -> float:
        if self._drawdown_enabled and self._current_drawdown_pct >= self._drawdown_warning_pct:
            return leverage * self._drawdown_leverage_reduction
        return leverage

    def _apply_probability_leverage(self, leverage: float, mfi: float) -> float | None:
        if not self._prob_leverage_enabled:
            return leverage
        if mfi >= 70:
            return min(leverage, self._prob_leverage_max)
        if mfi >= 60:
            return min(leverage, self._prob_leverage_high)
        if mfi >= 50:
            return min(leverage, self._prob_leverage_mid)
        if mfi >= 40:
            return min(leverage, self._prob_leverage_low)
        if mfi >= 30:
            return min(leverage, self._prob_leverage_min)
        return None

    def _open_position_from_signal(
        self,
        row: pd.Series,
        signal: Signal,
        values: Dict[str, Any],
        context: MarketContext,
    ) -> Dict[str, Any]:
        is_short = signal.side == "sell"
        ts_ms = self._extract_timestamp_ms(row)
        self.current_position = self._build_position_from_signal(signal, values["close"], is_short, ts_ms)
        self.high_water_mark = values["close"]
        self._notify_position_opened(ts_ms)

        fraction, position_reason = self._resolve_entry_fraction(signal, values["atr"], values["close"])
        reason = self._compose_entry_reason(signal.reason or "", position_reason)

        return {
            "action": "open_short" if is_short else "buy",
            "fraction": fraction,
            "price": values["close"],
            "reason": reason,
            "leverage": self._current_leverage,
            "regime": context.regime,
        }

    def _extract_timestamp_ms(self, row: pd.Series) -> int:
        ts_raw = row["timestamp"]
        return int(ts_raw.timestamp() * 1000) if hasattr(ts_raw, "timestamp") else 0

    def _build_position_from_signal(self, signal: Signal, close: float, is_short: bool, ts_ms: int) -> Position:
        entry_reason = getattr(signal, "reason", "") or ""
        strategy_with_reason = f"{self.strategy_name}|{entry_reason}" if entry_reason else self.strategy_name
        return Position(
            symbol=self.symbol,
            quantity=getattr(signal, "quantity", 1.0) or 1.0,
            entry_price=close,
            side="short" if is_short else "long",
            strategy=strategy_with_reason,
            market=self.market,
            timestamp=ts_ms,
            entry_time=ts_ms,
        )

    def _notify_position_opened(self, ts_ms: int) -> None:
        try:
            self.exit_strategy.on_position_opened(self.current_position, entry_timestamp=ts_ms)
        except TypeError:
            self.exit_strategy.on_position_opened(self.current_position)
        except Exception as e:
            logger.debug(f"on_position_opened failed: {e}")

    def _compose_entry_reason(self, base_reason: str, position_reason: str) -> str:
        if not position_reason:
            return base_reason
        return f"{base_reason} | {position_reason}" if base_reason else position_reason

    def _resolve_entry_fraction(self, signal: Signal, atr: float, close: float) -> tuple[float, str]:
        signal_qty = getattr(signal, "quantity", None)
        position_pct = float(self.config.get("position_pct", 0.02))
        use_signal_quantity = bool(self.config.get("use_signal_quantity", False))
        if use_signal_quantity and signal_qty is not None and signal_qty > 0:
            fraction = signal_qty
            position_reason = f"regime_size:{signal_qty:.2f}"
        else:
            fraction = position_pct
            position_reason = f"config_pct:{position_pct:.2f}"

        if self._vol_sizing_enabled and atr > 0 and close > 0:
            from trading.risk.volatility_scaler import compute_volatility_scale

            vol_scale = compute_volatility_scale(
                atr=atr,
                price=close,
                target_vol=self._vol_target,
                min_scale=self._vol_min_scale,
                max_scale=self._vol_max_scale,
            )
            fraction *= vol_scale
            position_reason += f" vol_scale:{vol_scale:.2f}"

        period_scale = self._period_risk_scale()
        if period_scale < 1.0:
            fraction *= period_scale
            position_reason += f" period_scale:{period_scale:.2f}"

        return fraction, position_reason

    def _period_risk_scale(self) -> float:
        if not self._period_risk_enabled:
            return 1.0
        if self._period_drawdown_pct >= abs(self._period_reduce_threshold_pct):
            return self._period_reduce_scale
        return 1.0
