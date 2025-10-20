#!/usr/bin/env python3
"""
저점 진입 패턴 분석 도구
완벽한 매수 타이밍에서 기술적 지표 패턴 식별
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import json
import talib


def load_perfect_timing(json_path):
    """
    완벽한 타이밍 데이터 로드

    Args:
        json_path: perfect_timing.json 경로

    Returns:
        dict: 타임프레임별 완벽한 타이밍 데이터
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_candle_data(db_path, timeframe, timestamp, window=50):
    """
    특정 시점 전후 캔들 데이터 로드

    Args:
        db_path: DB 경로
        timeframe: 타임프레임
        timestamp: 기준 시점
        window: 전후 캔들 개수

    Returns:
        DataFrame: 캔들 데이터
    """
    conn = sqlite3.connect(db_path)

    # 기준 시점 전후 데이터 로드
    query = f"""
    SELECT timestamp, opening_price as open, high_price as high,
           low_price as low, trade_price as close,
           candle_acc_trade_volume as volume
    FROM bitcoin_{timeframe}
    WHERE timestamp <= '{timestamp}'
    ORDER BY timestamp DESC
    LIMIT {window}
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    # 시간순 정렬
    df = df.sort_values('timestamp').reset_index(drop=True)

    return df


def calculate_indicators(df):
    """
    기술적 지표 계산

    Args:
        df: OHLCV DataFrame

    Returns:
        DataFrame with indicators
    """
    # NumPy 배열로 변환
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    # RSI
    df['rsi'] = talib.RSI(close, timeperiod=14)

    # Bollinger Bands
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    df['bb_upper'] = upper
    df['bb_middle'] = middle
    df['bb_lower'] = lower
    df['bb_position'] = (close - lower) / (upper - lower)  # 0~1, 0=하단, 1=상단

    # MACD
    macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df['macd'] = macd
    df['macd_signal'] = signal
    df['macd_hist'] = hist

    # ADX (추세 강도)
    df['adx'] = talib.ADX(high, low, close, timeperiod=14)

    # Volume SMA (거래량 평균 대비)
    df['volume_sma'] = talib.SMA(volume, timeperiod=20)
    df['volume_ratio'] = volume / df['volume_sma']

    # Stochastic
    slowk, slowd = talib.STOCH(high, low, close,
                                fastk_period=14, slowk_period=3, slowd_period=3)
    df['stoch_k'] = slowk
    df['stoch_d'] = slowd

    return df


def analyze_entry_point(db_path, timeframe, entry_timestamp, entry_price):
    """
    특정 진입 시점의 지표 분석

    Args:
        db_path: DB 경로
        timeframe: 타임프레임
        entry_timestamp: 진입 시점
        entry_price: 진입 가격

    Returns:
        dict: 진입 시점의 지표값
    """
    # 진입 시점 전후 50개 캔들 로드
    df = get_candle_data(db_path, timeframe, entry_timestamp, window=50)

    if len(df) == 0:
        return None

    # 지표 계산
    df = calculate_indicators(df)

    # 마지막 행이 진입 시점
    entry_row = df.iloc[-1]

    # 이전 캔들 (크로스 확인용)
    prev_row = df.iloc[-2] if len(df) > 1 else None

    result = {
        'timestamp': entry_timestamp,
        'price': entry_price,
        'indicators': {
            'rsi': entry_row['rsi'],
            'bb_position': entry_row['bb_position'],
            'macd': entry_row['macd'],
            'macd_signal': entry_row['macd_signal'],
            'macd_hist': entry_row['macd_hist'],
            'adx': entry_row['adx'],
            'volume_ratio': entry_row['volume_ratio'],
            'stoch_k': entry_row['stoch_k'],
            'stoch_d': entry_row['stoch_d']
        },
        'patterns': {}
    }

    # 패턴 식별
    if prev_row is not None:
        # MACD 골든크로스
        result['patterns']['macd_golden_cross'] = (
            prev_row['macd'] <= prev_row['macd_signal'] and
            entry_row['macd'] > entry_row['macd_signal']
        )

        # Stochastic 골든크로스
        result['patterns']['stoch_golden_cross'] = (
            prev_row['stoch_k'] <= prev_row['stoch_d'] and
            entry_row['stoch_k'] > entry_row['stoch_d']
        )

        # RSI 과매도 반등
        result['patterns']['rsi_oversold_bounce'] = (
            prev_row['rsi'] <= 30 and entry_row['rsi'] > 30
        )

    # Bollinger Band 터치
    result['patterns']['bb_lower_touch'] = entry_row['bb_position'] <= 0.1

    # 거래량 급증
    result['patterns']['volume_spike'] = entry_row['volume_ratio'] >= 2.0

    return result


def analyze_exit_point(db_path, timeframe, exit_timestamp, exit_price):
    """
    특정 청산 시점의 지표 분석

    Args:
        db_path: DB 경로
        timeframe: 타임프레임
        exit_timestamp: 청산 시점
        exit_price: 청산 가격

    Returns:
        dict: 청산 시점의 지표값
    """
    # 청산 시점 전후 50개 캔들 로드
    df = get_candle_data(db_path, timeframe, exit_timestamp, window=50)

    if len(df) == 0:
        return None

    # 지표 계산
    df = calculate_indicators(df)

    # 마지막 행이 청산 시점
    exit_row = df.iloc[-1]

    # 이전 캔들
    prev_row = df.iloc[-2] if len(df) > 1 else None

    result = {
        'timestamp': exit_timestamp,
        'price': exit_price,
        'indicators': {
            'rsi': exit_row['rsi'],
            'bb_position': exit_row['bb_position'],
            'macd': exit_row['macd'],
            'macd_signal': exit_row['macd_signal'],
            'macd_hist': exit_row['macd_hist'],
            'adx': exit_row['adx'],
            'volume_ratio': exit_row['volume_ratio'],
            'stoch_k': exit_row['stoch_k'],
            'stoch_d': exit_row['stoch_d']
        },
        'patterns': {}
    }

    # 패턴 식별
    if prev_row is not None:
        # MACD 데드크로스
        result['patterns']['macd_dead_cross'] = (
            prev_row['macd'] >= prev_row['macd_signal'] and
            exit_row['macd'] < exit_row['macd_signal']
        )

        # Stochastic 데드크로스
        result['patterns']['stoch_dead_cross'] = (
            prev_row['stoch_k'] >= prev_row['stoch_d'] and
            exit_row['stoch_k'] < exit_row['stoch_d']
        )

        # RSI 과매수 하락
        result['patterns']['rsi_overbought_drop'] = (
            prev_row['rsi'] >= 70 and exit_row['rsi'] < 70
        )

    # Bollinger Band 상단 터치
    result['patterns']['bb_upper_touch'] = exit_row['bb_position'] >= 0.9

    return result


def find_common_patterns(analyses):
    """
    여러 분석 결과에서 공통 패턴 찾기

    Args:
        analyses: 분석 결과 리스트

    Returns:
        dict: 공통 패턴 통계
    """
    if not analyses:
        return {}

    # 지표값 수집
    indicator_values = {key: [] for key in analyses[0]['indicators'].keys()}
    pattern_counts = {key: 0 for key in analyses[0]['patterns'].keys()}

    for analysis in analyses:
        # 지표값
        for key, value in analysis['indicators'].items():
            if not pd.isna(value):
                indicator_values[key].append(value)

        # 패턴 출현
        for key, value in analysis['patterns'].items():
            if value:
                pattern_counts[key] += 1

    # 통계 계산
    stats = {}

    for key, values in indicator_values.items():
        if values:
            stats[key] = {
                'mean': np.mean(values),
                'median': np.median(values),
                'std': np.std(values),
                'min': np.min(values),
                'max': np.max(values),
                'q25': np.percentile(values, 25),
                'q75': np.percentile(values, 75)
            }

    # 패턴 출현율
    pattern_freq = {key: count / len(analyses) for key, count in pattern_counts.items()}

    return {
        'indicator_stats': stats,
        'pattern_frequency': pattern_freq,
        'sample_count': len(analyses)
    }


def main():
    """메인 실행"""
    db_path = Path(__file__).parent.parent / 'upbit_bitcoin.db'
    perfect_timing_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'perfect_timing.json'

    # 완벽한 타이밍 데이터 로드
    perfect_data = load_perfect_timing(perfect_timing_path)

    timeframes = ['day', 'minute240', 'minute60', 'minute15']
    years = [2022, 2023, 2024, 2025]

    all_results = {}

    for tf in timeframes:
        print(f"\n{'='*80}")
        print(f"타임프레임: {tf}")
        print(f"{'='*80}")

        entry_analyses = []
        exit_analyses = []

        for year in years:
            year_str = str(year)

            # 해당 연도 데이터 확인
            if year_str not in perfect_data[tf]:
                continue

            year_data = perfect_data[tf][year_str]

            if not year_data.get('lowest_points') or not year_data.get('highest_points'):
                continue

            # 최저점 (진입)
            lowest = year_data['lowest_points'][0]
            entry_timestamp = lowest['timestamp']
            entry_price = lowest['low_price']

            # 최고점 (청산)
            highest = year_data['highest_points'][0]
            exit_timestamp = highest['timestamp']
            exit_price = highest['high_price']

            print(f"\n{year}년:")
            print(f"  진입: {entry_timestamp} @ {entry_price:,.0f}원")

            # 진입 지표 분석
            entry_analysis = analyze_entry_point(db_path, tf, entry_timestamp, entry_price)
            if entry_analysis:
                entry_analyses.append(entry_analysis)

                print(f"    RSI: {entry_analysis['indicators']['rsi']:.1f}")
                print(f"    BB Position: {entry_analysis['indicators']['bb_position']:.3f}")
                print(f"    MACD: {entry_analysis['indicators']['macd']:.1f}")
                print(f"    ADX: {entry_analysis['indicators']['adx']:.1f}")
                print(f"    Volume Ratio: {entry_analysis['indicators']['volume_ratio']:.2f}x")
                print(f"    패턴: {[k for k, v in entry_analysis['patterns'].items() if v]}")

            print(f"  청산: {exit_timestamp} @ {exit_price:,.0f}원")

            # 청산 지표 분석
            exit_analysis = analyze_exit_point(db_path, tf, exit_timestamp, exit_price)
            if exit_analysis:
                exit_analyses.append(exit_analysis)

                print(f"    RSI: {exit_analysis['indicators']['rsi']:.1f}")
                print(f"    BB Position: {exit_analysis['indicators']['bb_position']:.3f}")
                print(f"    MACD: {exit_analysis['indicators']['macd']:.1f}")
                print(f"    ADX: {exit_analysis['indicators']['adx']:.1f}")
                print(f"    패턴: {[k for k, v in exit_analysis['patterns'].items() if v]}")

        # 공통 패턴 찾기
        print(f"\n{'='*80}")
        print(f"진입 패턴 통계 ({tf})")
        print(f"{'='*80}")

        entry_common = find_common_patterns(entry_analyses)

        if entry_common:
            print(f"\n지표 통계 (N={entry_common['sample_count']}):")
            for key, stats in entry_common['indicator_stats'].items():
                print(f"\n{key}:")
                print(f"  평균: {stats['mean']:.2f}")
                print(f"  중앙값: {stats['median']:.2f}")
                print(f"  범위: {stats['min']:.2f} ~ {stats['max']:.2f}")

            print(f"\n패턴 출현율:")
            for key, freq in entry_common['pattern_frequency'].items():
                print(f"  {key}: {freq*100:.1f}%")

        print(f"\n{'='*80}")
        print(f"청산 패턴 통계 ({tf})")
        print(f"{'='*80}")

        exit_common = find_common_patterns(exit_analyses)

        if exit_common:
            print(f"\n지표 통계 (N={exit_common['sample_count']}):")
            for key, stats in exit_common['indicator_stats'].items():
                print(f"\n{key}:")
                print(f"  평균: {stats['mean']:.2f}")
                print(f"  중앙값: {stats['median']:.2f}")
                print(f"  범위: {stats['min']:.2f} ~ {stats['max']:.2f}")

            print(f"\n패턴 출현율:")
            for key, freq in exit_common['pattern_frequency'].items():
                print(f"  {key}: {freq*100:.1f}%")

        all_results[tf] = {
            'entry_analyses': entry_analyses,
            'exit_analyses': exit_analyses,
            'entry_common_patterns': entry_common,
            'exit_common_patterns': exit_common
        }

    # 결과 저장
    output_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'entry_exit_patterns.json'

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n\n✅ 결과 저장: {output_path}")


if __name__ == '__main__':
    main()
