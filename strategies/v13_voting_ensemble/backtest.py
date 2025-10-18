#!/usr/bin/env python3
"""
v13 Voting Ensemble 백테스팅
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime

from core.data_loader import DataLoader
from strategy import add_indicators, v13_strategy


def run_backtest():
    """백테스팅 실행"""
    # Config 로드
    with open('config.json', 'r') as f:
        config = json.load(f)

    print("="*80)
    print(f"{config['version'].upper()} {config['strategy_name'].upper()} 백테스팅")
    print("="*80)

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(config['timeframe'],
                                     start_date='2024-01-01',
                                     end_date='2024-12-31')

    print(f"\n데이터 로드 완료: {len(df)}개 캔들")
    print(f"기간: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")

    # 지표 추가
    df = add_indicators(df, config)
    print(f"지표 추가 완료: VWAP, Breakout, Stochastic")

    # 백테스팅
    capital = config['initial_capital']
    krw = capital
    btc = 0.0
    position = None  # {'entry_price', 'entry_date', 'highest_price', 'signals', 'score'}
    trades = []

    fee_rate = config['fee_rate']
    trailing_stop = config['trailing_stop']
    stop_loss = config['stop_loss']

    print(f"\n초기 자본: {capital:,}원")
    print(f"Trailing Stop: {trailing_stop*100}%")
    print(f"Stop Loss: {stop_loss*100}%")
    print(f"수수료: {fee_rate*100}%\n")

    for i in range(len(df)):
        current = df.iloc[i]
        close = current['close']
        timestamp = current['timestamp']

        # 포지션 있을 때 (매도 확인)
        if position is not None:
            # 최고가 업데이트
            if close > position['highest_price']:
                position['highest_price'] = close

            # Trailing Stop
            trailing_price = position['highest_price'] * (1 - trailing_stop)

            # Stop Loss
            stop_price = position['entry_price'] * (1 - stop_loss)

            if close <= trailing_price:
                # 매도 (Trailing Stop)
                btc_value = btc * close
                fee = btc_value * fee_rate
                krw = btc_value - fee
                btc = 0.0

                pnl_pct = ((close - position['entry_price']) / position['entry_price']) * 100

                trades.append({
                    'entry_date': position['entry_date'],
                    'entry_price': position['entry_price'],
                    'exit_date': timestamp,
                    'exit_price': close,
                    'pnl_pct': pnl_pct,
                    'reason': 'TRAILING_STOP',
                    'signals': position['signals'],
                    'score': position['score'],
                    'highest_price': position['highest_price']
                })

                position = None

            elif close <= stop_price:
                # 매도 (Stop Loss)
                btc_value = btc * close
                fee = btc_value * fee_rate
                krw = btc_value - fee
                btc = 0.0

                pnl_pct = ((close - position['entry_price']) / position['entry_price']) * 100

                trades.append({
                    'entry_date': position['entry_date'],
                    'entry_price': position['entry_price'],
                    'exit_date': timestamp,
                    'exit_price': close,
                    'pnl_pct': pnl_pct,
                    'reason': 'STOP_LOSS',
                    'signals': position['signals'],
                    'score': position['score'],
                    'highest_price': position['highest_price']
                })

                position = None

        # 포지션 없을 때 (매수 확인)
        else:
            signal = v13_strategy(df, i, config)

            if signal['action'] == 'buy':
                # 매수
                fee = krw * fee_rate
                btc = (krw - fee) / close
                krw = 0.0

                position = {
                    'entry_price': close,
                    'entry_date': timestamp,
                    'highest_price': close,
                    'signals': signal['signals'],
                    'score': signal['score']
                }

                print(f"매수: {timestamp} | {close:,}원 | {signal['reason']}")

    # 마지막 포지션 정리
    if position is not None:
        close = df.iloc[-1]['close']
        timestamp = df.iloc[-1]['timestamp']

        btc_value = btc * close
        fee = btc_value * fee_rate
        krw = btc_value - fee
        btc = 0.0

        pnl_pct = ((close - position['entry_price']) / position['entry_price']) * 100

        trades.append({
            'entry_date': position['entry_date'],
            'entry_price': position['entry_price'],
            'exit_date': timestamp,
            'exit_price': close,
            'pnl_pct': pnl_pct,
            'reason': 'END_OF_PERIOD',
            'signals': position['signals'],
            'score': position['score'],
            'highest_price': position['highest_price']
        })

    # 최종 자본
    final_capital = krw

    # 결과 출력
    print("\n" + "="*80)
    print("백테스팅 결과")
    print("="*80)

    print(f"\n초기 자본: {capital:,}원")
    print(f"최종 자본: {final_capital:,.0f}원")
    print(f"수익: {final_capital - capital:+,.0f}원")
    print(f"수익률: {((final_capital - capital) / capital * 100):+.2f}%")

    print(f"\n총 거래: {len(trades)}회")

    if len(trades) > 0:
        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] <= 0]

        print(f"승리: {len(wins)}회 ({len(wins)/len(trades)*100:.1f}%)")
        print(f"손실: {len(losses)}회")

        print(f"\n평균 수익: {sum([t['pnl_pct'] for t in trades]) / len(trades):+.2f}%")
        if wins:
            print(f"평균 승리: {sum([t['pnl_pct'] for t in wins]) / len(wins):+.2f}%")
        if losses:
            print(f"평균 손실: {sum([t['pnl_pct'] for t in losses]) / len(losses):+.2f}%")

        print(f"\n최대 승리: {max([t['pnl_pct'] for t in trades]):+.2f}%")
        print(f"최대 손실: {min([t['pnl_pct'] for t in trades]):+.2f}%")

        # 거래 상세
        print("\n" + "="*80)
        print("거래 상세")
        print("="*80)
        for i, trade in enumerate(trades, 1):
            print(f"\n[{i}] {trade['entry_date']} → {trade['exit_date']}")
            print(f"    진입: {trade['entry_price']:,.0f}원 | 청산: {trade['exit_price']:,.0f}원")
            print(f"    수익: {trade['pnl_pct']:+.2f}% | 이유: {trade['reason']}")
            print(f"    신호: {'+'.join(trade['signals'])} (Score={trade['score']:.1f})")
            print(f"    최고가: {trade['highest_price']:,.0f}원")

    # 결과 저장
    result = {
        'version': config['version'],
        'strategy_name': config['strategy_name'],
        'timeframe': config['timeframe'],
        'period': '2024-01-01 ~ 2024-12-31',
        'initial_capital': capital,
        'final_capital': final_capital,
        'total_return_pct': ((final_capital - capital) / capital * 100),
        'total_trades': len(trades),
        'wins': len(wins) if len(trades) > 0 else 0,
        'losses': len(losses) if len(trades) > 0 else 0,
        'win_rate': (len(wins) / len(trades) * 100) if len(trades) > 0 else 0,
        'trades': trades,
        'config': config
    }

    with open('result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n결과가 result.json에 저장되었습니다.")

    return result


if __name__ == '__main__':
    run_backtest()
