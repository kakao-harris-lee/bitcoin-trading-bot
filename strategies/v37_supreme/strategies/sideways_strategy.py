#!/usr/bin/env python3
"""
SIDEWAYS Strategy (횡보장 전용)

목표: 박스권 시장에서 안정적 수익
특징:
  - 3가지 진입 방법 (RSI+BB, Stochastic, Volume Breakout)
  - 빠른 회전 (평균 보유 5-15일)
  - 분할 익절 (TP 2-6%)
  - 손절 엄격 (-2%)

v35 검증 성과:
  2025년: +14.20% (Buy&Hold +8.44% vs +5.76%p 초과)
  2023년: +13.64% (v34 +2.48% vs +11.16%p 개선)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class SidewaysStrategy:
    """횡보장 전략 (v35 기반)"""

    def __init__(self, config: Dict):
        self.config = config
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.hold_days = 0
        self.entry_method = None  # 'rsi_bb', 'stoch', 'volume_breakout'

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        진입:
          1. RSI+BB: RSI < 30 AND price < BB_lower
          2. Stochastic: %K < 20 AND %K > %D (골든크로스)
          3. Volume Breakout: Volume > avg × 2.0 AND price 반등

        청산:
          - TP 2-6% (분할)
          - SL -2%
          - 최대 20일
        """

        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        if self.in_position:
            self.hold_days += 1

            exit_signal = self._check_exit(row, prev_row, df, i)
            if exit_signal:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.hold_days = 0
                self.entry_method = None
                return exit_signal

        else:
            entry_signal = self._check_entry(row, prev_row, df, i)
            if entry_signal:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.name
                self.hold_days = 0
                self.entry_method = entry_signal.get('strategy', 'unknown')
                return entry_signal

        return {'action': 'hold', 'reason': 'SIDEWAYS_HOLD'}

    def _check_entry(self, row: pd.Series, prev_row: pd.Series,
                     df: pd.DataFrame, i: int) -> Optional[Dict]:
        """진입 조건 확인 (3가지 방법)"""

        # 1. RSI + Bollinger Bands (가장 신뢰도 높음)
        if self.config.get('use_rsi_bb', True):
            rsi_bb_signal = self._check_rsi_bb_entry(row)
            if rsi_bb_signal:
                return rsi_bb_signal

        # 2. Stochastic Oscillator
        if self.config.get('use_stoch', True):
            stoch_signal = self._check_stoch_entry(row, prev_row)
            if stoch_signal:
                return stoch_signal

        # 3. Volume Breakout (거래량 급증 시 반등 기대)
        if self.config.get('use_volume_breakout', True):
            volume_signal = self._check_volume_breakout_entry(row, df, i)
            if volume_signal:
                return volume_signal

        return None

    def _check_rsi_bb_entry(self, row: pd.Series) -> Optional[Dict]:
        """RSI + Bollinger Bands 진입"""

        rsi = row.get('rsi', 50)
        bb_lower = row.get('bb_lower', 0)
        close = row['close']

        rsi_threshold = self.config.get('rsi_bb_oversold', 30)

        # RSI 과매도 + BB 하단 이탈
        if rsi < rsi_threshold and close < bb_lower:
            return {
                'action': 'buy',
                'fraction': self.config.get('sideways_position_size', 0.4),  # 40%
                'reason': f'SIDEWAYS_RSI_BB (RSI={rsi:.1f}, BB_lower)',
                'strategy': 'rsi_bb'
            }

        return None

    def _check_stoch_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """Stochastic Oscillator 진입"""

        stoch_k = row.get('stoch_k', 50)
        stoch_d = row.get('stoch_d', 50)
        prev_stoch_k = prev_row.get('stoch_k', 50) if prev_row is not None else 50
        prev_stoch_d = prev_row.get('stoch_d', 50) if prev_row is not None else 50

        oversold_threshold = self.config.get('stoch_oversold', 20)

        # 골든크로스 + 과매도 구간
        golden_cross = (prev_stoch_k <= prev_stoch_d) and (stoch_k > stoch_d)

        if golden_cross and stoch_k < oversold_threshold:
            return {
                'action': 'buy',
                'fraction': self.config.get('sideways_position_size', 0.4),
                'reason': f'SIDEWAYS_STOCH_GC (K={stoch_k:.1f}, D={stoch_d:.1f})',
                'strategy': 'stoch'
            }

        return None

    def _check_volume_breakout_entry(self, row: pd.Series, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """Volume Breakout 진입 (거래량 급증)"""

        if i < 20:
            return None

        volume = row.get('volume', 0)
        avg_volume = df['volume'].iloc[i-20:i].mean()

        volume_mult = self.config.get('volume_breakout_mult', 2.0)

        # 거래량 급증 (2배 이상)
        if volume > avg_volume * volume_mult:
            # RSI가 너무 높지 않을 때만 (< 60)
            rsi = row.get('rsi', 50)
            if rsi < 60:
                return {
                    'action': 'buy',
                    'fraction': self.config.get('sideways_position_size', 0.4),
                    'reason': f'SIDEWAYS_VOLUME_BREAKOUT (Vol={volume/avg_volume:.1f}x)',
                    'strategy': 'volume_breakout'
                }

        return None

    def _check_exit(self, row: pd.Series, prev_row: pd.Series,
                    df: pd.DataFrame, i: int) -> Optional[Dict]:
        """청산 조건 확인"""

        current_price = row['close']
        profit = (current_price - self.entry_price) / self.entry_price

        # 1. Take Profit (분할)
        tp1 = self.config.get('sideways_tp_1', 0.02)  # 2%
        tp2 = self.config.get('sideways_tp_2', 0.04)  # 4%
        tp3 = self.config.get('sideways_tp_3', 0.06)  # 6%

        if profit >= tp3:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SIDEWAYS_TP3 ({profit:.2%})',
                'strategy': self.entry_method
            }
        elif profit >= tp2:
            return {
                'action': 'sell',
                'fraction': 0.5,  # 50% 익절
                'reason': f'SIDEWAYS_TP2_PARTIAL ({profit:.2%})',
                'strategy': self.entry_method
            }
        elif profit >= tp1 and self.hold_days >= 5:
            return {
                'action': 'sell',
                'fraction': 0.3,  # 30% 익절
                'reason': f'SIDEWAYS_TP1_PARTIAL ({profit:.2%})',
                'strategy': self.entry_method
            }

        # 2. Stop Loss (-2%, 빡빡)
        stop_loss = self.config.get('sideways_stop_loss', -0.02)

        if profit <= stop_loss:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SIDEWAYS_STOP_LOSS ({stop_loss:.0%})',
                'strategy': self.entry_method
            }

        # 3. 진입 방법별 특수 청산 조건

        # RSI+BB: RSI > 70 OR price > BB_upper
        if self.entry_method == 'rsi_bb':
            rsi = row.get('rsi', 50)
            bb_upper = row.get('bb_upper', 0)
            overbought_threshold = self.config.get('rsi_bb_overbought', 70)

            if rsi > overbought_threshold or current_price > bb_upper:
                if profit > 0.01:  # 최소 1% 수익 시
                    return {
                        'action': 'sell',
                        'fraction': 0.5,
                        'reason': f'SIDEWAYS_RSI_BB_EXIT (RSI={rsi:.1f})',
                        'strategy': self.entry_method
                    }

        # Stochastic: 데드크로스 (%K < %D)
        elif self.entry_method == 'stoch':
            stoch_k = row.get('stoch_k', 50)
            stoch_d = row.get('stoch_d', 50)
            prev_stoch_k = prev_row.get('stoch_k', 50) if prev_row is not None else 50
            prev_stoch_d = prev_row.get('stoch_d', 50) if prev_row is not None else 50

            dead_cross = (prev_stoch_k >= prev_stoch_d) and (stoch_k < stoch_d)
            overbought_threshold = self.config.get('stoch_overbought', 80)

            if dead_cross and stoch_k > overbought_threshold:
                if profit > 0.01:
                    return {
                        'action': 'sell',
                        'fraction': 0.5,
                        'reason': f'SIDEWAYS_STOCH_DC (K={stoch_k:.1f})',
                        'strategy': self.entry_method
                    }

        # Volume Breakout: 거래량 다시 감소 시
        elif self.entry_method == 'volume_breakout':
            if i >= 5:
                recent_volume = df['volume'].iloc[i-5:i].mean()
                current_volume = row.get('volume', 0)

                if current_volume < recent_volume * 0.7 and profit > 0.015:
                    return {
                        'action': 'sell',
                        'fraction': 0.5,
                        'reason': 'SIDEWAYS_VOLUME_DECREASE',
                        'strategy': self.entry_method
                    }

        # 4. 최대 보유 기간 (20일, 빠른 회전)
        max_hold_days = self.config.get('sideways_max_hold_days', 20)

        if self.hold_days >= max_hold_days:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SIDEWAYS_MAX_HOLD (profit={profit:.2%}, {max_hold_days}d)',
                'strategy': self.entry_method
            }

        return None


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  SIDEWAYS Strategy - 테스트")
    print("="*70)

    # 시뮬레이션 데이터
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    # 횡보장 시뮬레이션 (40,000 ~ 42,000 박스권)
    base_price = 41000
    prices = base_price + np.random.randn(100).cumsum() * 200
    prices = np.clip(prices, 40000, 42000)

    # 지표 생성
    rsi_values = np.random.uniform(20, 80, 100)
    rsi_values[20] = 25  # 과매도
    rsi_values[50] = 28
    rsi_values[80] = 72  # 과매수

    # BB
    bb_middle = prices
    bb_upper = bb_middle + 500
    bb_lower = bb_middle - 500
    bb_lower[20] = prices[20] + 100  # 하단 이탈
    bb_lower[50] = prices[50] + 100

    # Stochastic
    stoch_k = np.random.uniform(20, 80, 100)
    stoch_d = stoch_k + np.random.randn(100) * 5
    stoch_k[30] = 18
    stoch_d[30] = 22
    stoch_k[31] = 23  # 골든크로스
    stoch_d[31] = 22

    # Volume
    volumes = np.random.uniform(1000, 2000, 100)
    volumes[40] = 4500  # 급등

    df = pd.DataFrame({
        'close': prices,
        'rsi': rsi_values,
        'bb_upper': bb_upper,
        'bb_middle': bb_middle,
        'bb_lower': bb_lower,
        'stoch_k': stoch_k,
        'stoch_d': stoch_d,
        'volume': volumes
    }, index=dates)

    config = {
        'use_rsi_bb': True,
        'use_stoch': True,
        'use_volume_breakout': True,
        'rsi_bb_oversold': 30,
        'rsi_bb_overbought': 70,
        'stoch_oversold': 20,
        'stoch_overbought': 80,
        'volume_breakout_mult': 2.0,
        'sideways_position_size': 0.4,
        'sideways_tp_1': 0.02,
        'sideways_tp_2': 0.04,
        'sideways_tp_3': 0.06,
        'sideways_stop_loss': -0.02,
        'sideways_max_hold_days': 20
    }

    strategy = SidewaysStrategy(config)

    trades = 0
    for i in range(30, len(df)):
        signal = strategy.execute(df, i)

        if signal['action'] == 'buy':
            print(f"  매수: {df.index[i].date()} | {signal['reason']}")
            trades += 1
        elif signal['action'] == 'sell':
            print(f"  매도: {df.index[i].date()} | {signal['reason']}")

    print(f"\n  총 거래: {trades}회")
    print(f"\n테스트 완료!")
    print(f"v37 SIDEWAYS 전략 (v35 검증: 2025년 +14.20% vs Buy&Hold +8.44%)")
