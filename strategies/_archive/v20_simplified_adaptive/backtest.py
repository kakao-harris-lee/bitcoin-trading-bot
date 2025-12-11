#!/usr/bin/env python3
"""
v20 Simplified Adaptive 백테스팅
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from pathlib import Path

from core.data_loader import DataLoader
from strategy import add_indicators, v20_strategy


def run_backtest(start_date='2022-01-01', end_date='2022-12-31'):
    """백테스팅 실행"""

    # Config 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        config = json.load(f)

    print("="*80)
    print(f"v20 {config['strategy_name'].upper()} 백테스팅")
    print("="*80)

    # 데이터 로드
    db_path = Path(__file__).parent / '../../upbit_bitcoin.db'

    with DataLoader(str(db_path)) as loader:
        df = loader.load_timeframe(
            config['timeframe'],
            start_date=start_date,
            end_date=end_date
        )

    if len(df) == 0:
        print(f"❌ 데이터가 없습니다: {start_date} ~ {end_date}")
        return

    print(f"\n데이터 로드 완료: {len(df)}개 캔들")
    print(f"기간: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")

    # 지표 추가
    df = add_indicators(df)

    # 초기화
    initial_capital = config['backtest_settings']['initial_capital']
    fee_rate = config['backtest_settings']['fee_rate']
    slippage = config['backtest_settings']['slippage']

    cash = initial_capital
    position = None
    trades = []
    equity_curve = []

    print(f"\n초기 자본: {initial_capital:,}원")
    print(f"수수료: {fee_rate*100}%\n")

    # 백테스팅 루프
    for i in range(len(df)):
        row = df.iloc[i]
        price = row['close']

        # 전략 실행
        signal = v20_strategy(df, i, position, config)
        action = signal.get('action', 'hold')

        # 매수
        if action == 'buy' and position is None:
            fraction = signal.get('fraction', 1.0)
            amount = cash * fraction
            quantity = (amount / price) * (1 - slippage)
            cost = quantity * price * (1 + fee_rate)

            if cost >= 10000:  # 최소 주문 금액
                position = {
                    'entry_time': row['timestamp'],
                    'entry_price': price,
                    'quantity': quantity,
                    'cost': cost,
                    'reason': signal.get('reason', 'BUY'),
                    'risk_mode': signal.get('risk_mode', 'NEUTRAL'),
                    'return_20d': signal.get('return_20d', 0)
                }
                cash -= cost

                print(f"매수: {row['timestamp']} | {price:,.0f}원 | {signal.get('reason', 'BUY')} | "
                      f"20d수익률: {signal.get('return_20d', 0)*100:+.1f}%")

        # 매도
        elif action == 'sell' and position is not None:
            proceeds = position['quantity'] * price * (1 - fee_rate - slippage)
            cash += proceeds

            pnl = proceeds - position['cost']
            pnl_pct = (pnl / position['cost']) * 100

            trade = {
                'entry_time': position['entry_time'],
                'entry_price': position['entry_price'],
                'exit_time': row['timestamp'],
                'exit_price': price,
                'quantity': position['quantity'],
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'reason': signal.get('reason', 'SELL'),
                'risk_mode': position.get('risk_mode', 'UNKNOWN'),
                'return_20d_entry': position.get('return_20d', 0)
            }
            trades.append(trade)

            print(f"매도: {row['timestamp']} | {price:,.0f}원 | {signal.get('reason', 'SELL')} | "
                  f"수익: {pnl_pct:+.2f}%")

            position = None

        # Equity 기록
        position_value = position['quantity'] * price if position else 0
        total_equity = cash + position_value
        equity_curve.append({
            'timestamp': row['timestamp'],
            'cash': cash,
            'position_value': position_value,
            'total_equity': total_equity
        })

    # 최종 청산
    if position is not None:
        final_price = df.iloc[-1]['close']
        proceeds = position['quantity'] * final_price * (1 - fee_rate - slippage)
        cash += proceeds

        pnl = proceeds - position['cost']
        pnl_pct = (pnl / position['cost']) * 100

        trade = {
            'entry_time': position['entry_time'],
            'entry_price': position['entry_price'],
            'exit_time': df.iloc[-1]['timestamp'],
            'exit_price': final_price,
            'quantity': position['quantity'],
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'reason': 'END_OF_PERIOD',
            'risk_mode': position.get('risk_mode', 'UNKNOWN'),
            'return_20d_entry': position.get('return_20d', 0)
        }
        trades.append(trade)

        print(f"매도: {df.iloc[-1]['timestamp']} | {final_price:,.0f}원 | END_OF_PERIOD | "
              f"수익: {pnl_pct:+.2f}%")

        position = None

    # 결과 계산
    final_capital = cash
    total_return_pct = ((final_capital - initial_capital) / initial_capital) * 100

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    avg_profit = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0

    max_win = max([t['pnl_pct'] for t in trades]) if trades else 0
    max_loss = min([t['pnl_pct'] for t in trades]) if trades else 0

    # 결과 출력
    print(f"\n{'='*80}")
    print("백테스팅 결과")
    print(f"{'='*80}\n")

    print(f"초기 자본: {initial_capital:,}원")
    print(f"최종 자본: {final_capital:,.0f}원")
    print(f"수익: {final_capital - initial_capital:+,.0f}원")
    print(f"수익률: {total_return_pct:+.2f}%\n")

    print(f"총 거래: {len(trades)}회")
    print(f"승리: {len(wins)}회 ({win_rate:.1f}%)")
    print(f"손실: {len(losses)}회\n")

    if trades:
        print(f"평균 수익: {avg_profit:+.2f}%")
        print(f"평균 승리: {avg_profit:+.2f}%")
        print(f"평균 손실: {avg_loss:+.2f}%\n")

        print(f"최대 승리: {max_win:+.2f}%")
        print(f"최대 손실: {max_loss:+.2f}%\n")

    # 거래 상세
    if trades:
        print(f"{'='*80}")
        print("거래 상세")
        print(f"{'='*80}\n")

        for idx, trade in enumerate(trades, 1):
            print(f"[{idx}] {trade['entry_time']} → {trade['exit_time']}")
            print(f"    진입: {trade['entry_price']:,.0f}원 | 청산: {trade['exit_price']:,.0f}원")
            print(f"    수익: {trade['pnl_pct']:+.2f}% | 이유: {trade['reason']}")
            print(f"    모드: {trade['risk_mode']} | 20d수익률: {trade['return_20d_entry']*100:+.1f}%\n")

    # 결과 저장
    result = {
        'version': 'v20',
        'start_date': start_date,
        'end_date': end_date,
        'initial_capital': initial_capital,
        'final_capital': final_capital,
        'total_return_pct': total_return_pct,
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate / 100,
        'avg_profit_pct': avg_profit,
        'avg_loss_pct': avg_loss,
        'max_win_pct': max_win,
        'max_loss_pct': max_loss,
        'trades': [{
            'entry_time': str(t['entry_time']),
            'entry_price': t['entry_price'],
            'exit_time': str(t['exit_time']),
            'exit_price': t['exit_price'],
            'pnl_pct': t['pnl_pct'],
            'reason': t['reason'],
            'risk_mode': t['risk_mode'],
            'return_20d_entry': t['return_20d_entry']
        } for t in trades]
    }

    result_path = Path(__file__).parent / 'result.json'
    with open(result_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"결과가 result.json에 저장되었습니다.")


if __name__ == '__main__':
    run_backtest()
