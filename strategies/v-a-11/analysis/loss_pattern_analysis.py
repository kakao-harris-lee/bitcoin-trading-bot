#!/usr/bin/env python3
"""
v-a-04 손실 패턴 분석
=====================
2021-2022 Sideways 손실 시그널 상세 분석

목표:
1. 손실 시그널의 진입 조건 분석
2. 변동성 (ATR) 패턴 분석
3. 시장 분류 타이밍 분석
4. Perfect Signals 비교
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import json
import numpy as np
from datetime import datetime, timedelta

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer


def load_signals(year: int) -> list:
    """v-a-04 시그널 로드"""
    signal_path = Path(__file__).parent.parent / 'signals' / f'day_{year}_signals.json'
    with open(signal_path, 'r') as f:
        data = json.load(f)
    return data['signals']


def load_market_data(year: int, db_path: Path) -> pd.DataFrame:
    """시장 데이터 로드 (지표 포함)"""
    with DataLoader(str(db_path)) as loader:
        df = loader.load_timeframe(
            timeframe='day',
            start_date=f'{year}-01-01',
            end_date=f'{year}-12-31'
        )

    # 지표 추가
    df = MarketAnalyzer.add_indicators(
        df,
        indicators=['rsi', 'macd', 'adx', 'atr', 'bb', 'stoch', 'mfi']
    )

    return df


def simulate_trade(signal: dict, df: pd.DataFrame) -> dict:
    """
    시그널 거래 시뮬레이션

    Returns:
        {
            'entry_date': str,
            'entry_price': float,
            'exit_date': str,
            'exit_price': float,
            'exit_reason': str,
            'return': float,
            'hold_days': int,
            'max_profit': float,
            'max_drawdown': float,
            'atr_at_entry': float,
            'volatility_20d': float
        }
    """
    entry_time = pd.Timestamp(signal['timestamp'])
    entry_price = signal['entry_price']
    strategy = signal['strategy']

    # Entry 시점 찾기
    entry_idx = df[df['timestamp'] == entry_time].index[0]

    # Exit 로직 (v37 방식)
    if strategy == 'trend_following':
        tp = 0.10  # 10%
        sl = -0.05  # -5%
        max_hold = 60
    elif strategy == 'sideways':
        tp1, tp2, tp3 = 0.02, 0.04, 0.06
        sl = -0.02
        max_hold = 20
    else:  # defensive
        tp = 0.05
        sl = -0.03
        max_hold = 30

    # Entry 시점 ATR, 변동성
    atr_at_entry = df.iloc[entry_idx]['atr']
    volatility_20d = df.iloc[max(0, entry_idx-20):entry_idx]['close'].std() / df.iloc[entry_idx]['close']

    highest_price = entry_price
    exit_reason = 'UNKNOWN'
    max_profit = 0.0
    max_drawdown = 0.0

    for i in range(entry_idx + 1, min(entry_idx + max_hold + 1, len(df))):
        row = df.iloc[i]
        current_price = row['close']
        profit = (current_price - entry_price) / entry_price

        highest_price = max(highest_price, current_price)
        max_profit = max(max_profit, profit)

        drawdown_from_high = (current_price - highest_price) / highest_price
        max_drawdown = min(max_drawdown, drawdown_from_high)

        # Exit 조건
        if strategy == 'sideways':
            if profit >= tp3:
                exit_reason = 'SIDEWAYS_TP3'
                break
            elif profit >= tp2:
                exit_reason = 'SIDEWAYS_TP2'
                break
            elif profit >= tp1:
                exit_reason = 'SIDEWAYS_TP1'
                break
            elif profit <= sl:
                exit_reason = 'SIDEWAYS_SL'
                break
            elif (highest_price - current_price) / highest_price >= 0.01:
                exit_reason = 'SIDEWAYS_TRAILING'
                break

        elif strategy == 'trend_following':
            # Dead Cross
            prev_row = df.iloc[i-1]
            macd = row['macd']
            macd_signal = row['macd_signal']
            prev_macd = prev_row['macd']
            prev_signal = prev_row['macd_signal']

            dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)

            if dead_cross and profit > 0:
                exit_reason = 'TREND_DEAD_CROSS'
                break
            elif profit >= tp:
                exit_reason = 'TREND_TP'
                break
            elif profit <= sl:
                exit_reason = 'TREND_SL'
                break
            elif (highest_price - current_price) / highest_price >= 0.03:
                exit_reason = 'TREND_TRAILING'
                break

        # Timeout
        if i == entry_idx + max_hold:
            exit_reason = f'{strategy.upper()}_TIMEOUT'
            current_price = row['close']
            break
    else:
        # 데이터 끝
        exit_reason = 'END_OF_DATA'
        current_price = df.iloc[-1]['close']
        i = len(df) - 1

    exit_time = df.iloc[i]['timestamp']
    exit_price = current_price
    final_return = (exit_price - entry_price) / entry_price
    hold_days = (exit_time - entry_time).days

    return {
        'entry_date': entry_time.strftime('%Y-%m-%d'),
        'entry_price': entry_price,
        'exit_date': exit_time.strftime('%Y-%m-%d'),
        'exit_price': exit_price,
        'exit_reason': exit_reason,
        'return': final_return,
        'hold_days': hold_days,
        'max_profit': max_profit,
        'max_drawdown': max_drawdown,
        'atr_at_entry': atr_at_entry,
        'volatility_20d': volatility_20d
    }


def analyze_year(year: int, db_path: Path):
    """연도별 손실 패턴 분석"""
    print(f"\n{'='*70}")
    print(f"  {year}년 손실 패턴 분석")
    print(f"{'='*70}\n")

    # 데이터 로드
    signals = load_signals(year)
    df = load_market_data(year, db_path)

    print(f"총 시그널: {len(signals)}개")

    # 전략별 분류
    sideways_signals = [s for s in signals if s['strategy'] == 'sideways']
    trend_signals = [s for s in signals if s['strategy'] == 'trend_following']

    print(f"  Sideways: {len(sideways_signals)}개")
    print(f"  Trend: {len(trend_signals)}개\n")

    # Sideways 시뮬레이션
    print("Sideways 시그널 분석:")
    print(f"{'날짜':>12s} | {'진입가':>10s} | {'Exit':>18s} | {'수익률':>8s} | {'보유':>5s} | {'ATR':>8s} | {'Vol':>6s}")
    print("-"*80)

    sideways_results = []
    for sig in sideways_signals:
        result = simulate_trade(sig, df)
        sideways_results.append(result)

        print(f"{result['entry_date']:>12s} | {result['entry_price']/1e6:>9.1f}M | "
              f"{result['exit_reason']:>18s} | {result['return']*100:>7.2f}% | "
              f"{result['hold_days']:>4d}일 | {result['atr_at_entry']/1e6:>7.2f}M | "
              f"{result['volatility_20d']*100:>5.2f}%")

    # 통계
    if len(sideways_results) > 0:
        wins = [r for r in sideways_results if r['return'] > 0]
        losses = [r for r in sideways_results if r['return'] <= 0]

        print(f"\n[Sideways 통계]")
        print(f"  승률: {len(wins)}/{len(sideways_results)} ({len(wins)/len(sideways_results)*100:.1f}%)")
        print(f"  평균 수익: {np.mean([r['return'] for r in sideways_results])*100:.2f}%")
        print(f"  평균 익절: {np.mean([r['return'] for r in wins])*100:.2f}%" if wins else "  평균 익절: N/A")
        print(f"  평균 손절: {np.mean([r['return'] for r in losses])*100:.2f}%" if losses else "  평균 손절: N/A")
        print(f"  평균 ATR: {np.mean([r['atr_at_entry'] for r in sideways_results])/1e6:.2f}M")
        print(f"  평균 변동성: {np.mean([r['volatility_20d'] for r in sideways_results])*100:.2f}%")

        # 손실 시그널 상세
        if losses:
            print(f"\n[손실 시그널 상세]")
            for r in losses:
                print(f"  {r['entry_date']}: {r['return']*100:+.2f}% "
                      f"(ATR {r['atr_at_entry']/1e6:.2f}M, Vol {r['volatility_20d']*100:.2f}%, "
                      f"MaxDD {r['max_drawdown']*100:.2f}%)")

    # 결과 저장
    output_dir = Path(__file__).parent
    output_file = output_dir / f'{year}_loss_analysis.json'

    with open(output_file, 'w') as f:
        json.dump({
            'year': year,
            'total_signals': len(signals),
            'sideways_count': len(sideways_signals),
            'sideways_results': sideways_results
        }, f, indent=2)

    print(f"\n✅ 저장: {output_file}")


def main():
    """메인 실행"""
    db_path = Path(__file__).parent.parent.parent.parent / 'upbit_bitcoin.db'

    print("="*70)
    print("  v-a-04 손실 패턴 분석")
    print("="*70)

    # 2021, 2022 분석
    analyze_year(2021, db_path)
    analyze_year(2022, db_path)

    print(f"\n{'='*70}")
    print("  분석 완료!")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
