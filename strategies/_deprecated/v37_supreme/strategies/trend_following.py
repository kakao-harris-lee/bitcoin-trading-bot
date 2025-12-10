#!/usr/bin/env python3
"""
Trend Following Strategy (BULL_STRONG 전용)

목표: Buy&Hold의 70-80% 달성
핵심: 장기 보유 (최대 90일), MACD 데드크로스까지 홀딩
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class TrendFollowingStrategy:
    """추세 추종 전략 (BULL_STRONG 시장용)"""

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

        진입: MACD 골든크로스 + ADX > 25
        보유: MACD 양수 유지 + 최대 90일
        청산: MACD 데드크로스 OR 90일 경과
        """

        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 포지션 있을 때
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

            # 최고가 업데이트
            if row['close'] > self.highest_price:
                self.highest_price = row['close']

        # 포지션 없을 때
        else:
            entry_signal = self._check_entry(row, prev_row)
            if entry_signal:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.name
                self.highest_price = row['close']
                self.hold_days = 0
                return entry_signal

        return {'action': 'hold', 'reason': 'TREND_FOLLOWING_HOLD'}

    def _check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """진입 조건 확인"""

        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        adx = row.get('adx', 20)

        if prev_row is None:
            return None

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # ADX 확인 (강한 추세)
        adx_threshold = self.config.get('trend_adx_threshold', 25)

        if golden_cross and adx >= adx_threshold:
            return {
                'action': 'buy',
                'fraction': self.config.get('trend_position_size', 0.8),  # 80% 공격적
                'reason': f'TREND_FOLLOWING_ENTRY (ADX={adx:.1f})',
                'strategy': 'trend_following'
            }

        return None

    def _check_exit(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """청산 조건 확인"""

        current_price = row['close']
        profit = (current_price - self.entry_price) / self.entry_price

        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        if prev_row is None:
            return None

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # 1. MACD 데드크로스 (최우선)
        dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)

        if dead_cross:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TREND_DEAD_CROSS (profit={profit:.2%}, hold={self.hold_days}d)'
            }

        # 2. 최대 보유 기간 (90일)
        max_hold_days = self.config.get('trend_max_hold_days', 90)

        if self.hold_days >= max_hold_days:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TREND_MAX_HOLD (profit={profit:.2%}, {max_hold_days}d)'
            }

        # 3. 손절 (-10%, 추세 추종이므로 큰 손절 허용)
        stop_loss = self.config.get('trend_stop_loss', -0.10)

        if profit <= stop_loss:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TREND_STOP_LOSS ({stop_loss:.0%})'
            }

        # 4. Trailing Stop (고점 대비 -5%, 수익 20% 이상일 때만)
        if profit > 0.20:
            trailing_pct = self.config.get('trend_trailing_stop', 0.05)
            drawdown = (current_price - self.highest_price) / self.highest_price

            if drawdown <= -trailing_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TREND_TRAILING_STOP (profit={profit:.2%}, peak-{trailing_pct:.0%})'
                }

        return None


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  Trend Following Strategy - 테스트")
    print("="*70)

    # 샘플 데이터 (강한 상승장)
    dates = pd.date_range('2024-01-01', periods=120, freq='D')

    # 강한 상승 트렌드 + MACD 시뮬레이션
    base_price = 50000
    prices = base_price * (1 + np.arange(120) * 0.01)  # 일 1% 상승
    prices += np.random.randn(120) * 1000  # 노이즈

    # MACD 시뮬레이션 (골든크로스 → 유지 → 데드크로스)
    macd = np.zeros(120)
    macd_signal = np.zeros(120)

    macd[:10] = -50  # 초기 음수
    macd_signal[:10] = -30

    macd[10:90] = 50  # 골든크로스 후 유지
    macd_signal[10:90] = 30

    macd[90:] = 20  # 데드크로스
    macd_signal[90:] = 40

    df = pd.DataFrame({
        'close': prices,
        'macd': macd,
        'macd_signal': macd_signal,
        'adx': 30
    }, index=dates)

    config = {
        'trend_adx_threshold': 25,
        'trend_position_size': 0.8,
        'trend_max_hold_days': 90,
        'trend_stop_loss': -0.10,
        'trend_trailing_stop': 0.05
    }

    strategy = TrendFollowingStrategy(config)

    # 백테스팅 시뮬레이션
    capital = 10000000
    position = 0

    for i in range(30, len(df)):
        signal = strategy.execute(df, i)

        if signal['action'] == 'buy' and position == 0:
            buy_price = df.iloc[i]['close']
            position = (capital * signal['fraction']) / buy_price
            print(f"\n매수: {df.index[i].date()} | 가격: {buy_price:,.0f}원 | 수량: {position:.4f} BTC")
            print(f"  이유: {signal['reason']}")

        elif signal['action'] == 'sell' and position > 0:
            sell_price = df.iloc[i]['close']
            proceeds = position * sell_price
            profit = (proceeds - capital) / capital * 100

            print(f"\n매도: {df.index[i].date()} | 가격: {sell_price:,.0f}원")
            print(f"  이유: {signal['reason']}")
            print(f"  수익률: {profit:.2f}%")

            capital = proceeds
            position = 0

    print(f"\n최종 자본: {capital:,.0f}원")
    print(f"총 수익률: {(capital - 10000000) / 10000000 * 100:.2f}%")
    print("\n테스트 완료!")
