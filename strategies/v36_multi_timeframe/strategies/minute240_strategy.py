#!/usr/bin/env python3
"""
Minute240 (4시간봉) 스윙 트레이딩 전략

특징:
- 보유 기간: 1-3일 (6-18 캔들)
- 목표 수익: 3-7%
- Day 필터 + Minute240 Entry
- 2025 목표: +8-12%

전략:
- Entry: Day BULL 확인 + Minute240 MACD 골든크로스 + RSI > 50
- Exit: MACD 데드크로스 OR TP 5% OR SL -2%
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np
import sys
sys.path.append('../../..')

from strategies.v34_supreme.market_classifier_v34 import MarketClassifierV34


class Minute240SwingStrategy:
    """Minute240 (4시간봉) 스윙 트레이딩"""

    def __init__(self, config: Dict, day_filter_state: str = 'UNKNOWN'):
        """
        Args:
            config: 하이퍼파라미터
            day_filter_state: Day 타임프레임의 시장 상태 (필터로 사용)
        """
        self.config = config
        self.day_filter_state = day_filter_state

        # 포지션 상태
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.highest_price = 0

    def set_day_filter(self, day_state: str):
        """Day 필터 상태 업데이트"""
        self.day_filter_state = day_state

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        Args:
            df: Minute240 데이터프레임 (지표 포함)
            i: 현재 인덱스

        Returns:
            시그널 딕셔너리
        """
        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 포지션 있을 때: Exit
        if self.in_position:
            exit_signal = self._check_exit(row, prev_row)
            if exit_signal:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.highest_price = 0
                return exit_signal

        # 포지션 없을 때: Entry
        else:
            entry_signal = self._check_entry(row, prev_row)
            if entry_signal:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.name
                self.highest_price = row['close']
                return entry_signal

        return {'action': 'hold', 'reason': 'NO_SIGNAL_M240'}

    def _check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """Entry 조건 확인"""

        # Day 필터: BULL 또는 SIDEWAYS_UP만 거래 허용
        if self.day_filter_state not in ['BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS_UP']:
            return None

        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        rsi = row.get('rsi', 50)

        if prev_row is None:
            return None

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # RSI 필터
        rsi_threshold = self.config.get('m240_rsi_threshold', 50)

        # Entry 조건
        if golden_cross and rsi > rsi_threshold:
            return {
                'action': 'buy',
                'fraction': self.config.get('m240_position_size', 0.3),
                'reason': f'M240_SWING_ENTRY (Day: {self.day_filter_state})',
                'timeframe': 'minute240'
            }

        return None

    def _check_exit(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """Exit 조건 확인"""

        current_price = row['close']
        profit = (current_price - self.entry_price) / self.entry_price

        # 최고가 업데이트
        if current_price > self.highest_price:
            self.highest_price = current_price

        # 1. Take Profit
        tp = self.config.get('m240_take_profit', 0.05)  # 5%
        if profit >= tp:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'M240_TAKE_PROFIT_{int(tp*100)}%'
            }

        # 2. Stop Loss
        sl = self.config.get('m240_stop_loss', -0.02)  # -2%
        if profit <= sl:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'M240_STOP_LOSS_{int(abs(sl)*100)}%'
            }

        # 3. MACD 데드크로스
        if prev_row is not None:
            macd = row.get('macd', 0)
            macd_signal = row.get('macd_signal', 0)
            prev_macd = prev_row.get('macd', 0)
            prev_signal = prev_row.get('macd_signal', 0)

            dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)

            if dead_cross and profit > 0.01:  # 수익 1% 이상일 때만
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': 'M240_MACD_REVERSE'
                }

        # 4. Trailing Stop (수익 3% 이상 시)
        if profit > 0.03:
            trailing_pct = self.config.get('m240_trailing_stop', 0.02)  # 고점 대비 -2%
            drawdown = (current_price - self.highest_price) / self.highest_price

            if drawdown <= -trailing_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': 'M240_TRAILING_STOP'
                }

        # 5. Day 필터 변경 (BEAR 전환)
        if self.day_filter_state in ['BEAR_STRONG', 'BEAR_MODERATE', 'SIDEWAYS_DOWN']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'M240_DAY_FILTER_BEAR'
            }

        return None


if __name__ == '__main__':
    """테스트"""
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    print("="*70)
    print("  Minute240 Swing Strategy - 테스트")
    print("="*70)

    # 2025 Minute240 데이터
    with DataLoader('../../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('minute240', start_date='2025-01-01', end_date='2025-10-17')

    print(f"데이터: {len(df)}개 캔들 (Minute240)")

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd'])

    # 전략 테스트 (Day 필터: BULL_STRONG 가정)
    config = {
        'm240_rsi_threshold': 50,
        'm240_position_size': 0.3,
        'm240_take_profit': 0.05,
        'm240_stop_loss': -0.02,
        'm240_trailing_stop': 0.02
    }

    strategy = Minute240SwingStrategy(config, day_filter_state='BULL_STRONG')

    signals = []
    for i in range(30, min(100, len(df))):
        signal = strategy.execute(df, i)
        if signal['action'] != 'hold':
            signals.append({
                'date': df.iloc[i].name,
                'action': signal['action'],
                'reason': signal['reason'],
                'price': df.iloc[i]['close']
            })

    print(f"\n[시그널 발생: {len(signals)}개]")
    for sig in signals[:10]:
        print(f"  {sig['date']} | {sig['action']:4s} | {sig['reason']:30s} | {sig['price']:,.0f}원")

    print(f"\nMinute240 전략 테스트 완료!")
    print(f"다음 단계: Minute60 스캘핑 전략")
