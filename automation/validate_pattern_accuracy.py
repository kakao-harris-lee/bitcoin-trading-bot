#!/usr/bin/env python3
"""
Phase 1-4: 패턴 정확도 검증
식별된 진입/청산 패턴의 Precision, Recall, F1-Score 계산
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import json
import talib
from datetime import datetime, timedelta


def calculate_indicators(df):
    """기술적 지표 계산"""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    df['rsi'] = talib.RSI(close, timeperiod=14)

    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    df['bb_upper'] = upper
    df['bb_middle'] = middle
    df['bb_lower'] = lower
    df['bb_position'] = (close - lower) / (upper - lower)

    macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df['macd'] = macd
    df['macd_signal'] = signal
    df['macd_hist'] = hist

    df['adx'] = talib.ADX(high, low, close, timeperiod=14)

    df['volume_sma'] = talib.SMA(volume, timeperiod=20)
    df['volume_ratio'] = volume / df['volume_sma']

    slowk, slowd = talib.STOCH(high, low, close,
                                fastk_period=14, slowk_period=3, slowd_period=3)
    df['stoch_k'] = slowk
    df['stoch_d'] = slowd

    return df


def load_full_data(db_path, timeframe, year):
    """연도별 전체 데이터 로드"""
    conn = sqlite3.connect(db_path)

    query = f"""
    SELECT timestamp, opening_price as open, high_price as high,
           low_price as low, trade_price as close,
           candle_acc_trade_volume as volume
    FROM bitcoin_{timeframe}
    WHERE timestamp >= '{year}-01-01' AND timestamp < '{year+1}-01-01'
    ORDER BY timestamp ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    if len(df) == 0:
        return None

    df = calculate_indicators(df)

    return df


def apply_entry_pattern_v1(df, i):
    """
    진입 패턴 V1: 기본 조합
    - RSI < 30
    - BB Position < 0.2
    - Volume Ratio > 1.5
    """
    if i < 26:
        return False

    row = df.iloc[i]

    if pd.isna(row['rsi']) or pd.isna(row['bb_position']) or pd.isna(row['volume_ratio']):
        return False

    return (row['rsi'] < 30 and
            row['bb_position'] < 0.2 and
            row['volume_ratio'] > 1.5)


def apply_entry_pattern_v2(df, i):
    """
    진입 패턴 V2: 강화 조합
    - RSI < 30
    - BB Position < 0.2
    - Volume Ratio > 2.0
    - Stochastic K < 20
    """
    if i < 26:
        return False

    row = df.iloc[i]

    if (pd.isna(row['rsi']) or pd.isna(row['bb_position']) or
        pd.isna(row['volume_ratio']) or pd.isna(row['stoch_k'])):
        return False

    return (row['rsi'] < 30 and
            row['bb_position'] < 0.2 and
            row['volume_ratio'] > 2.0 and
            row['stoch_k'] < 20)


def apply_entry_pattern_v3(df, i):
    """
    진입 패턴 V3: minute15 최적화
    - RSI < 25
    - BB Position < 0.2 (또는 음수)
    - Volume Ratio > 2.0
    - Stochastic K < 15
    - ADX > 35 (강한 하락 추세)
    """
    if i < 26:
        return False

    row = df.iloc[i]

    if (pd.isna(row['rsi']) or pd.isna(row['bb_position']) or
        pd.isna(row['volume_ratio']) or pd.isna(row['stoch_k']) or
        pd.isna(row['adx'])):
        return False

    return (row['rsi'] < 25 and
            row['bb_position'] < 0.2 and
            row['volume_ratio'] > 2.0 and
            row['stoch_k'] < 15 and
            row['adx'] > 35)


def apply_exit_pattern_v1(df, i):
    """
    청산 패턴 V1: 기본 조합
    - RSI > 70
    - BB Position > 0.8
    """
    if i < 26:
        return False

    row = df.iloc[i]

    if pd.isna(row['rsi']) or pd.isna(row['bb_position']):
        return False

    return (row['rsi'] > 70 and row['bb_position'] > 0.8)


def apply_exit_pattern_v2(df, i):
    """
    청산 패턴 V2: 강화 조합
    - BB Position > 0.9 (상단 밴드 돌파)
    - Stochastic Dead Cross
    - RSI > 65
    """
    if i < 27:
        return False

    row = df.iloc[i]
    prev_row = df.iloc[i-1]

    if (pd.isna(row['bb_position']) or pd.isna(row['stoch_k']) or
        pd.isna(row['stoch_d']) or pd.isna(row['rsi']) or
        pd.isna(prev_row['stoch_k']) or pd.isna(prev_row['stoch_d'])):
        return False

    stoch_dead_cross = (prev_row['stoch_k'] >= prev_row['stoch_d'] and
                        row['stoch_k'] < row['stoch_d'])

    return (row['bb_position'] > 0.9 and
            stoch_dead_cross and
            row['rsi'] > 65)


def apply_exit_pattern_v3(df, i):
    """
    청산 패턴 V3: minute15 최적화
    - BB Position > 0.9
    - Stochastic K > 90
    - RSI > 70
    """
    if i < 26:
        return False

    row = df.iloc[i]

    if (pd.isna(row['bb_position']) or pd.isna(row['stoch_k']) or
        pd.isna(row['rsi'])):
        return False

    return (row['bb_position'] > 0.9 and
            row['stoch_k'] > 90 and
            row['rsi'] > 70)


def calculate_future_return(df, entry_idx, horizon_days):
    """
    미래 수익률 계산

    Args:
        df: DataFrame
        entry_idx: 진입 인덱스
        horizon_days: 예측 기간 (일)

    Returns:
        float: 수익률 (%), None if not enough data
    """
    entry_price = df.iloc[entry_idx]['close']

    # 타임프레임별 캔들 개수 계산
    # day: 1일 = 1캔들
    # minute240: 1일 = 6캔들
    # minute60: 1일 = 24캔들
    # minute15: 1일 = 96캔들

    # 간단히 horizon_days만큼 캔들 이동
    future_idx = entry_idx + horizon_days

    if future_idx >= len(df):
        return None

    # 해당 기간 동안 최고가
    max_price = df.iloc[entry_idx:future_idx+1]['high'].max()

    return ((max_price - entry_price) / entry_price) * 100


def validate_entry_pattern(df, pattern_func, pattern_name, horizon_days=30, profit_threshold=5.0):
    """
    진입 패턴 검증

    Args:
        df: 전체 데이터
        pattern_func: 패턴 함수
        pattern_name: 패턴 이름
        horizon_days: 예측 기간
        profit_threshold: 수익 기준 (%)

    Returns:
        dict: Precision, Recall, F1-Score
    """
    signals = []

    for i in range(26, len(df)):
        if pattern_func(df, i):
            future_return = calculate_future_return(df, i, horizon_days)
            if future_return is not None:
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'future_return': future_return,
                    'success': future_return >= profit_threshold
                })

    if len(signals) == 0:
        return {
            'pattern_name': pattern_name,
            'total_signals': 0,
            'precision': 0.0,
            'recall': 0.0,
            'f1_score': 0.0,
            'avg_return': 0.0
        }

    # True Positive: 신호 발생 + 수익 달성
    tp = sum(1 for s in signals if s['success'])

    # False Positive: 신호 발생 + 수익 미달성
    fp = len(signals) - tp

    # Precision: 신호 중 성공 비율
    precision = tp / len(signals) if len(signals) > 0 else 0.0

    # Recall 계산은 실제 저점 개수 필요 (전체 데이터에서 5% 이상 상승한 구간)
    # 간단히 전체 캔들 중 N일 후 profit_threshold 이상 상승한 캔들 개수로 근사
    total_opportunities = 0
    for i in range(26, len(df)):
        future_return = calculate_future_return(df, i, horizon_days)
        if future_return is not None and future_return >= profit_threshold:
            total_opportunities += 1

    recall = tp / total_opportunities if total_opportunities > 0 else 0.0

    # F1-Score
    f1_score = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # 평균 수익률
    avg_return = np.mean([s['future_return'] for s in signals])

    return {
        'pattern_name': pattern_name,
        'total_signals': len(signals),
        'true_positives': tp,
        'false_positives': fp,
        'total_opportunities': total_opportunities,
        'precision': precision,
        'recall': recall,
        'f1_score': f1_score,
        'avg_return': avg_return,
        'signals': signals[:10]  # 처음 10개만 저장
    }


def validate_exit_pattern(df, entry_indices, pattern_func, pattern_name):
    """
    청산 패턴 검증

    Args:
        df: 전체 데이터
        entry_indices: 진입 인덱스 리스트
        pattern_func: 청산 패턴 함수
        pattern_name: 패턴 이름

    Returns:
        dict: 청산 정확도
    """
    results = []

    for entry_idx in entry_indices:
        # 진입 후 최대 90일 내 청산 신호 탐색
        for i in range(entry_idx + 1, min(entry_idx + 90, len(df))):
            if pattern_func(df, i):
                entry_price = df.iloc[entry_idx]['close']
                exit_price = df.iloc[i]['close']
                profit = ((exit_price - entry_price) / entry_price) * 100

                results.append({
                    'entry_timestamp': df.iloc[entry_idx]['timestamp'],
                    'exit_timestamp': df.iloc[i]['timestamp'],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit': profit,
                    'holding_days': i - entry_idx
                })
                break  # 첫 청산 신호에서 매도

    if len(results) == 0:
        return {
            'pattern_name': pattern_name,
            'total_exits': 0,
            'avg_profit': 0.0,
            'win_rate': 0.0,
            'avg_holding_days': 0
        }

    avg_profit = np.mean([r['profit'] for r in results])
    win_rate = sum(1 for r in results if r['profit'] > 0) / len(results)
    avg_holding_days = np.mean([r['holding_days'] for r in results])

    return {
        'pattern_name': pattern_name,
        'total_exits': len(results),
        'avg_profit': avg_profit,
        'win_rate': win_rate,
        'avg_holding_days': avg_holding_days,
        'max_profit': max(r['profit'] for r in results),
        'min_profit': min(r['profit'] for r in results),
        'exits': results[:10]  # 처음 10개만
    }


def main():
    """메인 실행"""
    db_path = Path(__file__).parent.parent / 'upbit_bitcoin.db'

    timeframes = ['day', 'minute240', 'minute60', 'minute15']
    years = [2022, 2023, 2024]

    entry_patterns = [
        (apply_entry_pattern_v1, 'Entry V1: RSI<30 + BB<0.2 + Vol>1.5'),
        (apply_entry_pattern_v2, 'Entry V2: RSI<30 + BB<0.2 + Vol>2.0 + Stoch<20'),
        (apply_entry_pattern_v3, 'Entry V3: RSI<25 + BB<0.2 + Vol>2.0 + Stoch<15 + ADX>35')
    ]

    exit_patterns = [
        (apply_exit_pattern_v1, 'Exit V1: RSI>70 + BB>0.8'),
        (apply_exit_pattern_v2, 'Exit V2: BB>0.9 + Stoch Dead Cross + RSI>65'),
        (apply_exit_pattern_v3, 'Exit V3: BB>0.9 + Stoch>90 + RSI>70')
    ]

    all_results = {}

    for tf in timeframes:
        print(f"\n{'='*80}")
        print(f"타임프레임: {tf}")
        print(f"{'='*80}")

        tf_results = {'entry_validation': [], 'exit_validation': []}

        for year in years:
            print(f"\n{year}년 데이터 로드 중...")
            df = load_full_data(db_path, tf, year)

            if df is None or len(df) == 0:
                print(f"  ⚠️  데이터 없음")
                continue

            print(f"  ✅ 캔들 개수: {len(df)}")

            # 진입 패턴 검증
            print(f"\n진입 패턴 검증:")
            for pattern_func, pattern_name in entry_patterns:
                result = validate_entry_pattern(df, pattern_func, pattern_name,
                                               horizon_days=30, profit_threshold=5.0)
                result['year'] = year
                result['timeframe'] = tf
                tf_results['entry_validation'].append(result)

                print(f"\n  {pattern_name}:")
                print(f"    신호 횟수: {result['total_signals']}")
                print(f"    Precision: {result['precision']*100:.1f}%")
                print(f"    Recall: {result['recall']*100:.1f}%")
                print(f"    F1-Score: {result['f1_score']:.3f}")
                print(f"    평균 수익률: {result['avg_return']:.2f}%")

            # 청산 패턴 검증 (Entry V2 기준)
            print(f"\n청산 패턴 검증:")
            entry_signals = []
            for i in range(26, len(df)):
                if apply_entry_pattern_v2(df, i):
                    entry_signals.append(i)

            print(f"  진입 신호 개수: {len(entry_signals)}")

            for pattern_func, pattern_name in exit_patterns:
                result = validate_exit_pattern(df, entry_signals, pattern_func, pattern_name)
                result['year'] = year
                result['timeframe'] = tf
                tf_results['exit_validation'].append(result)

                print(f"\n  {pattern_name}:")
                print(f"    청산 횟수: {result['total_exits']}")
                print(f"    평균 수익률: {result['avg_profit']:.2f}%")
                print(f"    승률: {result['win_rate']*100:.1f}%")
                print(f"    평균 보유 기간: {result['avg_holding_days']:.0f} 캔들")

        all_results[tf] = tf_results

    # 결과 저장
    output_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'pattern_validation.json'

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n\n✅ 결과 저장: {output_path}")

    # 종합 요약
    print(f"\n{'='*80}")
    print("종합 요약")
    print(f"{'='*80}")

    for tf in timeframes:
        if tf not in all_results:
            continue

        print(f"\n{tf}:")

        # 진입 패턴 평균
        entry_results = all_results[tf]['entry_validation']
        for pattern_idx in range(len(entry_patterns)):
            pattern_name = entry_patterns[pattern_idx][1]
            pattern_data = [r for r in entry_results if r['pattern_name'] == pattern_name]

            if not pattern_data:
                continue

            avg_precision = np.mean([r['precision'] for r in pattern_data])
            avg_recall = np.mean([r['recall'] for r in pattern_data])
            avg_f1 = np.mean([r['f1_score'] for r in pattern_data])
            avg_return = np.mean([r['avg_return'] for r in pattern_data])

            print(f"\n  {pattern_name}:")
            print(f"    평균 Precision: {avg_precision*100:.1f}%")
            print(f"    평균 Recall: {avg_recall*100:.1f}%")
            print(f"    평균 F1-Score: {avg_f1:.3f}")
            print(f"    평균 수익률: {avg_return:.2f}%")


if __name__ == '__main__':
    main()
