#!/usr/bin/env python3
"""
v21 백테스팅 스크립트
"""

import sys
import json
from pathlib import Path
import sqlite3
import pandas as pd
import talib

# 프로젝트 루트 추가
sys.path.append(str(Path(__file__).parent.parent.parent))

from strategy import v21_strategy


def load_data(db_path, timeframe, start_date, end_date=None):
    """데이터 로드"""
    conn = sqlite3.connect(db_path)

    if end_date:
        query = f"""
        SELECT timestamp, opening_price as open, high_price as high,
               low_price as low, trade_price as close,
               candle_acc_trade_volume as volume
        FROM bitcoin_{timeframe}
        WHERE timestamp >= '{start_date}' AND timestamp < '{end_date}'
        ORDER BY timestamp ASC
        """
    else:
        query = f"""
        SELECT timestamp, opening_price as open, high_price as high,
               low_price as low, trade_price as close,
               candle_acc_trade_volume as volume
        FROM bitcoin_{timeframe}
        WHERE timestamp >= '{start_date}'
        ORDER BY timestamp ASC
        """

    df = pd.read_sql_query(query, conn)
    conn.close()

    return df


def add_indicators(df):
    """기술적 지표 추가"""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    # RSI
    df['rsi'] = talib.RSI(close, timeperiod=14)

    # Bollinger Bands
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    df['bb_upper'] = upper
    df['bb_middle'] = middle
    df['bb_lower'] = lower
    df['bb_position'] = (close - lower) / (upper - lower)

    # MACD
    macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df['macd'] = macd
    df['macd_signal'] = signal
    df['macd_hist'] = hist

    # ADX
    df['adx'] = talib.ADX(high, low, close, timeperiod=14)

    # Volume Ratio
    df['volume_sma'] = talib.SMA(volume, timeperiod=20)
    df['volume_ratio'] = volume / df['volume_sma']

    # Stochastic
    slowk, slowd = talib.STOCH(high, low, close,
                                fastk_period=14, slowk_period=3, slowd_period=3)
    df['stoch_k'] = slowk
    df['stoch_d'] = slowd

    return df


def run_backtest(df, config):
    """백테스팅 실행"""
    initial_capital = config['risk_management']['initial_capital']
    fee_rate = config['trading_settings']['fee_rate']

    capital = initial_capital
    position = 0  # BTC 보유량
    entry_price = 0
    trades = []

    for i in range(26, len(df)):
        signal = v21_strategy(df, i, config)

        if signal['action'] == 'buy' and position == 0:
            # 매수
            price = df.iloc[i]['close']
            fee = capital * fee_rate
            position = (capital - fee) / price
            entry_price = price
            capital = 0

            trades.append({
                'type': 'buy',
                'timestamp': df.iloc[i]['timestamp'],
                'price': price,
                'amount': position,
                'capital': 0
            })

        elif signal['action'] == 'sell' and position > 0:
            # 매도
            price = df.iloc[i]['close']
            capital = position * price
            fee = capital * fee_rate
            capital -= fee

            profit_pct = ((price - entry_price) / entry_price) * 100

            trades.append({
                'type': 'sell',
                'timestamp': df.iloc[i]['timestamp'],
                'price': price,
                'amount': position,
                'capital': capital,
                'profit_pct': profit_pct
            })

            position = 0
            entry_price = 0

    # 마지막 포지션 정리
    if position > 0:
        price = df.iloc[-1]['close']
        capital = position * price
        fee = capital * fee_rate
        capital -= fee

        profit_pct = ((price - entry_price) / entry_price) * 100

        trades.append({
            'type': 'sell',
            'timestamp': df.iloc[-1]['timestamp'],
            'price': price,
            'amount': position,
            'capital': capital,
            'profit_pct': profit_pct
        })

    # 성과 계산
    total_return = ((capital - initial_capital) / initial_capital) * 100
    num_trades = len([t for t in trades if t['type'] == 'buy'])

    winning_trades = [t for t in trades if t['type'] == 'sell' and t['profit_pct'] > 0]
    win_rate = len(winning_trades) / num_trades if num_trades > 0 else 0

    avg_profit = sum(t['profit_pct'] for t in trades if t['type'] == 'sell') / num_trades if num_trades > 0 else 0

    # Sharpe Ratio 근사
    if num_trades > 1:
        returns = [t['profit_pct'] for t in trades if t['type'] == 'sell']
        sharpe_ratio = (sum(returns) / len(returns)) / (pd.Series(returns).std()) if pd.Series(returns).std() > 0 else 0
    else:
        sharpe_ratio = 0.0

    return {
        'initial_capital': initial_capital,
        'final_capital': capital,
        'total_return': total_return,
        'num_trades': num_trades,
        'win_rate': win_rate,
        'avg_profit': avg_profit,
        'sharpe_ratio': sharpe_ratio,
        'trades': trades
    }


def main():
    """메인 실행"""
    # Config 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # DB 경로
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'

    print(f"\n{'='*80}")
    print(f"v21 백테스팅: {config['description']}")
    print(f"{'='*80}")

    # 훈련 기간 백테스팅
    print(f"\n📊 훈련 기간: {config['backtest_period']['train_start']} ~ {config['backtest_period']['train_end']}")

    df_train = load_data(db_path, config['timeframe'],
                         config['backtest_period']['train_start'],
                         config['backtest_period']['test_start'])

    df_train = add_indicators(df_train)

    print(f"캔들 개수: {len(df_train)}")

    results_train = run_backtest(df_train, config)

    print(f"\n결과:")
    print(f"  초기 자본: {results_train['initial_capital']:,.0f}원")
    print(f"  최종 자본: {results_train['final_capital']:,.0f}원")
    print(f"  총 수익률: {results_train['total_return']:.2f}%")
    print(f"  거래 횟수: {results_train['num_trades']}")
    print(f"  승률: {results_train['win_rate']*100:.1f}%")
    print(f"  평균 수익: {results_train['avg_profit']:.2f}%")
    print(f"  Sharpe Ratio: {results_train['sharpe_ratio']:.2f}")

    # 테스트 기간 백테스팅 (Out-of-Sample)
    print(f"\n📊 테스트 기간 (Out-of-Sample): {config['backtest_period']['test_start']} ~ {config['backtest_period']['test_end']}")

    df_test = load_data(db_path, config['timeframe'],
                        config['backtest_period']['test_start'],
                        config['backtest_period']['test_end'])

    if len(df_test) > 0:
        df_test = add_indicators(df_test)

        print(f"캔들 개수: {len(df_test)}")

        results_test = run_backtest(df_test, config)

        print(f"\n결과:")
        print(f"  초기 자본: {results_test['initial_capital']:,.0f}원")
        print(f"  최종 자본: {results_test['final_capital']:,.0f}원")
        print(f"  총 수익률: {results_test['total_return']:.2f}%")
        print(f"  거래 횟수: {results_test['num_trades']}")
        print(f"  승률: {results_test['win_rate']*100:.1f}%")
        print(f"  평균 수익: {results_test['avg_profit']:.2f}%")
        print(f"  Sharpe Ratio: {results_test['sharpe_ratio']:.2f}")
    else:
        print("  데이터 없음")
        results_test = None

    # 결과 저장
    output = {
        'version': config['version'],
        'strategy_name': config['strategy_name'],
        'timeframe': config['timeframe'],
        'train_period': {
            'start': config['backtest_period']['train_start'],
            'end': config['backtest_period']['train_end'],
            'results': results_train
        },
        'test_period': {
            'start': config['backtest_period']['test_start'],
            'end': config['backtest_period']['test_end'],
            'results': results_test
        }
    }

    output_path = Path(__file__).parent / 'backtest_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✅ 결과 저장: {output_path}")

    # 목표 달성 여부
    print(f"\n{'='*80}")
    print("목표 달성 여부")
    print(f"{'='*80}")

    target_return = 79.75  # 4년 평균 목표
    buyhold_return = 147.52  # 4년 Buy&Hold (day)

    # 3년 평균 수익률 계산
    avg_3year_return = results_train['total_return'] / 3

    print(f"\n연평균 수익률: {avg_3year_return:.2f}%")
    print(f"목표 (79.75%): {'✅ 달성' if avg_3year_return >= target_return else '❌ 미달성'}")
    print(f"Buy&Hold 대비: {avg_3year_return - (buyhold_return/3):.2f}%p")


if __name__ == '__main__':
    main()
