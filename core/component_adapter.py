"""Adapter to bridge Component-based Strategies with the Functional Backtester.

This allows the historical backtester to run the exact same logic as live trading.

Supports regime filtering:
- v1: Basic regime classification (default)
- v2: EnhancedRegimeRouter with BBW + Volume + MTF filters
"""
from dataclasses import replace
from types import MappingProxyType
from typing import Dict, Any, Callable, Optional
import pandas as pd
from trading.strategies.components.models import MarketData, Position, Signal, MarketContext, TradingContext, build_market_context
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.strategies.volatility_tracker import VolatilityTracker
from trading.strategies.components.regime_filter import EnhancedRegimeRouter
from trading.strategies.components.rf_probability_service import RFProbabilityService

class ComponentStrategyAdapter:
    """Adapts a StrategyFactory strategy into a Backtester-compatible function.

    Supports regime filtering via config:
    - regime_version: "v1" (default) or "v2" (EnhancedRegimeRouter)
    - bbw_block_threshold: BBW percentile below which to block (default 25)
    - bbw_confirm_threshold: BBW percentile requiring confirmation (default 50)
    - volume_block_ratio: Volume ratio below which to block (default 0.8)
    - volume_boost_ratio: Volume ratio above which to boost confidence (default 1.2)
    - mtf_enabled: Whether to check 4h direction alignment (default True)
    """

    def __init__(self, factory: StrategyFactory, strategy_name: str, config: Dict[str, Any]):
        """
        Args:
            factory: Initialized StrategyFactory
            strategy_name: Name of the strategy to run (e.g., "v35_long")
            config: Configuration dictionary for the strategy
        """
        self.strategy_name = strategy_name
        self.config = config
        self.entry_strategy, self.exit_strategy = factory.create_components(
            strategy_name=strategy_name,
            config=config,
            persistent=False  # Backtesting is always non-persistent (stateless run)
        )
        self.market = factory.get_market(strategy_name)
        self.current_position: Optional[Position] = None
        self.high_water_mark: Optional[float] = None
        self.symbol = "BTC" # Default, will be updated if possible
        self.vol_tracker = VolatilityTracker(window=20)

        # Initialize regime filter based on regime_version config
        self._regime_router: Optional[EnhancedRegimeRouter] = None
        self._v2_entry_allowed: bool = True  # Default: allow entry
        regime_version = config.get('regime_version', 'v1')
        if regime_version == 'v2':
            self._regime_router = EnhancedRegimeRouter(
                bbw_block_threshold=config.get('bbw_block_threshold', 25),
                bbw_confirm_threshold=config.get('bbw_confirm_threshold', 50),
                bbw_window=config.get('bbw_window', 100),
                volume_block_ratio=config.get('volume_block_ratio', 0.8),
                volume_boost_ratio=config.get('volume_boost_ratio', 1.2),
                mtf_enabled=config.get('mtf_enabled', True),
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
        self._current_leverage: float = 3.0  # Current leverage (updated dynamically)

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
        self._v2_exit_on_filter: bool = config.get('v2_exit_on_filter', False)  # Exit when v2 blocks

        # === NEW: Regime Probability Filter ===
        # Use RF confidence (if available) or MFI proxy for bullish probability
        # Block entry if bull probability < threshold
        self._bull_prob_threshold: float = config.get('bull_prob_threshold', 0.0)  # 0 = disabled
        self._bull_prob_enabled: bool = self._bull_prob_threshold > 0

        # === NEW: RF Probability Integration ===
        # Use actual RF (RandomForest) confidence from HybridPredictor instead of MFI proxy
        self._use_rf_probability: bool = config.get('use_rf_probability', False)
        self._rf_service: RFProbabilityService | None = None
        self._rf_available: bool = False
        self._df_history: list = []  # Store recent candles for RF input
        self._rf_history_size: int = 720  # Rolling window for RF (matches LiveScaler)

        if self._use_rf_probability:
            self._rf_service = RFProbabilityService.get_instance(
                lstm_path=config.get('lstm_model_path', 'lstm_trainer/models/hybrid_lstm.pth'),
                rf_path=config.get('rf_model_path', 'lstm_trainer/models/noise_filter_rf.pkl'),
            )
            self._rf_available = self._rf_service.is_available()

        # RF prediction cache for backtesting (populated by precompute_rf_predictions)
        self._rf_cache: dict[int, dict] | None = None

        # === NEW: Dynamic Position Sizing based on RF Confidence ===
        # Scale position size based on model confidence:
        # High confidence (>70%) → large position, Low confidence (<50%) → small position
        self._dynamic_position_sizing: bool = config.get('dynamic_position_sizing', False)
        self._position_size_high: float = config.get('position_size_high', 0.30)   # 30% at high confidence
        self._position_size_mid: float = config.get('position_size_mid', 0.15)     # 15% at medium confidence
        self._position_size_low: float = config.get('position_size_low', 0.05)     # 5% at low confidence
        self._position_conf_low: float = config.get('position_conf_low', 0.50)     # Below this = low
        self._position_conf_high: float = config.get('position_conf_high', 0.70)   # Above this = high

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

    def precompute_rf_predictions(self, df: pd.DataFrame) -> None:
        """Pre-compute RF predictions for entire DataFrame (backtest optimization).

        Call this BEFORE running backtest loop to cache all RF predictions.
        Reduces backtest time from O(n*inference_time) to O(n) + O(batch_time).

        Args:
            df: Full DataFrame with OHLCV and indicators for backtest.
        """
        if not self._use_rf_probability or not self._rf_available or self._rf_service is None:
            return

        self._rf_cache = self._rf_service.precompute_batch(
            df=df,
            indicators_df=df,  # Same df has indicators
            window_size=self._rf_history_size,
            min_history=60,
        )

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

        # Decrement cooldown counter each candle
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        # Decrement loss pause counter each candle
        if self._loss_pause_remaining > 0:
            self._loss_pause_remaining -= 1

        # Extract indicators for context building
        mfi = row.get('mfi', 50.0)
        adx = row.get('adx', 20.0)
        atr = row.get('atr', 0.0)
        close = row['close']
        volume = row.get('volume', 0.0)
        avg_volume = row.get('avg_volume_20', 0.0)

        # === RF Probability Calculation ===
        # Get RF confidence from pre-computed cache (backtest) or live computation
        rf_confidence = 0.0
        rf_direction = "SIDEWAYS"
        rf_signal = "HOLD"

        if self._use_rf_probability:
            # Option 1: Read from pre-computed cache (backtest mode - fastest)
            if self._rf_cache is not None and i in self._rf_cache:
                cached_result = self._rf_cache[i]
                rf_confidence = cached_result.get('confidence', 0.0)
                rf_direction = cached_result.get('direction', 'SIDEWAYS')
                rf_signal = cached_result.get('signal', 'HOLD')
            # Option 2: Read from pre-computed DataFrame columns (alternative)
            elif 'rf_confidence' in df.columns:
                rf_confidence = float(row.get('rf_confidence', 0.0))
                rf_direction = str(row.get('rf_direction', 'SIDEWAYS'))
                rf_signal = str(row.get('rf_signal', 'HOLD'))
            # Option 3: Live mode - compute on-the-fly (slowest)
            elif self._rf_available and self._rf_service is not None:
                start_idx = max(0, i - self._rf_history_size)
                df_slice = df.iloc[start_idx:i+1]

                if len(df_slice) >= 60:
                    volatility = atr / close if close > 0 else 0.0
                    rf_result = self._rf_service.get_probability(
                        df=df_slice,
                        mfi=mfi,
                        adx=adx,
                        volatility=volatility,
                        regime=str(row.get('regime', 'SIDEWAYS_FLAT')),
                        breakout_signal=int(row.get('breakout_signal', 0)),
                    )
                    if rf_result.get('available', False):
                        rf_confidence = rf_result.get('confidence', 0.0)
                        rf_direction = rf_result.get('direction', 'SIDEWAYS')
                        rf_signal = rf_result.get('signal', 'HOLD')

        # Build Context using the standard function (ensures consistent regime/trend classification)
        # Includes drawdown-based BEAR detection (15% from recent high = BEAR override)
        context = build_market_context(
            mfi=mfi,
            adx=adx,
            atr=atr,
            close=close,
            volume=volume,
            avg_volume=avg_volume,
            # Use 30-day high for drawdown detection (fall back to 20-period if not available)
            recent_high=row.get('high_30d', 0.0) or row.get('prev_high_20', 0.0),
            # RF probability from HybridPredictor
            rf_confidence=rf_confidence,
            rf_direction=rf_direction,
            rf_signal=rf_signal,
        )

        # Regime v2 filtering: replace regime classification (matches live task behavior)
        self._v2_entry_allowed = True  # Used only for optional v2_exit_on_filter
        volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        if self._regime_router is not None:
            bb_upper = row.get('bb_upper', 0.0)
            bb_lower = row.get('bb_lower', 0.0)
            bb_middle = row.get('bb_middle', 0.0)

            filtered_regime = self._regime_router.get_regime(
                mfi=mfi,
                adx=adx,
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                bb_middle=bb_middle,
                volume_ratio=volume_ratio,
            )

            final_regime = filtered_regime
            final_trend = context.trend

            if context.is_drawdown_bear and filtered_regime not in ("BEAR_STRONG", "BEAR_MODERATE"):
                final_regime = "BEAR_STRONG" if context.adx >= 25 else "BEAR_MODERATE"
                final_trend = "BEAR"
            else:
                if final_regime in ("BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"):
                    final_trend = "BULL"
                elif final_regime in ("BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN"):
                    final_trend = "BEAR"
                else:
                    final_trend = "SIDEWAYS"

            context = MarketContext(
                trend=final_trend,
                regime=final_regime,
                volatility_score=context.volatility_score,
                is_extreme_volatility=context.is_extreme_volatility,
                adx=context.adx,
                volume_ratio=context.volume_ratio,
                is_high_volume=context.is_high_volume,
                drawdown=context.drawdown,
                is_drawdown_bear=context.is_drawdown_bear,
                rf_confidence=context.rf_confidence,
                rf_direction=context.rf_direction,
                rf_signal=context.rf_signal,
            )

        if self._v2_exit_on_filter and self._regime_router is not None:
            if context.regime in ("BULL_STRONG", "BULL_MODERATE"):
                if self._regime_router._volume_filter.should_block(volume_ratio, context.regime):
                    self._v2_entry_allowed = False

                bbw_boosted = self._regime_router._volume_filter.is_boosted(volume_ratio)
                if not bbw_boosted and self._regime_router._bbw_filter.should_block():
                    self._v2_entry_allowed = False

        # Extract indicators
        indicators = {}
        for k, v in row.items():
            if isinstance(k, str) and k.startswith(('ema', 'adx', 'rsi', 'plus', 'minus', 'bb')):
                indicators[k] = v

        # Explicit mapping for ShortV1 alias 'ema_fast'/'ema_slow'
        if self.config:
            ema_fast_len = self.config.get('ema_fast')
            ema_slow_len = self.config.get('ema_slow')
            if ema_fast_len:
                col = f"ema_{ema_fast_len}"
                if col in row: indicators['ema_fast'] = row[col]
            if ema_slow_len:
                col = f"ema_{ema_slow_len}"
                if col in row: indicators['ema_slow'] = row[col]

            # Map DI/ADX slope if needed and present
            if 'plus_di' in row: indicators['plus_di'] = row['plus_di']
            if 'minus_di' in row: indicators['minus_di'] = row['minus_di']
            if 'adx_slope' in row: indicators['adx_slope'] = row['adx_slope']

        # 1. MarketData construction with all fields needed by entry strategies
        # Handle timestamp conversion
        ts = row.get('timestamp', 0)
        if hasattr(ts, 'timestamp'):
            ts = int(ts.timestamp() * 1000)
        else:
            ts = int(ts) if ts else 0

        market_data = MarketData(
            symbol=self.symbol,
            close=close,
            timestamp=ts,
            mfi=mfi,
            adx=adx,
            rsi=row.get('rsi', 50.0),
            # OHLCV for breakout/sequence models
            open=float(row.get('open', close)) if pd.notna(row.get('open', close)) else close,
            high=row.get('high', 0.0) or 0.0,
            low=row.get('low', 0.0) or 0.0,
            volume=volume,
            # MACD for momentum entry
            macd=row.get('macd', 0.0),
            macd_signal=row.get('macd_signal', 0.0),
            # Stochastic for conservative entry
            stoch_k=row.get('stoch_k', 50.0),
            stoch_d=row.get('stoch_d', 50.0),
            # Bollinger Bands for range entry
            bb_upper=row.get('bb_upper', 0.0),
            bb_lower=row.get('bb_lower', 0.0),
            bb_middle=row.get('bb_middle', 0.0),
            # Volume for breakout entry
            avg_volume_20=avg_volume,
            # Support/resistance levels
            prev_high_20=row.get('prev_high_20', 0.0),
            prev_low_20=row.get('prev_low_20', 0.0),
            # ATR for volatility
            atr=atr,
            # EMA for trend filter
            ema_120=row.get('ema_120', 0.0),
            ema_200=row.get('ema_200', 0.0),
            # Market stress indicator
            market_stress=row.get('market_stress', 0.0),
            # 30-day high for drawdown-based BEAR detection
            high_30d=row.get('high_30d', 0.0),
            # Volatility breakout (Larry Williams strategy)
            breakout_signal=int(row.get('breakout_signal', 0)) if pd.notna(row.get('breakout_signal')) else 0,
            target_price=float(row.get('target_price', 0.0)) if pd.notna(row.get('target_price')) else 0.0,
            # Indicators map and HWM
            indicators=indicators,
            high_water_mark=self.high_water_mark
        )

        # 2. Check Exits first (if we have a position)
        if self.current_position:
            # Update high water mark
            is_long = getattr(self.current_position, 'side', 'long') == 'long'

            if is_long:
                if self.high_water_mark is None or close > self.high_water_mark:
                    self.high_water_mark = close
            else:
                if self.high_water_mark is None or close < self.high_water_mark:
                    self.high_water_mark = close

            # Create new MarketData with updated HWM (frozen dataclass)
            market_data = replace(market_data, high_water_mark=self.high_water_mark)

            # === PORTFOLIO DRAWDOWN PROTECTION ===
            # Graduated response to portfolio-level drawdown (capital preservation)
            # This is CRITICAL for MDD control - triggers BEFORE other exit logic
            if self._drawdown_enabled and self._current_drawdown_pct > 0:
                # Level 3: FULL EXIT at drawdown_exit_pct (default 12%)
                if self._current_drawdown_pct >= self._drawdown_exit_pct:
                    self.current_position = None
                    self.high_water_mark = None
                    try:
                        self.exit_strategy.on_position_closed(self.symbol)
                    except Exception:
                        pass
                    # Trigger extended pause after drawdown exit
                    self._loss_pause_remaining = self._loss_pause_candles
                    return {
                        'action': 'sell' if is_long else 'close_short',
                        'fraction': 1.0,
                        'reason': f'DRAWDOWN_EXIT: {self._current_drawdown_pct:.1f}% >= {self._drawdown_exit_pct:.1f}%'
                    }

                # Level 2: PARTIAL EXIT at drawdown_reduce_pct (default 10%)
                if self._current_drawdown_pct >= self._drawdown_reduce_pct and not self._partial_exit_done:
                    self._partial_exit_done = True
                    # Don't clear position - just reduce by configured fraction
                    return {
                        'action': 'sell' if is_long else 'close_short',
                        'fraction': self._drawdown_partial_exit_fraction,
                        'reason': (
                            f'DRAWDOWN_REDUCE: {self._current_drawdown_pct:.1f}% >= '
                            f'{self._drawdown_reduce_pct:.1f}%'
                        )
                    }

                # Level 1: WARNING at drawdown_warning_pct (default 8%)
                # This reduces leverage for FUTURE entries (not immediate action)
                # The leverage reduction is applied when checking entry below

            # === V2 Filter Exit for Existing Positions ===
            # If v2 filter blocks AND we have a position, exit to protect capital
            if self._v2_exit_on_filter and self._regime_router is not None and not self._v2_entry_allowed:
                self.current_position = None
                self.high_water_mark = None
                try:
                    self.exit_strategy.on_position_closed(self.symbol)
                except Exception:
                    pass
                return {
                    'action': 'sell' if is_long else 'close_short',
                    'fraction': 1.0,
                    'reason': 'v2_filter_protective_exit'
                }

            # === MA120 Panic Sell: Force exit when price < EMA120 ===
            # More aggressive MDD defense than EMA200
            ema_120 = row.get('ema_120', 0.0)
            if self._panic_sell_below_ma120 and is_long and ema_120 > 0 and close < ema_120:
                self.current_position = None
                self.high_water_mark = None
                try:
                    self.exit_strategy.on_position_closed(self.symbol)
                except Exception:
                    pass
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'MA120 panic_sell: close={close:.0f} < ema120={ema_120:.0f}'
                }

            # EMA200 protective exit: close long positions when price drops below EMA200
            # This defends against major drawdowns in bear markets
            ema_200 = row.get('ema_200', 0.0)
            if self._cash_below_ema200 and is_long and ema_200 > 0 and close < ema_200:
                self.current_position = None
                self.high_water_mark = None
                try:
                    self.exit_strategy.on_position_closed(self.symbol)
                except Exception:
                    pass
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'EMA200 protective exit: close={close:.0f} < ema200={ema_200:.0f}'
                }

            # Build TradingContext for new interface (immutable positions)
            positions = {self.strategy_name: self.current_position}
            ctx = TradingContext(
                symbol=self.symbol,
                timestamp=market_data.timestamp,
                market=market_data,
                regime=context,
                positions=MappingProxyType(positions),
            )
            signal = self.exit_strategy.check_exit(ctx, self.current_position)

            if signal:
                action = 'close_short' if not is_long else 'sell'
                reason = signal.reason or ""

                # Support partial exits: use signal.quantity vs current_position.quantity
                exit_qty = getattr(signal, "quantity", None)
                if exit_qty is not None and self.current_position and self.current_position.quantity > 0:
                    try:
                        exit_qty = float(exit_qty)
                        current_qty = float(self.current_position.quantity)
                    except Exception:
                        exit_qty = None
                        current_qty = 0.0

                    if exit_qty is not None and current_qty > 0:
                        fraction = max(min(exit_qty / current_qty, 1.0), 0.0)
                        if fraction < 1.0:
                            remaining_qty = max(current_qty - exit_qty, 0.0)
                            self.current_position = replace(self.current_position, quantity=remaining_qty)
                            return {
                                'action': action,
                                'fraction': fraction,
                                'reason': reason,
                                'consecutive_losses': self._consecutive_losses,
                            }

                # Full exit
                self.current_position = None
                self.high_water_mark = None
                try:
                    self.exit_strategy.on_position_closed(self.symbol)
                except Exception:
                    pass

                # Detect stop loss exit and trigger cooldown + consecutive loss tracking
                is_stop_loss = "stop loss" in reason.lower() or "stoploss" in reason.lower()

                if is_stop_loss:
                    self._cooldown_remaining = self._cooldown_candles
                    # Track consecutive losses
                    self._consecutive_losses += 1
                    if self._consecutive_losses >= self._max_consecutive_losses:
                        # Trigger extended pause after multiple consecutive losses
                        self._loss_pause_remaining = self._loss_pause_candles
                        self._consecutive_losses = 0  # Reset counter after pause
                else:
                    # Profitable exit or non-stop-loss exit resets consecutive loss counter
                    self._consecutive_losses = 0

                return {
                    'action': action,
                    'fraction': 1.0,
                    'reason': reason,
                    'consecutive_losses': self._consecutive_losses,
                }

            return {'action': 'hold'}

        # 3. Check Entries (if no position)
        else:
            # === NEW: Loss pause check (after consecutive losses) ===
            if self._loss_pause_remaining > 0:
                return {'action': 'hold', 'reason': f'loss_pause:{self._loss_pause_remaining}'}

            # Stop loss cooldown: block entry if still in cooldown period
            if self._cooldown_remaining > 0:
                return {'action': 'hold', 'reason': f'cooldown:{self._cooldown_remaining}'}

            # Cash strategy: no entry in BEAR regime
            current_regime = context.regime
            if self._cash_in_bear and current_regime in ("BEAR_STRONG", "BEAR_MODERATE"):
                return {'action': 'hold', 'reason': 'cash_bear_regime'}

            # Cash strategy: no entry below EMA200
            ema_200 = row.get('ema_200', 0.0)
            if self._cash_below_ema200 and ema_200 > 0 and close < ema_200:
                return {'action': 'hold', 'reason': 'cash_below_ema200'}

            # === Bull Probability Filter ===
            # Use RF confidence (if available) or MFI proxy for bullish probability
            # Block entry if bull_prob < threshold (e.g., 0.6 = 60%)
            if self._bull_prob_enabled:
                # Use RF confidence if available, otherwise fall back to MFI proxy
                if self._use_rf_probability and context.rf_confidence > 0:
                    bull_prob = context.rf_confidence
                    prob_source = "rf"
                else:
                    bull_prob = mfi / 100.0  # MFI 0-100 -> 0.0-1.0
                    prob_source = "mfi"

                if bull_prob < self._bull_prob_threshold:
                    return {'action': 'hold', 'reason': f'bull_prob_low({prob_source}):{bull_prob:.2f}<{self._bull_prob_threshold:.2f}'}

            # NOTE: MA120 is used for EXIT only (panic sell), not for entry blocking
            # Entry blocking is handled by cash_below_ema200 (EMA200 filter)

            # Calculate dynamic leverage based on regime
            if self._dynamic_leverage_enabled:
                if current_regime == "BULL_STRONG":
                    self._current_leverage = self._leverage_bull_strong
                elif current_regime == "BULL_MODERATE":
                    self._current_leverage = self._leverage_bull_moderate
                elif current_regime in ("SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"):
                    self._current_leverage = self._leverage_sideways
                else:  # BEAR regimes
                    self._current_leverage = self._leverage_bear
                    if self._current_leverage == 0:
                        return {'action': 'hold', 'reason': 'dynamic_lev_zero'}
            else:
                self._current_leverage = 3.0  # Default

            # === DRAWDOWN WARNING: Reduce leverage when approaching drawdown limits ===
            # Apply leverage reduction when in warning zone (8%+ drawdown)
            if self._drawdown_enabled and self._current_drawdown_pct >= self._drawdown_warning_pct:
                original_leverage = self._current_leverage
                self._current_leverage *= self._drawdown_leverage_reduction
                # Log reduction (reason will be visible in backtest)
                # At 8%+ drawdown, reduce risk by cutting leverage in half

            # === NEW: Probability-based leverage adjustment ===
            # Override leverage based on MFI (bull probability proxy)
            # Higher MFI = higher confidence = allow higher leverage
            if self._prob_leverage_enabled:
                if mfi >= 70:
                    self._current_leverage = min(self._current_leverage, self._prob_leverage_max)
                elif mfi >= 60:
                    self._current_leverage = min(self._current_leverage, self._prob_leverage_high)
                elif mfi >= 50:
                    self._current_leverage = min(self._current_leverage, self._prob_leverage_mid)
                elif mfi >= 40:
                    self._current_leverage = min(self._current_leverage, self._prob_leverage_low)
                elif mfi >= 30:
                    self._current_leverage = min(self._current_leverage, self._prob_leverage_min)
                else:  # MFI < 30: no entry
                    return {'action': 'hold', 'reason': f'prob_lev_zero:mfi={mfi:.1f}'}

            # Build TradingContext for new interface (immutable positions)
            ctx = TradingContext(
                symbol=self.symbol,
                timestamp=market_data.timestamp,
                market=market_data,
                regime=context,
                positions=MappingProxyType({}),  # No position when checking entry
            )
            signal = self.entry_strategy.check_entry(ctx)

            if signal:
                is_short = signal.side == 'sell'
                pos_side = 'short' if is_short else 'long'

                # Create simulated position
                ts_ms = int(row['timestamp'].timestamp() * 1000) if hasattr(row['timestamp'], 'timestamp') else 0

                self.current_position = Position(
                    symbol=self.symbol,
                    quantity=getattr(signal, "quantity", 1.0) or 1.0,
                    entry_price=row['close'],
                    side=pos_side,
                    strategy=self.strategy_name,
                    market="futures",  # Default for backtesting context unless specified
                    timestamp=ts_ms
                )
                self.high_water_mark = row['close']

                # Notify exit strategy (stateful exits may track entry)
                try:
                    self.exit_strategy.on_position_opened(self.current_position)
                except Exception:
                    pass

                # Use action names expected by backtest_runner:
                # 'buy' for opening long, 'open_short' for opening short
                action = "open_short" if is_short else "buy"
                fraction = getattr(signal, "quantity", 1.0) or 1.0

                # Align sizing with live task behavior
                use_dynamic = self.config.get("dynamic_sizing", False)
                position_pct = float(self.config.get("position_pct", 0.02))
                position_reason = ""
                if self._dynamic_position_sizing and use_dynamic:
                    rf_conf = context.rf_confidence if context.rf_confidence > 0 else 0.0
                    if rf_conf >= self._position_conf_high:
                        position_pct = self._position_size_high
                        position_reason = f"pos_high:{rf_conf:.2f}>={self._position_conf_high:.2f}"
                    elif rf_conf >= self._position_conf_low:
                        position_pct = self._position_size_mid
                        position_reason = f"pos_mid:{rf_conf:.2f}>={self._position_conf_low:.2f}"
                    else:
                        position_pct = self._position_size_low
                        position_reason = f"pos_low:{rf_conf:.2f}<{self._position_conf_low:.2f}"

                if use_dynamic:
                    fraction = position_pct
                else:
                    fraction = self.config.get("position_size", fraction)

                reason = signal.reason or ""
                if position_reason:
                    reason = f"{reason} | {position_reason}" if reason else position_reason

                return {
                    "action": action,
                    "fraction": fraction,
                    "price": close,
                    "reason": reason,
                    "leverage": self._current_leverage,  # Dynamic leverage
                    "regime": current_regime,  # For debugging
                    "rf_confidence": context.rf_confidence,  # For tracking
                }

        return {"action": "hold"}
