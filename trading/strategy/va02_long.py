"""
Trading Engine V2 - VA02 Long Strategy
7-dimension score-based strategy with 74% win rate
Upbit Long 전략 (v-a-02 이식)
"""

import logging
import json
from typing import Optional, Dict, Any
from pathlib import Path
import pandas as pd
import numpy as np
from scipy.signal import argrelextrema

from .base import BaseStrategy
from ..core.config import Config
from core.types import Exchange, Direction, MarketState

logger = logging.getLogger(__name__)


class MarketClassifier:
    """시장 상태 분류기 (7레벨)"""

    def __init__(self, config: Dict):
        self.config = config
        self.mfi_bull_strong = config.get('mfi_bull_strong', 52)
        self.mfi_bull_moderate = config.get('mfi_bull_moderate', 45)
        self.mfi_sideways_up = config.get('mfi_sideways_up', 42)
        self.mfi_bear_moderate = config.get('mfi_bear_moderate', 38)
        self.mfi_bear_strong = config.get('mfi_bear_strong', 35)
        self.adx_strong_trend = config.get('adx_strong_trend', 20)
        self.adx_moderate_trend = config.get('adx_moderate_trend', 15)

    def classify(self, row: pd.Series) -> str:
        mfi = row.get('mfi', 50)
        adx = row.get('adx', 20)

        is_strong_trend = adx >= self.adx_strong_trend
        is_moderate_trend = adx >= self.adx_moderate_trend

        if mfi >= self.mfi_bull_strong and is_strong_trend:
            return 'BULL_STRONG'
        elif mfi >= self.mfi_bull_moderate and is_moderate_trend:
            return 'BULL_MODERATE'
        elif mfi >= self.mfi_sideways_up:
            return 'SIDEWAYS_UP'
        elif mfi >= self.mfi_bear_moderate:
            return 'SIDEWAYS_FLAT'
        elif mfi >= self.mfi_bear_strong:
            return 'SIDEWAYS_DOWN'
        elif is_strong_trend:
            return 'BEAR_STRONG'
        else:
            return 'BEAR_MODERATE'


class VA02ScoreEngine:
    """7-dimension score engine"""

    def __init__(self, config: Dict):
        self.config = config

        # Weights from config
        weights_config = config.get('weights', {})
        self.weights = {
            'rsi_oversold': weights_config.get('rsi_oversold', 8),
            'mfi_bullish': weights_config.get('mfi_bullish', 28),
            'volume_spike': weights_config.get('volume_spike', 8),
            'low_vol': weights_config.get('low_vol', 15),
            'local_min': weights_config.get('local_min', 20),
            'trend_following': weights_config.get('trend_following', 12),
            'mean_reversion': weights_config.get('mean_reversion', 10),
        }

        # Indicator thresholds from config
        ind_config = config.get('indicators', {})
        self.rsi_threshold = ind_config.get('rsi_threshold', 30)
        self.mfi_bullish_threshold = ind_config.get('mfi_bullish_threshold', 50)
        self.mfi_very_bullish_threshold = ind_config.get('mfi_very_bullish_threshold', 60)
        self.volume_spike_ratio = ind_config.get('volume_spike_ratio', 1.5)
        self.low_vol_atr_ratio = ind_config.get('low_vol_atr_ratio', 0.8)
        self.very_low_vol_atr_ratio = ind_config.get('very_low_vol_atr_ratio', 0.6)
        self.adx_trend_threshold = ind_config.get('adx_trend_threshold', 25)
        self.adx_strong_trend_threshold = ind_config.get('adx_strong_trend_threshold', 40)

        # Tier thresholds from config
        tier_config = config.get('tier_thresholds', {})
        self.tier_thresholds = {
            'S': tier_config.get('S', 28),
            'A': tier_config.get('A', 18),
            'B': tier_config.get('B', 12),
        }

    def calculate_score(self, row: pd.Series) -> tuple:
        """Calculate score for a single row"""
        score = 0
        signals = []

        # 1. RSI Oversold
        if row.get('rsi', 50) <= self.rsi_threshold:
            score += self.weights['rsi_oversold']
            signals.append('RSI_OVERSOLD')

        # 2. MFI Bullish (strongest signal)
        mfi = row.get('mfi', 50)
        if mfi >= self.mfi_bullish_threshold:
            score += self.weights['mfi_bullish']
            signals.append('MFI_BULLISH')

            if mfi >= self.mfi_very_bullish_threshold:
                score += int(self.weights['mfi_bullish'] * 0.2)
                signals.append('MFI_VERY_BULLISH')

        # 3. Volume Spike
        volume_ratio = row.get('volume_ratio', 1.0)
        if volume_ratio >= self.volume_spike_ratio:
            score += self.weights['volume_spike']
            signals.append('VOLUME_SPIKE')

        # 4. Low Volatility (compression = pre-breakout)
        atr_ratio = row.get('atr_ratio', 1.0)
        if atr_ratio <= self.low_vol_atr_ratio:
            score += self.weights['low_vol']
            signals.append('LOW_VOL')

            if atr_ratio <= self.very_low_vol_atr_ratio:
                score += int(self.weights['low_vol'] * 0.3)
                signals.append('VERY_LOW_VOL')

        # 5. Local Minima
        if row.get('is_local_min', False):
            score += self.weights['local_min']
            signals.append('LOCAL_MIN')

        # 6. Trend Following (ADX)
        adx = row.get('adx', 20)
        if adx >= self.adx_trend_threshold:
            score += self.weights['trend_following']
            signals.append('TREND_STRONG')

            if adx >= self.adx_strong_trend_threshold:
                score += int(self.weights['trend_following'] * 0.5)
                signals.append('TREND_VERY_STRONG')

        # 7. Mean Reversion (Bollinger Bands)
        close = row.get('close', 0)
        bb_lower = row.get('bb_lower', 0)
        bb_position = row.get('bb_position', 0.5)

        if bb_lower > 0 and close < bb_lower:
            score += self.weights['mean_reversion']
            signals.append('BB_LOWER')

        if bb_position <= 0.2:
            score += int(self.weights['mean_reversion'] * 0.5)
            signals.append('BB_OVERSOLD')

        return score, signals

    def classify_tier(self, score: int) -> str:
        """Classify tier based on score"""
        if score >= self.tier_thresholds['S']:
            return 'S'
        elif score >= self.tier_thresholds['A']:
            return 'A'
        elif score >= self.tier_thresholds['B']:
            return 'B'
        else:
            return 'C'


class VA02LongStrategy(BaseStrategy):
    """
    VA02 Long Strategy

    7-dimension score-based entry with tier classification.
    Active in BULL and SIDEWAYS regimes.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        strategy_config: Optional[Dict] = None,
    ):
        # Load strategy config from file if not provided
        if strategy_config is None:
            config_path = Path(__file__).parent.parent.parent / 'config' / 'strategies' / 'va02_long.json'
            if config_path.exists():
                with open(config_path) as f:
                    strategy_config = json.load(f)
            else:
                strategy_config = {}

        super().__init__(
            strategy_name="va02-long",
            exchange=Exchange.UPBIT,
            direction=Direction.LONG,
            symbol="KRW-BTC",
            config=config,
            strategy_config=strategy_config,
        )

        # Initialize components
        classifier_config = strategy_config.get('classifier', {})
        self.classifier = MarketClassifier(classifier_config)
        self.score_engine = VA02ScoreEngine(strategy_config)

        # Entry tier threshold (default A-tier)
        tier_threshold = strategy_config.get('tier_threshold', 'A')
        self.entry_tier_threshold = self.score_engine.tier_thresholds.get(tier_threshold, 18)

        # Exit settings
        exit_config = strategy_config.get('exit', {})
        self.take_profit = exit_config.get('take_profit', 0.03)
        self.stop_loss = exit_config.get('stop_loss', 0.02)
        self.trailing_stop = exit_config.get('trailing_stop', 0.015)
        self.exit_tier = exit_config.get('tier_exit', 'C')
        self.exit_tier_threshold = self.score_engine.tier_thresholds.get(self.exit_tier, 0)

        # Position tracking
        self.highest_price = 0.0
        self.current_score = 0
        self.current_tier = 'C'

        logger.info(f"VA02LongStrategy initialized")
        logger.info(f"  Entry threshold: {tier_threshold} (score >= {self.entry_tier_threshold})")
        logger.info(f"  Take profit: {self.take_profit:.1%}, Stop loss: {self.stop_loss:.1%}")

    def _min_buffer_size(self) -> int:
        """Minimum buffer size for indicators"""
        return 50

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all required indicators"""
        try:
            import talib
        except ImportError as e:
            logger.error(f"talib not installed: {e}")
            raise ImportError("talib is required for VA02 strategy. Install with: pip install TA-Lib")

        try:
            # RSI
            df['rsi'] = talib.RSI(df['close'].values, timeperiod=14)

            # MFI
            df['mfi'] = talib.MFI(
                df['high'].values,
                df['low'].values,
                df['close'].values,
                df['volume'].values,
                timeperiod=14
            )

            # ADX
            df['adx'] = talib.ADX(
                df['high'].values,
                df['low'].values,
                df['close'].values,
                timeperiod=14
            )

            # ATR
            df['atr'] = talib.ATR(
                df['high'].values,
                df['low'].values,
                df['close'].values,
                timeperiod=14
            )
            atr_ma = df['atr'].rolling(20).mean()
            df['atr_ratio'] = np.where(atr_ma > 0, df['atr'] / atr_ma, 1.0)

            # Bollinger Bands
            df['bb_upper'], df['bb_middle'], df['bb_lower'] = talib.BBANDS(
                df['close'].values,
                timeperiod=20,
                nbdevup=2,
                nbdevdn=2
            )
            bb_range = df['bb_upper'] - df['bb_lower']
            df['bb_position'] = np.where(bb_range > 0, (df['close'] - df['bb_lower']) / bb_range, 0.5)

            # Volume ratio
            vol_ma = df['volume'].rolling(20).mean()
            df['volume_ratio'] = np.where(vol_ma > 0, df['volume'] / vol_ma, 1.0)

            # Local minima
            df = self._add_local_minima(df)

        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            raise

        return df

    def _add_local_minima(self, df: pd.DataFrame, order: int = 5) -> pd.DataFrame:
        """Add local minima detection"""
        df = df.reset_index(drop=True)

        # Local minima on low prices
        local_min_indices = argrelextrema(df['low'].values, np.less, order=order)[0]
        df['is_local_min'] = False
        if len(local_min_indices) > 0:
            df.loc[local_min_indices, 'is_local_min'] = True

        return df

    def generate_signal(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """Generate trading signal"""
        if i < self._min_buffer_size():
            return None

        row = df.iloc[i]
        prev_row = df.iloc[i - 1] if i > 0 else row

        # Classify market regime
        market_state = self.classifier.classify(row)

        # Only trade in BULL or SIDEWAYS
        if market_state.startswith('BEAR'):
            return {
                'action': 'hold',
                'reason': 'VA02_BEAR_SKIP',
                'market_state': market_state,
            }

        # Calculate score
        score, signals = self.score_engine.calculate_score(row)
        tier = self.score_engine.classify_tier(score)

        self.current_score = score
        self.current_tier = tier

        current_price = row['close']

        # ========== Exit Logic ==========
        if self.in_position:
            # Update highest price for trailing stop
            if current_price > self.highest_price:
                self.highest_price = current_price

            # Take profit
            pnl_pct = (current_price - self.entry_price) / self.entry_price
            if pnl_pct >= self.take_profit:
                self.clear_position()
                return {
                    'action': 'sell',
                    'reason': f'VA02_TAKE_PROFIT_{pnl_pct:.1%}',
                    'fraction': 1.0,
                    'score': score,
                    'tier': tier,
                    'market_state': market_state,
                }

            # Stop loss
            if pnl_pct <= -self.stop_loss:
                self.clear_position()
                return {
                    'action': 'sell',
                    'reason': f'VA02_STOP_LOSS_{pnl_pct:.1%}',
                    'fraction': 1.0,
                    'score': score,
                    'tier': tier,
                    'market_state': market_state,
                }

            # Trailing stop
            drawdown = (self.highest_price - current_price) / self.highest_price
            if drawdown >= self.trailing_stop and pnl_pct > 0:
                self.clear_position()
                return {
                    'action': 'sell',
                    'reason': f'VA02_TRAILING_STOP_{drawdown:.1%}',
                    'fraction': 1.0,
                    'score': score,
                    'tier': tier,
                    'market_state': market_state,
                }

            # Tier-based exit (score degradation)
            if score < self.exit_tier_threshold:
                self.clear_position()
                return {
                    'action': 'sell',
                    'reason': f'VA02_TIER_EXIT_{tier}',
                    'fraction': 1.0,
                    'score': score,
                    'tier': tier,
                    'market_state': market_state,
                }

            return {
                'action': 'hold',
                'reason': f'VA02_HOLDING_{tier}',
                'score': score,
                'tier': tier,
                'market_state': market_state,
            }

        # ========== Entry Logic ==========
        if score >= self.entry_tier_threshold:
            self.set_position(current_price, f'VA02_{tier}_ENTRY')
            self.highest_price = current_price

            return {
                'action': 'buy',
                'reason': f'VA02_{tier}_ENTRY',
                'fraction': 0.5,
                'score': score,
                'tier': tier,
                'signals': signals,
                'market_state': market_state,
                'stop_loss_pct': self.stop_loss,
                'take_profit_pct': self.take_profit,
            }

        return {
            'action': 'hold',
            'reason': f'VA02_NO_SIGNAL_{tier}',
            'score': score,
            'tier': tier,
            'market_state': market_state,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get strategy statistics"""
        stats = super().get_stats()
        stats.update({
            'current_score': self.current_score,
            'current_tier': self.current_tier,
            'highest_price': self.highest_price,
        })
        return stats
