#!/usr/bin/env python3
"""
Defensive Trading Strategy (BEAR 시장 전용)

목표: Buy&Hold 대비 +30-50%p 손실 방어
특징:
  - BEAR_MODERATE: 극단적 저점만 매수 (RSI < 25)
  - BEAR_STRONG: 완전 현금 보유 (거래 안 함)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class DefensiveTradingStrategy:
    """방어적 거래 전략 (BEAR 시장용)"""

    def __init__(self, config: Dict):
        self.config = config
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.hold_days = 0
        self.market_state = 'UNKNOWN'  # BEAR_MODERATE or BEAR_STRONG

    def set_market_state(self, state: str):
        """시장 상태 업데이트"""
        self.market_state = state

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        BEAR_STRONG:
          - 진입: 절대 안 함 (예외: RSI < 20 AND 5일 연속 하락)
          - 청산: 즉시 (TP 3%)

        BEAR_MODERATE:
          - 진입: RSI < 25 (극단적 저점만)
          - 청산: TP 5-10% OR SL -5%
        """

        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # BEAR_STRONG: 포지션 즉시 청산
        if self.market_state == 'BEAR_STRONG' and self.in_position:
            self.in_position = False
            self.entry_price = 0
            self.entry_time = None
            self.hold_days = 0
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'DEFENSIVE_BEAR_STRONG_EXIT'
            }

        if self.in_position:
            self.hold_days += 1

            exit_signal = self._check_exit(row, prev_row)
            if exit_signal:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.hold_days = 0
                return exit_signal

        else:
            # BEAR_STRONG: 매우 제한적 진입만
            if self.market_state == 'BEAR_STRONG':
                entry_signal = self._check_entry_bear_strong(df, i)
            # BEAR_MODERATE: 극단적 저점 매수
            else:
                entry_signal = self._check_entry_bear_moderate(row, prev_row)

            if entry_signal:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.name
                self.hold_days = 0
                return entry_signal

        return {'action': 'hold', 'reason': f'DEFENSIVE_HOLD ({self.market_state})'}

    def _check_entry_bear_strong(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """BEAR_STRONG 시장 진입 조건 (매우 제한적)"""

        row = df.iloc[i]
        rsi = row.get('rsi', 50)

        # 조건 1: RSI < 20 (극단적 과매도)
        if rsi >= 20:
            return None

        # 조건 2: 최근 5일 연속 하락 확인
        if i < 5:
            return None

        recent_closes = df['close'].iloc[i-5:i+1]
        consecutive_down = all(recent_closes.iloc[j] < recent_closes.iloc[j-1] for j in range(1, len(recent_closes)))

        if not consecutive_down:
            return None

        # 조건 3: 20일 최저가 근처 (95% 이하)
        if i < 20:
            return None

        low_20d = df['close'].iloc[i-20:i+1].min()
        if row['close'] > low_20d * 1.05:  # 최저가 대비 5% 이내
            return None

        return {
            'action': 'buy',
            'fraction': self.config.get('defensive_bear_strong_size', 0.1),  # 10% (극히 보수적)
            'reason': f'DEFENSIVE_BEAR_STRONG_EXTREME (RSI={rsi:.1f}, 5d_down)',
            'strategy': 'defensive_bear_strong'
        }

    def _check_entry_bear_moderate(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """BEAR_MODERATE 시장 진입 조건"""

        rsi = row.get('rsi', 50)

        # RSI < 25 (극단적 과매도)
        rsi_threshold = self.config.get('defensive_rsi_oversold', 25)

        if rsi < rsi_threshold:
            return {
                'action': 'buy',
                'fraction': self.config.get('defensive_position_size', 0.2),  # 20% (방어적)
                'reason': f'DEFENSIVE_BEAR_MODERATE (RSI={rsi:.1f})',
                'strategy': 'defensive_bear_moderate'
            }

        return None

    def _check_exit(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """청산 조건 확인"""

        current_price = row['close']
        profit = (current_price - self.entry_price) / self.entry_price

        # BEAR_STRONG: 빠른 탈출 (TP 3%)
        if self.market_state == 'BEAR_STRONG':
            tp_bear_strong = self.config.get('defensive_tp_bear_strong', 0.03)

            if profit >= tp_bear_strong:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'DEFENSIVE_BEAR_STRONG_TP ({profit:.2%})'
                }

            # 손절도 빡빡하게 (-3%)
            if profit <= -0.03:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': 'DEFENSIVE_BEAR_STRONG_SL (-3%)'
                }

        # BEAR_MODERATE: 일반 익절/손절
        else:
            # Take Profit (5-10%)
            tp1 = self.config.get('defensive_take_profit_1', 0.05)
            tp2 = self.config.get('defensive_take_profit_2', 0.10)

            if profit >= tp2:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'DEFENSIVE_TP2 ({profit:.2%})'
                }
            elif profit >= tp1:
                return {
                    'action': 'sell',
                    'fraction': 0.5,  # 50% 익절
                    'reason': f'DEFENSIVE_TP1_PARTIAL ({profit:.2%})'
                }

            # Stop Loss (-5%)
            stop_loss = self.config.get('defensive_stop_loss', -0.05)

            if profit <= stop_loss:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'DEFENSIVE_STOP_LOSS ({stop_loss:.0%})'
                }

        # 최대 보유 기간 (20일, 빠른 회전)
        max_hold_days = self.config.get('defensive_max_hold_days', 20)

        if self.hold_days >= max_hold_days:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'DEFENSIVE_MAX_HOLD (profit={profit:.2%}, {max_hold_days}d)'
            }

        return None


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  Defensive Trading Strategy - 테스트")
    print("="*70)

    # 시나리오 1: BEAR_MODERATE (중간 하락장)
    print("\n[시나리오 1: BEAR_MODERATE]")

    dates = pd.date_range('2024-01-01', periods=60, freq='D')

    base_price = 50000
    prices = base_price * (1 - np.arange(60) * 0.005)  # 일 -0.5% 하락
    prices += np.random.randn(60) * 500

    rsi_values = np.random.uniform(20, 50, 60)
    rsi_values[20] = 22  # RSI 극단적 저점
    rsi_values[40] = 24

    df = pd.DataFrame({
        'close': prices,
        'rsi': rsi_values
    }, index=dates)

    config = {
        'defensive_rsi_oversold': 25,
        'defensive_position_size': 0.2,
        'defensive_take_profit_1': 0.05,
        'defensive_take_profit_2': 0.10,
        'defensive_stop_loss': -0.05,
        'defensive_max_hold_days': 20
    }

    strategy = DefensiveTradingStrategy(config)
    strategy.set_market_state('BEAR_MODERATE')

    trades = 0
    for i in range(30, len(df)):
        signal = strategy.execute(df, i)

        if signal['action'] == 'buy':
            print(f"  매수: {df.index[i].date()} | RSI: {df.iloc[i]['rsi']:.1f} | {signal['reason']}")
            trades += 1
        elif signal['action'] == 'sell':
            print(f"  매도: {df.index[i].date()} | {signal['reason']}")

    print(f"  총 거래: {trades}회")

    # 시나리오 2: BEAR_STRONG (극심한 하락장)
    print("\n[시나리오 2: BEAR_STRONG]")

    prices_strong = base_price * (1 - np.arange(60) * 0.01)  # 일 -1% 하락 (극심)
    rsi_strong = np.random.uniform(10, 30, 60)
    rsi_strong[25] = 18  # 극단적 저점

    df_strong = pd.DataFrame({
        'close': prices_strong,
        'rsi': rsi_strong
    }, index=dates)

    config['defensive_bear_strong_size'] = 0.1
    config['defensive_tp_bear_strong'] = 0.03

    strategy2 = DefensiveTradingStrategy(config)
    strategy2.set_market_state('BEAR_STRONG')

    trades_strong = 0
    for i in range(30, len(df_strong)):
        signal = strategy2.execute(df_strong, i)

        if signal['action'] == 'buy':
            print(f"  매수: {df_strong.index[i].date()} | RSI: {df_strong.iloc[i]['rsi']:.1f} | {signal['reason']}")
            trades_strong += 1
        elif signal['action'] == 'sell':
            print(f"  매도: {df_strong.index[i].date()} | {signal['reason']}")

    print(f"  총 거래: {trades_strong}회 (거의 없어야 정상)")

    print("\n테스트 완료!")
