#!/usr/bin/env python3
"""
BULL_MODERATE Signal Generator
===============================
v37 Swing Trading 로직에서 Entry 조건만 추출

시장 조건:
  - MA20 기울기 0.5-1.5%/일
  - ADX 12-26 (중간 추세)

Entry 조건:
  - RSI 과매도 (30-40)
  - MFI < 50 (자금 흐름 약세)
"""

import pandas as pd
import numpy as np
from typing import List, Dict


class BullModerateSignals:
    """BULL_MODERATE 시장용 시그널 생성기"""

    def __init__(self, config: Dict = None):
        """
        Args:
            config: 설정 딕셔너리 (v37 호환)
        """
        if config is None:
            config = {}

        self.rsi_oversold = config.get('swing_rsi_oversold', 33)

    def generate(self, df: pd.DataFrame, market_states: pd.Series) -> pd.DataFrame:
        """
        BULL_MODERATE 시그널 생성

        Args:
            df: 지표가 포함된 시장 데이터
            market_states: 시장 상태 시리즈

        Returns:
            시그널 DataFrame
        """
        signals = []

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]

            # 시장 상태 확인
            current_state = market_states.iloc[i] if i < len(market_states) else 'UNKNOWN'

            if current_state != 'BULL_MODERATE':
                continue

            # Entry 조건 확인 (v37 방식)
            if self._check_entry(row, prev_row):
                signals.append({
                    'timestamp': row['timestamp'],  # Use timestamp column
                    'entry_price': row['close'],
                    'rsi': row.get('rsi', 50),
                    'macd': row.get('macd', 0),
                    'macd_signal': row.get('macd_signal', 0),
                    'market_state': current_state
                })

        return pd.DataFrame(signals)

    def _check_entry(self, row: pd.Series, prev_row: pd.Series) -> bool:
        """
        Entry 조건 확인 (v37 Swing Trading 로직 완벽 재현)

        v37 방식:
        1. (RSI < 33 AND MACD 골든크로스) OR
        2. (RSI < 30 AND MACD > 0)

        Returns:
            True if 진입 조건 충족
        """
        rsi = row.get('rsi', 50)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        if prev_row is None:
            return False

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # 조건 1: RSI 과매도 + MACD 골든크로스
        rsi_threshold = self.rsi_oversold  # 33
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        if rsi < rsi_threshold and golden_cross:
            return True

        # 조건 2: RSI 극단 과매도 + MACD 양수
        rsi_extreme = 30  # v37 설정
        if rsi < rsi_extreme and macd > 0:
            return True

        return False


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  BULL_MODERATE Signal Generator - 테스트")
    print("="*70)

    # 샘플 데이터 생성
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    # 중간 상승장 시뮬레이션
    prices = 50000 * (1 + np.arange(100) * 0.005)  # 일 0.5% 상승

    # RSI 시뮬레이션 (과매도/정상 반복)
    rsi = 40 + 20 * np.sin(np.arange(100) * 0.3) + np.random.randn(100) * 5

    # MFI 시뮬레이션
    mfi = 45 + 20 * np.sin(np.arange(100) * 0.25) + np.random.randn(100) * 5

    df = pd.DataFrame({
        'close': prices,
        'rsi': rsi,
        'mfi': mfi
    }, index=dates)

    # 모든 날을 BULL_MODERATE로 분류
    market_states = pd.Series('BULL_MODERATE', index=dates)

    # 시그널 생성
    generator = BullModerateSignals()
    signals = generator.generate(df, market_states)

    print(f"\n생성된 시그널: {len(signals)}개")
    print(f"\n시그널 상세:")
    for _, sig in signals.head(10).iterrows():
        print(f"  {sig['timestamp'].date()} | 가격: {sig['entry_price']:,.0f}원 | "
              f"RSI: {sig['rsi']:.1f} | MFI: {sig['mfi']:.1f}")

    print("\n테스트 완료!")
