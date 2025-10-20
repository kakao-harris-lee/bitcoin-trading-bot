#!/usr/bin/env python3
"""
완벽한 매수/매도 타이밍 탐색 도구
모든 타임프레임에서 연도별 최저점/최고점 식별
"""

import sqlite3
import pandas as pd
from pathlib import Path
import json


def find_extremes_per_year(db_path, timeframe, years=[2022, 2023, 2024, 2025]):
    """
    연도별 최저점/최고점 Top 10 식별

    Args:
        db_path: DB 경로
        timeframe: 타임프레임 (day, minute240, minute60, minute15)
        years: 분석 연도 리스트

    Returns:
        dict: 연도별 최저점/최고점 데이터
    """
    conn = sqlite3.connect(db_path)

    results = {}

    for year in years:
        if year == 2025:
            end_date = '2025-10-16'
        else:
            end_date = f'{year}-12-31'

        start_date = f'{year}-01-01'

        # 최저점 Top 10
        query_low = f"""
        SELECT timestamp, trade_price, high_price, low_price, candle_acc_trade_volume as volume
        FROM bitcoin_{timeframe}
        WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
        ORDER BY low_price ASC
        LIMIT 10
        """

        df_low = pd.read_sql_query(query_low, conn)

        # 최고점 Top 10
        query_high = f"""
        SELECT timestamp, trade_price, high_price, low_price, candle_acc_trade_volume as volume
        FROM bitcoin_{timeframe}
        WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
        ORDER BY high_price DESC
        LIMIT 10
        """

        df_high = pd.read_sql_query(query_high, conn)

        results[year] = {
            'lowest_points': df_low.to_dict('records'),
            'highest_points': df_high.to_dict('records')
        }

    conn.close()
    return results


def analyze_perfect_trades(results, year):
    """
    완벽한 거래 시나리오 계산

    Args:
        results: find_extremes_per_year 결과
        year: 분석 연도

    Returns:
        dict: 완벽 거래 정보 또는 None (데이터 없으면)
    """
    data = results[year]

    # 데이터 존재 확인
    if not data['lowest_points'] or not data['highest_points']:
        return None

    # 최저점 (매수)
    lowest = data['lowest_points'][0]
    buy_time = lowest['timestamp']
    buy_price = lowest['low_price']

    # 최고점 (매도)
    highest = data['highest_points'][0]
    sell_time = highest['timestamp']
    sell_price = highest['high_price']

    # 수익률 계산
    profit_pct = ((sell_price - buy_price) / buy_price) * 100

    return {
        'year': year,
        'buy_time': buy_time,
        'buy_price': buy_price,
        'sell_time': sell_time,
        'sell_price': sell_price,
        'profit_pct': profit_pct,
        'buy_info': lowest,
        'sell_info': highest
    }


def calculate_multi_trade_scenario(buy_sell_pairs):
    """
    다중 거래 시나리오 계산 (연중 여러 번 매수/매도)

    Args:
        buy_sell_pairs: [(buy_price, sell_price), ...]

    Returns:
        dict: 누적 수익률 등
    """
    capital = 10_000_000
    initial = capital

    trades = []
    for idx, (buy, sell) in enumerate(buy_sell_pairs, 1):
        quantity = capital / buy
        proceeds = quantity * sell
        profit = proceeds - capital
        profit_pct = (profit / capital) * 100

        trades.append({
            'trade_num': idx,
            'buy_price': buy,
            'sell_price': sell,
            'profit_pct': profit_pct,
            'capital_before': capital,
            'capital_after': proceeds
        })

        capital = proceeds

    total_return = ((capital - initial) / initial) * 100

    return {
        'initial_capital': initial,
        'final_capital': capital,
        'total_return_pct': total_return,
        'num_trades': len(trades),
        'trades': trades
    }


def main():
    """메인 실행"""
    db_path = Path(__file__).parent.parent / 'upbit_bitcoin.db'

    timeframes = ['day', 'minute240', 'minute60', 'minute15']
    years = [2022, 2023, 2024, 2025]

    all_results = {}

    for tf in timeframes:
        print(f"\n{'='*80}")
        print(f"타임프레임: {tf}")
        print(f"{'='*80}")

        results = find_extremes_per_year(db_path, tf, years)
        all_results[tf] = results

        for year in years:
            perfect = analyze_perfect_trades(results, year)

            if perfect:
                print(f"\n{year}년 완벽 거래:")
                print(f"  매수: {perfect['buy_time']} @ {perfect['buy_price']:,.0f}원")
                print(f"  매도: {perfect['sell_time']} @ {perfect['sell_price']:,.0f}원")
                print(f"  수익률: {perfect['profit_pct']:+.2f}%")
            else:
                print(f"\n{year}년: 데이터 없음 (타임프레임: {tf})")

    # 결과 저장
    output_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'perfect_timing.json'
    output_path.parent.mkdir(exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n\n✅ 결과 저장: {output_path}")

    # 4년 평균 계산
    print(f"\n{'='*80}")
    print("4년 완벽 거래 평균 수익률 (day 기준)")
    print(f"{'='*80}")

    day_results = all_results['day']
    profits = []
    for year in years:
        perfect = analyze_perfect_trades(day_results, year)
        if perfect:
            profits.append(perfect['profit_pct'])
            print(f"{year}: {perfect['profit_pct']:+.2f}%")

    if profits:
        avg_profit = sum(profits) / len(profits)
        print(f"\n4년 평균: {avg_profit:.2f}%")
        print(f"목표: 79.75%")
        print(f"달성 여부: {'✅' if avg_profit >= 79.75 else '❌'}")


if __name__ == '__main__':
    main()
