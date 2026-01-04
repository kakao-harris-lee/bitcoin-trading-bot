#!/usr/bin/env python3
"""
H4 Short Strategy - Sideways/Bear 시장 대응 4시간봉 숏 전략 (Binance Futures)

H4 Conservative의 반대 로직으로 과매수 구간에서 숏 진입

진입 조건:
- 하락 추세 (EMA50 < EMA200)
- RSI > 70 (과매수)
- BB position > 0.8 (볼린저 상단)
- 최근 저점 대비 5%+ 상승 (데드캣 바운스)
- 거래량 1.5배 이상

청산 조건:
- 익절: +4% (가격 하락)
- 손절: -2% (가격 상승)
- 시간 청산: 72시간 (18 bars)
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime

from trading.indicators import technical as ta


@dataclass
class H4ShortConfig:
    """H4 Short 전략 설정 (최적화됨)

    백테스트 성과:
    - Train (2020-2024): +7.97%, 38건, 53% 승률, MDD -6.7%
    - Validation (2025): +15.53%, 8건, 88% 승률, MDD -1.3%
    """
    # 진입 조건 (최적화됨)
    rsi_overbought: float = 72.0      # RSI > 72 (과매수)
    bb_position_min: float = 0.82     # BB position > 0.82 (상단)
    pct_rise_threshold: float = 6.0   # 최근 저점 대비 6%+ 상승
    volume_ratio_min: float = 1.5

    # 청산 조건 (최적화됨)
    take_profit: float = 0.05   # 5% (가격 하락 시 수익)
    stop_loss: float = -0.02    # -2% (가격 상승 시 손실)
    max_hold_bars: int = 18     # 72시간 (4H * 18)

    # 자본 배분
    position_fraction: float = 0.5  # 50% 자본 사용

    # 지표 기간
    rsi_period: int = 14
    bb_period: int = 20
    ema_short: int = 50
    ema_long: int = 200
    low_lookback: int = 24  # 최근 저점 계산 기간 (4일)


class H4ShortStrategy:
    """H4 Short Strategy for Sideways/Bear Market (Binance Futures)"""

    DEFAULT_CONFIG = H4ShortConfig()

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: 전략 설정 (없으면 기본값 사용)
        """
        self.cfg = H4ShortConfig()
        if config:
            for key, value in config.items():
                if hasattr(self.cfg, key):
                    setattr(self.cfg, key, value)

        # 상태
        self.entry_price: Optional[float] = None
        self.entry_time: Optional[datetime] = None
        self.hold_count: int = 0
        self._cached_df: Optional[pd.DataFrame] = None
        self._last_signal: Optional[Dict[str, Any]] = None

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """지표 계산 (using talib via shared library)"""
        df = df.copy()

        # RSI (using talib)
        df['rsi'] = ta.rsi(df['close'], period=self.cfg.rsi_period)

        # Bollinger Bands (using talib)
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = ta.bbands(
            df['close'], period=self.cfg.bb_period, std=2.0
        )
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)

        # EMA Trend (using talib)
        df['ema_short'] = ta.ema(df['close'], period=self.cfg.ema_short)
        df['ema_long'] = ta.ema(df['close'], period=self.cfg.ema_long)
        df['downtrend'] = (df['ema_short'] < df['ema_long']).astype(int)

        # Volume ratio
        df['vol_ma'] = df['volume'].rolling(self.cfg.bb_period).mean()
        df['vol_ratio'] = df['volume'] / (df['vol_ma'] + 1e-10)

        # 최근 저점 대비 상승률
        df['recent_low'] = df['low'].rolling(self.cfg.low_lookback).min()
        df['pct_from_low'] = (df['close'] - df['recent_low']) / df['recent_low'] * 100

        return df

    def generate_signal(self, df: pd.DataFrame, i: int) -> Optional[Dict[str, Any]]:
        """
        신호 생성

        Args:
            df: 지표가 계산된 DataFrame
            i: 현재 인덱스

        Returns:
            신호 딕셔너리 또는 None
        """
        # 지표 계산 대기
        if i < self.cfg.ema_long + 10:
            return None

        row = df.iloc[i]

        # NaN 체크
        if pd.isna(row['rsi']) or pd.isna(row['bb_position']):
            return None

        rsi = float(row['rsi'])
        bb_pos = float(row['bb_position'])
        downtrend = int(row['downtrend'])
        vol_ratio = float(row['vol_ratio'])
        pct_rise = float(row['pct_from_low'])
        current_price = float(row['close'])

        # 포지션 있을 때: 청산 조건 체크
        if self.entry_price is not None:
            self.hold_count += 1
            # 숏 포지션: 가격 하락이 수익
            current_return = (self.entry_price - current_price) / self.entry_price

            # 익절 (가격 하락 = 수익)
            if current_return >= self.cfg.take_profit:
                signal = {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'TP {current_return*100:.2f}%',
                    'return': current_return
                }
                self._reset_position()
                return signal

            # 손절 (가격 상승 = 손실)
            if current_return <= self.cfg.stop_loss:
                signal = {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'SL {current_return*100:.2f}%',
                    'return': current_return
                }
                self._reset_position()
                return signal

            # 시간 청산 (수익 상태에서만)
            if self.hold_count >= self.cfg.max_hold_bars and current_return > 0:
                signal = {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'TimeExit {current_return*100:.2f}%',
                    'return': current_return
                }
                self._reset_position()
                return signal

            # RSI 과매도 청산 (반등 예상)
            if rsi < 30:
                signal = {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'RSI_exit {current_return*100:.2f}%',
                    'return': current_return
                }
                self._reset_position()
                return signal

            return {'action': 'hold'}

        # 숏 진입 조건 체크
        entry_conditions = (
            downtrend == 1 and                           # 하락 추세
            rsi > self.cfg.rsi_overbought and            # RSI 과매수
            bb_pos > self.cfg.bb_position_min and        # BB 상단
            pct_rise > self.cfg.pct_rise_threshold and   # 저점 대비 상승
            vol_ratio > self.cfg.volume_ratio_min        # 거래량 증가
        )

        if entry_conditions:
            self.entry_price = current_price
            self.entry_time = pd.to_datetime(row['timestamp']) if 'timestamp' in row else None
            self.hold_count = 0

            return {
                'action': 'short',
                'fraction': self.cfg.position_fraction,
                'reason': f'H4_short RSI={rsi:.1f} BB={bb_pos:.2f} Rise={pct_rise:.1f}%',
                'entry_price': current_price
            }

        return {'action': 'hold'}

    def _reset_position(self):
        """포지션 상태 초기화"""
        self.entry_price = None
        self.entry_time = None
        self.hold_count = 0

    def get_status(self) -> Dict[str, Any]:
        """현재 전략 상태 반환"""
        return {
            'strategy': 'H4_Short',
            'timeframe': 'minute240',
            'in_position': self.entry_price is not None,
            'entry_price': self.entry_price,
            'hold_bars': self.hold_count,
            'config': {
                'rsi_overbought': self.cfg.rsi_overbought,
                'bb_min': self.cfg.bb_position_min,
                'take_profit': f'{self.cfg.take_profit*100:.1f}%',
                'stop_loss': f'{self.cfg.stop_loss*100:.1f}%',
                'position_fraction': f'{self.cfg.position_fraction*100:.0f}%'
            }
        }


# Backtester 호환 어댑터
class H4ShortAdapter:
    """Backtester 호환 어댑터 (숏 전략)"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.strategy = H4ShortStrategy(config)
        self._cached_df: Optional[pd.DataFrame] = None

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict[str, Any]:
        # 지표 캐싱
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        signal = self.strategy.generate_signal(self._cached_df, i)
        return signal or {'action': 'hold'}


if __name__ == '__main__':
    print("H4 Short Strategy module loaded successfully")
    print(f"Default config: {H4ShortConfig()}")
