#!/usr/bin/env python3
"""
v-a-02: Multi-Indicator Score-Based Reproducer
v42 Score Engine의 7차원 지표를 활용하여 Perfect Signal 재현
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
import json
from datetime import datetime

# v-a-02 modules
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'utils'))
from score_engine import UnifiedScoreEngine
from perfect_signal_loader import PerfectSignalLoader
from reproduction_calculator import ReproductionCalculator

# Core modules (project root)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / 'core'))
from data_loader import DataLoader
from market_analyzer import MarketAnalyzer


def load_and_prepare_data(timeframe='day', year=2024):
    """
    시장 데이터 로드 및 지표 계산

    Returns:
        DataFrame with all indicators needed for Score Engine
    """
    print(f"📊 Loading market data ({timeframe} {year})...")

    # 데이터 로드
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'
    data_loader = DataLoader(str(db_path))
    df = data_loader.load_timeframe(
        timeframe=timeframe,
        start_date=f'{year}-01-01',
        end_date=f'{year}-12-31'
    )

    print(f"   Loaded: {len(df)} candles")

    # 필수 지표 계산
    print(f"📈 Calculating indicators...")

    # RSI, MFI, ADX, Bollinger Bands, ATR
    df = MarketAnalyzer.add_indicators(
        df,
        indicators=['rsi', 'mfi', 'adx', 'bollinger_bands', 'atr']
    )

    # 컬럼명 확인
    print(f"   Available columns: {list(df.columns)}")

    # Volume Ratio
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()

    # ATR Ratio
    df['atr_ratio'] = df['atr'] / df['atr'].rolling(20).mean()

    # BB Position (0 = lower, 1 = upper)
    # Bollinger Bands 컬럼명 확인 (bb_lower, bb_middle, bb_upper 또는 다른 이름)
    bb_lower_col = 'bb_lower' if 'bb_lower' in df.columns else 'lower_band'
    bb_upper_col = 'bb_upper' if 'bb_upper' in df.columns else 'upper_band'

    if bb_lower_col in df.columns and bb_upper_col in df.columns:
        df['bb_position'] = (df['close'] - df[bb_lower_col]) / (df[bb_upper_col] - df[bb_lower_col])
        df['bb_lower'] = df[bb_lower_col]
        df['bb_upper'] = df[bb_upper_col]
    else:
        # Bollinger Bands를 직접 계산
        bb_period = 20
        bb_std = 2
        df['bb_middle'] = df['close'].rolling(bb_period).mean()
        bb_std_val = df['close'].rolling(bb_period).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std_val * bb_std)
        df['bb_lower'] = df['bb_middle'] - (bb_std_val * bb_std)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

    # NaN 제거
    df = df.dropna()

    print(f"   Indicators calculated: {len(df)} valid candles")
    print(f"   Columns: {list(df.columns)}")

    return df


def generate_score_based_signals(df, timeframe='day', tier_threshold=28):
    """
    Score Engine 기반 시그널 생성

    Args:
        df: 지표가 계산된 DataFrame
        timeframe: 타임프레임
        tier_threshold: 시그널 생성 임계값 (28=S-Tier, 18=A-Tier, 12=B-Tier)

    Returns:
        DataFrame with signals
    """
    print(f"\n🎯 Generating signals (tier_threshold={tier_threshold})...")

    # Score Engine 설정
    config = {
        'strategies': {
            'rsi_oversold': {
                'params': {
                    'day': {'threshold': 30},
                    'minute60': {'threshold': 25},
                    'minute15': {'threshold': 25}
                }
            },
            'volume_spike': {
                'params': {
                    'day': {'ratio': 1.5},
                    'minute60': {'ratio': 1.5},
                    'minute15': {'ratio': 1.5}
                }
            }
        }
    }

    # Score Engine 생성
    engine = UnifiedScoreEngine(config)

    # Score 계산
    scored_df = engine.score_dataframe(df.copy(), timeframe=timeframe)

    # Tier 필터링
    signals_df = scored_df[scored_df['score'] >= tier_threshold].copy()

    print(f"   Total candles: {len(scored_df)}")
    print(f"   Score >= {tier_threshold}: {len(signals_df)} signals")

    # Tier 분포
    tier_dist = scored_df['tier'].value_counts()
    print(f"   Tier distribution:")
    for tier in ['S', 'A', 'B', 'C']:
        count = tier_dist.get(tier, 0)
        pct = count / len(scored_df) * 100
        print(f"      {tier}-Tier: {count:>4d} ({pct:>5.1f}%)")

    return signals_df, scored_df


def save_signals_json(signals_df, timeframe='day', year=2024, tier_name='S'):
    """
    Universal Engine 형식으로 시그널 JSON 저장
    """
    signals_dir = Path(__file__).parent / 'signals'
    signals_dir.mkdir(exist_ok=True)

    output_file = signals_dir / f'{timeframe}_{year}_{tier_name}tier_signals.json'

    signals_json = {
        'strategy': f'v-a-02-{tier_name}tier',
        'timeframe': timeframe,
        'year': year,
        'total_signals': len(signals_df),
        'tier_threshold': tier_name,
        'signals': []
    }

    for idx, row in signals_df.iterrows():
        signals_json['signals'].append({
            'timestamp': row['timestamp'].isoformat(),
            'action': 'BUY',
            'price': float(row['close']),
            'score': float(row['score']),
            'tier': row['tier'],
            'metadata': {
                'rsi': float(row['rsi']),
                'mfi': float(row['mfi']),
                'adx': float(row.get('adx', 0)),
                'volume_ratio': float(row['volume_ratio']),
                'atr_ratio': float(row['atr_ratio']),
                'bb_position': float(row['bb_position']),
                'signals': row['signals']
            }
        })

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(signals_json, f, indent=2, ensure_ascii=False)

    print(f"✅ Signals saved: {output_file}")
    return output_file


def calculate_signal_reproduction(signals_df, perfect_signals_df, tier_name='S'):
    """
    시그널 재현율 계산 (빠른 버전, 수익률 제외)
    """
    print(f"\n📊 Calculating signal reproduction ({tier_name}-Tier)...")

    calc = ReproductionCalculator(tolerance_days=1)

    # 시그널 매칭
    matched_count = calc._match_signals(
        signals_df['timestamp'],
        perfect_signals_df['timestamp']
    )

    signal_rate = matched_count / len(perfect_signals_df) if len(perfect_signals_df) > 0 else 0

    print(f"   Matched signals: {matched_count}/{len(perfect_signals_df)}")
    print(f"   Signal reproduction rate: {signal_rate:.2%}")

    return {
        'matched_count': matched_count,
        'total_perfect': len(perfect_signals_df),
        'total_strategy': len(signals_df),
        'signal_reproduction_rate': signal_rate
    }


def main():
    """메인 실행"""

    print("=" * 70)
    print("v-a-02: Multi-Indicator Score-Based Reproducer")
    print("=" * 70)
    print()

    # 설정
    TIMEFRAME = 'day'
    YEAR = 2024

    # Tier 임계값 설정
    tier_configs = [
        {'name': 'S', 'threshold': 28, 'desc': '보수적 (S-Tier only)'},
        {'name': 'A', 'threshold': 18, 'desc': '균형 (S+A-Tier)'},
        {'name': 'B', 'threshold': 12, 'desc': '공격적 (S+A+B-Tier)'}
    ]

    # 1. 완벽한 시그널 로드
    print("📈 Loading perfect signals...")
    loader = PerfectSignalLoader()
    perfect_signals = loader.load_perfect_signals(TIMEFRAME, YEAR)
    perfect_stats = loader.analyze_perfect_signals(perfect_signals)

    print(f"   Perfect signals: {len(perfect_signals)}개")
    print(f"   Perfect avg return: {perfect_stats['avg_return']:.2%}")
    print(f"   Perfect avg hold: {perfect_stats['avg_hold_days']:.1f}일")
    print()

    # 2. 시장 데이터 로드 및 지표 계산
    df = load_and_prepare_data(TIMEFRAME, YEAR)

    # 3. 3가지 Tier 버전 생성
    all_results = {}

    for tier_config in tier_configs:
        tier_name = tier_config['name']
        tier_threshold = tier_config['threshold']
        tier_desc = tier_config['desc']

        print("\n" + "=" * 70)
        print(f"{tier_name}-Tier Strategy: {tier_desc}")
        print("=" * 70)

        # 시그널 생성
        signals_df, scored_df = generate_score_based_signals(
            df,
            timeframe=TIMEFRAME,
            tier_threshold=tier_threshold
        )

        if len(signals_df) == 0:
            print(f"⚠️  No signals generated for {tier_name}-Tier (threshold={tier_threshold})")
            continue

        # JSON 저장
        signal_file = save_signals_json(
            signals_df,
            timeframe=TIMEFRAME,
            year=YEAR,
            tier_name=tier_name
        )

        # 재현율 계산
        repro_result = calculate_signal_reproduction(
            signals_df,
            perfect_signals,
            tier_name=tier_name
        )

        # 결과 저장
        all_results[tier_name] = {
            'tier_name': tier_name,
            'tier_threshold': tier_threshold,
            'tier_desc': tier_desc,
            'signal_file': str(signal_file),
            'total_signals': len(signals_df),
            'reproduction': repro_result
        }

        print()

    # 4. 최종 요약
    print("\n" + "=" * 70)
    print("📊 Final Summary")
    print("=" * 70)
    print()

    print(f"Perfect Signals: {len(perfect_signals)}개 (평균 {perfect_stats['avg_return']:.2%} 수익)")
    print()

    for tier_name, result in all_results.items():
        print(f"[{tier_name}-Tier] {result['tier_desc']}")
        print(f"   Threshold: {result['tier_threshold']}점")
        print(f"   Generated: {result['total_signals']}개")
        print(f"   Matched: {result['reproduction']['matched_count']}/{len(perfect_signals)}")
        print(f"   Signal Reproduction: {result['reproduction']['signal_reproduction_rate']:.2%}")
        print()

    # 5. 결과 저장
    output_dir = Path(__file__).parent / 'analysis'
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f'{TIMEFRAME}_{YEAR}_multi_tier_analysis.json'

    summary = {
        'strategy': 'v-a-02',
        'timeframe': TIMEFRAME,
        'year': YEAR,
        'perfect_signals': {
            'total': len(perfect_signals),
            'avg_return': float(perfect_stats['avg_return']),
            'avg_hold_days': float(perfect_stats['avg_hold_days'])
        },
        'tier_results': all_results
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"💾 Analysis saved: {output_file}")
    print()

    # 6. 다음 단계 안내
    print("🔄 Next Steps:")
    print("  1. Universal Engine으로 각 Tier 백테스팅")
    print("  2. 수익률 재현율 계산")
    print("  3. 최고 성과 Tier 선택")
    print()


if __name__ == '__main__':
    main()
