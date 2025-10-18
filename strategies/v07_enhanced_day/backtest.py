#!/usr/bin/env python3
"""
v07 Enhanced DAY Strategy Backtest Script

DualLayerBacktester 기반 정확한 백테스팅
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime
from core.data_loader import DataLoader
from core.evaluator import Evaluator
from simple_backtester import SimpleBacktester
from strategy import v07_strategy


def load_config():
    """Config 로드"""
    with open('config.json', 'r') as f:
        return json.load(f)


def prepare_data(config):
    """데이터 로드 및 지표 추가"""
    print("="*80)
    print("v07 Enhanced DAY Strategy Backtest")
    print("="*80)

    # Load data
    print("\n[1/6] 데이터 로드 중...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            config['timeframe'],
            start_date=config['backtest']['start_date'],
            end_date=config['backtest']['end_date']
        )

    print(f"  로드 완료: {len(df)}개 캔들")
    print(f"  기간: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")

    # Add indicators
    print("\n[2/6] 기술 지표 추가 중...")

    # EMA
    df['ema12'] = df['close'].ewm(span=config['indicators']['ema_fast'], adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=config['indicators']['ema_slow'], adjust=False).mean()
    df['prev_ema12'] = df['ema12'].shift(1)
    df['prev_ema26'] = df['ema26'].shift(1)

    # MACD
    from core.market_analyzer import MarketAnalyzer
    df = MarketAnalyzer.add_indicators(df, indicators=['macd'])
    df['prev_macd'] = df['macd'].shift(1)
    df['prev_macd_signal'] = df['macd_signal'].shift(1)

    print("  지표 추가 완료: EMA(12,26), MACD(12,26,9)")

    return df


def run_backtest(df, config):
    """백테스팅 실행"""
    print("\n[3/6] 백테스팅 실행 중...")

    # Initialize backtester
    backtester = SimpleBacktester(
        initial_capital=config['trading']['initial_capital'],
        fee_rate=config['trading']['fee_rate'],
        slippage=config['trading']['slippage']
    )

    # Reset strategy state
    v07_strategy.in_position = False
    v07_strategy.entry_price = None
    v07_strategy.highest_price = None

    # Strategy params
    params = {
        'trailing_stop_pct': config['exit']['trailing_stop_pct'],
        'stop_loss_pct': config['exit']['stop_loss_pct'],
        'position_fraction': config['position']['position_fraction']
    }

    # Run backtest
    trade_count = 0
    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row['timestamp']
        price = row['close']

        # Get strategy decision
        decision = v07_strategy(df, i, params)
        action = decision['action']

        # Execute
        if action == 'buy':
            fraction = decision['fraction']
            backtester.execute_buy(timestamp, price, fraction)
            trade_count += 1
            print(f"  [{i}/{len(df)}] BUY #{trade_count}: {timestamp.date()} @ {price:,.0f}원 (투자: {fraction*100:.0f}%)")

        elif action == 'sell':
            fraction = decision['fraction']
            backtester.execute_sell(timestamp, price, fraction)
            print(f"  [{i}/{len(df)}] SELL: {timestamp.date()} @ {price:,.0f}원 (청산: {fraction*100:.0f}%)")

        # Record equity
        backtester.record_equity(timestamp, price)

    # Force liquidate at end
    final_time = df.iloc[-1]['timestamp']
    final_price = df.iloc[-1]['close']

    if backtester.position > 0:
        print(f"\n  [최종] 포지션 청산: {final_time.date()} @ {final_price:,.0f}원")
        backtester.execute_sell(final_time, final_price, 1.0)

    backtester.record_equity(final_time, final_price)

    print(f"\n  백테스팅 완료: 총 {trade_count}회 진입")

    return backtester


def evaluate_results(backtester, df, config):
    """결과 평가"""
    print("\n[4/6] 결과 평가 중...")

    results = backtester.get_results()

    # Evaluator 계산
    metrics = Evaluator.calculate_all_metrics(results)

    # Buy&Hold 계산
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buy_hold_return = ((end_price - start_price) / start_price) * 100

    return metrics, buy_hold_return


def print_results(metrics, buy_hold_return, config):
    """결과 출력"""
    print("\n[5/6] 결과 출력")
    print("="*80)
    print("백테스팅 결과 요약")
    print("="*80)

    # Period
    print(f"\n기간: {config['backtest']['start_date']} ~ {config['backtest']['end_date']}")
    print(f"타임프레임: {config['timeframe'].upper()}")

    # Performance
    print(f"\n{'='*80}")
    print("성과 지표")
    print("="*80)
    print(f"초기 자본:      {metrics['initial_capital']:>15,}원")
    print(f"최종 자본:      {metrics['final_capital']:>15,}원")
    print(f"절대 수익:      {metrics['final_capital'] - metrics['initial_capital']:>15,}원")
    print(f"수익률:         {metrics['total_return']:>14.2f}%")

    # Buy&Hold comparison
    print(f"\n{'='*80}")
    print("Buy&Hold 비교")
    print("="*80)
    print(f"Buy&Hold:       {buy_hold_return:>14.2f}%")
    print(f"전략:           {metrics['total_return']:>14.2f}%")
    print(f"차이:           {metrics['total_return'] - buy_hold_return:>14.2f}%p")

    target = buy_hold_return + 20
    achieved = "✅" if metrics['total_return'] >= target else "❌"
    print(f"목표 (BH+20%):  {target:>14.2f}% {achieved}")

    # Risk metrics
    print(f"\n{'='*80}")
    print("리스크 지표")
    print("="*80)
    sharpe_ok = "✅" if metrics['sharpe_ratio'] >= 1.0 else "❌"
    mdd_ok = "✅" if metrics['max_drawdown'] <= 30.0 else "❌"

    print(f"Sharpe Ratio:   {metrics['sharpe_ratio']:>14.2f} (목표 >= 1.0) {sharpe_ok}")
    print(f"Max Drawdown:   {metrics['max_drawdown']:>14.2f}% (목표 <= 30%) {mdd_ok}")
    print(f"Sortino Ratio:  {metrics.get('sortino_ratio', 0):>14.2f}")

    # Trading stats
    print(f"\n{'='*80}")
    print("거래 통계")
    print("="*80)
    print(f"총 거래:        {metrics['total_trades']:>15}회")
    print(f"승리 거래:      {metrics['winning_trades']:>15}회")
    print(f"패배 거래:      {metrics['losing_trades']:>15}회")
    print(f"승률:           {metrics['win_rate']:>14.1%}")
    print(f"평균 수익:      {metrics['avg_profit']:>14.2f}%")
    print(f"평균 손실:      {metrics['avg_loss']:>14.2f}%")
    print(f"Profit Factor:  {metrics.get('profit_factor', 0):>14.2f}")

    # Success criteria
    print(f"\n{'='*80}")
    print("성공 기준 평가")
    print("="*80)

    required = config['success_criteria']['required']
    return_ok = "✅" if metrics['total_return'] >= required['total_return'] else "❌"
    sharpe_ok = "✅" if metrics['sharpe_ratio'] >= required['sharpe_ratio'] else "❌"
    mdd_ok = "✅" if metrics['max_drawdown'] <= required['max_drawdown'] else "❌"

    print(f"필수 조건:")
    print(f"  수익률 >= {required['total_return']}%:  {return_ok}")
    print(f"  Sharpe >= {required['sharpe_ratio']}:      {sharpe_ok}")
    print(f"  MDD <= {required['max_drawdown']}%:      {mdd_ok}")

    all_required = (
        metrics['total_return'] >= required['total_return'] and
        metrics['sharpe_ratio'] >= required['sharpe_ratio'] and
        metrics['max_drawdown'] <= required['max_drawdown']
    )

    print(f"\n종합: {'✅ 필수 조건 달성' if all_required else '❌ 필수 조건 미달'}")

    print("="*80)


def save_results(metrics, buy_hold_return, config):
    """결과 저장"""
    print("\n[6/6] 결과 저장 중...")

    results = {
        'version': config['version'],
        'strategy_name': config['strategy_name'],
        'timestamp': datetime.now().isoformat(),
        'timeframe': config['timeframe'],
        'backtest_period': {
            'start': config['backtest']['start_date'],
            'end': config['backtest']['end_date']
        },
        'metrics': metrics,
        'buy_hold_return': buy_hold_return,
        'config': config
    }

    with open('results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print("  결과 저장 완료: results.json")


def main():
    """메인 실행"""
    # Load config
    config = load_config()

    # Prepare data
    df = prepare_data(config)

    # Run backtest
    backtester = run_backtest(df, config)

    # Evaluate
    metrics, buy_hold_return = evaluate_results(backtester, df, config)

    # Print results
    print_results(metrics, buy_hold_return, config)

    # Save results
    save_results(metrics, buy_hold_return, config)

    print("\n백테스팅 완료!")


if __name__ == '__main__':
    main()
