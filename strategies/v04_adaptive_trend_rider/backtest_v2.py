#!/usr/bin/env python3
"""
backtest_v2.py
v04 전략 백테스팅 (재설계 버전)
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

from strategy_v2 import AdaptiveHybridStrategy, v04_strategy_wrapper


def run_backtest(
    timeframe: str = 'minute240',
    start_date: str = '2024-01-01',
    end_date: str = '2024-12-30',
    config_path: str = 'config_v2.json'
):
    """
    v04 전략 백테스팅 실행

    Args:
        timeframe: 거래 타임프레임
        start_date: 시작일
        end_date: 종료일
        config_path: config 경로
    """
    print("="*80)
    print("v04 Adaptive Hybrid Strategy Backtest (v2)")
    print("="*80)

    # === 1. Config 로드 ===
    with open(config_path, 'r') as f:
        config = json.load(f)

    config['timeframe'] = timeframe

    print(f"\n[1/5] Loading Config...")
    print(f"  - Strategy: {config['strategy_name']} ({config['version']})")
    print(f"  - Timeframe: {timeframe}")
    print(f"  - Period: {start_date} ~ {end_date}")

    # === 2. 데이터 로드 ===
    print(f"\n[2/5] Loading Data...")

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            timeframe,
            start_date=start_date,
            end_date=end_date
        )

    print(f"  - Candles: {len(df):,}")

    # === 3. 지표 추가 ===
    print(f"\n[3/5] Adding Indicators...")

    # EMA, MACD, BB, RSI, ATR, ADX
    df = MarketAnalyzer.add_indicators(
        df,
        indicators=['ema', 'macd', 'bb', 'rsi', 'atr', 'adx']
    )

    print(f"  - Indicators added: {list(df.columns)}")

    # === 4. 전략 인스턴스 생성 ===
    print(f"\n[4/5] Initializing Strategy...")
    strategy = AdaptiveHybridStrategy(config)

    # === 5. 백테스팅 실행 ===
    print(f"\n[5/5] Running Backtest...")
    backtester = Backtester(
        initial_capital=config['initial_capital'],
        fee_rate=config['fee_rate'],
        slippage=config['slippage']
    )

    strategy_params = {
        'strategy_instance': strategy,
        'backtester': backtester
    }

    results = backtester.run(
        df,
        v04_strategy_wrapper,
        strategy_params
    )

    # === 6. 성과 평가 ===
    print(f"\n[6/6] Evaluating Performance...")

    # Buy&Hold 기준선
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buyhold_return = ((end_price - start_price) / start_price) * 100

    # 전략 성과
    metrics = Evaluator.calculate_all_metrics(results)

    # === 결과 출력 ===
    print("\n" + "="*80)
    print("BACKTEST RESULTS")
    print("="*80)

    print(f"\n=== 백테스팅 기간 ===")
    print(f"시작: {df.iloc[0]['timestamp']} (시작가: {start_price:,.0f}원)")
    print(f"종료: {df.iloc[-1]['timestamp']} (종료가: {end_price:,.0f}원)")
    print(f"기간: {(pd.to_datetime(end_date) - pd.to_datetime(start_date)).days}일 | 캔들: {len(df):,}개")

    print(f"\n=== Buy&Hold 기준선 ===")
    print(f"시작가: {start_price:,.0f}원")
    print(f"종료가: {end_price:,.0f}원")
    print(f"수익률: {buyhold_return:+.2f}%")
    target_return = buyhold_return + 20
    print(f"목표: Buy&Hold + 20%p = {target_return:+.2f}%")

    print(f"\n=== 전략 성과 ===")
    print(f"초기 자본: {metrics['initial_capital']:,.0f}원")
    print(f"최종 자본: {metrics['final_capital']:,.0f}원")
    print(f"절대 수익: {metrics['final_capital'] - metrics['initial_capital']:+,.0f}원")
    print(f"수익률: {metrics['total_return']:+.2f}% (vs Buy&Hold: {metrics['total_return'] - buyhold_return:+.2f}%p)")

    # 목표 달성 여부
    target_170 = 170.0
    achieved_170 = "✅" if metrics['total_return'] >= target_170 else "❌"
    achieved_bh = "✅" if metrics['total_return'] >= target_return else "❌"
    print(f"170% 목표 달성: {achieved_170} ({metrics['total_return']:.2f}% vs 170%)")
    print(f"BH+20%p 목표 달성: {achieved_bh} ({metrics['total_return']:.2f}% vs {target_return:.2f}%)")

    print(f"\n=== 리스크 지표 ===")
    sharpe_ok = "✅" if metrics['sharpe_ratio'] >= 1.0 else "❌"
    mdd_ok = "✅" if metrics['max_drawdown'] <= 30.0 else "❌"
    print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f} (목표 >= 1.0) {sharpe_ok}")
    print(f"Max Drawdown: {metrics['max_drawdown']:.2f}% (목표 <= 30%) {mdd_ok}")
    print(f"Sortino Ratio: {metrics.get('sortino_ratio', 0):.2f}")

    print(f"\n=== 거래 통계 ===")
    print(f"총 거래: {metrics['total_trades']}회 | 승률: {metrics['win_rate']:.1%}")
    print(f"평균 수익: {metrics.get('avg_profit', 0):.2f}% | 평균 손실: {metrics.get('avg_loss', 0):.2f}%")
    print(f"Profit Factor: {metrics.get('profit_factor', 0):.2f}")

    print(f"\n=== 종합 평가 ===")
    print(f"{achieved_170} 수익률 >= 170%")
    print(f"{achieved_bh} 수익률 >= Buy&Hold + 20%p")
    print(f"{sharpe_ok} Sharpe Ratio >= 1.0")
    print(f"{mdd_ok} Max Drawdown <= 30%")

    print("\n" + "="*80)

    # === 7. 결과 저장 ===
    result_data = {
        'version': config['version'],
        'strategy_name': config['strategy_name'],
        'timeframe': timeframe,
        'period': {'start': start_date, 'end': end_date},
        'buyhold_return': buyhold_return,
        'target_return': target_return,
        'metrics': metrics,
        'config': config,
        'timestamp': datetime.now().isoformat()
    }

    result_filename = f'results_v2_{timeframe}.json'
    with open(result_filename, 'w') as f:
        json.dump(result_data, f, indent=2, default=str)

    print(f"\nResults saved to: {result_filename}")

    return result_data


if __name__ == '__main__':
    # 기본 실행: minute240 타임프레임
    run_backtest(
        timeframe='minute240',
        start_date='2024-01-01',
        end_date='2024-12-30'
    )
