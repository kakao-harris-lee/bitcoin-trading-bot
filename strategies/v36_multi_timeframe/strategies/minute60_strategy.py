#!/usr/bin/env python3
"""
Minute60 (1시간봉) 스캘핑 전략
v31 기반 포팅

특징:
- 보유 기간: 3-12시간 (3-12 캔들)
- 목표 수익: 1.5-3%
- Day BULL/SIDEWAYS 필터 필수
- 2025 목표: +10-15%

전략:
- Entry: Day BULL/SIDEWAYS + Minute60 RSI<30 + MACD 골든크로스
- Exit: RSI>70 OR MACD 데드크로스 OR TP 2.5% OR SL -1.5%
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np
import sys
sys.path.append('../../..')


class Minute60ScalpingStrategy:
    """Minute60 (1시간봉) 스캘핑 (v31 기반)"""

    def __init__(self, config: Dict, day_filter_state: str = 'UNKNOWN'):
        """
        Args:
            config: 하이퍼파라미터
            day_filter_state: Day 타임프레임의 시장 상태
        """
        self.config = config
        self.day_filter_state = day_filter_state

        # 포지션 상태
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None

    def set_day_filter(self, day_state: str):
        """Day 필터 상태 업데이트"""
        self.day_filter_state = day_state

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        Args:
            df: Minute60 데이터프레임 (지표 포함)
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
                return exit_signal

        # 포지션 없을 때: Entry
        else:
            entry_signal = self._check_entry(row, prev_row)
            if entry_signal:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.name
                return entry_signal

        return {'action': 'hold', 'reason': 'NO_SIGNAL_M60'}

    def _check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """Entry 조건 확인 (v31 기반)"""

        # Day 필터: BEAR 시 거래 금지
        if self.day_filter_state in ['BEAR_STRONG', 'BEAR_MODERATE']:
            return None

        rsi = row.get('rsi', 50)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        if prev_row is None:
            return None

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # RSI 과매도
        rsi_oversold = self.config.get('m60_rsi_oversold', 30)

        # Entry 조건
        if golden_cross and rsi < rsi_oversold:
            return {
                'action': 'buy',
                'fraction': self.config.get('m60_position_size', 0.3),
                'reason': f'M60_SCALPING_ENTRY (Day: {self.day_filter_state})',
                'timeframe': 'minute60'
            }

        return None

    def _check_exit(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """Exit 조건 확인"""

        current_price = row['close']
        profit = (current_price - self.entry_price) / self.entry_price

        rsi = row.get('rsi', 50)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        # 1. Take Profit
        tp = self.config.get('m60_take_profit', 0.025)  # 2.5%
        if profit >= tp:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'M60_TAKE_PROFIT_{int(tp*100)}%'
            }

        # 2. Stop Loss
        sl = self.config.get('m60_stop_loss', -0.015)  # -1.5%
        if profit <= sl:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'M60_STOP_LOSS_{int(abs(sl)*100)}%'
            }

        # 3. RSI 과매수
        rsi_overbought = self.config.get('m60_rsi_overbought', 70)
        if rsi > rsi_overbought:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'M60_RSI_OVERBOUGHT'
            }

        # 4. MACD 데드크로스
        if prev_row is not None:
            prev_macd = prev_row.get('macd', 0)
            prev_signal = prev_row.get('macd_signal', 0)

            dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)

            if dead_cross and profit > 0.005:  # 수익 0.5% 이상일 때만
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': 'M60_MACD_REVERSE'
                }

        # 5. Day 필터 변경 (BEAR 전환)
        if self.day_filter_state in ['BEAR_STRONG', 'BEAR_MODERATE']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'M60_DAY_FILTER_BEAR'
            }

        return None


if __name__ == '__main__':
    """테스트"""
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    print("="*70)
    print("  Minute60 Scalping Strategy - 테스트")
    print("="*70)

    # 2025 Minute60 데이터
    with DataLoader('../../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('minute60', start_date='2025-01-01', end_date='2025-10-17')

    print(f"데이터: {len(df)}개 캔들 (Minute60)")

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd'])

    # 전략 테스트 (Day 필터: BULL_MODERATE 가정)
    config = {
        'm60_rsi_oversold': 30,
        'm60_rsi_overbought': 70,
        'm60_position_size': 0.3,
        'm60_take_profit': 0.025,
        'm60_stop_loss': -0.015
    }

    strategy = Minute60ScalpingStrategy(config, day_filter_state='BULL_MODERATE')

    signals = []
    for i in range(30, min(200, len(df))):
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
        print(f"  {sig['date']} | {sig['action']:4s} | {sig['reason']:35s} | {sig['price']:,.0f}원")

    print(f"\nMinute60 전략 테스트 완료!")
    print(f"다음 단계: Ensemble Manager")
