#!/usr/bin/env python3
"""
Phase 0-2: Lookforward 성과 분석

각 매수 신호 이후 N 캔들 동안의 성과 추적
- 수익률
- 최고점/최저점
- 도달 시점
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from tqdm import tqdm
import warnings
warnings.filterwarnings('ignore')

from core import DataLoader


# Lookforward 기간 정의 (타임프레임별)
LOOKFORWARD_PERIODS = {
    'minute5': [1, 2, 4, 8, 16, 32, 64],      # 5분~5시간20분
    'minute15': [1, 2, 4, 8, 16, 32],         # 15분~8시간
    'minute60': [1, 2, 4, 8, 16, 24],         # 1시간~24시간
    'minute240': [1, 2, 4, 8, 12],            # 4시간~48시간
    'day': [1, 2, 5, 10, 20, 30]              # 1일~30일
}


def analyze_lookforward(timeframe, db_path='../../upbit_bitcoin.db'):
    """
    단일 타임프레임 Lookforward 분석

    Args:
        timeframe: 'minute5', 'minute15', 'minute60', 'minute240', 'day'
        db_path: upbit_bitcoin.db 경로
    """
    print(f"\n{'='*70}")
    print(f"[{timeframe}] Lookforward 분석 시작")
    print(f"{'='*70}\n")

    # 신호 파일 로드
    signals_file = f'analysis/signals/signals_{timeframe}_buy.csv'
    try:
        signals_df = pd.read_csv(signals_file)
        print(f"[{timeframe}] 신호 파일 로드: {len(signals_df):,} 개")
    except Exception as e:
        print(f"[{timeframe}] ERROR: 신호 파일 없음 - {e}")
        return

    # 전체 데이터 로드
    print(f"[{timeframe}] 전체 데이터 로드 중...")
    with DataLoader(db_path) as loader:
        # 신호 데이터의 시작/종료 날짜 파악
        start_date = pd.to_datetime(signals_df['timestamp'].min()).strftime('%Y-%m-%d')
        end_date = pd.to_datetime(signals_df['timestamp'].max()).strftime('%Y-%m-%d')

        # 여유롭게 로드 (Lookforward 기간 고려)
        df_full = loader.load_timeframe(timeframe, start_date=start_date)

    print(f"[{timeframe}] 전체 데이터: {len(df_full):,} 캔들")

    # 타임스탬프 인덱스 매칭을 위한 딕셔너리
    timestamp_to_idx = {ts: idx for idx, ts in enumerate(df_full['timestamp'])}

    # Lookforward 기간
    lookforward_periods = LOOKFORWARD_PERIODS[timeframe]

    print(f"[{timeframe}] Lookforward 분석 중... ({len(signals_df):,} 신호)")

    # 각 신호마다 Lookforward 분석
    for idx, signal in tqdm(signals_df.iterrows(), total=len(signals_df), desc=f"[{timeframe}] Lookforward"):
        entry_time = signal['timestamp']
        entry_price = signal['price']

        # 전체 데이터에서 진입 시점 인덱스 찾기
        if entry_time not in timestamp_to_idx:
            # 타임스탬프 매칭 실패 시 스킵
            continue

        entry_idx = timestamp_to_idx[entry_time]

        # 각 Lookforward 기간별 분석
        for n in lookforward_periods:
            future_idx = min(entry_idx + n, len(df_full) - 1)

            # N 캔들 후 가격
            future_price = df_full.iloc[future_idx]['close']

            # N 캔들 동안의 구간 데이터
            window = df_full.iloc[entry_idx:future_idx+1]

            if len(window) == 0:
                continue

            # 최고가/최저가
            max_price = window['high'].max()
            min_price = window['low'].min()

            # PnL 계산
            pnl_pct = (future_price - entry_price) / entry_price
            max_profit_pct = (max_price - entry_price) / entry_price
            max_loss_pct = (min_price - entry_price) / entry_price

            # 최고점/최저점 도달 시점
            max_idx = window['high'].idxmax() - entry_idx
            min_idx = window['low'].idxmin() - entry_idx

            # DataFrame에 기록
            signals_df.at[idx, f'pnl_{n}c'] = pnl_pct
            signals_df.at[idx, f'max_profit_{n}c'] = max_profit_pct
            signals_df.at[idx, f'max_loss_{n}c'] = max_loss_pct
            signals_df.at[idx, f'peak_time_{n}c'] = max_idx
            signals_df.at[idx, f'trough_time_{n}c'] = min_idx

            # 승/패 기록
            signals_df.at[idx, f'win_{n}c'] = 1 if pnl_pct > 0 else 0

    # 업데이트된 신호 데이터 저장
    output_file = f'analysis/signals/signals_{timeframe}_buy_with_performance.csv'
    signals_df.to_csv(output_file, index=False)

    print(f"\n[{timeframe}] Lookforward 분석 완료")
    print(f"  - 저장: {output_file}")

    # 간단한 통계 출력
    print(f"\n[{timeframe}] Lookforward 승률 요약:")
    for n in lookforward_periods:
        if f'win_{n}c' in signals_df.columns:
            win_rate = signals_df[f'win_{n}c'].mean()
            avg_pnl = signals_df[f'pnl_{n}c'].mean()
            print(f"  - {n:3d} 캔들 후: 승률 {win_rate:.1%}, 평균 PnL {avg_pnl:+.2%}")


def run_all_lookforward():
    """전체 타임프레임 Lookforward 분석 실행"""
    timeframes = ['minute5', 'minute15', 'minute60', 'minute240', 'day']

    print(f"\n{'='*70}")
    print(f"v41 전수 Lookforward 분석 시작")
    print(f"{'='*70}\n")

    for tf in timeframes:
        try:
            analyze_lookforward(tf)
        except Exception as e:
            print(f"\n[{tf}] ERROR: {e}\n")
            continue

    print(f"\n{'='*70}")
    print(f"전체 Lookforward 분석 완료")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    run_all_lookforward()
