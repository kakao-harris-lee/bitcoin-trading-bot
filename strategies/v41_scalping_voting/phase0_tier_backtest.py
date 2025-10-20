#!/usr/bin/env python3
"""
Step 3-4: Tier별 백테스팅 검증
- 브루트포스 수익 케이스에 최적화된 점수 적용
- Tier별 재분류
- 각 Tier별 실제 백테스팅 성과 검증
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class TierBacktester:
    """Tier별 백테스팅 검증"""

    def __init__(self):
        # 최적화된 가중치 (score_optimization.json에서 도출)
        self.optimized_weights = {
            'minute15': {
                'is_local_min': 27,
                'mfi_bullish': 20,
                'low_vol': 16,
                'volume_spike': 12,
                'breakout_20d': 11,
                'swing_end': 7,
                'rsi_oversold': 8
            },
            'minute60': {
                'low_vol': 37,
                'is_local_min': 26,
                'mfi_bullish': 16,
                'breakout_20d': 8,
                'volume_spike': 6,
                'swing_end': 2,
                'rsi_oversold': 8
            },
            'day': {
                'mfi_bullish': 28,
                'is_local_min': 20,
                'breakout_20d': 5,
                'swing_end': 15,
                'rsi_oversold': 8,
                'volume_spike': 7,
                'low_vol': 10
            }
        }

        # 최적화된 임계값
        self.thresholds = {
            'S': 25,  # 상위 20%
            'A': 15,  # 상위 40%
            'B': 10   # 상위 60%
        }

    def load_bruteforce_results(self, timeframe):
        """브루트포스 수익 케이스 로드"""
        file_path = f'analysis/bruteforce/bruteforce_{timeframe}_30d_profitable.csv'
        print(f"[{timeframe}] 브루트포스 수익 케이스 로드: {file_path}")

        df = pd.read_csv(file_path)
        print(f"  - {len(df):,}개 수익 케이스 로드")

        return df

    def calculate_optimized_score(self, df, timeframe):
        """최적화된 점수 계산"""
        print(f"[{timeframe}] 최적화된 점수 계산 중...")

        if timeframe not in self.optimized_weights:
            print(f"  - {timeframe}에 대한 가중치 없음, 기본 가중치 사용")
            weights = {
                'is_local_min': 20,
                'mfi_bullish': 15,
                'rsi_oversold': 8,
                'volume_spike': 7,
                'low_vol': 10,
                'swing_end': 10,
                'breakout_20d': 5
            }
        else:
            weights = self.optimized_weights[timeframe]

        scores = []
        for i in range(len(df)):
            score = 0

            # RSI
            rsi = df.iloc[i].get('rsi', 50)
            if rsi < 30:
                score += weights.get('rsi_oversold', 8)

            # MFI
            mfi = df.iloc[i].get('mfi', 50)
            if mfi > 50:
                score += weights.get('mfi_bullish', 15)

            # Volume
            volume_ratio = df.iloc[i].get('volume_ratio', 1.0)
            if volume_ratio > 2.0:
                score += weights.get('volume_spike', 7)

            # ATR (변동성)
            atr_ratio = df.iloc[i].get('atr_ratio', 1.0)
            if atr_ratio < 0.8:  # 낮은 변동성
                score += weights.get('low_vol', 10)

            # 추가 보너스 (극단 RSI)
            if rsi < 25:
                score += 5

            # 극단 MFI
            if mfi > 60:
                score += 5

            scores.append(score)

        df['optimized_score'] = scores

        print(f"  - 점수 계산 완료")
        print(f"  - 평균: {df['optimized_score'].mean():.2f}점")
        print(f"  - 중앙값: {df['optimized_score'].median():.0f}점")
        print(f"  - 최대: {df['optimized_score'].max():.0f}점")

        return df

    def classify_tiers(self, df):
        """Tier 분류"""
        print(f"Tier 분류 중...")

        df['tier'] = 'C'
        df.loc[df['optimized_score'] >= self.thresholds['B'], 'tier'] = 'B'
        df.loc[df['optimized_score'] >= self.thresholds['A'], 'tier'] = 'A'
        df.loc[df['optimized_score'] >= self.thresholds['S'], 'tier'] = 'S'

        tier_counts = df['tier'].value_counts()
        print(f"\n  Tier 분포:")
        for tier in ['S', 'A', 'B', 'C']:
            count = tier_counts.get(tier, 0)
            pct = count / len(df) * 100 if len(df) > 0 else 0
            print(f"    {tier}-Tier: {count:,}개 ({pct:.2f}%)")

        return df

    def evaluate_tier_performance(self, df, timeframe):
        """Tier별 성과 평가"""
        print(f"\n[{timeframe}] Tier별 성과 분석:")
        print(f"{'='*70}")

        results = {}

        for tier in ['S', 'A', 'B', 'C']:
            tier_df = df[df['tier'] == tier]

            if len(tier_df) == 0:
                print(f"\n{tier}-Tier: 데이터 없음")
                results[tier] = {
                    'count': 0,
                    'win_rate': 0,
                    'avg_return': 0,
                    'median_return': 0,
                    'std_return': 0
                }
                continue

            # 통계 계산
            returns = tier_df['return_30d']

            count = len(tier_df)
            win_rate = (returns > 0.01).sum() / count
            avg_return = returns.mean()
            median_return = returns.median()
            std_return = returns.std()
            sharpe = (avg_return / std_return) if std_return > 0 else 0

            # 백분위수
            p25 = returns.quantile(0.25)
            p75 = returns.quantile(0.75)

            print(f"\n{tier}-Tier ({count:,}개):")
            print(f"  승률: {win_rate:.1%}")
            print(f"  평균 수익률: {avg_return:.2%}")
            print(f"  중앙 수익률: {median_return:.2%}")
            print(f"  표준편차: {std_return:.2%}")
            print(f"  Sharpe Ratio: {sharpe:.2f}")
            print(f"  25% / 75% 백분위: {p25:.2%} / {p75:.2%}")

            results[tier] = {
                'count': int(count),
                'win_rate': float(win_rate),
                'avg_return': float(avg_return),
                'median_return': float(median_return),
                'std_return': float(std_return),
                'sharpe': float(sharpe),
                'p25': float(p25),
                'p75': float(p75)
            }

        return results

    def save_results(self, df, stats, timeframe):
        """결과 저장"""
        # 전체 데이터
        output_file = f'analysis/tier_backtest/{timeframe}_tier_classified.csv'
        df.to_csv(output_file, index=False)
        print(f"\n저장 완료: {output_file}")

        # S/A Tier만 별도 저장
        high_tier = df[df['tier'].isin(['S', 'A'])].copy()
        if len(high_tier) > 0:
            high_file = f'analysis/tier_backtest/{timeframe}_SA_tier.csv'
            high_tier.to_csv(high_file, index=False)
            print(f"S/A Tier 저장: {high_file} ({len(high_tier):,}개)")

        # 통계 저장
        stats_file = f'analysis/tier_backtest/{timeframe}_tier_stats.json'
        with open(stats_file, 'w') as f:
            json.dump(stats, f, indent=2)
        print(f"통계 저장: {stats_file}")

    def run(self, timeframe):
        """전체 프로세스 실행"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] Tier 백테스팅 시작")
        print(f"{'='*70}\n")

        # 1. 브루트포스 결과 로드
        df = self.load_bruteforce_results(timeframe)

        # 2. 최적화된 점수 계산
        df = self.calculate_optimized_score(df, timeframe)

        # 3. Tier 분류
        df = self.classify_tiers(df)

        # 4. Tier별 성과 평가
        stats = self.evaluate_tier_performance(df, timeframe)

        # 5. 결과 저장
        self.save_results(df, stats, timeframe)

        return df, stats


def main():
    """메인 실행"""
    print(f"\n{'='*70}")
    print(f"Tier별 백테스팅 검증 시작")
    print(f"{'='*70}\n")

    start_time = datetime.now()

    # 출력 디렉토리 생성
    import os
    os.makedirs('analysis/tier_backtest', exist_ok=True)

    backtester = TierBacktester()

    timeframes = ['minute15', 'minute60', 'day']

    all_stats = {}

    for tf in timeframes:
        try:
            df, stats = backtester.run(tf)
            all_stats[tf] = stats

        except Exception as e:
            print(f"\n[{tf}] 오류: {e}")
            import traceback
            traceback.print_exc()

    # 전체 요약 저장
    with open('analysis/tier_backtest/tier_backtest_summary.json', 'w') as f:
        json.dump(all_stats, f, indent=2)

    # 최종 리포트
    print(f"\n{'='*70}")
    print(f"Tier 백테스팅 완료!")
    print(f"{'='*70}\n")

    print(f"{'타임프레임':<12} {'Tier':<6} {'시그널수':<10} {'승률':<10} {'평균수익률':<12}")
    print(f"{'-'*60}")

    for tf, tiers in all_stats.items():
        for tier, data in tiers.items():
            if data['count'] > 0:
                print(f"{tf:<12} {tier:<6} {data['count']:<10,} "
                      f"{data['win_rate']:<10.1%} {data['avg_return']:<12.2%}")

    elapsed = datetime.now() - start_time
    print(f"\n소요 시간: {elapsed}")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
