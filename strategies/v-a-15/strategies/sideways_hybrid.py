#!/usr/bin/env python3
"""
SIDEWAYS Hybrid Strategy (v-a-15)

v-a-11 Mean Reversion + Grid Trading 병행

목표: SIDEWAYS 수익 +30-50%, 총 +8-12%p
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, List
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

try:
    from core.grid_manager import GridManager
except ImportError:
    GridManager = None


class SidewaysHybridStrategy:
    """
    횡보장 하이브리드 전략

    우선순위:
      1. Grid Trading (강세): 명확한 S/R 구간
      2. Mean Reversion (보조): RSI+BB, Stochastic
    """

    def __init__(self, config: Dict):
        self.config = config
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.hold_days = 0
        self.entry_method = None  # 'grid', 'rsi_bb', 'stoch'
        self.grid_level = None  # Grid 레벨 (Grid Trading 시)

        # Grid Manager
        self.use_grid = config.get('use_grid_trading', True) and GridManager is not None
        if self.use_grid:
            self.grid_manager = GridManager({
                'grid_levels': config.get('grid_levels', 7),
                'lookback_period': config.get('grid_lookback', 20),
                'grid_position_size': config.get('grid_position_size', 0.15),
                'grid_threshold': config.get('grid_entry_threshold', 0.02),
                'grid_exit_threshold': config.get('grid_exit_threshold', 0.02)
            })
        else:
            self.grid_manager = None

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """전략 실행"""

        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # Grid 업데이트
        if self.use_grid and self.grid_manager:
            self.grid_manager.update_grid(df, i)

        # 포지션 있을 때
        if self.in_position:
            self.hold_days += 1

            exit_signal = self._check_exit(row, prev_row, df, i)
            if exit_signal:
                # Grid 레벨 청산 등록
                if self.entry_method == 'grid' and self.grid_level is not None:
                    if self.grid_manager:
                        self.grid_manager.register_exit(self.grid_level)

                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.hold_days = 0
                self.entry_method = None
                self.grid_level = None
                return exit_signal

        # 포지션 없을 때
        else:
            entry_signal = self._check_entry(row, prev_row, df, i)
            if entry_signal:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.name
                self.hold_days = 0
                self.entry_method = entry_signal.get('strategy', 'unknown')
                self.grid_level = entry_signal.get('level')

                # Grid 레벨 진입 등록
                if self.entry_method == 'grid' and self.grid_level is not None:
                    if self.grid_manager:
                        # 포지션 크기 계산
                        volume = entry_signal.get('fraction', 0.15) * 1.0  # 임시
                        self.grid_manager.register_entry(
                            level_position=self.grid_level,
                            entry_price=row['close'],
                            volume=volume
                        )

                return entry_signal

        return {'action': 'hold', 'reason': 'SIDEWAYS_HOLD'}

    def _check_entry(self, row: pd.Series, prev_row: pd.Series,
                     df: pd.DataFrame, i: int) -> Optional[Dict]:
        """진입 조건 확인 (우선순위: Grid > Mean Reversion)"""

        # 1. Grid Trading (최우선)
        if self.use_grid and self.grid_manager and self.grid_manager.active:
            grid_signal = self.grid_manager.check_entry(
                current_price=row['close'],
                capital=1000000  # 임시 자본
            )
            if grid_signal:
                return grid_signal

        # 2. Mean Reversion (보조)

        # 2-1. RSI + Bollinger Bands
        if self.config.get('use_rsi_bb', True):
            rsi_bb_signal = self._check_rsi_bb_entry(row)
            if rsi_bb_signal:
                return rsi_bb_signal

        # 2-2. Stochastic
        if self.config.get('use_stoch', True):
            stoch_signal = self._check_stoch_entry(row, prev_row)
            if stoch_signal:
                return stoch_signal

        return None

    def _check_rsi_bb_entry(self, row: pd.Series) -> Optional[Dict]:
        """RSI + Bollinger Bands 진입"""

        rsi = row.get('rsi', 50)
        bb_lower = row.get('bb_lower', 0)
        close = row['close']

        rsi_threshold = self.config.get('rsi_bb_oversold', 30)

        if rsi < rsi_threshold and close < bb_lower:
            return {
                'action': 'buy',
                'fraction': self.config.get('sideways_position_size', 0.4),
                'reason': f'SIDEWAYS_RSI_BB (RSI={rsi:.1f})',
                'strategy': 'rsi_bb'
            }

        return None

    def _check_stoch_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """Stochastic Oscillator 진입"""

        if prev_row is None:
            return None

        stoch_k = row.get('stoch_k', 50)
        stoch_d = row.get('stoch_d', 50)
        prev_k = prev_row.get('stoch_k', 50)
        prev_d = prev_row.get('stoch_d', 50)

        oversold = self.config.get('stoch_oversold', 20)

        # 골든크로스 + 과매도
        golden_cross = (prev_k <= prev_d) and (stoch_k > stoch_d)

        if golden_cross and stoch_k < oversold:
            return {
                'action': 'buy',
                'fraction': self.config.get('sideways_position_size', 0.4),
                'reason': f'SIDEWAYS_STOCH (K={stoch_k:.1f})',
                'strategy': 'stoch'
            }

        return None

    def _check_exit(self, row: pd.Series, prev_row: pd.Series,
                    df: pd.DataFrame, i: int) -> Optional[Dict]:
        """청산 조건 확인"""

        current_price = row['close']
        profit = (current_price - self.entry_price) / self.entry_price

        # 1. Grid Trading 청산
        if self.entry_method == 'grid' and self.grid_manager:
            grid_exit = self.grid_manager.check_exit(current_price)
            if grid_exit:
                return grid_exit

        # 2. Mean Reversion 청산

        # Take Profit
        tp1 = self.config.get('sideways_tp_1', 0.02)
        tp2 = self.config.get('sideways_tp_2', 0.04)
        tp3 = self.config.get('sideways_tp_3', 0.06)

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
                'fraction': 0.5,
                'reason': f'SIDEWAYS_TP2_PARTIAL ({profit:.2%})',
                'strategy': self.entry_method
            }
        elif profit >= tp1 and self.hold_days >= 5:
            return {
                'action': 'sell',
                'fraction': 0.3,
                'reason': f'SIDEWAYS_TP1_PARTIAL ({profit:.2%})',
                'strategy': self.entry_method
            }

        # Stop Loss
        stop_loss = self.config.get('sideways_stop_loss', -0.02)
        if profit <= stop_loss:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SIDEWAYS_STOP_LOSS ({stop_loss:.0%})',
                'strategy': self.entry_method
            }

        # 진입 방법별 특수 청산

        # RSI+BB: RSI > 70 OR price > BB_upper
        if self.entry_method == 'rsi_bb':
            rsi = row.get('rsi', 50)
            bb_upper = row.get('bb_upper', 0)
            overbought = self.config.get('rsi_bb_overbought', 70)

            if (rsi > overbought or current_price > bb_upper) and profit > 0.01:
                return {
                    'action': 'sell',
                    'fraction': 0.5,
                    'reason': f'SIDEWAYS_RSI_BB_EXIT (RSI={rsi:.1f})',
                    'strategy': self.entry_method
                }

        # Stochastic: 데드크로스
        elif self.entry_method == 'stoch' and prev_row is not None:
            stoch_k = row.get('stoch_k', 50)
            stoch_d = row.get('stoch_d', 50)
            prev_k = prev_row.get('stoch_k', 50)
            prev_d = prev_row.get('stoch_d', 50)

            dead_cross = (prev_k >= prev_d) and (stoch_k < stoch_d)
            overbought = self.config.get('stoch_overbought', 80)

            if dead_cross and stoch_k > overbought and profit > 0.01:
                return {
                    'action': 'sell',
                    'fraction': 0.5,
                    'reason': f'SIDEWAYS_STOCH_DC (K={stoch_k:.1f})',
                    'strategy': self.entry_method
                }

        # 최대 보유 기간
        max_hold = self.config.get('sideways_max_hold_days', 20)
        if self.hold_days >= max_hold:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SIDEWAYS_MAX_HOLD (profit={profit:.2%}, {max_hold}d)',
                'strategy': self.entry_method
            }

        return None

    def get_grid_status(self) -> Optional[Dict]:
        """Grid 상태 조회"""
        if self.grid_manager:
            return self.grid_manager.get_status()
        return None


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  SIDEWAYS Hybrid Strategy - 테스트")
    print("="*70)

    # SIDEWAYS 시장 시뮬레이션
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    base_price = 105_000_000
    noise = np.random.randn(100) * 2_000_000
    prices = base_price + noise
    prices = np.clip(prices, 100_000_000, 110_000_000)  # 박스권

    # 지표
    rsi_values = np.random.uniform(30, 70, 100)
    rsi_values[25] = 28  # 과매도
    rsi_values[65] = 72  # 과매수

    bb_middle = prices
    bb_upper = bb_middle + 3_000_000
    bb_lower = bb_middle - 3_000_000
    bb_lower[25] = prices[25] + 500_000  # 하단 이탈

    stoch_k = np.random.uniform(30, 70, 100)
    stoch_d = stoch_k + np.random.randn(100) * 5

    df = pd.DataFrame({
        'close': prices,
        'high': prices * 1.01,
        'low': prices * 0.99,
        'rsi': rsi_values,
        'bb_upper': bb_upper,
        'bb_middle': bb_middle,
        'bb_lower': bb_lower,
        'stoch_k': stoch_k,
        'stoch_d': stoch_d,
        'volume': np.random.uniform(1000, 2000, 100)
    }, index=dates)

    config = {
        'use_grid_trading': True,
        'grid_levels': 7,
        'grid_lookback': 20,
        'grid_position_size': 0.15,
        'grid_entry_threshold': 0.02,
        'grid_exit_threshold': 0.02,
        'use_rsi_bb': True,
        'use_stoch': True,
        'rsi_bb_oversold': 30,
        'rsi_bb_overbought': 70,
        'stoch_oversold': 20,
        'stoch_overbought': 80,
        'sideways_position_size': 0.4,
        'sideways_tp_1': 0.02,
        'sideways_tp_2': 0.04,
        'sideways_tp_3': 0.06,
        'sideways_stop_loss': -0.02,
        'sideways_max_hold_days': 20
    }

    strategy = SidewaysHybridStrategy(config)

    print("\n[전략 실행 테스트]")
    for i in range(30, len(df)):
        signal = strategy.execute(df, i)

        if signal['action'] == 'buy':
            print(f"\n  매수: {df.index[i].date()}")
            print(f"    {signal['reason']}")
            if 'level' in signal:
                print(f"    Grid 레벨: {signal['level']}")

        elif signal['action'] == 'sell':
            print(f"\n  매도: {df.index[i].date()}")
            print(f"    {signal['reason']}")

    # Grid 상태 출력
    grid_status = strategy.get_grid_status()
    if grid_status:
        print(f"\n\n[Grid Trading 상태]")
        print(f"  활성: {grid_status['active']}")
        if grid_status['active']:
            print(f"  Support: {grid_status['support']:,.0f}")
            print(f"  Resistance: {grid_status['resistance']:,.0f}")
            print(f"  Range: {grid_status['range_pct']:.2f}%")
            print(f"  레벨: {grid_status['total_levels']}개")
            print(f"  활용률: {grid_status['utilization']:.1f}%")

    print("\n\n✅ SIDEWAYS Hybrid 테스트 완료!")
    print("\n특징:")
    print("  ✓ Grid Trading (S/R 기반, 7레벨)")
    print("  ✓ Mean Reversion (RSI+BB, Stochastic)")
    print("  ✓ 우선순위: Grid > Mean Reversion")
    print("  ✓ 예상 효과: SIDEWAYS 수익 +30-50%")
