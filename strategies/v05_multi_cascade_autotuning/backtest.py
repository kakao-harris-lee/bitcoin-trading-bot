#!/usr/bin/env python3
"""
backtest.py
v05 Multi-Cascade Strategy 백테스팅

Phase 1: 기본 통합 (분할 매수/매도 없이)
Phase 2: 분할 매수/매도 활성화
Phase 3: Kelly Criterion 활성화
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

from core.data_loader import DataLoader
from core.evaluator import Evaluator
from core.market_analyzer import MarketAnalyzer

from multi_timeframe_backtester import MultiTimeframeBacktester
from strategy_cascade import CascadeStrategy, cascade_strategy_wrapper


def load_config(config_path: str = 'config.json') -> dict:
    """설정 파일 로드"""
    with open(config_path, 'r') as f:
        return json.load(f)


def load_all_timeframes(start_date: str = '2024-01-01', end_date: str = '2024-12-31') -> dict:
    """모든 타임프레임 데이터 로드"""
    print("[1/6] Loading all timeframe data...")

    dataframes = {}
    timeframes = ['day', 'minute240', 'minute60', 'minute30', 'minute15', 'minute5']

    with DataLoader('../../upbit_bitcoin.db') as loader:
        for tf in timeframes:
            print(f"  Loading {tf}...", end=' ')
            df = loader.load_timeframe(tf, start_date=start_date, end_date=end_date)

            # EMA 지표 추가
            df = MarketAnalyzer.add_indicators(df, indicators=['ema'])

            dataframes[tf] = df
            print(f"{len(df)} candles")

    return dataframes


def run_backtest(
    config: dict,
    dataframes: dict,
    phase: str = 'full'
) -> dict:
    """
    백테스팅 실행

    Args:
        config: 전략 설정
        dataframes: 타임프레임 데이터
        phase: 'basic', 'split', 'kelly', 'full'

    Returns:
        백테스팅 결과
    """
    # Phase별 설정 조정
    if phase == 'basic':
        config['split_orders']['enabled'] = False
        config['kelly_criterion']['enabled'] = False
        print("\n[Phase 1: Basic Integration - No split orders, No Kelly]")

    elif phase == 'split':
        config['split_orders']['enabled'] = True
        config['kelly_criterion']['enabled'] = False
        print("\n[Phase 2: Split Orders Enabled]")

    elif phase == 'kelly':
        config['split_orders']['enabled'] = True
        config['kelly_criterion']['enabled'] = True
        print("\n[Phase 3: Kelly Criterion Enabled]")

    else:  # full
        config['split_orders']['enabled'] = True
        config['kelly_criterion']['enabled'] = True
        print("\n[Phase Full: All Features Enabled]")

    # 전략 인스턴스 생성
    strategy = CascadeStrategy(config)

    # 백테스터 생성
    backtest_config = config['backtest_settings']
    backtester = MultiTimeframeBacktester(
        config=config,
        initial_capital=backtest_config['initial_capital'],
        fee_rate=backtest_config['fee_rate'],
        slippage=backtest_config['slippage']
    )

    # 백테스팅 실행
    print("\n[2/6] Running backtest...")
    results = backtester.run(
        dataframes=dataframes,
        strategy_func=cascade_strategy_wrapper,
        strategy_params={'strategy_instance': strategy}
    )

    # 거래 히스토리 업데이트
    for trade in results['trades']:
        trade_dict = {
            'profit_loss': trade.profit_loss,
            'profit_loss_pct': trade.profit_loss_pct
        }
        strategy.on_trade_closed(trade.layer, trade_dict)

    # Evaluator로 추가 지표 계산
    print("\n[3/6] Calculating metrics...")

    # Evaluator의 calculate_all_metrics 사용
    metrics = Evaluator.calculate_all_metrics(results)

    results['sharpe_ratio'] = metrics.get('sharpe_ratio', 0.0)
    results['max_drawdown'] = metrics.get('max_drawdown', 0.0)

    # Kelly 분석
    kelly_analysis = strategy.get_kelly_analysis()
    results['kelly_analysis'] = kelly_analysis

    return results


def print_results(results: dict, config: dict):
    """결과 출력"""
    print("\n" + "=" * 80)
    print("v05 Multi-Cascade Strategy - Backtest Results")
    print("=" * 80)

    baseline = config.get('baseline', {})
    v04_return = baseline.get('v04_return_2024', 288.67)
    v05_target = baseline.get('v05_target', 350.0)

    print(f"\n=== Baseline (v04) ===")
    print(f"v04 Best: {baseline.get('v04_best', 'DAY timeframe')}")
    print(f"v04 Return: {v04_return:.2f}%")
    print(f"v04 Sharpe: {baseline.get('v04_sharpe', 1.80):.2f}")
    print(f"v04 MDD: {baseline.get('v04_mdd', 28.43):.2f}%")
    print(f"v04 Trades: {baseline.get('v04_trades', 4)}")

    print(f"\n=== v05 Performance ===")
    print(f"Initial Capital: {results['initial_capital']:,.0f} KRW")
    print(f"Final Capital: {results['final_capital']:,.0f} KRW")
    print(f"Total Return: {results['total_return']:.2f}%")
    print(f"  vs v04: {results['total_return'] - v04_return:+.2f}pp")
    print(f"  vs Target: {results['total_return'] - v05_target:+.2f}pp")

    print(f"\n=== Risk Metrics ===")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f} (target >= 1.8)")
    print(f"Max Drawdown: {results['max_drawdown']:.2f}% (target <= 25%)")

    print(f"\n=== Trading Statistics ===")
    print(f"Total Trades: {results['total_trades']}")
    print(f"Winning Trades: {results['winning_trades']}")
    print(f"Losing Trades: {results['losing_trades']}")
    print(f"Win Rate: {results['win_rate']:.1%}")
    print(f"Profit Factor: {results['profit_factor']:.2f}")

    # 레이어별 통계
    print(f"\n=== Layer Statistics ===")
    layer_stats = results.get('layer_stats', {})
    for layer, stats in layer_stats.items():
        print(f"\n{layer.upper()}:")
        print(f"  Trades: {stats['total_trades']}")
        print(f"  Win Rate: {stats['win_rate']:.1%}")
        print(f"  Total PnL: {stats['total_pnl']:,.0f} KRW")

    # Kelly 분석
    print(f"\n=== Kelly Analysis ===")
    kelly_analysis = results.get('kelly_analysis', {})
    for layer, analysis in kelly_analysis.items():
        if analysis.get('kelly_available', False):
            print(f"\n{layer.upper()}:")
            print(f"  Kelly Final: {analysis['kelly_final']:.2%}")
            print(f"  Win Rate: {analysis['win_rate']:.1%}")
            print(f"  Win/Loss Ratio: {analysis['win_loss_ratio']:.2f}")
            print(f"  Recommendation: {analysis['recommendation']}")

    # 목표 달성 여부
    print(f"\n=== Goal Achievement ===")
    return_goal = results['total_return'] >= v05_target
    sharpe_goal = results['sharpe_ratio'] >= 1.8
    mdd_goal = results['max_drawdown'] <= 25.0

    print(f"✅ Return >= {v05_target}%: {'PASS' if return_goal else 'FAIL'}")
    print(f"✅ Sharpe >= 1.8: {'PASS' if sharpe_goal else 'FAIL'}")
    print(f"✅ MDD <= 25%: {'PASS' if mdd_goal else 'FAIL'}")

    overall = return_goal and sharpe_goal and mdd_goal
    print(f"\n{'🎉 ALL GOALS ACHIEVED!' if overall else '⚠️  Some goals not met'}")

    print("=" * 80 + "\n")


def save_results(results: dict, phase: str, output_path: str = 'results'):
    """결과 저장"""
    Path(output_path).mkdir(exist_ok=True)

    # JSON 저장
    filename = f"{output_path}/results_{phase}.json"

    # Trade 객체를 딕셔너리로 변환
    trades_dict = []
    for trade in results.get('trades', []):
        trades_dict.append({
            'layer': trade.layer,
            'entry_time': str(trade.entry_time),
            'entry_price': trade.entry_price,
            'quantity': trade.quantity,
            'exit_time': str(trade.exit_time),
            'exit_price': trade.exit_price,
            'profit_loss': trade.profit_loss,
            'profit_loss_pct': trade.profit_loss_pct,
            'reason': trade.reason
        })

    results_json = {
        'phase': phase,
        'timestamp': str(datetime.now()),
        'initial_capital': results['initial_capital'],
        'final_capital': results['final_capital'],
        'total_return': results['total_return'],
        'sharpe_ratio': results['sharpe_ratio'],
        'max_drawdown': results['max_drawdown'],
        'total_trades': results['total_trades'],
        'win_rate': results['win_rate'],
        'profit_factor': results['profit_factor'],
        'layer_stats': results.get('layer_stats', {}),
        'kelly_analysis': results.get('kelly_analysis', {}),
        'trades': trades_dict
    }

    with open(filename, 'w') as f:
        json.dump(results_json, f, indent=2)

    print(f"\n✅ Results saved to: {filename}")


def main():
    """메인 실행"""
    print("=" * 80)
    print("v05 Multi-Cascade Auto-Tuning Strategy - Backtest")
    print("=" * 80)

    # 설정 로드
    config = load_config()

    # 데이터 로드
    dataframes = load_all_timeframes(
        start_date='2024-01-01',
        end_date='2024-12-31'
    )

    # Phase별 백테스팅
    phases = ['basic', 'split', 'kelly', 'full']

    for phase in phases:
        results = run_backtest(config, dataframes, phase=phase)

        print_results(results, config)

        save_results(results, phase)

        print("\n" + "-" * 80 + "\n")


if __name__ == "__main__":
    main()
