"""
Trading Engine V2 - Short V1 Strategy (Enhanced)
Binance Short 전략 (SHORT_V1 이식)

EMA/ADX 기반 추세 추종 숏 전략
- EMA 데드크로스 진입
- ADX 강한 추세 확인 + ADX declining filter
- ATR 기반 손절 (변동성 버퍼)
- 2단계 익절 (50% at 1R, 50% trailing)
"""

import logging
from enum import Enum
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np

from .base import BaseStrategy
from ..indicators import technical as ta
from ..core.config import Config
from core.types import Exchange, Direction

logger = logging.getLogger(__name__)


class PositionTier(Enum):
    """Position tier state for two-tier exit management."""
    CLOSED = "CLOSED"
    FULL = "FULL"
    HALF = "HALF"


class ShortV1Strategy(BaseStrategy):
    """
    SHORT_V1 Strategy (Binance Futures)

    EMA/ADX 기반 비트코인 선물 숏 전략
    - EMA50 < EMA200 (데드크로스)
    - ADX >= 25 (강한 추세)
    - -DI > +DI (하락 우위)
    """

    # 기본 설정
    DEFAULT_CONFIG = {
        # 지표 설정
        'ema_fast': 50,
        'ema_slow': 200,
        'adx_period': 14,
        'adx_threshold': 25,

        # 진입 조건
        'adx_min': 25,
        'require_death_cross': True,
        'di_negative_dominant': True,

        # 리스크 관리
        'max_leverage': 3,
        'position_risk_pct': 1.0,
        'max_stop_loss_pct': 5.0,
        'risk_reward_ratio': 2.5,

        # 청산
        'exit_on_golden_cross': True,

        # 버퍼
        'buffer_size': 300,
    }

    def __init__(
        self,
        config: Optional[Config] = None,
        strategy_config: Optional[Dict] = None,
    ):
        # 설정 병합
        merged_config = {**self.DEFAULT_CONFIG, **(strategy_config or {})}

        super().__init__(
            strategy_name="short-v1",
            exchange=Exchange.BINANCE,
            direction=Direction.SHORT,
            symbol="BTCUSDT",
            config=config,
            strategy_config=merged_config,
        )

        # 포지션 관리
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.position_leverage = 1

        # Two-tier exit state (T006)
        self.position_tier = PositionTier.CLOSED
        self.take_profit_1r = 0.0
        self.take_profit_2r = 0.0
        self.first_tp_hit = False
        self.trailing_stop_active = False
        self.trailing_stop_price = 0.0
        self.lowest_since_1r = 0.0
        self.initial_quantity = 0.0
        self.remaining_quantity = 0.0

        # Extreme volatility state
        self.extreme_volatility = False

    def _min_buffer_size(self) -> int:
        """EMA 200 워밍업 필요"""
        return 200

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """EMA, ADX, DI, ATR indicators using shared library."""
        # EMA (using talib via shared library)
        df['ema_fast'] = ta.ema(df['close'], period=self.strategy_config['ema_fast'])
        df['ema_slow'] = ta.ema(df['close'], period=self.strategy_config['ema_slow'])

        # ADX, +DI, -DI (using talib via shared library)
        adx_period = self.strategy_config['adx_period']
        df['adx'], df['plus_di'], df['minus_di'] = ta.adx(
            df['high'], df['low'], df['close'], period=adx_period
        )

        # ATR for volatility-based stop loss (T007)
        atr_period = self.strategy_config.get('atr_period', 14)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], period=atr_period)

        # ADX slope detection (T008)
        adx_slope_bars = self.strategy_config.get('adx_slope_bars', 3)
        df['adx_prev'] = df['adx'].shift(adx_slope_bars)
        df['adx_declining'] = df['adx'] < df['adx_prev']

        # EMA crossover signals
        ema_fast = df['ema_fast']
        ema_slow = df['ema_slow']
        prev_fast = ema_fast.shift(1)
        prev_slow = ema_slow.shift(1)

        # Death cross: fast crosses below slow
        df['death_cross'] = (ema_fast < ema_slow) & (prev_fast >= prev_slow)

        # Golden cross: fast crosses above slow
        df['golden_cross'] = (ema_fast > ema_slow) & (prev_fast <= prev_slow)

        # Trend state
        df['trend'] = np.where(
            ema_fast > ema_slow, 'BULL',
            np.where(ema_fast < ema_slow, 'BEAR', 'NEUTRAL')
        )

        # DI dominance
        df['di_dominant'] = np.where(
            df['minus_di'] > df['plus_di'], 'BEAR',
            np.where(df['plus_di'] > df['minus_di'], 'BULL', 'NEUTRAL')
        )

        # Swing high/low
        df['swing_high'] = df['high'].rolling(window=10).max()
        df['swing_low'] = df['low'].rolling(window=10).min()

        return df

    def generate_signal(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        신호 생성 (T028: Enhanced for two-tier exits)

        Returns:
            {'action': 'open_short'/'close_short'/'partial_close', 'fraction': float, ...} or None
        """
        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 포지션 있을 때: 청산 조건
        if self.in_position:
            exit_signal = self._check_exit(row)
            if exit_signal:
                # T028: Handle partial_close differently - don't clear full position
                if exit_signal.get('action') == 'partial_close':
                    # Position tier already updated in _check_first_tier_exit
                    return exit_signal
                else:
                    # Full close - clear position
                    self.clear_position()
                    return exit_signal

        # 포지션 없을 때: 진입 조건
        else:
            entry_signal = self._check_entry(row, prev_row, df.iloc[:i+1])
            if entry_signal:
                self.set_position(row['close'], entry_signal['reason'])
                self.stop_loss_price = entry_signal.get('stop_loss', 0)
                self.take_profit_price = entry_signal.get('take_profit', 0)
                self.position_leverage = entry_signal.get('leverage', 1)
                # T028: Initialize position tier to FULL on entry
                self.position_tier = PositionTier.FULL
                self.initial_quantity = 1.0  # Will be set by execution layer
                self.remaining_quantity = 1.0
                return entry_signal

        return None

    def _check_entry(
        self,
        row: pd.Series,
        prev_row: Optional[pd.Series],
        df_history: pd.DataFrame
    ) -> Optional[Dict]:
        """숏 진입 조건 확인 (Enhanced with FR-011, FR-012, FR-013)"""
        reasons = []
        strength = 0.0

        # T012/FR-013: Skip entry during extreme volatility
        if self._check_extreme_volatility(row, df_history):
            logger.info("Entry skipped: extreme volatility detected")
            return None

        # T011/FR-011: Skip entry when ADX is declining
        adx_declining = row.get('adx_declining', False)
        require_adx_not_declining = self.strategy_config.get('require_adx_not_declining', True)
        if require_adx_not_declining and adx_declining:
            logger.debug("Entry skipped: ADX is declining")
            return None

        # 조건 1: EMA 데드크로스 또는 BEAR 추세
        if self.strategy_config['require_death_cross']:
            if row.get('death_cross', False):
                reasons.append('DEATH_CROSS')
                strength += 0.4
            elif row.get('trend', '') == 'BEAR':
                reasons.append('BEAR_TREND')
                strength += 0.2
            else:
                return None

        # 조건 2: ADX >= 임계값
        adx = row.get('adx', 0)
        adx_min = self.strategy_config['adx_min']
        if adx >= adx_min:
            reasons.append(f'ADX_{adx:.0f}')
            strength += 0.3
        else:
            return None

        # 조건 3: -DI > +DI
        if self.strategy_config['di_negative_dominant']:
            if row.get('di_dominant', '') == 'BEAR':
                reasons.append('DI_BEAR')
                strength += 0.2
            else:
                return None

        # T013: Require confidence >= 0.7 for entry
        confidence = min(strength, 1.0)
        min_confidence = self.strategy_config.get('min_entry_confidence', 0.7)
        if confidence < min_confidence:
            logger.debug(f"Entry skipped: confidence {confidence:.2f} < {min_confidence}")
            return None

        # 손절/익절 계산
        entry_price = row['close']
        swing_high = row.get('swing_high', entry_price * 1.05)
        atr_value = row.get('atr', 0)

        # T017: Pass atr_value for ATR-based stop loss
        levels = self._calculate_position_levels(
            entry_price=entry_price,
            swing_high=swing_high,
            atr_value=atr_value
        )

        # T014: Enhanced metadata with adx_prev and adx_declining
        return {
            'action': 'open_short',
            'fraction': 1.0,  # 전액 진입
            'reason': '+'.join(reasons),
            'confidence': confidence,
            'leverage': self.strategy_config['max_leverage'],
            'stop_loss': levels['stop_loss'],
            'take_profit': levels['take_profit'],
            'stop_loss_pct': levels['risk_pct'],
            'take_profit_pct': levels['reward_pct'],
            'metadata': {
                'adx': adx,
                'adx_prev': row.get('adx_prev', 0),
                'adx_declining': adx_declining,
                'plus_di': row.get('plus_di', 0),
                'minus_di': row.get('minus_di', 0),
                'trend': row.get('trend', ''),
                'atr': atr_value,
                'swing_high': swing_high,
            }
        }

    def _check_exit(self, row: pd.Series) -> Optional[Dict]:
        """숏 청산 조건 확인 (T020, T026: Two-tier exits with gap check)"""
        current_price = row['close']
        high_price = row['high']
        low_price = row['low']

        # T020/FR-012: Check for gap past stop loss FIRST (highest priority)
        gap_exit = self._check_gap_exit(row)
        if gap_exit:
            return gap_exit

        # 손절 (가격이 스탑로스 이상으로 상승)
        if self.stop_loss_price > 0 and high_price >= self.stop_loss_price:
            pnl_pct = (self.entry_price - self.stop_loss_price) / self.entry_price * 100
            return {
                'action': 'close_short',
                'fraction': 1.0,
                'reason': f'STOP_LOSS_HIT_{pnl_pct:.2f}%',
                'confidence': 0.95,
                'exit_type': 'STOP_LOSS',
                'metadata': {
                    'exit_price': self.stop_loss_price,
                    'pnl_pct': pnl_pct,
                    'gap_exit': False,
                }
            }

        # T026: Two-tier exit handling
        two_tier_enabled = self.strategy_config.get('two_tier_enabled', True)
        if two_tier_enabled:
            # Check for first tier exit (50% at 1R)
            if self.position_tier == PositionTier.FULL:
                first_tier_exit = self._check_first_tier_exit(row)
                if first_tier_exit:
                    return first_tier_exit

            # Check for trailing stop / 2R exit (remaining 50%)
            if self.position_tier == PositionTier.HALF:
                trailing_exit = self._check_trailing_stop_exit(row)
                if trailing_exit:
                    return trailing_exit
        else:
            # Legacy: single take profit exit
            if self.take_profit_price > 0 and low_price <= self.take_profit_price:
                pnl_pct = (self.entry_price - self.take_profit_price) / self.entry_price * 100
                return {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'TAKE_PROFIT_HIT_{pnl_pct:.2f}%',
                    'confidence': 0.95,
                    'exit_type': 'TAKE_PROFIT',
                    'metadata': {
                        'exit_price': self.take_profit_price,
                        'pnl_pct': pnl_pct,
                    }
                }

        # 골든크로스 시 청산
        if self.strategy_config.get('exit_on_golden_cross', True):
            if row.get('golden_cross', False):
                pnl_pct = (self.entry_price - current_price) / self.entry_price * 100
                return {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'GOLDEN_CROSS_REVERSAL_{pnl_pct:.2f}%',
                    'confidence': 0.8,
                    'exit_type': 'GOLDEN_CROSS',
                    'metadata': {
                        'exit_price': current_price,
                        'pnl_pct': pnl_pct,
                    }
                }

        return None

    def _check_extreme_volatility(self, row: pd.Series, df_history: pd.DataFrame) -> bool:
        """
        Check for extreme daily volatility (FR-013).

        Detects >10% daily price range which indicates extreme volatility.
        When detected, new entries should be halted.

        Returns:
            True if volatility exceeds threshold (entry should be skipped).
        """
        threshold = self.strategy_config.get('extreme_volatility_threshold', 0.10)
        halt_enabled = self.strategy_config.get('halt_entries_on_extreme_vol', True)

        if not halt_enabled:
            return False

        # Calculate daily range from current candle
        high = row.get('high', 0)
        low = row.get('low', 0)
        open_price = row.get('open', 0)

        if open_price <= 0:
            return False

        daily_range = (high - low) / open_price

        if daily_range > threshold:
            self.extreme_volatility = True
            logger.warning(
                f"Extreme volatility detected: {daily_range:.2%} > {threshold:.2%}"
            )
            return True

        self.extreme_volatility = False
        return False

    def _calculate_stop_loss(
        self,
        entry_price: float,
        swing_high: float,
        atr_value: float
    ) -> Dict:
        """
        Calculate ATR-buffered stop loss (T016, FR-004, FR-005).

        Formula:
            raw_stop = swing_high + (atr_value * atr_multiplier)
            capped_stop = min(raw_stop, entry_price * 1.05)

        Returns:
            Dict with stop_loss price, risk_pct, and atr_buffer.
        """
        atr_multiplier = self.strategy_config.get('atr_buffer_multiplier', 1.5)
        max_sl_pct = self.strategy_config.get('max_stop_loss_pct', 5.0)

        # ATR-buffered stop loss: swing high + ATR buffer
        atr_buffer = atr_value * atr_multiplier
        raw_stop = swing_high + atr_buffer

        # Apply maximum stop loss cap (5%)
        max_stop = entry_price * (1 + max_sl_pct / 100)
        stop_loss = min(raw_stop, max_stop)

        # Calculate risk percentage
        risk_pct = (stop_loss - entry_price) / entry_price * 100

        return {
            'stop_loss': stop_loss,
            'risk_pct': risk_pct,
            'atr_buffer': atr_buffer,
            'raw_stop': raw_stop,
            'capped': raw_stop > max_stop,
        }

    def _check_gap_exit(self, row: pd.Series) -> Optional[Dict]:
        """
        Check for gap opening past stop loss (T019, FR-012).

        When market gaps past stop loss (open > stop_loss for shorts),
        exit immediately at market price to limit damage.

        Returns:
            Exit signal if gap detected, None otherwise.
        """
        if not self.in_position or self.stop_loss_price <= 0:
            return None

        open_price = row.get('open', 0)

        # For short: gap UP past stop loss is bad
        if open_price >= self.stop_loss_price:
            pnl_pct = (self.entry_price - open_price) / self.entry_price * 100
            logger.warning(
                f"Gap past stop loss detected: open={open_price:.2f} >= stop={self.stop_loss_price:.2f}"
            )
            return {
                'action': 'close_short',
                'fraction': 1.0,
                'reason': f'GAP_PAST_STOP_{pnl_pct:.2f}%',
                'confidence': 0.99,
                'exit_type': 'GAP_STOP',
                'metadata': {
                    'exit_price': open_price,
                    'pnl_pct': pnl_pct,
                    'gap_exit': True,
                    'stop_loss_price': self.stop_loss_price,
                }
            }

        return None

    def _calculate_position_levels(
        self,
        entry_price: float,
        swing_high: float,
        atr_value: float = 0
    ) -> Dict:
        """손절/익절 레벨 계산 (T017: Updated with ATR-based stop loss)"""
        rr_ratio = self.strategy_config.get('risk_reward_ratio', 2.5)

        # T017: Use ATR-based stop loss calculation
        if atr_value > 0:
            sl_result = self._calculate_stop_loss(entry_price, swing_high, atr_value)
            stop_loss = sl_result['stop_loss']
            risk_pct = sl_result['risk_pct']
            atr_buffer = sl_result['atr_buffer']
        else:
            # Fallback to original calculation if no ATR
            max_sl_pct = self.strategy_config.get('max_stop_loss_pct', 5.0)
            sl_from_swing = swing_high
            sl_from_max = entry_price * (1 + max_sl_pct / 100)
            stop_loss = min(sl_from_swing, sl_from_max)
            risk_pct = (stop_loss - entry_price) / entry_price * 100
            atr_buffer = 0

        # 익절 (R:R 비율 적용)
        reward_pct = risk_pct * rr_ratio
        take_profit = entry_price * (1 - reward_pct / 100)

        # T021: Include atr_value and atr_buffer in return
        return {
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_pct': risk_pct,
            'reward_pct': reward_pct,
            'atr_buffer': atr_buffer,
        }

    def _check_first_tier_exit(self, row: pd.Series) -> Optional[Dict]:
        """
        Check for first tier (50%) exit at 1R target (T023, FR-006).

        When price reaches 1R profit target, exit 50% of position
        and activate trailing stop for the remaining 50%.

        Returns:
            Partial exit signal if 1R hit, None otherwise.
        """
        if not self.in_position or self.first_tp_hit:
            return None

        two_tier_enabled = self.strategy_config.get('two_tier_enabled', True)
        if not two_tier_enabled:
            return None

        low_price = row.get('low', 0)
        first_tier_r = self.strategy_config.get('first_tier_r_multiple', 1.0)
        risk_amount = self.stop_loss_price - self.entry_price  # positive for short

        # 1R target for short: entry - (risk * 1R)
        target_1r = self.entry_price - (risk_amount * first_tier_r)

        if low_price <= target_1r and self.position_tier == PositionTier.FULL:
            pnl_pct = (self.entry_price - target_1r) / self.entry_price * 100
            self.first_tp_hit = True
            self.position_tier = PositionTier.HALF
            self.take_profit_1r = target_1r
            self.lowest_since_1r = low_price
            self.trailing_stop_active = True
            # Initial trailing stop at break-even (entry price)
            self.trailing_stop_price = self.entry_price

            logger.info(
                f"First tier exit: 50% at 1R target {target_1r:.2f}, PnL={pnl_pct:.2f}%"
            )

            first_tier_pct = self.strategy_config.get('first_tier_pct', 0.5)
            return {
                'action': 'partial_close',
                'fraction': first_tier_pct,
                'reason': f'TAKE_PROFIT_1R_HIT_{pnl_pct:.2f}%',
                'confidence': 0.95,
                'exit_type': 'TAKE_PROFIT_1R',
                'metadata': {
                    'exit_price': target_1r,
                    'pnl_pct': pnl_pct,
                    'remaining_fraction': 1.0 - first_tier_pct,
                    'trailing_activated': True,
                }
            }

        return None

    def _update_trailing_stop(self, current_low: float, atr_value: float) -> Optional[float]:
        """
        Update trailing stop for remaining position (T024, FR-006).

        Rules:
        - Only active after 1R hit
        - Initial trail at entry_price (break-even)
        - Trail at: lowest_since_1r + (atr * multiplier)
        - Only tighten (lower for short), never widen

        Returns:
            New trailing stop price, or None if no change.
        """
        if not self.trailing_stop_active:
            return None

        # Update lowest since 1R hit
        if current_low < self.lowest_since_1r:
            self.lowest_since_1r = current_low

        # Calculate new trailing stop
        atr_multiplier = self.strategy_config.get('trailing_stop_atr_multiplier', 1.5)
        new_trail = self.lowest_since_1r + (atr_value * atr_multiplier)

        # Only tighten (lower) the trailing stop for shorts
        if new_trail < self.trailing_stop_price:
            old_trail = self.trailing_stop_price
            self.trailing_stop_price = new_trail
            logger.debug(
                f"Trailing stop tightened: {old_trail:.2f} -> {new_trail:.2f}"
            )
            return new_trail

        return None

    def _check_trailing_stop_exit(self, row: pd.Series) -> Optional[Dict]:
        """
        Check trailing stop for remaining 50% position (T025, FR-006).

        Returns:
            Exit signal if trailing stop hit, None otherwise.
        """
        if not self.trailing_stop_active or self.position_tier != PositionTier.HALF:
            return None

        high_price = row.get('high', 0)
        atr_value = row.get('atr', 0)

        # Update trailing stop first
        self._update_trailing_stop(row.get('low', 0), atr_value)

        # Check if trailing stop hit (price rises above trailing stop for short)
        if high_price >= self.trailing_stop_price:
            pnl_pct = (self.entry_price - self.trailing_stop_price) / self.entry_price * 100
            logger.info(
                f"Trailing stop hit at {self.trailing_stop_price:.2f}, PnL={pnl_pct:.2f}%"
            )

            return {
                'action': 'close_short',
                'fraction': 1.0,  # Close remaining position
                'reason': f'TRAILING_STOP_HIT_{pnl_pct:.2f}%',
                'confidence': 0.95,
                'exit_type': 'TRAILING_STOP',
                'metadata': {
                    'exit_price': self.trailing_stop_price,
                    'pnl_pct': pnl_pct,
                    'lowest_since_1r': self.lowest_since_1r,
                }
            }

        # Also check for 2R target
        second_tier_r = self.strategy_config.get('second_tier_r_multiple', 2.0)
        risk_amount = self.stop_loss_price - self.entry_price
        target_2r = self.entry_price - (risk_amount * second_tier_r)

        low_price = row.get('low', 0)
        if low_price <= target_2r:
            pnl_pct = (self.entry_price - target_2r) / self.entry_price * 100
            self.take_profit_2r = target_2r
            logger.info(
                f"Second tier exit: remaining 50% at 2R target {target_2r:.2f}, PnL={pnl_pct:.2f}%"
            )

            return {
                'action': 'close_short',
                'fraction': 1.0,  # Close remaining position
                'reason': f'TAKE_PROFIT_2R_HIT_{pnl_pct:.2f}%',
                'confidence': 0.95,
                'exit_type': 'TAKE_PROFIT_2R',
                'metadata': {
                    'exit_price': target_2r,
                    'pnl_pct': pnl_pct,
                }
            }

        return None

    def clear_position(self):
        """포지션 해제 (확장) - T009: Reset all state fields"""
        super().clear_position()
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.position_leverage = 1

        # Reset two-tier exit state
        self.position_tier = PositionTier.CLOSED
        self.take_profit_1r = 0.0
        self.take_profit_2r = 0.0
        self.first_tp_hit = False
        self.trailing_stop_active = False
        self.trailing_stop_price = 0.0
        self.lowest_since_1r = 0.0
        self.initial_quantity = 0.0
        self.remaining_quantity = 0.0
        self.extreme_volatility = False

    def get_stats(self) -> Dict[str, Any]:
        """통계 (확장)"""
        stats = super().get_stats()
        stats.update({
            'stop_loss_price': self.stop_loss_price,
            'take_profit_price': self.take_profit_price,
            'position_leverage': self.position_leverage,
        })
        return stats
