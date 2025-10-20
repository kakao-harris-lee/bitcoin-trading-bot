#!/usr/bin/env python3
"""
Step 1-3: 점수 체계 최적화

목표:
1. 브루트포스 수익 케이스의 7차원 점수 분포 분석
2. 수익률/승률과 점수의 상관관계 계산
3. 차원별 가중치 최적화
4. 최적 Tier 임계값 도출
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime
from scipy.stats import pearsonr
from scipy.signal import argrelextrema
from sklearn.cluster import DBSCAN
import warnings
warnings.filterwarnings('ignore')


class ScoreOptimizer:
    """점수 체계 최적화 분석기"""

    def __init__(self, config_path='config.json'):
        with open(config_path) as f:
            self.config = json.load(f)

        self.timeframes = ['minute5', 'minute15', 'minute60', 'minute240', 'day']
        self.results = {}

    def load_profitable_cases(self, timeframe):
        """브루트포스 수익 케이스 로드"""
        file_path = f'analysis/bruteforce/bruteforce_{timeframe}_30d_profitable.csv'
        df = pd.read_csv(file_path)
        print(f"[{timeframe}] 수익 케이스 로드: {len(df):,}개")
        return df

    def calculate_7d_score(self, df):
        """7차원 점수 계산 (기존 로직)"""
        scores = []

        # Local extrema 탐지
        local_min_idx = argrelextrema(df['close'].values, np.less, order=5)[0]
        df['is_local_min'] = False
        df.iloc[local_min_idx, df.columns.get_loc('is_local_min')] = True

        # Swing 탐지
        df['swing_type'] = 'neutral'
        for i in range(3, len(df)):
            recent_closes = df.iloc[i-3:i]['close'].values
            is_declining = all(recent_closes[j] > recent_closes[j+1] for j in range(len(recent_closes)-1))
            if is_declining and df.iloc[i]['close'] > df.iloc[i-1]['close']:
                df.iloc[i, df.columns.get_loc('swing_type')] = 'down_swing_end'

        # Support/Resistance (간소화)
        df['near_support'] = False  # 실제 계산은 시간이 오래 걸리므로 생략

        # Volatility regime
        df['atr_pct'] = df.get('atr', 0) / df['close']
        df['vol_regime'] = 'medium'
        df.loc[df['atr_pct'] < 0.02, 'vol_regime'] = 'low'
        df.loc[df['atr_pct'] > 0.05, 'vol_regime'] = 'high'

        # Mean reversion distance
        df['ma20_distance'] = (df['close'] - df.get('ma20', df['close'])) / df.get('ma20', df['close'])
        df['extreme_below_ma'] = (df['ma20_distance'] < -0.10)

        # Breakout
        df['high_20d'] = df['high'].rolling(window=20).max()
        df['breakout_20d'] = (df['close'] > df['high_20d'].shift(1)) & (df['volume_ratio'] > 2.0)

        # 종합 점수 계산
        for i in range(len(df)):
            score = 0
            components = {}

            # 1. Local Min (+20)
            if df.iloc[i].get('is_local_min', False):
                score += 20
                components['local_min'] = True

            # 2. Swing (+15)
            if df.iloc[i].get('swing_type') == 'down_swing_end':
                score += 15
                components['swing_end'] = True

            # 3. Support (+15)
            if df.iloc[i].get('near_support', False):
                score += 15
                components['near_support'] = True

            # 4. Low Vol (+10)
            if df.iloc[i].get('vol_regime') == 'low':
                score += 10
                components['low_vol'] = True

            # 6. Extreme Below MA (+10)
            if df.iloc[i].get('extreme_below_ma', False):
                score += 10
                components['extreme_below_ma'] = True

            # 7. Breakout (+5)
            if df.iloc[i].get('breakout_20d', False):
                score += 5
                components['breakout'] = True

            # 보너스
            if df.iloc[i].get('rsi', 50) < 30:
                score += 8
                components['rsi_oversold'] = True

            if df.iloc[i].get('volume_ratio', 1.0) > 2.0:
                score += 7
                components['volume_spike'] = True

            if df.iloc[i].get('mfi', 50) > 50:
                score += 5
                components['mfi_bullish'] = True

            scores.append(score)

        df['signal_score'] = scores
        return df

    def analyze_score_distribution(self, timeframe):
        """점수 분포 분석"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] 점수 분포 분석 시작")
        print(f"{'='*70}\n")

        # 수익 케이스 로드
        df = self.load_profitable_cases(timeframe)

        # 7차원 점수 계산
        df = self.calculate_7d_score(df)

        # 점수 분포 통계
        print(f"점수 분포:")
        print(df['signal_score'].describe())

        # 백분위수
        percentiles = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99]
        print(f"\n백분위수:")
        for p in percentiles:
            score_p = np.percentile(df['signal_score'], p)
            print(f"  {p}th percentile: {score_p:.1f}점")

        # 수익률과 점수의 상관관계
        corr, p_value = pearsonr(df['signal_score'], df['return_30d'])
        print(f"\n상관관계:")
        print(f"  점수 vs 수익률: {corr:.3f} (p={p_value:.4f})")

        # 점수 구간별 평균 수익률
        print(f"\n점수 구간별 평균 수익률:")
        bins = [0, 20, 30, 40, 50, 60, 70, 100]
        df['score_bin'] = pd.cut(df['signal_score'], bins=bins)
        score_performance = df.groupby('score_bin')['return_30d'].agg(['count', 'mean', 'std'])
        print(score_performance)

        # 최적 임계값 도출
        print(f"\n{'='*70}")
        print(f"최적 임계값 제안:")
        print(f"{'='*70}")

        # 상위 20% → S-Tier
        s_threshold = np.percentile(df['signal_score'], 80)
        s_tier_return = df[df['signal_score'] >= s_threshold]['return_30d'].mean()

        # 상위 40% → A-Tier
        a_threshold = np.percentile(df['signal_score'], 60)
        a_tier_return = df[df['signal_score'] >= a_threshold]['return_30d'].mean()

        # 상위 60% → B-Tier
        b_threshold = np.percentile(df['signal_score'], 40)
        b_tier_return = df[df['signal_score'] >= b_threshold]['return_30d'].mean()

        print(f"S-Tier: {s_threshold:.1f}점 이상 (평균 수익률: {s_tier_return:.2%})")
        print(f"A-Tier: {a_threshold:.1f}점 이상 (평균 수익률: {a_tier_return:.2%})")
        print(f"B-Tier: {b_threshold:.1f}점 이상 (평균 수익률: {b_tier_return:.2%})")

        # 차원별 기여도 분석
        print(f"\n{'='*70}")
        print(f"차원별 수익 기여도:")
        print(f"{'='*70}")

        dimensions = {
            'is_local_min': 20,
            'swing_end': 15,
            'near_support': 15,
            'low_vol': 10,
            'extreme_below_ma': 10,
            'breakout_20d': 5,
            'rsi_oversold': 8,
            'volume_spike': 7,
            'mfi_bullish': 5
        }

        correlations = {}
        for dim, weight in dimensions.items():
            if dim == 'swing_end':
                dim_col = (df['swing_type'] == 'down_swing_end').astype(int)
            elif dim == 'low_vol':
                dim_col = (df['vol_regime'] == 'low').astype(int)
            elif dim == 'rsi_oversold':
                dim_col = (df['rsi'] < 30).astype(int)
            elif dim == 'volume_spike':
                dim_col = (df['volume_ratio'] > 2.0).astype(int)
            elif dim == 'mfi_bullish':
                dim_col = (df['mfi'] > 50).astype(int)
            else:
                dim_col = df.get(dim, pd.Series([False]*len(df))).astype(int)

            if dim_col.sum() > 10:  # 최소 10개 케이스
                corr, p = pearsonr(dim_col, df['return_30d'])
                correlations[dim] = {
                    'current_weight': weight,
                    'correlation': corr,
                    'p_value': p,
                    'count': dim_col.sum()
                }

        # 상관관계 순으로 정렬
        sorted_dims = sorted(correlations.items(), key=lambda x: abs(x[1]['correlation']), reverse=True)

        print(f"\n{'차원':<20} {'현재 가중치':<12} {'상관계수':<12} {'발생 횟수':<12}")
        print(f"{'-'*70}")
        for dim, stats in sorted_dims:
            print(f"{dim:<20} {stats['current_weight']:<12} {stats['correlation']:<12.3f} {stats['count']:<12}")

        # 최적 가중치 제안 (상관계수 기반)
        print(f"\n{'='*70}")
        print(f"최적 가중치 제안:")
        print(f"{'='*70}")

        total_abs_corr = sum(abs(s['correlation']) for s in correlations.values())
        new_weights = {}

        for dim, stats in sorted_dims[:6]:  # 상위 6개만
            # 상관계수 비율로 100점 배분
            new_weight = int((abs(stats['correlation']) / total_abs_corr) * 100)
            new_weights[dim] = new_weight
            print(f"{dim:<20}: {stats['current_weight']:>3} → {new_weight:>3}점 (상관계수: {stats['correlation']:.3f})")

        # 결과 저장
        self.results[timeframe] = {
            'score_stats': df['signal_score'].describe().to_dict(),
            'percentiles': {p: float(np.percentile(df['signal_score'], p)) for p in percentiles},
            'correlation': float(corr),
            'thresholds': {
                'S_tier': float(s_threshold),
                'A_tier': float(a_threshold),
                'B_tier': float(b_threshold)
            },
            'tier_returns': {
                'S_tier': float(s_tier_return),
                'A_tier': float(a_tier_return),
                'B_tier': float(b_tier_return)
            },
            'dimension_correlations': {k: {'weight': v['current_weight'], 'corr': float(v['correlation'])} for k, v in correlations.items()},
            'new_weights': new_weights
        }

        return df

    def run_optimization(self):
        """전체 타임프레임 최적화"""
        print(f"{'='*70}")
        print(f"점수 체계 최적화 시작")
        print(f"{'='*70}\n")

        start_time = datetime.now()

        # 타임프레임별 분석
        for tf in self.timeframes:
            try:
                self.analyze_score_distribution(tf)
            except Exception as e:
                print(f"[{tf}] 오류: {e}")

        end_time = datetime.now()
        elapsed = end_time - start_time

        # 최종 요약
        print(f"\n{'='*70}")
        print(f"최적화 완료!")
        print(f"{'='*70}")
        print(f"소요 시간: {elapsed}")

        # JSON 저장
        import os
        os.makedirs('analysis/optimization', exist_ok=True)

        with open('analysis/optimization/score_optimization.json', 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"\n결과 저장: analysis/optimization/score_optimization.json")
        print(f"{'='*70}\n")


if __name__ == '__main__':
    optimizer = ScoreOptimizer()
    optimizer.run_optimization()
