"""
Trading Engine V2 - Short V1 Strategy
Binance Short 전략 (SHORT_V1 이식)

EMA/ADX 기반 추세 추종 숏 전략
- EMA 데드크로스 진입
- ADX 강한 추세 확인
- 스윙 하이 기반 손절
"""

import logging
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np

from .base_strategy import BaseStrategy
from ..core.config import Config
from ..core.message_types import Exchange, Direction

logger = logging.getLogger(__name__)


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

    def _min_buffer_size(self) -> int:
        """EMA 200 워밍업 필요"""
        return 200

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """EMA, ADX, DI 지표 추가"""
        # EMA
        df['ema_fast'] = df['close'].ewm(
            span=self.strategy_config['ema_fast'], adjust=False
        ).mean()
        df['ema_slow'] = df['close'].ewm(
            span=self.strategy_config['ema_slow'], adjust=False
        ).mean()

        # ADX, +DI, -DI
        df = self._calculate_adx_di(df)

        # EMA 크로스오버
        ema_fast = df['ema_fast']
        ema_slow = df['ema_slow']
        prev_fast = ema_fast.shift(1)
        prev_slow = ema_slow.shift(1)

        # 데드크로스: fast가 slow 아래로 하향 돌파
        df['death_cross'] = (ema_fast < ema_slow) & (prev_fast >= prev_slow)

        # 골든크로스: fast가 slow 위로 상향 돌파
        df['golden_cross'] = (ema_fast > ema_slow) & (prev_fast <= prev_slow)

        # 추세 상태
        df['trend'] = np.where(
            ema_fast > ema_slow, 'BULL',
            np.where(ema_fast < ema_slow, 'BEAR', 'NEUTRAL')
        )

        # DI 우위
        df['di_dominant'] = np.where(
            df['minus_di'] > df['plus_di'], 'BEAR',
            np.where(df['plus_di'] > df['minus_di'], 'BULL', 'NEUTRAL')
        )

        # 스윙 하이/로우
        df['swing_high'] = df['high'].rolling(window=10).max()
        df['swing_low'] = df['low'].rolling(window=10).min()

        return df

    def _calculate_adx_di(self, df: pd.DataFrame) -> pd.DataFrame:
        """ADX, +DI, -DI 계산"""
        period = self.strategy_config['adx_period']

        high = df['high']
        low = df['low']
        close = df['close']

        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_dm = pd.Series(plus_dm, index=df.index)
        minus_dm = pd.Series(minus_dm, index=df.index)

        # Smoothed
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        smooth_plus = plus_dm.ewm(alpha=1/period, adjust=False).mean()
        smooth_minus = minus_dm.ewm(alpha=1/period, adjust=False).mean()

        # DI
        df['plus_di'] = 100 * smooth_plus / atr.replace(0, np.nan)
        df['minus_di'] = 100 * smooth_minus / atr.replace(0, np.nan)

        # DX, ADX
        di_sum = df['plus_di'] + df['minus_di']
        di_diff = abs(df['plus_di'] - df['minus_di'])
        dx = 100 * di_diff / di_sum.replace(0, np.nan)
        df['adx'] = dx.ewm(alpha=1/period, adjust=False).mean()

        return df

    def generate_signal(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        신호 생성

        Returns:
            {'action': 'open_short'/'close_short', 'fraction': float, ...} or None
        """
        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 포지션 있을 때: 청산 조건
        if self.in_position:
            exit_signal = self._check_exit(row)
            if exit_signal:
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
                return entry_signal

        return None

    def _check_entry(
        self,
        row: pd.Series,
        prev_row: Optional[pd.Series],
        df_history: pd.DataFrame
    ) -> Optional[Dict]:
        """숏 진입 조건 확인"""
        reasons = []
        strength = 0.0

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

        # 손절/익절 계산
        entry_price = row['close']
        swing_high = row.get('swing_high', entry_price * 1.05)

        levels = self._calculate_position_levels(
            entry_price=entry_price,
            swing_high=swing_high
        )

        return {
            'action': 'open_short',
            'fraction': 1.0,  # 전액 진입
            'reason': '+'.join(reasons),
            'confidence': min(strength, 1.0),
            'leverage': self.strategy_config['max_leverage'],
            'stop_loss': levels['stop_loss'],
            'take_profit': levels['take_profit'],
            'stop_loss_pct': levels['risk_pct'],
            'take_profit_pct': levels['reward_pct'],
            'metadata': {
                'adx': adx,
                'plus_di': row.get('plus_di', 0),
                'minus_di': row.get('minus_di', 0),
                'trend': row.get('trend', ''),
            }
        }

    def _check_exit(self, row: pd.Series) -> Optional[Dict]:
        """숏 청산 조건 확인"""
        current_price = row['close']
        high_price = row['high']
        low_price = row['low']

        # 손절 (가격이 스탑로스 이상으로 상승)
        if self.stop_loss_price > 0 and high_price >= self.stop_loss_price:
            pnl_pct = (self.entry_price - self.stop_loss_price) / self.entry_price * 100
            return {
                'action': 'close_short',
                'fraction': 1.0,
                'reason': f'STOP_LOSS_HIT_{pnl_pct:.2f}%',
                'confidence': 0.95,
                'metadata': {'exit_price': self.stop_loss_price}
            }

        # 익절 (가격이 테이크프로핏 이하로 하락)
        if self.take_profit_price > 0 and low_price <= self.take_profit_price:
            pnl_pct = (self.entry_price - self.take_profit_price) / self.entry_price * 100
            return {
                'action': 'close_short',
                'fraction': 1.0,
                'reason': f'TAKE_PROFIT_HIT_{pnl_pct:.2f}%',
                'confidence': 0.95,
                'metadata': {'exit_price': self.take_profit_price}
            }

        # 골든크로스 시 청산
        if self.strategy_config['exit_on_golden_cross']:
            if row.get('golden_cross', False):
                pnl_pct = (self.entry_price - current_price) / self.entry_price * 100
                return {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'GOLDEN_CROSS_REVERSAL_{pnl_pct:.2f}%',
                    'confidence': 0.8,
                    'metadata': {'exit_price': current_price}
                }

        return None

    def _calculate_position_levels(
        self,
        entry_price: float,
        swing_high: float
    ) -> Dict:
        """손절/익절 레벨 계산"""
        max_sl_pct = self.strategy_config['max_stop_loss_pct']
        rr_ratio = self.strategy_config['risk_reward_ratio']

        # 스윙 하이 기반 손절 (최대 제한 적용)
        sl_from_swing = swing_high
        sl_from_max = entry_price * (1 + max_sl_pct / 100)
        stop_loss = min(sl_from_swing, sl_from_max)

        # 리스크 계산
        risk_pct = (stop_loss - entry_price) / entry_price * 100

        # 익절 (R:R 비율 적용)
        reward_pct = risk_pct * rr_ratio
        take_profit = entry_price * (1 - reward_pct / 100)

        return {
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_pct': risk_pct,
            'reward_pct': reward_pct,
        }

    def clear_position(self):
        """포지션 해제 (확장)"""
        super().clear_position()
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.position_leverage = 1

    def get_stats(self) -> Dict[str, Any]:
        """통계 (확장)"""
        stats = super().get_stats()
        stats.update({
            'stop_loss_price': self.stop_loss_price,
            'take_profit_price': self.take_profit_price,
            'position_leverage': self.position_leverage,
        })
        return stats
