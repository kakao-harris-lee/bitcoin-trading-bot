#!/usr/bin/env python3
"""
Multi-Timeframe Confluence System
- 상위 타임프레임 필터링
- Confluence 보너스 점수
- 신호 강도 증폭
"""

import pandas as pd
import numpy as np


class MultiTimeframeConfluence:
    """다중 타임프레임 합치 시스템"""

    def __init__(self, config):
        self.config = config

        # Confluence 보너스 (config에서 로드)
        self.bonus = config.get('confluence', {}).get('bonus', {
            '2_timeframes': 10,
            '3_timeframes': 20,
            '4_timeframes': 30,
            '5_timeframes': 40
        })

        # 타임프레임 계층 (하위 → 상위)
        self.timeframe_hierarchy = ['minute5', 'minute15', 'minute60', 'minute240', 'day']

    def get_higher_timeframes(self, current_tf):
        """현재 타임프레임보다 상위 타임프레임들 반환"""

        current_idx = self.timeframe_hierarchy.index(current_tf)
        return self.timeframe_hierarchy[current_idx + 1:]

    def align_timestamp(self, timestamp, target_timeframe):
        """타임스탬프를 상위 타임프레임에 맞춰 정렬"""

        # minute5 → minute15: 15분 단위로 내림
        # minute15 → minute60: 60분 단위로 내림
        # 등등

        if target_timeframe == 'minute15':
            # 15분 단위로 내림
            return timestamp.floor('15T')
        elif target_timeframe == 'minute60':
            # 60분 단위로 내림
            return timestamp.floor('H')
        elif target_timeframe == 'minute240':
            # 240분(4시간) 단위로 내림
            return timestamp.floor('4H')
        elif target_timeframe == 'day':
            # 일 단위로 내림
            return timestamp.floor('D')
        else:
            return timestamp

    def check_confluence(self, timestamp, current_tf, all_data, min_tier='B'):
        """특정 타임스탬프에서 상위 TF들의 Confluence 확인"""

        higher_tfs = self.get_higher_timeframes(current_tf)
        confluence_count = 0
        confluence_tfs = []

        for higher_tf in higher_tfs:
            # 상위 TF 데이터 가져오기
            higher_df = all_data.get(higher_tf)

            if higher_df is None or len(higher_df) == 0:
                continue

            # 타임스탬프 정렬
            aligned_ts = self.align_timestamp(timestamp, higher_tf)

            # 해당 타임스탬프의 데이터 찾기
            matching = higher_df[higher_df['timestamp'] == aligned_ts]

            if len(matching) > 0:
                row = matching.iloc[0]

                # Tier 확인
                tier = row.get('tier', 'C')

                # B-Tier 이상이면 Confluence로 인정
                if tier in ['S', 'A', 'B'] and tier <= min_tier or tier == 'S' or tier == 'A':
                    confluence_count += 1
                    confluence_tfs.append(higher_tf)

        return confluence_count, confluence_tfs

    def calculate_confluence_bonus(self, confluence_count):
        """Confluence 개수에 따른 보너스 점수 계산"""

        if confluence_count >= 4:
            return self.bonus['5_timeframes']
        elif confluence_count == 3:
            return self.bonus['4_timeframes']
        elif confluence_count == 2:
            return self.bonus['3_timeframes']
        elif confluence_count == 1:
            return self.bonus['2_timeframes']
        else:
            return 0

    def apply_confluence(self, data_dict, min_tier='B'):
        """모든 타임프레임에 Confluence 적용"""

        print(f"\n{'='*70}")
        print(f"Multi-Timeframe Confluence 계산")
        print(f"{'='*70}\n")

        enhanced_data = {}

        for timeframe in ['minute5', 'minute15', 'minute60', 'minute240']:
            df = data_dict.get(timeframe)

            if df is None or len(df) == 0:
                print(f"[{timeframe}] 데이터 없음, 스킵")
                continue

            print(f"[{timeframe}] Confluence 계산 중...")

            # Confluence 정보 추가
            confluence_counts = []
            confluence_tfs_list = []
            bonus_scores = []

            for idx, row in df.iterrows():
                timestamp = row['timestamp']

                # Confluence 확인
                conf_count, conf_tfs = self.check_confluence(
                    timestamp, timeframe, data_dict, min_tier
                )

                # 보너스 점수
                bonus = self.calculate_confluence_bonus(conf_count)

                confluence_counts.append(conf_count)
                confluence_tfs_list.append(conf_tfs)
                bonus_scores.append(bonus)

            df['confluence_count'] = confluence_counts
            df['confluence_tfs'] = confluence_tfs_list
            df['confluence_bonus'] = bonus_scores

            # 원래 점수에 보너스 추가
            df['score_original'] = df['score'].copy()
            df['score'] = df['score'] + df['confluence_bonus']

            # Tier 재분류 (보너스 점수 포함)
            # 이미 score_engine에 classify_tier 메서드 있다고 가정
            # 여기서는 간단히 임계값만 적용
            from score_engine import UnifiedScoreEngine
            engine = UnifiedScoreEngine(self.config)

            df['tier'] = df['score'].apply(
                lambda x: engine.classify_tier(x, timeframe)
            )

            # 통계
            upgraded = (df['tier'] != df['tier']).sum()  # 실제로는 이전 tier와 비교 필요
            avg_bonus = df['confluence_bonus'].mean()

            print(f"  - 평균 Confluence: {df['confluence_count'].mean():.2f}개")
            print(f"  - 평균 보너스: {avg_bonus:.1f}점")
            print(f"  - Confluence 3+: {(df['confluence_count'] >= 3).sum():,}개")

            enhanced_data[timeframe] = df

        # Day는 필터 역할만 (Confluence 불필요)
        enhanced_data['day'] = data_dict.get('day')

        print(f"\n{'='*70}")
        print(f"Confluence 계산 완료")
        print(f"{'='*70}\n")

        return enhanced_data

    def filter_by_day(self, data_dict, day_min_tier='B'):
        """Day 타임프레임으로 전체 필터링"""

        print(f"\n{'='*70}")
        print(f"Day 필터 적용 (최소 Tier: {day_min_tier})")
        print(f"{'='*70}\n")

        day_df = data_dict.get('day')

        if day_df is None or len(day_df) == 0:
            print("  - Day 데이터 없음, 필터 스킵")
            return data_dict

        # Day의 B-Tier 이상 날짜만 추출
        valid_dates = day_df[day_df['tier'].isin(['S', 'A', 'B'])]['timestamp'].dt.date.unique()

        print(f"  - 유효 거래일: {len(valid_dates)}일")

        filtered_data = {}

        for timeframe, df in data_dict.items():
            if timeframe == 'day':
                filtered_data[timeframe] = df
                continue

            # 날짜로 필터링
            df_filtered = df[df['timestamp'].dt.date.isin(valid_dates)].copy()

            before = len(df)
            after = len(df_filtered)
            removed = before - after

            print(f"  - [{timeframe}] {before:,} → {after:,} ({removed:,}개 제거)")

            filtered_data[timeframe] = df_filtered

        print(f"\n{'='*70}")
        print(f"Day 필터 완료")
        print(f"{'='*70}\n")

        return filtered_data


def test_confluence():
    """Confluence 테스트"""
    import sys
    import os
    import json

    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)

    from data_loader import MultiTimeframeDataLoader
    from score_engine import UnifiedScoreEngine

    # Config 로드
    with open('../config/base_config.json') as f:
        config = json.load(f)

    # 데이터 로드
    loader = MultiTimeframeDataLoader()
    data = loader.load_all_timeframes(
        start_date='2024-01-01',
        end_date='2024-02-01'
    )

    # Score 계산
    engine = UnifiedScoreEngine(config)
    scored_data = engine.score_all_timeframes(data)

    # Confluence 적용
    confluence = MultiTimeframeConfluence(config)
    enhanced_data = confluence.apply_confluence(scored_data)

    # Day 필터 적용 (테스트용으로 스킵)
    # filtered_data = confluence.filter_by_day(enhanced_data)

    # 결과 출력
    print(f"\n{'='*70}")
    print(f"Confluence 결과 (minute15)")
    print(f"{'='*70}\n")

    df = enhanced_data['minute15']

    # Confluence 3+ 시그널
    high_conf = df[df['confluence_count'] >= 3].copy()
    print(f"\nConfluence 3+ 시그널: {len(high_conf)}개\n")

    for idx, row in high_conf.head(10).iterrows():
        print(f"{row['timestamp']} | "
              f"Score: {row['score_original']:.0f}→{row['score']:.0f} (+{row['confluence_bonus']:.0f}) | "
              f"Tier: {row['tier']} | "
              f"Conf: {row['confluence_count']} {row['confluence_tfs']}")


if __name__ == '__main__':
    test_confluence()
