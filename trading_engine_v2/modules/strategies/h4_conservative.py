#!/usr/bin/env python3
"""
H4 Conservative Strategy - Sideways 시장 대응 4시간봉 전략

진입 조건:
- 상승 추세 (EMA50 > EMA200)
- RSI < 30 (과매도)
- BB position < 0.2 (볼린저 하단)
- 최근 고점 대비 5%+ 하락
- 거래량 1.5배 이상

청산 조건:
- 익절: +4%
- 손절: -2%
- 시간 청산: 72시간 (18 bars)

백테스트 성과:
- Train (2020-2024): +76.33%, 56% 승률, MDD -14.6%
- Validation (2025): +7.17%, 100% 승률, MDD -0.66%
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime


@dataclass
class H4ConservativeConfig:
    """H4 Conservative 전략 설정"""
    # 진입 조건
    rsi_oversold: float = 30.0
    bb_position_max: float = 0.2
    pct_drop_threshold: float = -5.0  # 최근 고점 대비 하락률
    volume_ratio_min: float = 1.5

    # 청산 조건
    take_profit: float = 0.04   # 4%
    stop_loss: float = -0.02    # -2%
    max_hold_bars: int = 18     # 72시간 (4H * 18)

    # 자본 배분
    position_fraction: float = 0.5  # 50% 자본 사용

    # 지표 기간
    rsi_period: int = 14
    bb_period: int = 20
    ema_short: int = 50
    ema_long: int = 200
    high_lookback: int = 24  # 최근 고점 계산 기간 (4일)


class H4ConservativeStrategy:
    """H4 Conservative Strategy for Sideways Market"""

    DEFAULT_CONFIG = H4ConservativeConfig()

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: 전략 설정 (없으면 기본값 사용)
        """
        self.cfg = H4ConservativeConfig()
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
        """지표 계산"""
        df = df.copy()

        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(self.cfg.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.cfg.rsi_period).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))

        # Bollinger Bands
        df['bb_mid'] = df['close'].rolling(self.cfg.bb_period).mean()
        df['bb_std'] = df['close'].rolling(self.cfg.bb_period).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)

        # EMA Trend
        df['ema_short'] = df['close'].ewm(span=self.cfg.ema_short).mean()
        df['ema_long'] = df['close'].ewm(span=self.cfg.ema_long).mean()
        df['uptrend'] = (df['ema_short'] > df['ema_long']).astype(int)

        # Volume ratio
        df['vol_ma'] = df['volume'].rolling(self.cfg.bb_period).mean()
        df['vol_ratio'] = df['volume'] / (df['vol_ma'] + 1e-10)

        # 최근 고점 대비 하락률
        df['recent_high'] = df['high'].rolling(self.cfg.high_lookback).max()
        df['pct_from_high'] = (df['close'] - df['recent_high']) / df['recent_high'] * 100

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
        uptrend = int(row['uptrend'])
        vol_ratio = float(row['vol_ratio'])
        pct_drop = float(row['pct_from_high'])
        current_price = float(row['close'])

        # 포지션 있을 때: 청산 조건 체크
        if self.entry_price is not None:
            self.hold_count += 1
            current_return = (current_price - self.entry_price) / self.entry_price

            # 익절
            if current_return >= self.cfg.take_profit:
                signal = {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TP {current_return*100:.2f}%',
                    'return': current_return
                }
                self._reset_position()
                return signal

            # 손절
            if current_return <= self.cfg.stop_loss:
                signal = {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'SL {current_return*100:.2f}%',
                    'return': current_return
                }
                self._reset_position()
                return signal

            # 시간 청산 (수익 상태에서만)
            if self.hold_count >= self.cfg.max_hold_bars and current_return > 0:
                signal = {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TimeExit {current_return*100:.2f}%',
                    'return': current_return
                }
                self._reset_position()
                return signal

            # RSI 과매수 청산
            if rsi > 70:
                signal = {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'RSI_exit {current_return*100:.2f}%',
                    'return': current_return
                }
                self._reset_position()
                return signal

            return {'action': 'hold'}

        # 진입 조건 체크
        entry_conditions = (
            uptrend == 1 and                           # 상승 추세
            rsi < self.cfg.rsi_oversold and            # RSI 과매도
            bb_pos < self.cfg.bb_position_max and      # BB 하단
            pct_drop < self.cfg.pct_drop_threshold and # 고점 대비 하락
            vol_ratio > self.cfg.volume_ratio_min      # 거래량 증가
        )

        if entry_conditions:
            self.entry_price = current_price
            self.entry_time = pd.to_datetime(row['timestamp']) if 'timestamp' in row else None
            self.hold_count = 0

            return {
                'action': 'buy',
                'fraction': self.cfg.position_fraction,
                'reason': f'H4_entry RSI={rsi:.1f} BB={bb_pos:.2f} Drop={pct_drop:.1f}%',
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
            'strategy': 'H4_Conservative',
            'timeframe': 'minute240',
            'in_position': self.entry_price is not None,
            'entry_price': self.entry_price,
            'hold_bars': self.hold_count,
            'config': {
                'rsi_oversold': self.cfg.rsi_oversold,
                'bb_max': self.cfg.bb_position_max,
                'take_profit': f'{self.cfg.take_profit*100:.1f}%',
                'stop_loss': f'{self.cfg.stop_loss*100:.1f}%',
                'position_fraction': f'{self.cfg.position_fraction*100:.0f}%'
            }
        }


# Backtester 호환 어댑터
class H4ConservativeAdapter:
    """Backtester 호환 어댑터"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.strategy = H4ConservativeStrategy(config)
        self._cached_df: Optional[pd.DataFrame] = None

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict[str, Any]:
        # 지표 캐싱
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        signal = self.strategy.generate_signal(self._cached_df, i)
        return signal or {'action': 'hold'}


if __name__ == '__main__':
    # 테스트
    from core.data_loader import DataLoader
    from core.backtester import Backtester

    loader = DataLoader()
    df = loader.load_timeframe('minute240', '2024-01-01', '2024-12-31')
    loader.conn.close()

    bt = Backtester(initial_capital=10_000_000, fee_rate=0.0005, slippage=0.0002)
    adapter = H4ConservativeAdapter()
    result = bt.run(df, adapter, {})

    print("H4 Conservative Strategy Test")
    print(f"  Return: {result['total_return']:.2f}%")
    print(f"  Trades: {result['total_trades']}")
    print(f"  Win Rate: {(result['win_rate'] or 0) * 100:.1f}%")
