#!/usr/bin/env python3
"""
Step 2-3: 최적화된 점수 체계로 재분류
- 최적화된 가중치 적용
- 새 임계값으로 Tier 재분류
- 전체 타임프레임 데이터 재분석
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime
from scipy.signal import argrelextrema
from sklearn.cluster import DBSCAN
import warnings
warnings.filterwarnings('ignore')


class OptimizedScoreClassifier:
    """최적화된 점수 체계로 재분류"""

    def __init__(self):
        self.db_path = '../../upbit_bitcoin.db'

        # 최적화된 가중치 (타임프레임별)
        self.optimized_weights = {
            'minute5': {
                'is_local_min': 20,  # 유지
                'swing_end': 7,      # 15 → 7 (하향)
                'near_support': 15,  # 유지
                'low_vol': 10,       # 유지
                'extreme_below_ma': 10,  # 유지
                'breakout_20d': 5,   # 유지
                'rsi_oversold': 8,   # 유지
                'volume_spike': 7,   # 유지
                'mfi_bullish': 20    # 5 → 20 (대폭 상향)
            },
            'minute15': {
                'is_local_min': 27,  # 20 → 27
                'swing_end': 7,      # 15 → 7
                'near_support': 15,
                'low_vol': 16,       # 10 → 16
                'extreme_below_ma': 10,
                'breakout_20d': 11,  # 5 → 11
                'rsi_oversold': 8,
                'volume_spike': 12,  # 7 → 12
                'mfi_bullish': 20    # 5 → 20
            },
            'minute60': {
                'is_local_min': 26,  # 20 → 26
                'swing_end': 2,      # 15 → 2 (대폭 하향)
                'near_support': 15,
                'low_vol': 37,       # 10 → 37 (대폭 상향)
                'extreme_below_ma': 10,
                'breakout_20d': 8,   # 5 → 8
                'rsi_oversold': 8,
                'volume_spike': 6,   # 7 → 6
                'mfi_bullish': 16    # 5 → 16
            },
            'minute240': {
                'is_local_min': 20,
                'swing_end': 15,
                'near_support': 15,
                'low_vol': 10,
                'extreme_below_ma': 10,
                'breakout_20d': 5,
                'rsi_oversold': 8,
                'volume_spike': 7,
                'mfi_bullish': 20    # 5 → 20
            },
            'day': {
                'is_local_min': 20,
                'swing_end': 15,
                'near_support': 15,
                'low_vol': 10,
                'extreme_below_ma': 10,
                'breakout_20d': 5,
                'rsi_oversold': 8,
                'volume_spike': 7,
                'mfi_bullish': 28    # 5 → 28 (가장 강력한 상관)
            }
        }

        # 최적화된 임계값 (백분위수 기반)
        self.optimized_thresholds = {
            'S_tier': 25,  # 70 → 25 (상위 20%)
            'A_tier': 15,  # 55 → 15 (상위 40%)
            'B_tier': 10   # 40 → 10 (상위 60%)
        }

    def load_advanced_results(self, timeframe):
        """기존 7차원 분석 결과 로드"""
        file_path = f'analysis/advanced/signals_{timeframe}_advanced.csv'
        print(f"[{timeframe}] 기존 분석 결과 로드: {file_path}")

        df = pd.read_csv(file_path)
        print(f"  - 로드 완료: {len(df):,}개 캔들")

        return df

    def recalculate_score(self, df, timeframe):
        """최적화된 가중치로 점수 재계산"""
        print(f"[{timeframe}] 최적화된 점수 재계산 중...")

        weights = self.optimized_weights[timeframe]

        scores = []
        for i in range(len(df)):
            score = 0

            # 7차원 점수 계산
            if df.iloc[i].get('is_local_min', False):
                score += weights['is_local_min']

            if df.iloc[i].get('swing_type', '') == 'down_swing_end':
                score += weights['swing_end']

            if df.iloc[i].get('near_support', False):
                score += weights['near_support']

            if df.iloc[i].get('vol_regime', '') == 'low':
                score += weights['low_vol']

            if df.iloc[i].get('extreme_below_ma', False):
                score += weights['extreme_below_ma']

            if df.iloc[i].get('breakout_20d', False):
                score += weights['breakout_20d']

            # 보너스 점수
            rsi = df.iloc[i].get('rsi', 50)
            if rsi < 30:
                score += weights['rsi_oversold']

            volume_ratio = df.iloc[i].get('volume_ratio', 1.0)
            if volume_ratio > 2.0:
                score += weights['volume_spike']

            mfi = df.iloc[i].get('mfi', 50)
            if mfi > 50:
                score += weights['mfi_bullish']

            scores.append(score)

        df['optimized_score'] = scores

        print(f"  - 점수 재계산 완료")
        print(f"  - 평균: {df['optimized_score'].mean():.2f}점")
        print(f"  - 최대: {df['optimized_score'].max():.0f}점")

        return df

    def reclassify_tiers(self, df):
        """새 임계값으로 Tier 재분류"""
        print(f"Tier 재분류 중...")

        df['new_tier'] = 'C'
        df.loc[df['optimized_score'] >= self.optimized_thresholds['B_tier'], 'new_tier'] = 'B'
        df.loc[df['optimized_score'] >= self.optimized_thresholds['A_tier'], 'new_tier'] = 'A'
        df.loc[df['optimized_score'] >= self.optimized_thresholds['S_tier'], 'new_tier'] = 'S'

        # 통계
        tier_counts = df['new_tier'].value_counts()
        print(f"\n  Tier 분포:")
        for tier in ['S', 'A', 'B', 'C']:
            count = tier_counts.get(tier, 0)
            pct = count / len(df) * 100
            print(f"    {tier}-Tier: {count:,}개 ({pct:.2f}%)")

        return df

    def save_results(self, df, timeframe):
        """재분류 결과 저장"""
        output_file = f'analysis/optimized/optimized_{timeframe}.csv'
        df.to_csv(output_file, index=False)
        print(f"\n저장 완료: {output_file}")

        # S/A Tier만 별도 저장
        high_tier = df[df['new_tier'].isin(['S', 'A'])].copy()
        high_tier_file = f'analysis/optimized/optimized_{timeframe}_SA.csv'
        high_tier.to_csv(high_tier_file, index=False)
        print(f"S/A Tier 저장: {high_tier_file} ({len(high_tier):,}개)")

    def run(self, timeframe):
        """전체 재분류 프로세스 실행"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] 최적화된 점수 체계로 재분류 시작")
        print(f"{'='*70}\n")

        # 1. 기존 결과 로드
        df = self.load_advanced_results(timeframe)

        # 2. 점수 재계산
        df = self.recalculate_score(df, timeframe)

        # 3. Tier 재분류
        df = self.reclassify_tiers(df)

        # 4. 결과 저장
        self.save_results(df, timeframe)

        return df


def main():
    """메인 실행"""
    print(f"\n{'='*70}")
    print(f"최적화된 점수 체계 재분류 시작")
    print(f"{'='*70}\n")

    start_time = datetime.now()

    # 출력 디렉토리 생성
    import os
    os.makedirs('analysis/optimized', exist_ok=True)

    classifier = OptimizedScoreClassifier()

    timeframes = ['minute5', 'minute15', 'minute60', 'minute240', 'day']

    summary = {}

    for tf in timeframes:
        try:
            df = classifier.run(tf)

            # 요약 정보
            tier_counts = df['new_tier'].value_counts().to_dict()
            summary[tf] = {
                'total_candles': len(df),
                'tier_counts': tier_counts,
                'avg_score': float(df['optimized_score'].mean()),
                'max_score': float(df['optimized_score'].max()),
                'S_tier_count': tier_counts.get('S', 0),
                'A_tier_count': tier_counts.get('A', 0)
            }

        except Exception as e:
            print(f"\n[{tf}] 오류: {e}")
            import traceback
            traceback.print_exc()

    # 전체 요약 저장
    with open('analysis/optimized/reclassify_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)

    # 최종 리포트
    print(f"\n{'='*70}")
    print(f"재분류 완료!")
    print(f"{'='*70}\n")

    print(f"{'타임프레임':<12} {'S-Tier':<10} {'A-Tier':<10} {'평균 점수':<12}")
    print(f"{'-'*50}")
    for tf, data in summary.items():
        print(f"{tf:<12} {data['S_tier_count']:<10,} {data['A_tier_count']:<10,} {data['avg_score']:<12.2f}")

    elapsed = datetime.now() - start_time
    print(f"\n소요 시간: {elapsed}")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
