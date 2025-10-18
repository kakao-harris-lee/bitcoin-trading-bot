#!/usr/bin/env python3
"""
v09 간단한 백테스팅 스크립트

v07 함수 기반 전략을 사용한 단순 백테스팅
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from simple_backtester import SimpleBacktester


def v07_strategy_function(df, i, params):
    """
    v07 전략 함수 (간소화 버전)

    진입: EMA Golden Cross OR MACD Golden Cross
    청산: Trailing Stop OR Stop Loss
    """
    if i < 27:  # 충분한 지표 데이터 필요
        return {'action': 'hold'}

    row = df.iloc[i]
    prev_row = df.iloc[i-1]

    # 현재 포지션 상태 (전역 변수 사용)
    global in_position, entry_price, highest_price

    # 진입 신호 확인
    if not in_position:
        # EMA Golden Cross
        ema_golden = (prev_row['ema12'] <= prev_row['ema26']) and (row['ema12'] > row['ema26'])

        # MACD Golden Cross
        macd_golden = (prev_row['macd'] <= prev_row['macd_signal']) and (row['macd'] > row['macd_signal'])

        if ema_golden or macd_golden:
            in_position = True
            entry_price = row['close']
            highest_price = row['close']
            return {
                'action': 'buy',
                'fraction': params['position_fraction'],
                'reason': 'EMA_GOLDEN' if ema_golden else 'MACD_GOLDEN'
            }

    # 청산 신호 확인
    else:
        current_price = row['close']

        # Highest price 업데이트
        if current_price > highest_price:
            highest_price = current_price

        # Trailing Stop
        trailing_threshold = highest_price * (1 - params['trailing_stop_pct'])
        if current_price <= trailing_threshold:
            in_position = False
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'TRAILING_STOP'
            }

        # Stop Loss
        stop_loss_threshold = entry_price * (1 - params['stop_loss_pct'])
        if current_price <= stop_loss_threshold:
            in_position = False
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'STOP_LOSS'
            }

    return {'action': 'hold'}


# 전역 변수
in_position = False
entry_price = 0.0
highest_price = 0.0


def run_backtest(start_date, end_date, params):
    """백테스팅 실행"""
    global in_position, entry_price, highest_price

    # 초기화
    in_position = False
    entry_price = 0.0
    highest_price = 0.0

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date=start_date, end_date=end_date)

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['macd'])

    # EMA 직접 계산
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()

    # 백테스팅
    backtester = SimpleBacktester(10_000_000, 0.0005, 0.0002)

    for i in range(len(df)):
        row = df.iloc[i]
        decision = v07_strategy_function(df, i, params)

        if decision['action'] == 'buy':
            backtester.execute_buy(row['timestamp'], row['close'], decision['fraction'])
        elif decision['action'] == 'sell':
            backtester.execute_sell(row['timestamp'], row['close'], decision['fraction'])

        backtester.record_equity(row['timestamp'], row['close'])

    # 결과
    results = backtester.get_results()

    # Sharpe Ratio 계산
    returns = results['equity_curve']['returns'].dropna()
    if len(returns) > 0 and returns.std() > 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
    else:
        sharpe = 0

    results['sharpe_ratio'] = sharpe

    return results


if __name__ == '__main__':
    print("="*80)
    print("v09 간단한 백테스팅 테스트")
    print("="*80)

    # 테스트 파라미터
    test_params = {
        'trailing_stop_pct': 0.15,
        'stop_loss_pct': 0.10,
        'position_fraction': 0.95
    }

    print(f"\n학습 기간: 2018-09-04 ~ 2023-12-31")
    print(f"파라미터: {test_params}\n")

    results = run_backtest('2018-09-04', '2023-12-31', test_params)

    print(f"\n{'='*80}")
    print("백테스팅 결과")
    print(f"{'='*80}")
    print(f"수익률: {results['total_return']:.2f}%")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results['max_drawdown']:.2f}%")
    print(f"총 거래: {results['total_trades']}회")
    print(f"승률: {results['win_rate']:.1%}")
    print(f"Profit Factor: {results.get('profit_factor', 0):.2f}")
    print(f"{'='*80}\n")
