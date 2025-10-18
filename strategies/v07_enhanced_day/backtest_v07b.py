#!/usr/bin/env python3
"""v07b Backtest with Partial Profit Taking"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime
from core.data_loader import DataLoader
from core.evaluator import Evaluator
from core.market_analyzer import MarketAnalyzer
from simple_backtester import SimpleBacktester
from strategy_v07b import v07b_strategy, reset_state


def main():
    print("="*80)
    print("v07b Enhanced DAY Strategy with Partial Profit Taking")
    print("="*80)

    # Load config
    with open('config_v07b.json', 'r') as f:
        config = json.load(f)

    # Load data
    print("\n[1/5] 데이터 로드...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            config['timeframe'],
            start_date=config['backtest']['start_date'],
            end_date=config['backtest']['end_date']
        )
    print(f"  {len(df)}개 캔들")

    # Add indicators
    print("\n[2/5] 지표 추가...")
    df['ema12'] = df['close'].ewm(span=config['indicators']['ema_fast'], adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=config['indicators']['ema_slow'], adjust=False).mean()
    df['prev_ema12'] = df['ema12'].shift(1)
    df['prev_ema26'] = df['ema26'].shift(1)

    df = MarketAnalyzer.add_indicators(df, indicators=['macd'])
    df['prev_macd'] = df['macd'].shift(1)
    df['prev_macd_signal'] = df['macd_signal'].shift(1)

    # Initialize backtester
    print("\n[3/5] 백테스팅 실행...")
    backtester = SimpleBacktester(
        initial_capital=config['trading']['initial_capital'],
        fee_rate=config['trading']['fee_rate'],
        slippage=config['trading']['slippage']
    )

    reset_state()

    params = {
        'trailing_stop_pct': config['exit']['trailing_stop_pct'],
        'stop_loss_pct': config['exit']['stop_loss_pct'],
        'position_fraction': config['position']['position_fraction'],
        'profit_targets': config['exit']['profit_targets']
    }

    trade_count = 0
    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row['timestamp']
        price = row['close']

        decision = v07b_strategy(df, i, params)
        action = decision['action']

        if action == 'buy':
            fraction = decision['fraction']
            backtester.execute_buy(timestamp, price, fraction)
            trade_count += 1
            reason = decision.get('reason', '')
            print(f"  BUY #{trade_count}: {timestamp.date()} @ {price:,.0f}원 ({reason})")

        elif action == 'sell':
            fraction = decision['fraction']
            backtester.execute_sell(timestamp, price, fraction)
            reason = decision.get('reason', '')
            print(f"  SELL: {timestamp.date()} @ {price:,.0f}원 ({reason}, {fraction*100:.0f}%)")

        backtester.record_equity(timestamp, price)

    # Final liquidation
    final_time = df.iloc[-1]['timestamp']
    final_price = df.iloc[-1]['close']

    if backtester.position > 0:
        print(f"  [최종] 청산: {final_time.date()} @ {final_price:,.0f}원")
        backtester.execute_sell(final_time, final_price, 1.0)

    backtester.record_equity(final_time, final_price)

    print(f"\n  완료: 총 {trade_count}회 진입")

    # Evaluate
    print("\n[4/5] 결과 평가...")
    results = backtester.get_results()
    metrics = Evaluator.calculate_all_metrics(results)

    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buy_hold_return = ((end_price - start_price) / start_price) * 100

    # Print results
    print("\n[5/5] 결과")
    print("="*80)
    print(f"초기 자본:      {metrics['initial_capital']:>15,}원")
    print(f"최종 자본:      {metrics['final_capital']:>15,.0f}원")
    print(f"수익률:         {metrics['total_return']:>14.2f}%")
    print(f"\nBuy&Hold:       {buy_hold_return:>14.2f}%")
    print(f"차이:           {metrics['total_return'] - buy_hold_return:>14.2f}%p")
    print(f"\nSharpe Ratio:   {metrics['sharpe_ratio']:>14.2f}")
    print(f"Max Drawdown:   {metrics['max_drawdown']:>14.2f}%")
    print(f"\n총 거래:        {metrics['total_trades']:>15}회")
    print(f"승률:           {metrics['win_rate']:>14.1%}")
    print(f"Profit Factor:  {metrics.get('profit_factor', 0):>14.2f}")

    # Success criteria
    print(f"\n{'='*80}")
    required = config['success_criteria']['required']
    return_ok = "✅" if metrics['total_return'] >= required['total_return'] else "❌"
    sharpe_ok = "✅" if metrics['sharpe_ratio'] >= required['sharpe_ratio'] else "❌"
    mdd_ok = "✅" if metrics['max_drawdown'] <= required['max_drawdown'] else "❌"

    print("성공 기준:")
    print(f"  수익률 >= {required['total_return']}%:  {return_ok} ({metrics['total_return']:.2f}%)")
    print(f"  Sharpe >= {required['sharpe_ratio']}:      {sharpe_ok} ({metrics['sharpe_ratio']:.2f})")
    print(f"  MDD <= {required['max_drawdown']}%:      {mdd_ok} ({metrics['max_drawdown']:.2f}%)")

    all_ok = (
        metrics['total_return'] >= required['total_return'] and
        metrics['sharpe_ratio'] >= required['sharpe_ratio'] and
        metrics['max_drawdown'] <= required['max_drawdown']
    )

    print(f"\n종합: {'✅ 목표 달성' if all_ok else '❌ 목표 미달'}")
    print("="*80)

    # Save
    output = {
        'version': 'v07b',
        'timestamp': datetime.now().isoformat(),
        'metrics': metrics,
        'buy_hold_return': buy_hold_return,
        'config': config
    }

    with open('results_v07b.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print("\n결과 저장: results_v07b.json")


if __name__ == '__main__':
    main()
