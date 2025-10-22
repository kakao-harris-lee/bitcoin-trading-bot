#!/usr/bin/env python3
"""
v-a-01: Perfect Signal Reproduction Attempt
단순 RSI + MFI 조합으로 완벽한 시그널 재현 시도
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import pandas as pd
import json
from utils.perfect_signal_loader import PerfectSignalLoader
from utils.reproduction_calculator import ReproductionCalculator
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer


def generate_simple_rsi_mfi_signals(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    단순 RSI + MFI 조합 시그널 생성

    완벽한 시그널 패턴 학습 결과:
    - Day: RSI 평균 44.3, MFI 평균 45.2
    - Minute60: RSI 평균 46.1, MFI 평균 47.3

    Entry 조건:
    - RSI <= 50 (과매수 회피)
    - MFI <= 50 (자금 흐름 약세)
    - Volume Ratio >= 1.2 (거래량 증가)

    Args:
        df: 시장 데이터
        timeframe: day, minute60, etc.

    Returns:
        시그널 DataFrame (timestamp 컬럼 포함)
    """
    signals = []

    for i in range(len(df)):
        row = df.iloc[i]

        # Entry 조건
        entry_conditions = [
            row['rsi'] <= 50,
            row['mfi'] <= 50,
            row['volume_ratio'] >= 1.2
        ]

        if all(entry_conditions):
            signals.append({
                'timestamp': row['timestamp'],
                'price': row['close'],
                'rsi': row['rsi'],
                'mfi': row['mfi'],
                'volume_ratio': row['volume_ratio']
            })

    return pd.DataFrame(signals)


def main():
    """메인 실행"""

    # 설정
    TIMEFRAME = 'day'
    YEAR = 2024

    print(f"📊 v-a-01: Perfect Signal Reproduction")
    print(f"  Timeframe: {TIMEFRAME}")
    print(f"  Year: {YEAR}")
    print()

    # 1. 완벽한 시그널 로드
    print("📈 Loading perfect signals...")
    loader = PerfectSignalLoader()
    perfect_signals = loader.load_perfect_signals(TIMEFRAME, YEAR)
    perfect_stats = loader.analyze_perfect_signals(perfect_signals)

    print(f"  Perfect signals: {len(perfect_signals)}개")
    print(f"  Average return: {perfect_stats['avg_return']:.2%}")
    print(f"  Average hold: {perfect_stats['avg_hold_days']:.1f}일")
    print()

    # 2. 완벽한 시그널 패턴 분석
    print("🎯 Analyzing perfect signal patterns...")
    features = loader.get_signal_pattern_features(perfect_signals)

    if len(features) > 0:
        print("  Pattern statistics:")
        for col in ['rsi', 'mfi', 'volume_ratio']:
            if col in features.columns:
                avg = features[col].mean()
                median = features[col].median()
                print(f"    {col}: avg={avg:.2f}, median={median:.2f}")
    print()

    # 3. 시장 데이터 로드
    print("📊 Loading market data...")
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'
    data_loader = DataLoader(str(db_path))
    df = data_loader.load_timeframe(
        timeframe=TIMEFRAME,
        start_date=f'{YEAR}-01-01',
        end_date=f'{YEAR}-12-31'
    )

    # 4. 지표 계산
    print("📊 Calculating indicators...")
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'mfi'])

    # Volume ratio 계산
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
    df = df.dropna()  # NaN 제거

    print(f"  Market data: {len(df)} candles")
    print()

    # 5. 시그널 생성
    print("🎯 Generating signals (RSI + MFI)...")
    strategy_signals = generate_simple_rsi_mfi_signals(df, TIMEFRAME)
    print(f"  Generated signals: {len(strategy_signals)}개")
    print()

    # 6. 재현율 계산 (시그널만)
    print("📊 Calculating signal reproduction rate...")
    calc = ReproductionCalculator(tolerance_days=1)

    # 시그널 매칭만 계산 (수익률은 백테스팅 후)
    matched_count = calc._match_signals(
        strategy_signals['timestamp'],
        perfect_signals['timestamp']
    )

    signal_rate = matched_count / len(perfect_signals) if len(perfect_signals) > 0 else 0

    print(f"  Matched signals: {matched_count}/{len(perfect_signals)}")
    print(f"  Signal reproduction rate: {signal_rate:.2%}")
    print()

    # 7. 시그널 저장 (Universal Engine 형식)
    output_dir = Path(__file__).parent / 'signals'
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f'{TIMEFRAME}_{YEAR}_signals.json'

    # JSON 형식 변환
    signals_json = {
        'strategy': 'v-a-01',
        'timeframe': TIMEFRAME,
        'year': YEAR,
        'total_signals': len(strategy_signals),
        'signals': []
    }

    for _, row in strategy_signals.iterrows():
        signals_json['signals'].append({
            'timestamp': row['timestamp'].isoformat(),
            'entry_price': float(row['price']),
            'indicators': {
                'rsi': float(row['rsi']),
                'mfi': float(row['mfi']),
                'volume_ratio': float(row['volume_ratio'])
            }
        })

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(signals_json, f, indent=2, ensure_ascii=False)

    print(f"✅ Signals saved: {output_file}")
    print()

    # 8. 분석 결과 저장
    analysis_dir = Path(__file__).parent / 'analysis'
    analysis_dir.mkdir(exist_ok=True)

    analysis_file = analysis_dir / f'{TIMEFRAME}_{YEAR}_analysis.json'

    analysis_result = {
        'strategy': 'v-a-01',
        'timeframe': TIMEFRAME,
        'year': YEAR,
        'perfect_signals': {
            'total': len(perfect_signals),
            'avg_return': float(perfect_stats['avg_return']),
            'avg_hold_days': float(perfect_stats['avg_hold_days'])
        },
        'strategy_signals': {
            'total': len(strategy_signals),
            'signal_reproduction_rate': float(signal_rate),
            'matched_count': int(matched_count)
        },
        'pattern_analysis': {}
    }

    # 패턴 통계 추가
    if len(features) > 0:
        for col in ['rsi', 'mfi', 'volume_ratio']:
            if col in features.columns:
                analysis_result['pattern_analysis'][col] = {
                    'perfect_avg': float(features[col].mean()),
                    'perfect_median': float(features[col].median())
                }

                if col in strategy_signals.columns:
                    analysis_result['pattern_analysis'][col]['strategy_avg'] = \
                        float(strategy_signals[col].mean())
                    analysis_result['pattern_analysis'][col]['strategy_median'] = \
                        float(strategy_signals[col].median())

    with open(analysis_file, 'w', encoding='utf-8') as f:
        json.dump(analysis_result, f, indent=2, ensure_ascii=False)

    print(f"✅ Analysis saved: {analysis_file}")
    print()

    # 9. 요약
    print("=" * 60)
    print("📊 Summary")
    print("=" * 60)
    print(f"Perfect Signals: {len(perfect_signals)}개 (평균 수익 {perfect_stats['avg_return']:.2%})")
    print(f"Strategy Signals: {len(strategy_signals)}개")
    print(f"Signal Reproduction: {signal_rate:.2%} ({matched_count}/{len(perfect_signals)})")
    print()
    print("🔄 Next Step:")
    print("  1. 시그널 JSON을 Universal Evaluation Engine으로 백테스팅")
    print("  2. 수익률 재현율 계산")
    print("  3. 종합 재현율 및 Tier 분류")
    print()


if __name__ == '__main__':
    main()
