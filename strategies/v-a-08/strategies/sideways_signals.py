#!/usr/bin/env python3
"""
SIDEWAYS Signal Generator
=========================
v35 검증된 3종 조합 전략

시장 조건:
  - MA20 기울기 -0.2~0.2%/일
  - ADX < 20 (약한 추세)

Entry 조건 (3가지):
  1. RSI+BB: RSI < 30 AND price < BB_lower
  2. Stochastic: %K < 20 AND %K > %D (골든크로스)
  3. Volume Breakout: Volume > avg × 2.0 AND 반등
"""

import pandas as pd
import numpy as np
from typing import List, Dict


class SidewaysSignals:
    """SIDEWAYS 시장용 시그널 생성기"""

    def __init__(self, config: Dict = None):
        """
        Args:
            config: 설정 딕셔너리 (v37 호환)
        """
        if config is None:
            config = {}

        # v37 설정 재활용
        self.use_rsi_bb = config.get('use_rsi_bb', True)
        self.use_stoch = config.get('use_stoch', True)
        self.use_volume_breakout = config.get('use_volume_breakout', True)

        self.rsi_bb_oversold = config.get('rsi_bb_oversold', 24)
        self.rsi_bb_overbought = config.get('rsi_bb_overbought', 72)

        self.stoch_oversold = config.get('stoch_oversold', 20)
        self.stoch_overbought = config.get('stoch_overbought', 80)

        self.volume_breakout_mult = config.get('volume_breakout_mult', 1.68)

    def generate(self, df: pd.DataFrame, market_states: pd.Series) -> pd.DataFrame:
        """
        SIDEWAYS 시그널 생성

        Args:
            df: 지표가 포함된 시장 데이터
            market_states: 시장 상태 시리즈

        Returns:
            시그널 DataFrame
        """
        signals = []

        for i in range(20, len(df)):  # 20일 rolling 필요
            row = df.iloc[i]
            prev_row = df.iloc[i-1]

            # 시장 상태 확인
            current_state = market_states.iloc[i] if i < len(market_states) else 'UNKNOWN'

            if current_state != 'SIDEWAYS':
                continue

            # Entry 조건 확인 (3가지 중 하나)
            entry_method = self._check_entry(row, prev_row, df, i)

            if entry_method:
                signals.append({
                    'timestamp': row['timestamp'],  # Use timestamp column
                    'entry_price': row['close'],
                    'rsi': row.get('rsi', 50),
                    'bb_position': row.get('bb_position', 0.5),
                    'stoch_k': row.get('stoch_k', 50),
                    'volume_ratio': row.get('volume_ratio', 1.0),
                    'entry_method': entry_method,
                    'market_state': current_state
                })

        return pd.DataFrame(signals)

    def _check_entry(self, row: pd.Series, prev_row: pd.Series,
                     df: pd.DataFrame, i: int) -> str:
        """
        Entry 조건 확인 (3가지)

        Returns:
            'rsi_bb', 'stoch', 'volume_breakout', or None
        """

        # 1. RSI + Bollinger Bands (가장 신뢰도 높음)
        if self.use_rsi_bb:
            rsi = row.get('rsi', 50)
            bb_position = row.get('bb_position', 0.5)

            # RSI 과매도 + BB 하단 근처
            if rsi < self.rsi_bb_oversold and bb_position < 0.2:
                return 'rsi_bb'

        # 2. Stochastic Oscillator
        if self.use_stoch:
            stoch_k = row.get('stoch_k', 50)
            stoch_d = row.get('stoch_d', 50)

            prev_stoch_k = prev_row.get('stoch_k', 50)
            prev_stoch_d = prev_row.get('stoch_d', 50)

            # 과매도 + 골든크로스
            golden_cross = (prev_stoch_k <= prev_stoch_d) and (stoch_k > stoch_d)

            if stoch_k < self.stoch_oversold and golden_cross:
                return 'stoch'

        # 3. Volume Breakout
        if self.use_volume_breakout:
            volume_ratio = row.get('volume_ratio', 1.0)
            price_change = (row['close'] - prev_row['close']) / prev_row['close']

            # 거래량 급증 + 반등
            if volume_ratio > self.volume_breakout_mult and price_change > 0:
                return 'volume_breakout'

        return None


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  SIDEWAYS Signal Generator - 테스트")
    print("="*70)

    # 샘플 데이터 생성 (횡보장)
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    # 횡보 시뮬레이션
    base_price = 50000
    prices = base_price + np.random.randn(100).cumsum() * 500  # 작은 변동

    # RSI 시뮬레이션 (과매도/과매수 반복)
    rsi = 50 + 30 * np.sin(np.arange(100) * 0.2) + np.random.randn(100) * 5

    # BB Position 시뮬레이션
    bb_position = 0.5 + 0.3 * np.sin(np.arange(100) * 0.3)

    # Stochastic 시뮬레이션
    stoch_k = 50 + 40 * np.sin(np.arange(100) * 0.25)
    stoch_d = 50 + 40 * np.sin(np.arange(100) * 0.25 - 0.1)

    # Volume ratio
    volume_ratio = 1.0 + np.random.exponential(0.5, 100)

    df = pd.DataFrame({
        'close': prices,
        'rsi': rsi,
        'bb_position': bb_position,
        'stoch_k': stoch_k,
        'stoch_d': stoch_d,
        'volume_ratio': volume_ratio
    }, index=dates)

    # 모든 날을 SIDEWAYS로 분류
    market_states = pd.Series('SIDEWAYS', index=dates)

    # 시그널 생성
    generator = SidewaysSignals()
    signals = generator.generate(df, market_states)

    print(f"\n생성된 시그널: {len(signals)}개")

    # Entry 방법별 분포
    if len(signals) > 0:
        method_counts = signals['entry_method'].value_counts()
        print(f"\nEntry 방법별 분포:")
        for method, count in method_counts.items():
            print(f"  {method}: {count}개 ({count/len(signals)*100:.1f}%)")

        print(f"\n시그널 상세 (처음 10개):")
        for _, sig in signals.head(10).iterrows():
            print(f"  {sig['timestamp'].date()} | 가격: {sig['entry_price']:,.0f}원 | "
                  f"방법: {sig['entry_method']:15s} | RSI: {sig['rsi']:.1f}")

    print("\n테스트 완료!")
