#!/usr/bin/env python3
"""
BEAR Signal Generator
=====================
v37 Defensive Trading 로직에서 Entry 조건만 추출

시장 조건:
  - MA20 기울기 < -0.5%/일
  - BEAR_MODERATE or BEAR_STRONG

Entry 조건:
  - RSI < 20 (극단 과매도)
  - 매우 보수적 진입
"""

import pandas as pd
import numpy as np
from typing import List, Dict


class BearSignals:
    """BEAR 시장용 시그널 생성기"""

    def __init__(self, config: Dict = None):
        """
        Args:
            config: 설정 딕셔너리 (v37 호환)
        """
        if config is None:
            config = {}

        self.rsi_oversold = config.get('defensive_rsi_oversold', 17)

    def generate(self, df: pd.DataFrame, market_states: pd.Series) -> pd.DataFrame:
        """
        BEAR 시그널 생성

        Args:
            df: 지표가 포함된 시장 데이터
            market_states: 시장 상태 시리즈

        Returns:
            시그널 DataFrame
        """
        signals = []

        for i in range(1, len(df)):
            row = df.iloc[i]

            # 시장 상태 확인
            current_state = market_states.iloc[i] if i < len(market_states) else 'UNKNOWN'

            if current_state not in ['BEAR_MODERATE', 'BEAR_STRONG']:
                continue

            # Entry 조건 확인
            if self._check_entry(row, current_state):
                signals.append({
                    'timestamp': row['timestamp'],  # Use timestamp column
                    'entry_price': row['close'],
                    'rsi': row.get('rsi', 50),
                    'market_state': current_state
                })

        return pd.DataFrame(signals)

    def _check_entry(self, row: pd.Series, market_state: str) -> bool:
        """
        Entry 조건 확인 (v37 Defensive 로직)

        Returns:
            True if 진입 조건 충족
        """
        rsi = row.get('rsi', 50)

        # 극단 과매도
        return rsi < self.rsi_oversold


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  BEAR Signal Generator - 테스트")
    print("="*70)

    # 샘플 데이터 생성
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    # 하락장 시뮬레이션
    prices = 50000 * (1 - np.arange(100) * 0.005)  # 일 0.5% 하락

    # RSI 시뮬레이션 (저점에서 과매도)
    rsi = 30 - 15 * np.sin(np.arange(100) * 0.2) + np.random.randn(100) * 5

    df = pd.DataFrame({
        'close': prices,
        'rsi': rsi
    }, index=dates)

    # BEAR_MODERATE와 BEAR_STRONG 섞기
    market_states = pd.Series(
        ['BEAR_MODERATE'] * 50 + ['BEAR_STRONG'] * 50,
        index=dates
    )

    # 시그널 생성
    generator = BearSignals()
    signals = generator.generate(df, market_states)

    print(f"\n생성된 시그널: {len(signals)}개")

    if len(signals) > 0:
        # 시장별 분포
        state_counts = signals['market_state'].value_counts()
        print(f"\n시장별 분포:")
        for state, count in state_counts.items():
            print(f"  {state}: {count}개")

        print(f"\n시그널 상세:")
        for _, sig in signals.head(10).iterrows():
            print(f"  {sig['timestamp'].date()} | 가격: {sig['entry_price']:,.0f}원 | "
                  f"RSI: {sig['rsi']:.1f} | 시장: {sig['market_state']}")

    print("\n테스트 완료!")
