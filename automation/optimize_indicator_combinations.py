#!/usr/bin/env python3
"""
Phase 1-5: 다중 지표 조합 최적화 (Genetic Algorithm)
최적의 진입/청산 조건을 유전 알고리즘으로 탐색
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import json
import talib
from deap import base, creator, tools, algorithms
import random
import multiprocessing


def calculate_indicators(df):
    """기술적 지표 계산"""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    df['rsi'] = talib.RSI(close, timeperiod=14)
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    df['bb_upper'] = upper
    df['bb_middle'] = middle
    df['bb_lower'] = lower
    df['bb_position'] = (close - lower) / (upper - lower)

    macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    df['macd'] = macd
    df['macd_signal'] = signal
    df['macd_hist'] = hist

    df['adx'] = talib.ADX(high, low, close, timeperiod=14)
    df['volume_sma'] = talib.SMA(volume, timeperiod=20)
    df['volume_ratio'] = volume / df['volume_sma']

    slowk, slowd = talib.STOCH(high, low, close, fastk_period=14, slowk_period=3, slowd_period=3)
    df['stoch_k'] = slowk
    df['stoch_d'] = slowd

    return df


def load_full_data(db_path, timeframe, years=[2022, 2023, 2024]):
    """여러 연도 데이터 로드"""
    conn = sqlite3.connect(db_path)

    dfs = []
    for year in years:
        query = f"""
        SELECT timestamp, opening_price as open, high_price as high,
               low_price as low, trade_price as close,
               candle_acc_trade_volume as volume
        FROM bitcoin_{timeframe}
        WHERE timestamp >= '{year}-01-01' AND timestamp < '{year+1}-01-01'
        ORDER BY timestamp ASC
        """
        df = pd.read_sql_query(query, conn)
        if len(df) > 0:
            dfs.append(df)

    conn.close()

    if not dfs:
        return None

    df = pd.concat(dfs, ignore_index=True)
    df = calculate_indicators(df)

    return df


def backtest_strategy(df, entry_params, exit_params, initial_capital=10_000_000):
    """
    백테스팅 실행

    Args:
        df: 데이터프레임
        entry_params: [rsi_threshold, bb_threshold, volume_threshold, stoch_threshold, adx_threshold]
        exit_params: [rsi_threshold, bb_threshold, stoch_threshold]

    Returns:
        dict: 성과 지표
    """
    capital = initial_capital
    position = 0  # 보유 BTC 수량
    entry_price = 0
    trades = []

    entry_rsi, entry_bb, entry_vol, entry_stoch, entry_adx = entry_params
    exit_rsi, exit_bb, exit_stoch = exit_params

    for i in range(26, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]

        # 데이터 유효성 검사
        if any(pd.isna([row['rsi'], row['bb_position'], row['volume_ratio'],
                        row['stoch_k'], row['adx']])):
            continue

        # 진입 조건
        if position == 0:
            entry_signal = (
                row['rsi'] < entry_rsi and
                row['bb_position'] < entry_bb and
                row['volume_ratio'] > entry_vol and
                row['stoch_k'] < entry_stoch and
                row['adx'] > entry_adx
            )

            if entry_signal:
                # 전액 매수
                position = capital / row['close']
                entry_price = row['close']
                capital = 0

        # 청산 조건
        elif position > 0:
            # Stochastic Dead Cross
            stoch_dead_cross = (prev_row['stoch_k'] >= prev_row['stoch_d'] and
                               row['stoch_k'] < row['stoch_d'])

            exit_signal = (
                row['bb_position'] > exit_bb and
                stoch_dead_cross and
                row['rsi'] > exit_rsi
            ) or (
                # 간단한 청산 조건 (BB만)
                row['bb_position'] > exit_bb and
                row['stoch_k'] > exit_stoch
            )

            if exit_signal:
                # 전액 매도
                exit_price = row['close']
                capital = position * exit_price
                profit_pct = ((exit_price - entry_price) / entry_price) * 100

                trades.append({
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit_pct': profit_pct
                })

                position = 0
                entry_price = 0

    # 마지막 포지션 청산
    if position > 0:
        capital = position * df.iloc[-1]['close']
        profit_pct = ((df.iloc[-1]['close'] - entry_price) / entry_price) * 100
        trades.append({
            'entry_price': entry_price,
            'exit_price': df.iloc[-1]['close'],
            'profit_pct': profit_pct
        })

    # 성과 계산
    if len(trades) == 0:
        return {
            'total_return': 0.0,
            'win_rate': 0.0,
            'avg_profit': 0.0,
            'num_trades': 0,
            'sharpe_ratio': 0.0,
            'fitness': 0.0
        }

    total_return = ((capital - initial_capital) / initial_capital) * 100
    winning_trades = [t for t in trades if t['profit_pct'] > 0]
    win_rate = len(winning_trades) / len(trades)
    avg_profit = np.mean([t['profit_pct'] for t in trades])

    # Sharpe Ratio 근사 (수익률 / 변동성)
    returns = [t['profit_pct'] for t in trades]
    sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0

    # Fitness: 가중 합산 (총 수익률 60%, 승률 20%, Sharpe 20%)
    fitness = (total_return * 0.6 +
               win_rate * 100 * 0.2 +
               sharpe_ratio * 10 * 0.2)

    return {
        'total_return': total_return,
        'win_rate': win_rate,
        'avg_profit': avg_profit,
        'num_trades': len(trades),
        'sharpe_ratio': sharpe_ratio,
        'fitness': fitness
    }


# DEAP 설정
creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", list, fitness=creator.FitnessMax)

toolbox = base.Toolbox()

# 유전자 정의
# Entry: [rsi_threshold, bb_threshold, volume_threshold, stoch_threshold, adx_threshold]
# Exit: [rsi_threshold, bb_threshold, stoch_threshold]
toolbox.register("attr_entry_rsi", random.randint, 15, 40)
toolbox.register("attr_entry_bb", random.uniform, 0.0, 0.3)
toolbox.register("attr_entry_vol", random.uniform, 1.0, 3.0)
toolbox.register("attr_entry_stoch", random.randint, 10, 30)
toolbox.register("attr_entry_adx", random.randint, 15, 50)

toolbox.register("attr_exit_rsi", random.randint, 55, 80)
toolbox.register("attr_exit_bb", random.uniform, 0.7, 1.0)
toolbox.register("attr_exit_stoch", random.randint, 80, 95)

# 개체 생성
toolbox.register("individual", tools.initCycle, creator.Individual,
                 (toolbox.attr_entry_rsi, toolbox.attr_entry_bb, toolbox.attr_entry_vol,
                  toolbox.attr_entry_stoch, toolbox.attr_entry_adx,
                  toolbox.attr_exit_rsi, toolbox.attr_exit_bb, toolbox.attr_exit_stoch), n=1)

toolbox.register("population", tools.initRepeat, list, toolbox.individual)


def evaluate(individual, df):
    """개체 평가 함수"""
    entry_params = individual[:5]
    exit_params = individual[5:]

    result = backtest_strategy(df, entry_params, exit_params)

    return (result['fitness'],)


def run_genetic_algorithm(df, timeframe, generations=50, population_size=100):
    """
    유전 알고리즘 실행

    Args:
        df: 데이터프레임
        timeframe: 타임프레임
        generations: 세대 수
        population_size: 개체 수

    Returns:
        dict: 최적 파라미터 및 성과
    """
    print(f"\n{'='*80}")
    print(f"유전 알고리즘 최적화 시작: {timeframe}")
    print(f"세대 수: {generations}, 개체 수: {population_size}")
    print(f"{'='*80}")

    # 평가 함수 등록
    toolbox.register("evaluate", evaluate, df=df)
    toolbox.register("mate", tools.cxTwoPoint)
    toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=1, indpb=0.2)
    toolbox.register("select", tools.selTournament, tournsize=3)

    # 초기 개체군 생성
    pop = toolbox.population(n=population_size)

    # 통계
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("avg", np.mean)
    stats.register("max", np.max)
    stats.register("min", np.min)

    # 진화 실행
    pop, logbook = algorithms.eaSimple(pop, toolbox,
                                        cxpb=0.7,  # 교차 확률
                                        mutpb=0.2,  # 돌연변이 확률
                                        ngen=generations,
                                        stats=stats,
                                        verbose=True)

    # 최적 개체 선택
    best_ind = tools.selBest(pop, 1)[0]

    entry_params = best_ind[:5]
    exit_params = best_ind[5:]

    # 최종 성과 계산
    final_result = backtest_strategy(df, entry_params, exit_params)

    print(f"\n{'='*80}")
    print(f"최적화 완료!")
    print(f"{'='*80}")
    print(f"최적 진입 조건:")
    print(f"  RSI < {entry_params[0]}")
    print(f"  BB Position < {entry_params[1]:.3f}")
    print(f"  Volume Ratio > {entry_params[2]:.2f}")
    print(f"  Stochastic K < {entry_params[3]}")
    print(f"  ADX > {entry_params[4]}")
    print(f"\n최적 청산 조건:")
    print(f"  RSI > {exit_params[0]}")
    print(f"  BB Position > {exit_params[1]:.3f}")
    print(f"  Stochastic K > {exit_params[2]}")
    print(f"\n성과:")
    print(f"  총 수익률: {final_result['total_return']:.2f}%")
    print(f"  승률: {final_result['win_rate']*100:.1f}%")
    print(f"  평균 수익: {final_result['avg_profit']:.2f}%")
    print(f"  거래 횟수: {final_result['num_trades']}")
    print(f"  Sharpe Ratio: {final_result['sharpe_ratio']:.2f}")
    print(f"  Fitness: {final_result['fitness']:.2f}")

    return {
        'timeframe': timeframe,
        'entry_params': {
            'rsi_threshold': entry_params[0],
            'bb_threshold': float(entry_params[1]),
            'volume_threshold': float(entry_params[2]),
            'stoch_threshold': entry_params[3],
            'adx_threshold': entry_params[4]
        },
        'exit_params': {
            'rsi_threshold': exit_params[0],
            'bb_threshold': float(exit_params[1]),
            'stoch_threshold': exit_params[2]
        },
        'performance': final_result,
        'logbook': str(logbook)
    }


def main():
    """메인 실행"""
    db_path = Path(__file__).parent.parent / 'upbit_bitcoin.db'

    # Day와 Minute240만 최적화 (성능이 좋은 타임프레임)
    timeframes = ['day', 'minute240']

    all_results = {}

    for tf in timeframes:
        print(f"\n{'='*80}")
        print(f"타임프레임: {tf} 데이터 로드 중...")
        print(f"{'='*80}")

        df = load_full_data(db_path, tf, years=[2022, 2023, 2024])

        if df is None or len(df) == 0:
            print(f"  ⚠️  데이터 없음")
            continue

        print(f"  ✅ 캔들 개수: {len(df)}")

        # 유전 알고리즘 실행
        result = run_genetic_algorithm(df, tf, generations=30, population_size=50)

        all_results[tf] = result

    # 결과 저장
    output_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'optimized_parameters.json'

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n\n✅ 최적화 결과 저장: {output_path}")

    # 종합 요약
    print(f"\n{'='*80}")
    print("종합 요약")
    print(f"{'='*80}")

    for tf, result in all_results.items():
        perf = result['performance']
        print(f"\n{tf}:")
        print(f"  총 수익률: {perf['total_return']:.2f}%")
        print(f"  승률: {perf['win_rate']*100:.1f}%")
        print(f"  거래 횟수: {perf['num_trades']}")
        print(f"  Sharpe Ratio: {perf['sharpe_ratio']:.2f}")


if __name__ == '__main__':
    # 멀티프로세싱 지원
    multiprocessing.freeze_support()
    main()
