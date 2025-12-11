#!/usr/bin/env python3
"""
Swing Trading Strategy (BULL_MODERATE 전용)

목표: 연 30-50% 수익
특징: 중기 보유 (20-40일), RSI 조정 구간 매수
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class SwingTradingStrategy:
    """스윙 트레이딩 전략 (BULL_MODERATE 시장용)"""

    def __init__(self, config: Dict):
        self.config = config
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.highest_price = 0
        self.hold_days = 0

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        진입: RSI < 40 + MACD 골든크로스
        보유: 20-40일
        청산: TP 10-15% OR SL -3% OR 40일 경과
        """

        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        if self.in_position:
            self.hold_days += 1

            exit_signal = self._check_exit(row, prev_row)
            if exit_signal:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.highest_price = 0
                self.hold_days = 0
                return exit_signal

            if row['close'] > self.highest_price:
                self.highest_price = row['close']

        else:
            entry_signal = self._check_entry(row, prev_row)
            if entry_signal:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.name
                self.highest_price = row['close']
                self.hold_days = 0
                return entry_signal

        return {'action': 'hold', 'reason': 'SWING_HOLD'}

    def _check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """진입 조건 확인"""

        rsi = row.get('rsi', 50)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        if prev_row is None:
            return None

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # RSI 과매도 (완화된 기준)
        rsi_threshold = self.config.get('swing_rsi_oversold', 40)

        # MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        if rsi < rsi_threshold and golden_cross:
            return {
                'action': 'buy',
                'fraction': self.config.get('swing_position_size', 0.6),  # 60%
                'reason': f'SWING_ENTRY (RSI={rsi:.1f}, MACD_GC)',
                'strategy': 'swing_trading'
            }

        # RSI만으로도 진입 (MACD 없이, 극단적 저점)
        rsi_extreme = self.config.get('swing_rsi_extreme', 30)

        if rsi < rsi_extreme and macd > 0:  # MACD 양수 확인
            return {
                'action': 'buy',
                'fraction': self.config.get('swing_position_size', 0.6),
                'reason': f'SWING_ENTRY_RSI_EXTREME (RSI={rsi:.1f})',
                'strategy': 'swing_trading'
            }

        return None

    def _check_exit(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """청산 조건 확인"""

        current_price = row['close']
        profit = (current_price - self.entry_price) / self.entry_price

        # 1. Take Profit (분할 익절)
        tp1 = self.config.get('swing_take_profit_1', 0.10)  # 10%
        tp2 = self.config.get('swing_take_profit_2', 0.15)  # 15%

        if profit >= tp2:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SWING_TP2 ({profit:.2%}, {self.hold_days}d)'
            }
        elif profit >= tp1 and self.hold_days >= 10:  # 10일 이상 보유 시
            return {
                'action': 'sell',
                'fraction': 0.5,  # 50% 익절
                'reason': f'SWING_TP1_PARTIAL ({profit:.2%}, {self.hold_days}d)'
            }

        # 2. Stop Loss
        stop_loss = self.config.get('swing_stop_loss', -0.03)  # -3%

        if profit <= stop_loss:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SWING_STOP_LOSS ({stop_loss:.0%})'
            }

        # 3. 최대 보유 기간 (40일)
        max_hold_days = self.config.get('swing_max_hold_days', 40)

        if self.hold_days >= max_hold_days:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SWING_MAX_HOLD (profit={profit:.2%}, {max_hold_days}d)'
            }

        # 4. Trailing Stop (고점 대비 -3%, 수익 5% 이상일 때)
        if profit > 0.05:
            trailing_pct = self.config.get('swing_trailing_stop', 0.03)
            drawdown = (current_price - self.highest_price) / self.highest_price

            if drawdown <= -trailing_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'SWING_TRAILING_STOP (profit={profit:.2%}, peak-{trailing_pct:.0%})'
                }

        # 5. RSI 과매수 (70 이상)
        rsi = row.get('rsi', 50)
        rsi_overbought = self.config.get('swing_rsi_overbought', 70)

        if rsi > rsi_overbought and profit > 0.03:  # 수익 3% 이상일 때만
            return {
                'action': 'sell',
                'fraction': 0.5,  # 50% 익절
                'reason': f'SWING_RSI_OVERBOUGHT (RSI={rsi:.1f}, profit={profit:.2%})'
            }

        return None


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  Swing Trading Strategy - 테스트")
    print("="*70)

    # 샘플 데이터 (중간 강도 상승장)
    dates = pd.date_range('2024-01-01', periods=60, freq='D')

    base_price = 50000
    prices = base_price + np.random.randn(60).cumsum() * 2000
    prices = prices * (1 + np.arange(60) * 0.003)  # 일 0.3% 상승

    # RSI 시뮬레이션
    rsi_values = np.random.uniform(30, 70, 60)
    rsi_values[10] = 35  # RSI 저점
    rsi_values[30] = 38

    # MACD 시뮬레이션
    macd = np.random.uniform(-20, 20, 60)
    macd_signal = macd - 5

    # 골든크로스 포인트
    macd[10:] = 10
    macd_signal[10:] = 5

    df = pd.DataFrame({
        'close': prices,
        'rsi': rsi_values,
        'macd': macd,
        'macd_signal': macd_signal
    }, index=dates)

    config = {
        'swing_rsi_oversold': 40,
        'swing_rsi_extreme': 30,
        'swing_rsi_overbought': 70,
        'swing_position_size': 0.6,
        'swing_take_profit_1': 0.10,
        'swing_take_profit_2': 0.15,
        'swing_stop_loss': -0.03,
        'swing_max_hold_days': 40,
        'swing_trailing_stop': 0.03
    }

    strategy = SwingTradingStrategy(config)

    capital = 10000000
    position = 0

    for i in range(30, len(df)):
        signal = strategy.execute(df, i)

        if signal['action'] == 'buy' and position == 0:
            buy_price = df.iloc[i]['close']
            position = (capital * signal['fraction']) / buy_price
            print(f"\n매수: {df.index[i].date()} | RSI: {df.iloc[i]['rsi']:.1f} | 가격: {buy_price:,.0f}원")
            print(f"  이유: {signal['reason']}")

        elif signal['action'] == 'sell' and position > 0:
            sell_price = df.iloc[i]['close']
            fraction = signal.get('fraction', 1.0)
            sell_amount = position * fraction
            proceeds = sell_amount * sell_price
            profit = (proceeds - (capital * 0.6 * fraction)) / (capital * 0.6 * fraction) * 100

            print(f"\n매도 ({fraction:.0%}): {df.index[i].date()} | RSI: {df.iloc[i]['rsi']:.1f}")
            print(f"  이유: {signal['reason']}")
            print(f"  수익률: {profit:.2f}%")

            capital += (proceeds - capital * 0.6 * fraction)
            position -= sell_amount

    print(f"\n최종 자본: {capital:,.0f}원")
    print(f"총 수익률: {(capital - 10000000) / 10000000 * 100:.2f}%")
    print("\n테스트 완료!")
