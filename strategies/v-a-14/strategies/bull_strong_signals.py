#!/usr/bin/env python3
"""
BULL_STRONG Signal Generator
=============================
v37 Trend Following 로직에서 Entry 조건만 추출

시장 조건:
  - MA20 기울기 > 1.5%/일
  - ADX > 26 (강한 추세)

Entry 조건:
  - MACD 골든크로스
  - ADX > 25
"""

import pandas as pd
import numpy as np
from typing import List, Dict


class BullStrongSignals:
    """BULL_STRONG 시장용 시그널 생성기"""

    def __init__(self, config: Dict = None):
        """
        Args:
            config: 설정 딕셔너리 (v37 호환)
        """
        if config is None:
            config = {}

        self.adx_threshold = config.get('trend_adx_threshold', 25)

    def generate(self, df: pd.DataFrame, market_states: pd.Series) -> pd.DataFrame:
        """
        BULL_STRONG 시그널 생성

        Args:
            df: 지표가 포함된 시장 데이터
            market_states: 시장 상태 시리즈 (index=timestamp, value='BULL_STRONG' 등)

        Returns:
            시그널 DataFrame (timestamp, entry_price, indicators)
        """
        signals = []

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]

            # 시장 상태 확인
            current_state = market_states.iloc[i] if i < len(market_states) else 'UNKNOWN'

            if current_state != 'BULL_STRONG':
                continue

            # Entry 조건 확인
            if self._check_entry(row, prev_row):
                signals.append({
                    'timestamp': row['timestamp'],  # Use timestamp column
                    'entry_price': row['close'],
                    'macd': row.get('macd', 0),
                    'macd_signal': row.get('macd_signal', 0),
                    'adx': row.get('adx', 20),
                    'market_state': current_state
                })

        return pd.DataFrame(signals)

    def _check_entry(self, row: pd.Series, prev_row: pd.Series) -> bool:
        """
        Entry 조건 확인 (v37 Trend Following 로직)

        Returns:
            True if 진입 조건 충족
        """
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        adx = row.get('adx', 20)

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # 1. MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # 2. ADX 임계값
        adx_strong = adx >= self.adx_threshold

        return golden_cross and adx_strong


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  BULL_STRONG Signal Generator - 테스트")
    print("="*70)

    # 샘플 데이터 생성
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    # 강한 상승장 시뮬레이션
    prices = 50000 * (1 + np.arange(100) * 0.01)  # 일 1% 상승

    # MACD 시뮬레이션 (중간에 골든크로스)
    macd = np.concatenate([
        -50 + np.random.randn(30) * 5,  # 초기 음수
        50 + np.random.randn(70) * 5    # 골든크로스 후 양수
    ])

    macd_signal = np.concatenate([
        -30 + np.random.randn(30) * 5,
        30 + np.random.randn(70) * 5
    ])

    df = pd.DataFrame({
        'close': prices,
        'macd': macd,
        'macd_signal': macd_signal,
        'adx': 30  # 강한 추세
    }, index=dates)

    # 모든 날을 BULL_STRONG으로 분류
    market_states = pd.Series('BULL_STRONG', index=dates)

    # 시그널 생성
    generator = BullStrongSignals()
    signals = generator.generate(df, market_states)

    print(f"\n생성된 시그널: {len(signals)}개")
    print(f"\n시그널 상세:")
    for _, sig in signals.head(10).iterrows():
        print(f"  {sig['timestamp'].date()} | 가격: {sig['entry_price']:,.0f}원 | "
              f"MACD: {sig['macd']:.2f} | ADX: {sig['adx']:.1f}")

    print("\n테스트 완료!")
