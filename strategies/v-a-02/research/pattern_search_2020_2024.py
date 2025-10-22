#!/usr/bin/env python3
"""
v-a-02 Phase 1: Exhaustive Pattern Search (2020-2024)
100+ 조합 테스트로 최적 패턴 발견
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
import json
import itertools
from datetime import datetime
from utils.perfect_signal_loader import PerfectSignalLoader
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# 테스트할 조합
RSI_RANGES = [(30,50), (40,60), (45,60), (50,65), (55,70), (50,75)]
MFI_RANGES = [(30,50), (40,60), (45,60), (50,65), (55,70), (50,75)]
VOL_RANGES = [(0.8,1.2), (0.9,1.3), (1.0,1.5), (1.2,1.8), (1.5,2.5)]

def test_pattern_combination(
    perfect_signals: pd.DataFrame,
    market_data: pd.DataFrame,
    rsi_range: tuple,
    mfi_range: tuple,
    vol_range: tuple
) -> dict:
    """패턴 조합 테스트"""

    # 시그널 생성
    signals = []
    for i in range(len(market_data)):
        row = market_data.iloc[i]

        conditions = [
            rsi_range[0] <= row['rsi'] <= rsi_range[1],
            mfi_range[0] <= row['mfi'] <= mfi_range[1],
            vol_range[0] <= row['volume_ratio'] <= vol_range[1]
        ]

        if all(conditions):
            signals.append(row['timestamp'])

    # 재현율 계산 (간이)
    if len(signals) == 0:
        return {
            'params': {
                'rsi': rsi_range,
                'mfi': mfi_range,
                'vol': vol_range
            },
            'signal_count': 0,
            'reproduction_rate': 0.0
        }

    matched = 0
    for sig_ts in signals:
        for perfect_ts in perfect_signals['timestamp']:
            if abs((sig_ts - perfect_ts).total_seconds()) < 86400:  # ±1일
                matched += 1
                break

    signal_rate = matched / len(perfect_signals) if len(perfect_signals) > 0 else 0

    return {
        'params': {
            'rsi': rsi_range,
            'mfi': mfi_range,
            'vol': vol_range
        },
        'signal_count': len(signals),
        'matched_count': matched,
        'reproduction_rate': signal_rate
    }

def search_patterns_for_timeframe(timeframe: str, years: list) -> dict:
    """타임프레임별 패턴 탐색"""

    print(f"\n{'='*60}")
    print(f"Searching patterns for {timeframe}")
    print(f"{'='*60}")

    # 1. 완벽한 시그널 로드 (2020-2024)
    loader = PerfectSignalLoader()
    all_perfect_signals = []

    for year in years:
        try:
            df = loader.load_perfect_signals(timeframe, year)
            all_perfect_signals.append(df)
            print(f"✅ Loaded {len(df)} perfect signals from {year}")
        except FileNotFoundError:
            print(f"⚠️  No data for {timeframe} {year}")
            continue

    if len(all_perfect_signals) == 0:
        return None

    perfect_signals = pd.concat(all_perfect_signals, ignore_index=True)
    print(f"\n📊 Total perfect signals: {len(perfect_signals)}")

    # 2. 시장 데이터 로드
    db_path = Path(__file__).parent.parent.parent.parent / 'upbit_bitcoin.db'
    data_loader = DataLoader(str(db_path))

    all_market_data = []
    for year in years:
        df = data_loader.load_timeframe(
            timeframe=timeframe,
            start_date=f'{year}-01-01',
            end_date=f'{year}-12-31'
        )
        df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'mfi'])
        df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        df = df.dropna()
        all_market_data.append(df)

    market_data = pd.concat(all_market_data, ignore_index=True)
    print(f"📈 Total market data: {len(market_data)} candles")

    # 3. 조합 테스트
    total_combinations = len(RSI_RANGES) * len(MFI_RANGES) * len(VOL_RANGES)
    print(f"\n🔬 Testing {total_combinations} combinations...")

    results = []
    counter = 0

    for rsi, mfi, vol in itertools.product(RSI_RANGES, MFI_RANGES, VOL_RANGES):
        counter += 1
        result = test_pattern_combination(perfect_signals, market_data, rsi, mfi, vol)
        results.append(result)

        if counter % 20 == 0:
            print(f"  Progress: {counter}/{total_combinations} ({counter/total_combinations*100:.1f}%)")

    # 4. 정렬 및 Top 10 선택
    results.sort(key=lambda x: x['reproduction_rate'], reverse=True)
    top_10 = results[:10]

    print(f"\n🏆 Top 10 patterns:")
    for i, r in enumerate(top_10, 1):
        print(f"  #{i}: RSI {r['params']['rsi']}, MFI {r['params']['mfi']}, Vol {r['params']['vol']}")
        print(f"      Signals: {r['signal_count']}, Matched: {r['matched_count']}, Rate: {r['reproduction_rate']:.2%}")

    return {
        'timeframe': timeframe,
        'years': years,
        'total_perfect_signals': len(perfect_signals),
        'total_market_candles': len(market_data),
        'total_combinations_tested': total_combinations,
        'top_10_patterns': top_10,
        'all_results_count': len(results)
    }

def main():
    """메인 실행"""

    print("="*60)
    print("v-a-02 Phase 1: Exhaustive Pattern Search (2020-2024)")
    print("="*60)

    # 타임프레임별 데이터 가용성
    timeframes_config = {
        'day': [2020, 2021, 2022, 2023, 2024],
        'minute60': [2020, 2021, 2022, 2023, 2024],
        'minute240': [2020, 2021, 2022, 2023, 2024],
        'minute15': [2023, 2024],  # 데이터 제한
        'minute5': [2024]  # 데이터 제한
    }

    all_results = {}

    for timeframe, years in timeframes_config.items():
        result = search_patterns_for_timeframe(timeframe, years)
        if result:
            all_results[timeframe] = result

    # 결과 저장
    from utils.perfect_signal_loader import PerfectSignalLoader  # get_current_time 대체
    import time
    timestamp = time.strftime('%y%m%d-%H%M')

    results_dir = Path(__file__).parent / 'results'
    results_dir.mkdir(exist_ok=True)

    output_file = results_dir / f'{timestamp}_pattern_search_2020_2024.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✅ Results saved: {output_file}")
    print(f"\n{'='*60}")
    print("Summary:")
    print(f"{'='*60}")
    for tf, res in all_results.items():
        top1 = res['top_10_patterns'][0]
        print(f"{tf}: {top1['reproduction_rate']:.2%} (RSI {top1['params']['rsi']}, MFI {top1['params']['mfi']})")

if __name__ == '__main__':
    main()
