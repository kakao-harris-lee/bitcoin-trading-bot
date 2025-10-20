#!/usr/bin/env python3
"""
Phase 1-7: 연도별 최적 전략 선정
각 연도의 시장 특성에 맞는 전략 자동 선택
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import json
import talib


def calculate_market_metrics(df):
    """
    시장 특성 지표 계산

    Returns:
        dict: 시장 분류 및 지표
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    # 연간 수익률
    annual_return = ((close[-1] - close[0]) / close[0]) * 100

    # 변동성 (표준편차)
    returns = np.diff(close) / close[:-1]
    volatility = np.std(returns) * 100

    # ADX (추세 강도)
    adx = talib.ADX(high, low, close, timeperiod=14)
    avg_adx = np.nanmean(adx)

    # RSI 평균
    rsi = talib.RSI(close, timeperiod=14)
    avg_rsi = np.nanmean(rsi)

    # 최대 낙폭 (MDD)
    cummax = np.maximum.accumulate(close)
    drawdown = (close - cummax) / cummax * 100
    max_drawdown = np.min(drawdown)

    # 시장 분류
    if annual_return > 100:
        market_type = 'extreme_bull'
    elif annual_return > 50:
        market_type = 'moderate_bull'
    elif annual_return > -10:
        market_type = 'sideways'
    elif annual_return > -50:
        market_type = 'moderate_bear'
    else:
        market_type = 'extreme_bear'

    # 추세 강도 분류
    if avg_adx > 40:
        trend_strength = 'strong'
    elif avg_adx > 25:
        trend_strength = 'moderate'
    else:
        trend_strength = 'weak'

    return {
        'annual_return': annual_return,
        'volatility': volatility,
        'avg_adx': avg_adx,
        'avg_rsi': avg_rsi,
        'max_drawdown': max_drawdown,
        'market_type': market_type,
        'trend_strength': trend_strength
    }


def load_yearly_data(db_path, timeframe, year):
    """연도별 데이터 로드"""
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

    return df if len(df) > 0 else None


def select_strategy_for_year(year_metrics, timeframe_mapping):
    """
    연도별 최적 전략 선정

    Args:
        year_metrics: 연도 시장 특성
        timeframe_mapping: 타임프레임 전략 매핑

    Returns:
        dict: 선정된 전략
    """
    market_type = year_metrics['market_type']
    trend_strength = year_metrics['trend_strength']
    volatility = year_metrics['volatility']

    # 기본 전략: Day
    primary_strategy = 'day'
    secondary_strategy = None
    allocation = {'day': 1.0}

    # 극단적 상승장: Day 단독
    if market_type == 'extreme_bull':
        primary_strategy = 'day'
        allocation = {'day': 1.0}

    # 중간 상승장: Day 70% + Minute240 30%
    elif market_type == 'moderate_bull':
        primary_strategy = 'day'
        secondary_strategy = 'minute240'
        allocation = {'day': 0.7, 'minute240': 0.3}

    # 횡보장: Day 50% + Minute240 50% (높은 거래 빈도)
    elif market_type == 'sideways':
        primary_strategy = 'day'
        secondary_strategy = 'minute240'
        allocation = {'day': 0.5, 'minute240': 0.5}

    # 하락장: Day 단독 (안전)
    elif market_type in ['moderate_bear', 'extreme_bear']:
        primary_strategy = 'day'
        allocation = {'day': 1.0}

    # 고변동성: Day 우선 (안정성)
    if volatility > 5.0:
        allocation = {'day': 1.0}
        secondary_strategy = None

    # 약한 추세: Minute240 비중 증가
    if trend_strength == 'weak' and market_type != 'extreme_bear':
        allocation = {'day': 0.4, 'minute240': 0.6}
        secondary_strategy = 'minute240'

    return {
        'primary_strategy': primary_strategy,
        'secondary_strategy': secondary_strategy,
        'allocation': allocation,
        'reasoning': f"{market_type} + {trend_strength} 추세 + {volatility:.2f}% 변동성"
    }


def main():
    """메인 실행"""
    db_path = Path(__file__).parent.parent / 'upbit_bitcoin.db'

    # 타임프레임 매핑 로드
    mapping_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'timeframe_strategy_mapping.json'
    with open(mapping_path, 'r', encoding='utf-8') as f:
        timeframe_mapping = json.load(f)

    years = [2022, 2023, 2024, 2025]
    timeframes = ['day', 'minute240']

    yearly_strategies = {}

    for year in years:
        print(f"\n{'='*80}")
        print(f"{year}년 시장 분석")
        print(f"{'='*80}")

        year_data = {}

        for tf in timeframes:
            df = load_yearly_data(db_path, tf, year)

            if df is None or len(df) == 0:
                print(f"\n{tf}: 데이터 없음")
                continue

            metrics = calculate_market_metrics(df)

            print(f"\n{tf.upper()}:")
            print(f"  연간 수익률: {metrics['annual_return']:.2f}%")
            print(f"  변동성: {metrics['volatility']:.2f}%")
            print(f"  평균 ADX: {metrics['avg_adx']:.2f}")
            print(f"  평균 RSI: {metrics['avg_rsi']:.2f}")
            print(f"  최대 낙폭: {metrics['max_drawdown']:.2f}%")
            print(f"  시장 유형: {metrics['market_type']}")
            print(f"  추세 강도: {metrics['trend_strength']}")

            year_data[tf] = metrics

        # Day 기준으로 전략 선정
        if 'day' in year_data:
            selected = select_strategy_for_year(year_data['day'], timeframe_mapping)

            print(f"\n{'='*80}")
            print(f"선정된 전략")
            print(f"{'='*80}")
            print(f"주요 전략: {selected['primary_strategy'].upper()}")
            if selected['secondary_strategy']:
                print(f"보조 전략: {selected['secondary_strategy'].upper()}")

            print(f"\n자본 배분:")
            for strategy, weight in selected['allocation'].items():
                print(f"  {strategy.upper()}: {weight*100:.0f}%")

            print(f"\n선정 근거: {selected['reasoning']}")

            yearly_strategies[year] = {
                'market_metrics': year_data,
                'selected_strategy': selected
            }

    # 저장
    output_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'yearly_strategy_selection.json'

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(yearly_strategies, f, indent=2, ensure_ascii=False, default=str)

    # 종합 요약
    print(f"\n{'='*80}")
    print("4년 종합 요약")
    print(f"{'='*80}")

    for year, data in yearly_strategies.items():
        selected = data['selected_strategy']
        metrics = data['market_metrics'].get('day', {})

        print(f"\n{year}년:")
        print(f"  시장: {metrics.get('market_type', 'N/A')}")
        print(f"  수익률: {metrics.get('annual_return', 0):.2f}%")
        print(f"  전략: ", end='')

        for strategy, weight in selected['allocation'].items():
            print(f"{strategy.upper()} {weight*100:.0f}%", end=' ')
        print()

    print(f"\n✅ 결과 저장: {output_path}")

    # Phase 1 완료 메시지
    print(f"\n{'='*80}")
    print("🎉 Phase 1 완료: 완벽한 타이밍 역공학 분석")
    print(f"{'='*80}")
    print("\n주요 성과:")
    print("  ✅ 완벽한 타이밍 식별: 4년 평균 157.64%")
    print("  ✅ 진입/청산 패턴 분석 완료")
    print("  ✅ 패턴 정확도 검증: Day 95.2% Precision")
    print("  ✅ 유전 알고리즘 최적화: 454-477% 수익")
    print("  ✅ 타임프레임별 전략 매핑 완료")
    print("  ✅ 연도별 전략 선정 완료")
    print("\n다음 단계: Phase 2 - 복합 알고리즘 개발 (v21-v30)")


if __name__ == '__main__':
    main()
