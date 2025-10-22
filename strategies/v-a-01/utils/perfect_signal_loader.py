#!/usr/bin/env python3
"""
Perfect Signal Loader
완벽한 정답 시그널 로드 및 분석 유틸리티
"""

import pandas as pd
from pathlib import Path
from typing import Dict, List
import json


class PerfectSignalLoader:
    """완벽한 시그널 로더"""

    def __init__(self, perfect_signals_dir: str = None):
        """
        Args:
            perfect_signals_dir: 완벽한 시그널 CSV 디렉토리
        """
        if perfect_signals_dir is None:
            # 기본 경로
            self.signals_dir = Path(__file__).parent.parent.parent / \
                "v41_scalping_voting/analysis/perfect_signals"
        else:
            self.signals_dir = Path(perfect_signals_dir)

    def load_perfect_signals(self, timeframe: str, year: int) -> pd.DataFrame:
        """
        완벽한 시그널 로드

        Args:
            timeframe: day, minute60, minute240, minute15, minute5
            year: 2020-2024

        Returns:
            DataFrame with perfect signals
        """
        csv_file = self.signals_dir / f"{timeframe}_{year}_perfect.csv"

        if not csv_file.exists():
            raise FileNotFoundError(f"Perfect signals not found: {csv_file}")

        df = pd.read_csv(csv_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        return df

    def get_available_datasets(self) -> Dict[str, List[int]]:
        """
        사용 가능한 데이터셋 목록

        Returns:
            {'day': [2020, 2021, ...], 'minute60': [...]}
        """
        datasets = {}

        for csv_file in self.signals_dir.glob("*.csv"):
            # 파일명 파싱: minute60_2024_perfect.csv
            parts = csv_file.stem.split('_')

            if len(parts) >= 3:
                timeframe = '_'.join(parts[:-2])  # minute60, minute240 등
                year = int(parts[-2])

                if timeframe not in datasets:
                    datasets[timeframe] = []

                datasets[timeframe].append(year)

        # 정렬
        for tf in datasets:
            datasets[tf].sort()

        return datasets

    def analyze_perfect_signals(self, df: pd.DataFrame) -> Dict:
        """
        완벽한 시그널 통계 분석

        Args:
            df: Perfect signals DataFrame

        Returns:
            통계 딕셔너리
        """
        stats = {
            'total_signals': len(df),
            'avg_return': df['best_return'].mean(),
            'median_return': df['best_return'].median(),
            'max_return': df['best_return'].max(),
            'min_return': df['best_return'].min(),
            'std_return': df['best_return'].std(),
            'avg_hold_days': df['best_hold_days'].mean(),
            'median_hold_days': df['best_hold_days'].median(),
        }

        # 보유 기간 분포
        hold_dist = df['best_hold_days'].value_counts().to_dict()
        stats['hold_period_distribution'] = {
            int(k): int(v) for k, v in hold_dist.items()
        }

        # 수익률 구간별 분포
        bins = [-100, 0, 5, 10, 20, 100]
        labels = ['loss', '0-5%', '5-10%', '10-20%', '20%+']
        df['return_bin'] = pd.cut(df['best_return'], bins=bins, labels=labels)
        return_dist = df['return_bin'].value_counts().to_dict()
        stats['return_distribution'] = {
            str(k): int(v) for k, v in return_dist.items()
        }

        return stats

    def get_signal_pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        완벽한 시그널의 지표 패턴 추출

        Args:
            df: Perfect signals DataFrame

        Returns:
            지표 특성 DataFrame
        """
        # 사용 가능한 지표 컬럼
        indicator_cols = [
            'rsi', 'mfi', 'volume_ratio', 'macd', 'macd_signal', 'macd_hist',
            'bb_position', 'adx'
        ]

        # 존재하는 컬럼만 선택
        available_cols = [col for col in indicator_cols if col in df.columns]

        if not available_cols:
            return pd.DataFrame()

        features = df[['timestamp'] + available_cols + ['best_return', 'best_hold_days']].copy()

        return features

    def save_analysis_report(self, stats: Dict, output_file: Path):
        """분석 리포트 저장"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        print(f"✅ Analysis saved: {output_file}")


if __name__ == '__main__':
    # 테스트
    loader = PerfectSignalLoader()

    # 사용 가능한 데이터셋 확인
    datasets = loader.get_available_datasets()
    print("📊 Available datasets:")
    for tf, years in datasets.items():
        print(f"  {tf}: {years}")

    # Day 2024 로드
    print("\n📈 Loading day_2024_perfect...")
    df = loader.load_perfect_signals('day', 2024)
    print(f"  Total signals: {len(df)}")
    print(f"  Columns: {df.columns.tolist()}")

    # 통계 분석
    print("\n📊 Statistics:")
    stats = loader.analyze_perfect_signals(df)
    for key, value in stats.items():
        if not isinstance(value, dict):
            print(f"  {key}: {value}")

    # 패턴 특성 추출
    print("\n🎯 Pattern features:")
    features = loader.get_signal_pattern_features(df)
    print(features.head())
