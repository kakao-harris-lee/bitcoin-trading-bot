#!/usr/bin/env python3
"""
backtest_2025.py
v04 Simple 전략 - 2025년 데이터 백테스팅
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.backtester import Backtester
from core.evaluator import Evaluator

from strategy_simple import SimpleTrendFollowing, simple_strategy_wrapper


def run_backtest_2025():
    """2025년 데이터로 백테스팅"""

    print("="*80)
    print("v04 Simple Strategy - 2025 Data Backtest")
    print("="*80)

    # DAY 타임프레임 최적 파라미터 (2024 최적화 결과)
    config = {
        'strategy_name': 'simple_trend_following',
        'version': 'v04_simple_day',
        'timeframe': 'day',
        'position_fraction': 0.95,
        'trailing_stop_pct': 0.20,
        'stop_loss_pct': 0.10,
        'initial_capital': 10000000,
        'fee_rate': 0.0005,
        'slippage': 0.0002
    }

    print(f"\n[1/5] Config (2024 Optimized for DAY)")
    print(f"  - Position: {config['position_fraction']:.0%}")
    print(f"  - Trailing Stop: {config['trailing_stop_pct']:.0%}")
    print(f"  - Stop Loss: {config['stop_loss_pct']:.0%}")

    # === 데이터 로드 ===
    print(f"\n[2/5] Loading 2025 Data...")

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            'day',
            start_date='2025-01-01',
            end_date='2025-12-31'
        )

    print(f"  - Candles: {len(df):,}")
    print(f"  - Period: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")

    # === 지표 추가 ===
    print(f"\n[3/5] Adding Indicators...")
    df = MarketAnalyzer.add_indicators(df, indicators=['ema'])
    print(f"  - EMA added: ema_12, ema_26")

    # === 백테스팅 실행 ===
    print(f"\n[4/5] Running Backtest...")

    strategy = SimpleTrendFollowing(config)
    backtester = Backtester(
        initial_capital=config['initial_capital'],
        fee_rate=config['fee_rate'],
        slippage=config['slippage']
    )

    strategy_params = {
        'strategy_instance': strategy,
        'backtester': backtester
    }

    results = backtester.run(df, simple_strategy_wrapper, strategy_params)

    # === 성과 평가 ===
    print(f"\n[5/5] Evaluating Performance...")

    # Buy&Hold 기준
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buyhold_return = ((end_price - start_price) / start_price) * 100

    # 전략 성과
    metrics = Evaluator.calculate_all_metrics(results)

    # === 결과 출력 ===
    print("\n" + "="*80)
    print("2025 BACKTEST RESULTS")
    print("="*80)

    print(f"\n=== 백테스팅 기간 ===")
    print(f"시작: {df.iloc[0]['timestamp']} (시작가: {start_price:,.0f}원)")
    print(f"종료: {df.iloc[-1]['timestamp']} (종료가: {end_price:,.0f}원)")
    print(f"기간: {len(df)}일")

    print(f"\n=== Buy&Hold 기준선 (2025) ===")
    print(f"시작가: {start_price:,.0f}원")
    print(f"종료가: {end_price:,.0f}원")
    print(f"수익률: {buyhold_return:+.2f}%")

    print(f"\n=== 전략 성과 (2025) ===")
    print(f"초기 자본: {metrics['initial_capital']:,.0f}원")
    print(f"최종 자본: {metrics['final_capital']:,.0f}원")
    print(f"절대 수익: {metrics['final_capital'] - metrics['initial_capital']:+,.0f}원")
    print(f"수익률: {metrics['total_return']:+.2f}% (vs Buy&Hold: {metrics['total_return'] - buyhold_return:+.2f}%p)")

    print(f"\n=== 리스크 지표 ===")
    sharpe_ok = "✅" if metrics['sharpe_ratio'] >= 1.0 else "❌"
    mdd_ok = "✅" if metrics['max_drawdown'] <= 30.0 else "❌"
    print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f} (목표 >= 1.0) {sharpe_ok}")
    print(f"Max Drawdown: {metrics['max_drawdown']:.2f}% (목표 <= 30%) {mdd_ok}")

    print(f"\n=== 거래 통계 ===")
    print(f"총 거래: {metrics['total_trades']}회")

    if metrics['total_trades'] > 0:
        print(f"승률: {metrics['win_rate']:.1%}")
        print(f"승리 거래: {metrics.get('winning_trades', 0)}회")
        print(f"패배 거래: {metrics.get('losing_trades', 0)}회")
        print(f"평균 수익: {metrics.get('avg_profit', 0):,.0f}원")
        print(f"평균 손실: {metrics.get('avg_loss', 0):,.0f}원")
        print(f"Profit Factor: {metrics.get('profit_factor', 0):.2f}")

    # === 2024 vs 2025 비교 ===
    print(f"\n=== 2024 vs 2025 비교 ===")
    print(f"2024 성과: 288.67% (Buy&Hold: 137.49%)")
    print(f"2025 성과: {metrics['total_return']:.2f}% (Buy&Hold: {buyhold_return:.2f}%)")

    if metrics['total_return'] > 0:
        consistency = "✅ 일관된 성과" if metrics['total_return'] >= buyhold_return else "⚠️  Buy&Hold 대비 부족"
        print(f"평가: {consistency}")
    else:
        print(f"평가: ❌ 손실 발생")

    # === 거래 내역 ===
    if metrics['total_trades'] > 0:
        print(f"\n=== 거래 내역 ===")
        trades = results.get('trades', [])
        for idx, trade in enumerate(trades, 1):
            print(f"{idx}. Entry: {trade.entry_time} @ {trade.entry_price:,.0f}원")
            if trade.exit_time:
                print(f"   Exit:  {trade.exit_time} @ {trade.exit_price:,.0f}원")
                print(f"   P&L:   {trade.profit_loss:+,.0f}원 ({trade.profit_loss_pct:+.2f}%)")
                print(f"   Reason: {trade.reason}")
            else:
                print(f"   Status: 보유 중")
            print()

    # === 결과 저장 ===
    result_data = {
        'version': config['version'],
        'strategy_name': config['strategy_name'],
        'timeframe': 'day',
        'year': 2025,
        'period': {
            'start': str(df.iloc[0]['timestamp']),
            'end': str(df.iloc[-1]['timestamp'])
        },
        'buyhold_return': buyhold_return,
        'strategy_return': metrics['total_return'],
        'metrics': metrics,
        'config': config,
        'timestamp': datetime.now().isoformat()
    }

    with open('results_2025_day.json', 'w') as f:
        json.dump(result_data, f, indent=2, default=str)

    print(f"\nResults saved to: results_2025_day.json")
    print("="*80)

    return result_data


if __name__ == '__main__':
    run_backtest_2025()
