#!/usr/bin/env python3
"""
v42 Full Backtest - 2024년 전체
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from backtest_engine import V42BacktestEngine
import json
from datetime import datetime


def run_2024_backtest():
    """2024년 전체 백테스트"""

    print("\n" + "="*80)
    print("v42 Ultimate Scalping - 2024년 Full Backtest")
    print("="*80 + "\n")

    engine = V42BacktestEngine()

    # Strategy 1: minute15 S-Tier (고품질)
    print("\n>>> Strategy 1: minute15 S-Tier <<<\n")
    stats1 = engine.run_single_timeframe(
        timeframe='minute15',
        start_date='2024-01-01',
        end_date='2025-01-01',
        min_tier='S',
        min_score=35
    )
    engine.print_results(stats1, "Strategy 1 (minute15 S-Tier)")

    # Strategy 2: minute60 S-Tier (중단타)
    print("\n>>> Strategy 2: minute60 S-Tier <<<\n")
    engine2 = V42BacktestEngine()
    stats2 = engine2.run_single_timeframe(
        timeframe='minute60',
        start_date='2024-01-01',
        end_date='2025-01-01',
        min_tier='S',
        min_score=35
    )
    engine2.print_results(stats2, "Strategy 2 (minute60 S-Tier)")

    # Strategy 3: day S-Tier (장타)
    print("\n>>> Strategy 3: day S-Tier <<<\n")
    engine3 = V42BacktestEngine()
    stats3 = engine3.run_single_timeframe(
        timeframe='day',
        start_date='2024-01-01',
        end_date='2025-01-01',
        min_tier='S',
        min_score=40
    )
    engine3.print_results(stats3, "Strategy 3 (day S-Tier)")

    # 최고 성과 선택
    stats = max([stats1, stats2, stats3], key=lambda x: x['total_return'] if x else 0)

    # 결과 출력
    engine.print_results(stats, "v42 2024년 결과")

    # Buy&Hold 기준
    buy_hold_2024 = 1.3667  # 136.67%

    if stats:
        print(f"\n{'='*80}")
        print("Buy&Hold 비교")
        print(f"{'='*80}\n")

        print(f"v42 수익률:    {stats['total_return']*100:>14.2f}%")
        print(f"Buy&Hold:      {buy_hold_2024*100:>14.2f}%")
        print(f"초과 수익:     {(stats['total_return'] - buy_hold_2024)*100:>14.2f}%p")
        print()

        # 목표 달성 여부
        target = 2.5  # 250%
        achievement = stats['total_return'] / target * 100

        print(f"목표 수익률:   {target*100:>14.0f}%")
        print(f"달성률:        {achievement:>14.1f}%")
        print()

        # 결과 저장
        result = {
            'version': 'v42_ultimate_scalping',
            'timeframe': 'multi_tf',
            'period': '2024-01-01 ~ 2024-12-31',
            'timeframes': ['minute15', 'minute60', 'minute240'],
            **stats,
            'buy_hold_return': buy_hold_2024,
            'outperformance': stats['total_return'] - buy_hold_2024,
            'backtest_timestamp': datetime.now().isoformat()
        }

        # 저장
        output_file = '../results_2024.json'
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"결과 저장: {output_file}\n")

        # 거래 상세 저장
        if engine.position_manager and engine.position_manager.trade_history:
            trades_output = '../trades_2024.json'
            trades = engine.position_manager.trade_history

            # Timestamp를 문자열로 변환
            trades_serializable = []
            for trade in trades:
                t = trade.copy()
                t['entry_timestamp'] = str(t['entry_timestamp'])
                t['exit_timestamp'] = str(t['exit_timestamp'])
                trades_serializable.append(t)

            with open(trades_output, 'w') as f:
                json.dump(trades_serializable, f, indent=2, ensure_ascii=False)

            print(f"거래 기록 저장: {trades_output}\n")


if __name__ == '__main__':
    run_2024_backtest()
