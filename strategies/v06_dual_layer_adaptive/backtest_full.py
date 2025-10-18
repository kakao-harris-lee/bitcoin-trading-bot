#!/usr/bin/env python3
"""
backtest_full.py
v06 전체 시스템 백테스팅

Layer 1 (DAY) + Layer 2 (minute60 or minute240)
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from core.data_loader import DataLoader
from core.evaluator import Evaluator
from core.market_analyzer import MarketAnalyzer

from layer1_day import DayStrategy
from layer2_scalping import AdaptiveScalpingStrategy
from dual_backtester import DualLayerBacktester


def run_dual_backtest(
    df_day: pd.DataFrame,
    df_layer2: pd.DataFrame,
    config: dict,
    strategy_type: str = 'A'
) -> dict:
    """
    이중 레이어 백테스팅 실행

    Args:
        df_day: DAY 데이터
        df_layer2: minute60 or minute240 데이터
        config: 전체 설정
        strategy_type: 'A' (scalping) or 'B' (swing)

    Returns:
        백테스팅 결과
    """
    # 전략 생성
    day_strategy = DayStrategy(config['layer1_day'])

    strategy_config = config[f'strategy_{"a" if strategy_type == "A" else "b"}_{"scalping" if strategy_type == "A" else "swing"}']
    layer2_strategy = AdaptiveScalpingStrategy(strategy_config, strategy_type)

    # 백테스터 생성
    backtester = DualLayerBacktester(
        initial_capital=config['backtest_settings']['initial_capital'],
        fee_rate=config['backtest_settings']['fee_rate'],
        slippage=config['backtest_settings']['slippage']
    )

    layer2_config = config['layer2_scalping']

    # 백테스팅 루프
    # DAY 기준으로 순회하되, 각 DAY 캔들 내에서 layer2 캔들 처리
    for day_idx in range(len(df_day)):
        day_candle = df_day.iloc[day_idx]
        day_time = day_candle['timestamp']
        day_price = day_candle['close']

        # === Layer 1 (DAY) 신호 처리 ===
        day_signal = day_strategy.generate_signal(df_day, day_idx, backtester.day_cash)

        if day_signal['action'] == 'buy':
            success = backtester.execute_day_buy(day_time, day_price, day_signal['fraction'])
            if success:
                day_strategy.on_buy(day_time, day_price)

        elif day_signal['action'] == 'sell':
            success, pnl = backtester.execute_day_sell(day_time, day_price, day_signal['fraction'])
            if success:
                day_strategy.on_sell()
                # DAY 청산 시 Layer 2도 강제 청산
                if backtester.layer2_position > 0:
                    layer2_idx = _find_layer2_index(df_layer2, day_time)
                    if layer2_idx is not None:
                        layer2_price = df_layer2.iloc[layer2_idx]['close']
                        backtester.execute_layer2_sell(day_time, layer2_price, 1.0)
                        layer2_strategy.on_sell(0)  # pnl은 backtester에서 계산

        # === Layer 2 활성화 조건 체크 ===
        day_profit_threshold = layer2_config['activation_conditions']['day_profit_threshold']

        if (day_strategy.meets_layer2_activation(day_profit_threshold) and
            layer2_config['enabled'] and
            not backtester.layer2_shutdown):

            # 해당 DAY 기간의 layer2 캔들 찾기
            layer2_candles = _get_layer2_candles_for_day(df_layer2, day_time)

            for layer2_idx in layer2_candles:
                layer2_candle = df_layer2.iloc[layer2_idx]
                layer2_time = layer2_candle['timestamp']
                layer2_price = layer2_candle['close']

                # Layer 2 신호 처리
                available_capital = backtester.calculate_layer2_capital(day_price, layer2_config)

                layer2_signal = layer2_strategy.generate_signal(
                    df_layer2, layer2_idx, available_capital, layer2_time
                )

                if layer2_signal['action'] == 'buy' and available_capital > 10_000:
                    success = backtester.execute_layer2_buy(layer2_time, layer2_price, available_capital)
                    if success:
                        layer2_strategy.on_buy(layer2_time, layer2_price)

                elif layer2_signal['action'] == 'sell':
                    success, pnl = backtester.execute_layer2_sell(layer2_time, layer2_price, layer2_signal['fraction'])
                    if success:
                        if layer2_signal['fraction'] >= 0.99:  # 전량 매도
                            layer2_strategy.on_sell(pnl)

                # Layer 2 손실 체크
                max_loss = config['global_risk_management']['max_layer2_loss_pct']
                if backtester.check_layer2_shutdown(max_loss):
                    backtester.layer2_shutdown = True
                    print(f"⚠️  Layer 2 shutdown at {day_time} due to excessive loss")
                    break

        # Equity curve 기록 (하루에 한 번)
        layer2_price = day_price  # 간단화
        backtester.record_equity(day_time, day_price, layer2_price)

    # === 백테스팅 종료 시 모든 포지션 강제 청산 ===
    final_time = df_day.iloc[-1]['timestamp']
    final_price = df_day.iloc[-1]['close']

    # Layer 2 청산
    if backtester.layer2_position > 0:
        backtester.execute_layer2_sell(final_time, final_price, 1.0)

    # DAY 청산
    if backtester.day_position > 0:
        backtester.execute_day_sell(final_time, final_price, 1.0)

    # 최종 equity 기록
    backtester.record_equity(final_time, final_price, final_price)

    # 결과 생성
    return backtester.get_results()


def _find_layer2_index(df: pd.DataFrame, target_time) -> int:
    """특정 시각에 해당하는 layer2 인덱스 찾기"""
    mask = df['timestamp'] <= target_time
    if mask.any():
        return mask[::-1].idxmax()
    return None


def _get_layer2_candles_for_day(df: pd.DataFrame, day_time) -> list:
    """특정 DAY에 속하는 layer2 캔들 인덱스 리스트"""
    # 간단화: 해당 날짜의 모든 캔들
    day_date = day_time.date()
    indices = []

    for idx in range(len(df)):
        candle_time = df.iloc[idx]['timestamp']
        if candle_time.date() == day_date:
            indices.append(idx)

    return indices


def print_results(results: dict, config: dict, strategy_type: str):
    """결과 출력"""
    print("\n" + "="*80)
    print(f"v06 Dual Layer Strategy - {strategy_type} Results")
    print("="*80)

    baseline = config['baseline']

    print(f"\n=== Baseline (v05 DAY) ===")
    print(f"Return: {baseline['v05_day_return_2024']:.2f}%")
    print(f"Target (v06): {baseline['v06_target']:.2f}%")

    print(f"\n=== Total Performance ===")
    print(f"Initial: {results['initial_capital']:,.0f} KRW")
    print(f"Final: {results['final_capital']:,.0f} KRW")
    print(f"Return: {results['total_return']:.2f}%")
    print(f"  vs v05: {results['total_return'] - baseline['v05_day_return_2024']:+.2f}pp")
    print(f"  vs Target: {results['total_return'] - baseline['v06_target']:+.2f}pp")

    print(f"\n=== Layer 1 (DAY) ===")
    day_stats = results['day_stats']
    print(f"Trades: {day_stats['total_trades']}")
    print(f"Win Rate: {day_stats['win_rate']:.1%}")
    print(f"Total PnL: {day_stats['total_pnl']:,.0f} KRW")

    print(f"\n=== Layer 2 ({strategy_type}) ===")
    layer2_stats = results['layer2_stats']
    print(f"Trades: {layer2_stats['total_trades']}")
    print(f"Win Rate: {layer2_stats['win_rate']:.1%}")
    print(f"Total PnL: {layer2_stats['total_pnl']:,.0f} KRW")
    print(f"Cumulative PnL: {results['layer2_cumulative_pnl']:,.0f} KRW")

    if results['layer2_shutdown']:
        print(f"⚠️  Layer 2 was shutdown due to excessive loss")

    # 평가
    metrics = Evaluator.calculate_all_metrics(results)
    print(f"\n=== Risk Metrics ===")
    print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    print(f"MDD: {metrics['max_drawdown']:.2f}%")

    # 목표 달성
    achieved = results['total_return'] >= baseline['v06_target']
    print(f"\n=== Goal ===")
    print(f"{'✅ TARGET ACHIEVED!' if achieved else '❌ Target not met'}")

    print("="*80 + "\n")

    return metrics


def main():
    print("="*80)
    print("v06 Dual Layer Adaptive Strategy - Full Backtest")
    print("="*80)

    # Config 로드
    with open('config.json', 'r') as f:
        config = json.load(f)

    # 데이터 로드
    print("\n[1/5] Loading data...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df_day = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')
        df_minute60 = loader.load_timeframe('minute60', start_date='2024-01-01', end_date='2024-12-31')
        df_minute240 = loader.load_timeframe('minute240', start_date='2024-01-01', end_date='2024-12-31')

    print(f"  DAY: {len(df_day)} candles")
    print(f"  minute60: {len(df_minute60)} candles")
    print(f"  minute240: {len(df_minute240)} candles")

    # 지표 추가
    print("\n[2/5] Adding indicators...")
    df_day = MarketAnalyzer.add_indicators(df_day, indicators=['ema'])
    df_minute60 = MarketAnalyzer.add_indicators(df_minute60, indicators=['ema', 'rsi', 'macd'])
    df_minute240 = MarketAnalyzer.add_indicators(df_minute240, indicators=['ema', 'rsi', 'macd', 'adx'])

    # 전략 A (minute60 scalping) 테스트
    print("\n[3/5] Testing Strategy A (minute60 scalping)...")
    results_a = run_dual_backtest(df_day, df_minute60, config, strategy_type='A')
    metrics_a = print_results(results_a, config, 'Strategy A (minute60)')

    # 전략 B (minute240 swing) 테스트
    print("\n[4/5] Testing Strategy B (minute240 swing)...")
    results_b = run_dual_backtest(df_day, df_minute240, config, strategy_type='B')
    metrics_b = print_results(results_b, config, 'Strategy B (minute240)')

    # 비교
    print("\n[5/5] Comparison...")
    print("\n" + "="*80)
    print("STRATEGY COMPARISON")
    print("="*80)

    print(f"\n{'Strategy':<30} {'Return':<15} {'Sharpe':<10} {'MDD':<10} {'L2 Trades':<10}")
    print("-"*80)
    print(f"{'v05 (DAY only)':<30} {293.38:<15.2f} {1.76:<10.2f} {29.10:<10.2f} {0:<10}")
    print(f"{'v06 A (minute60)':<30} {results_a['total_return']:<15.2f} {metrics_a['sharpe_ratio']:<10.2f} {metrics_a['max_drawdown']:<10.2f} {results_a['layer2_stats']['total_trades']:<10}")
    print(f"{'v06 B (minute240)':<30} {results_b['total_return']:<15.2f} {metrics_b['sharpe_ratio']:<10.2f} {metrics_b['max_drawdown']:<10.2f} {results_b['layer2_stats']['total_trades']:<10}")

    # 최고 전략 선택
    best = 'A' if results_a['total_return'] > results_b['total_return'] else 'B'
    best_return = max(results_a['total_return'], results_b['total_return'])

    print(f"\n🏆 Best Strategy: {best} with {best_return:.2f}% return")

    print("="*80 + "\n")

    # 저장
    with open(f'results_strategy_a.json', 'w') as f:
        json.dump({
            'strategy': 'A (minute60)',
            'return': results_a['total_return'],
            'sharpe': metrics_a['sharpe_ratio'],
            'mdd': metrics_a['max_drawdown'],
            'layer2_trades': results_a['layer2_stats']['total_trades']
        }, f, indent=2)

    with open(f'results_strategy_b.json', 'w') as f:
        json.dump({
            'strategy': 'B (minute240)',
            'return': results_b['total_return'],
            'sharpe': metrics_b['sharpe_ratio'],
            'mdd': metrics_b['max_drawdown'],
            'layer2_trades': results_b['layer2_stats']['total_trades']
        }, f, indent=2)

    print("✅ Results saved\n")


if __name__ == "__main__":
    main()
