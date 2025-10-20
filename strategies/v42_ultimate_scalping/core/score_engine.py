#!/usr/bin/env python3
"""
Unified Score Engine for v42
- v41 최적 가중치 적용
- 7차원 투표 시스템
- 타임프레임별 차등 점수
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


class UnifiedScoreEngine:
    """통합 점수 계산 엔진"""

    def __init__(self, config):
        self.config = config

        # v41 최적 가중치 (상관계수 기반)
        self.optimized_weights = {
            'minute5': {
                'rsi_oversold': 10,      # 극단값 중요
                'mfi_bullish': 15,
                'volume_spike': 12,
                'low_vol': 8,
                'local_min': 20,
                'trend_following': 5,
                'mean_reversion': 5
            },
            'minute15': {
                'rsi_oversold': 8,
                'mfi_bullish': 20,       # 상관 0.065 ← 대폭 상향
                'volume_spike': 12,      # 상관 0.039
                'low_vol': 16,           # 역상관 -0.053
                'local_min': 27,         # 상관 0.085 (최고)
                'trend_following': 7,
                'mean_reversion': 5
            },
            'minute60': {
                'rsi_oversold': 5,
                'mfi_bullish': 16,       # 상관 0.054
                'volume_spike': 6,
                'low_vol': 37,           # 역상관 -0.123 (최강!)
                'local_min': 26,         # 상관 0.088
                'trend_following': 8,
                'mean_reversion': 7
            },
            'minute240': {
                'rsi_oversold': 8,
                'mfi_bullish': 22,
                'volume_spike': 10,
                'low_vol': 20,
                'local_min': 25,
                'trend_following': 10,
                'mean_reversion': 10
            },
            'day': {
                'rsi_oversold': 8,       # 역상관 -0.092
                'mfi_bullish': 28,       # 상관 0.170 (압도적!)
                'volume_spike': 8,
                'low_vol': 15,
                'local_min': 20,         # 상관 0.063
                'trend_following': 12,
                'mean_reversion': 10
            }
        }

        # v41 최적 임계값 (백분위수 기반)
        self.tier_thresholds = {
            'minute5': {'S': 30, 'A': 20, 'B': 15},
            'minute15': {'S': 25, 'A': 15, 'B': 10},
            'minute60': {'S': 25, 'A': 15, 'B': 10},
            'minute240': {'S': 30, 'A': 20, 'B': 15},
            'day': {'S': 28, 'A': 18, 'B': 12}
        }

    def calculate_score(self, row, timeframe='minute15'):
        """단일 행에 대한 점수 계산"""

        weights = self.optimized_weights.get(timeframe, self.optimized_weights['minute15'])
        score = 0
        signals = []

        # 1. RSI Oversold (타임프레임별 차등)
        rsi_threshold = self.config['strategies']['rsi_oversold']['params'][timeframe]['threshold']
        if row['rsi'] <= rsi_threshold:
            score += weights['rsi_oversold']
            signals.append('RSI_OVERSOLD')

        # 2. MFI Bullish (가장 강력한 지표!)
        if row['mfi'] >= 50:
            score += weights['mfi_bullish']
            signals.append('MFI_BULLISH')

            # 보너스: MFI >= 60
            if row['mfi'] >= 60:
                score += weights['mfi_bullish'] * 0.2  # 20% 추가
                signals.append('MFI_VERY_BULLISH')

        # 3. Volume Spike
        vol_ratio = self.config['strategies']['volume_spike']['params'][timeframe]['ratio']
        if row['volume_ratio'] >= vol_ratio:
            score += weights['volume_spike']
            signals.append('VOLUME_SPIKE')

        # 4. Low Volatility (압축 구간 = 폭발 직전)
        # minute60에서 가장 중요! (역상관 -0.123)
        if row['atr_ratio'] <= 0.8:
            score += weights['low_vol']
            signals.append('LOW_VOL')

            # 초저변동성 보너스
            if row['atr_ratio'] <= 0.6:
                score += weights['low_vol'] * 0.3
                signals.append('VERY_LOW_VOL')

        # 5. Local Minima (바닥 확인)
        # 이미 계산되어 있다고 가정 (row['is_local_min'])
        if row.get('is_local_min', False):
            score += weights['local_min']
            signals.append('LOCAL_MIN')

        # 6. Trend Following (ADX)
        if row['adx'] >= 25:
            score += weights['trend_following']
            signals.append('TREND_STRONG')

            # 강한 추세 보너스
            if row['adx'] >= 40:
                score += weights['trend_following'] * 0.5
                signals.append('TREND_VERY_STRONG')

        # 7. Mean Reversion (BB)
        # BB 하단 돌파 시
        if row['close'] < row['bb_lower']:
            score += weights['mean_reversion']
            signals.append('BB_LOWER')

        # BB Position 극단값
        if row['bb_position'] <= 0.2:
            score += weights['mean_reversion'] * 0.5
            signals.append('BB_OVERSOLD')

        return score, signals

    def classify_tier(self, score, timeframe='minute15'):
        """점수에 따라 Tier 분류"""

        thresholds = self.tier_thresholds.get(timeframe, self.tier_thresholds['minute15'])

        if score >= thresholds['S']:
            return 'S'
        elif score >= thresholds['A']:
            return 'A'
        elif score >= thresholds['B']:
            return 'B'
        else:
            return 'C'

    def add_local_extrema(self, df, order=5):
        """Local Minima/Maxima 계산"""

        # Local minima
        local_min_indices = argrelextrema(df['low'].values, np.less, order=order)[0]
        df['is_local_min'] = False
        df.loc[local_min_indices, 'is_local_min'] = True

        # Local maxima
        local_max_indices = argrelextrema(df['high'].values, np.greater, order=order)[0]
        df['is_local_max'] = False
        df.loc[local_max_indices, 'is_local_max'] = True

        return df

    def score_dataframe(self, df, timeframe='minute15'):
        """전체 데이터프레임 점수 계산"""

        print(f"[{timeframe}] 점수 계산 중...")

        # Local extrema 추가
        df = self.add_local_extrema(df)

        # 각 행에 대해 점수 계산
        scores = []
        all_signals = []

        for idx, row in df.iterrows():
            score, signals = self.calculate_score(row, timeframe)
            scores.append(score)
            all_signals.append(signals)

        df['score'] = scores
        df['signals'] = all_signals

        # Tier 분류
        df['tier'] = df['score'].apply(lambda x: self.classify_tier(x, timeframe))

        # 통계
        tier_counts = df['tier'].value_counts()
        print(f"  - S-Tier: {tier_counts.get('S', 0):,}개")
        print(f"  - A-Tier: {tier_counts.get('A', 0):,}개")
        print(f"  - B-Tier: {tier_counts.get('B', 0):,}개")
        print(f"  - C-Tier: {tier_counts.get('C', 0):,}개")
        print(f"  - 평균 점수: {df['score'].mean():.1f}")
        print(f"  - 최고 점수: {df['score'].max():.1f}")

        return df

    def score_all_timeframes(self, data_dict):
        """모든 타임프레임 점수 계산"""

        print(f"\n{'='*70}")
        print(f"통합 점수 계산")
        print(f"{'='*70}\n")

        scored_data = {}

        for timeframe, df in data_dict.items():
            try:
                scored_df = self.score_dataframe(df.copy(), timeframe)
                scored_data[timeframe] = scored_df
            except Exception as e:
                print(f"[{timeframe}] 오류: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n{'='*70}")
        print(f"점수 계산 완료")
        print(f"{'='*70}\n")

        return scored_data


def test_score_engine():
    """Score Engine 테스트"""
    import sys
    import os

    # v42 core 디렉토리 추가
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)

    from data_loader import MultiTimeframeDataLoader
    import json

    # Config 로드
    with open('../config/base_config.json') as f:
        config = json.load(f)

    # DataLoader
    loader = MultiTimeframeDataLoader()
    data = loader.load_all_timeframes(
        start_date='2024-01-01',
        end_date='2024-02-01'  # 1개월만 테스트
    )

    # Score Engine
    engine = UnifiedScoreEngine(config)
    scored_data = engine.score_all_timeframes(data)

    # 결과 출력
    print(f"\n{'='*70}")
    print(f"결과 샘플 (minute15)")
    print(f"{'='*70}\n")

    df = scored_data['minute15']

    # S-Tier 시그널만 출력
    s_tier = df[df['tier'] == 'S'].copy()
    print(f"\nS-Tier 시그널: {len(s_tier)}개\n")

    for idx, row in s_tier.head(5).iterrows():
        print(f"{row['timestamp']} | Score: {row['score']:.0f} | Signals: {row['signals']}")

    # 점수 분포
    print(f"\n점수 분포:")
    print(df['score'].describe())

    print(f"\nTier 분포:")
    print(df['tier'].value_counts())


if __name__ == '__main__':
    test_score_engine()
