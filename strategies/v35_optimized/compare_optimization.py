#!/usr/bin/env python3
"""
Optuna 최적화 전후 비교 분석
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V35OptimizedStrategy
import pandas as pd
import numpy as np
import json
from datetime import datetime


def run_backtest_single(year: str, config: dict):
    """단일 연도 백테스팅"""
    with DataLoader('../../upbit_bitcoin.db') as loader:
        if year == '2025':
            df = loader.load_timeframe('day', start_date=f'{year}-01-01')
        else:
            df = loader.load_timeframe('day', start_date=f'{year}-01-01', end_date=f'{year}-12-31')
    
    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=[
        'rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch'
    ])
    
    # 전략 실행
    strategy = V35OptimizedStrategy(config)
    
    initial_capital = 10_000_000
    capital = initial_capital
    position = 0.0
    trades = []
    
    for i in range(30, len(df)):
        signal = strategy.execute(df, i)
        row = df.iloc[i]
        
        # Buy
        if signal['action'] == 'buy' and position == 0:
            fraction = signal.get('fraction', 0.5)
            buy_amount = capital * fraction
            buy_price = row['close'] * 1.0002
            fee = buy_amount * 0.0005
            shares = (buy_amount - fee) / buy_price
            
            if buy_amount >= 5000:
                position = shares
                capital -= buy_amount
                
                trades.append({
                    'type': 'buy',
                    'price': buy_price,
                    'amount': buy_amount,
                    'shares': shares,
                    'date': row.name
                })
        
        # Sell
        elif signal['action'] == 'sell' and position > 0:
            sell_fraction = signal.get('fraction', 1.0)
            shares_to_sell = position * sell_fraction
            sell_price = row['close'] * 0.9998
            sell_amount = shares_to_sell * sell_price
            fee = sell_amount * 0.0005
            
            capital += (sell_amount - fee)
            position -= shares_to_sell
            
            trades.append({
                'type': 'sell',
                'price': sell_price,
                'amount': sell_amount,
                'shares': shares_to_sell,
                'date': row.name
            })
    
    # 최종 청산
    if position > 0:
        final_price = df.iloc[-1]['close'] * 0.9998
        final_amount = position * final_price
        fee = final_amount * 0.0005
        capital += (final_amount - fee)
        position = 0
    
    final_capital = capital
    total_return = (final_capital - initial_capital) / initial_capital * 100
    
    # Buy & Hold
    first_price = df.iloc[30]['close']
    last_price = df.iloc[-1]['close']
    bnh_return = (last_price - first_price) / first_price * 100
    
    # 거래 분석
    buy_trades = [t for t in trades if t['type'] == 'buy']
    sell_trades = [t for t in trades if t['type'] == 'sell']
    
    wins = 0
    losses = 0
    for i in range(min(len(buy_trades), len(sell_trades))):
        if sell_trades[i]['price'] > buy_trades[i]['price']:
            wins += 1
        else:
            losses += 1
    
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    return {
        'total_return': total_return,
        'buy_hold_return': bnh_return,
        'excess_return': total_return - bnh_return,
        'final_capital': final_capital,
        'total_trades': total_trades,
        'win_rate': win_rate
    }


def compare_configs():
    """최적화 전후 비교"""
    
    # Config 로드
    with open('config.json', 'r', encoding='utf-8') as f:
        config_before = json.load(f)
    
    with open('config_optimized.json', 'r', encoding='utf-8') as f:
        config_after = json.load(f)
    
    # Config 병합
    def merge_config(config):
        merged = {}
        for key, value in config.items():
            if isinstance(value, dict):
                merged.update(value)
            else:
                merged[key] = value
        return merged
    
    config_before_merged = merge_config(config_before)
    config_after_merged = merge_config(config_after)
    
    print("="*80)
    print("  v35 Optuna 최적화 전후 비교 분석 (2020~2025)")
    print("="*80)
    
    years = ['2020', '2021', '2022', '2023', '2024', '2025']
    
    results_before = {}
    results_after = {}
    
    # 최적화 전
    print("\n[최적화 전 백테스팅 (config.json)]")
    for year in years:
        print(f"  {year}년 실행 중...", end='', flush=True)
        results_before[year] = run_backtest_single(year, config_before_merged)
        print(f" 완료 ({results_before[year]['total_return']:+.2f}%)")
    
    # 최적화 후
    print("\n[최적화 후 백테스팅 (config_optimized.json)]")
    for year in years:
        print(f"  {year}년 실행 중...", end='', flush=True)
        results_after[year] = run_backtest_single(year, config_after_merged)
        print(f" 완료 ({results_after[year]['total_return']:+.2f}%)")
    
    # 비교 테이블
    print(f"\n{'='*80}")
    print(f"  연도별 비교")
    print(f"{'='*80}")
    print(f"\n{'연도':^6s} | {'최적화 전':^10s} | {'최적화 후':^10s} | {'개선':^10s} | {'거래(전)':^8s} | {'거래(후)':^8s} | {'승률(전)':^8s} | {'승률(후)':^8s}")
    print(f"{'-'*6}|{'-'*12}|{'-'*12}|{'-'*12}|{'-'*10}|{'-'*10}|{'-'*10}|{'-'*10}")
    
    for year in years:
        before = results_before[year]
        after = results_after[year]
        improvement = after['total_return'] - before['total_return']
        
        print(f"{year:^6s} | {before['total_return']:>9.2f}% | {after['total_return']:>9.2f}% | "
              f"{improvement:>+9.2f}%p | {before['total_trades']:>7d}회 | {after['total_trades']:>7d}회 | "
              f"{before['win_rate']:>7.1f}% | {after['win_rate']:>7.1f}%")
    
    # 누적 수익률 계산
    cumulative_before = 1.0
    cumulative_after = 1.0
    
    for year in years:
        cumulative_before *= (1 + results_before[year]['total_return'] / 100)
        cumulative_after *= (1 + results_after[year]['total_return'] / 100)
    
    cumulative_return_before = (cumulative_before - 1) * 100
    cumulative_return_after = (cumulative_after - 1) * 100
    
    # CAGR 계산 (2020~2025, 6년)
    years_count = len(years)
    cagr_before = (cumulative_before ** (1/years_count) - 1) * 100
    cagr_after = (cumulative_after ** (1/years_count) - 1) * 100
    
    print(f"\n{'='*80}")
    print(f"  누적 성과 (2020~2025)")
    print(f"{'='*80}")
    print(f"\n{'지표':^20s} | {'최적화 전':^15s} | {'최적화 후':^15s} | {'개선':^12s}")
    print(f"{'-'*20}|{'-'*17}|{'-'*17}|{'-'*14}")
    print(f"{'누적 수익률':^20s} | {cumulative_return_before:>14.2f}% | {cumulative_return_after:>14.2f}% | {cumulative_return_after - cumulative_return_before:>+11.2f}%p")
    print(f"{'CAGR (연평균)':^20s} | {cagr_before:>14.2f}% | {cagr_after:>14.2f}% | {cagr_after - cagr_before:>+11.2f}%p")
    
    # 결과 저장
    output = {
        'comparison_date': datetime.now().isoformat(),
        'before': results_before,
        'after': results_after,
        'cumulative': {
            'before': cumulative_return_before,
            'after': cumulative_return_after,
            'improvement': cumulative_return_after - cumulative_return_before
        },
        'cagr': {
            'before': cagr_before,
            'after': cagr_after,
            'improvement': cagr_after - cagr_before
        }
    }
    
    with open('optimization_comparison.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n결과 저장: optimization_comparison.json")
    print(f"\n{'='*80}")
    print(f"✅ 비교 분석 완료!")
    print(f"{'='*80}")


if __name__ == '__main__':
    compare_configs()
