#!/usr/bin/env python3
"""v-a-01 연도별 백테스팅 (2020-2025)"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import json
import pandas as pd
from datetime import timedelta
from utils.perfect_signal_loader import PerfectSignalLoader
from utils.reproduction_calculator import ReproductionCalculator
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """RSI+MFI 시그널 생성"""
    signals = []
    for i in range(len(df)):
        row = df.iloc[i]
        if row['rsi'] <= 50 and row['mfi'] <= 50 and row['volume_ratio'] >= 1.2:
            signals.append({'timestamp': row['timestamp'], 'entry_price': row['close']})
    return pd.DataFrame(signals)

def simple_backtest(signals: pd.DataFrame, price_data: pd.DataFrame, hold_days=30) -> dict:
    """단순 백테스팅"""
    price_data = price_data.set_index('timestamp') if 'timestamp' in price_data.columns else price_data
    trades = []

    for _, sig in signals.iterrows():
        exit_time = sig['timestamp'] + timedelta(days=hold_days)
        exit_data = price_data[price_data.index >= exit_time]
        if len(exit_data) == 0:
            continue

        entry_price, exit_price = sig['entry_price'], exit_data.iloc[0]['close']
        return_pct = (exit_price - entry_price) / entry_price
        trades.append({'return_pct': return_pct})

    if not trades:
        return {'total_return': 0, 'win_rate': 0, 'trades': 0}

    trades_df = pd.DataFrame(trades)
    return {
        'total_return': trades_df['return_pct'].sum(),
        'win_rate': (trades_df['return_pct'] > 0).sum() / len(trades),
        'trades': len(trades)
    }

print("v-a-01 연도별 백테스팅 (2020-2025)")
print("="*60)

loader, db_path = PerfectSignalLoader(), Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'
data_loader = DataLoader(str(db_path))
results_all = {}

for year in [2020, 2021, 2022, 2023, 2024, 2025]:
    print(f"\n[{year}]")

    # 완벽한 시그널
    try:
        perfect = loader.load_perfect_signals('day', year)
        perfect_stats = loader.analyze_perfect_signals(perfect)
        print(f"  Perfect: {len(perfect)}개, 평균 {perfect_stats['avg_return']:.2%}")
    except:
        print(f"  ⚠️  No perfect signals")
        continue

    # 시장 데이터
    df = data_loader.load_timeframe('day', f'{year}-01-01', f'{year}-12-31')
    df = MarketAnalyzer.add_indicators(df, ['rsi', 'mfi'])
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
    df = df.dropna()

    # 시그널 생성 & 백테스팅
    signals = generate_signals(df)
    bt = simple_backtest(signals, df)

    # 재현율
    calc = ReproductionCalculator()
    repro = calc.calculate_reproduction_rate(signals, perfect, bt['total_return'],
                                              perfect_stats['avg_return'] * len(perfect))

    results_all[year] = {
        'return': bt['total_return'], 'trades': bt['trades'], 'win_rate': bt['win_rate'],
        'reproduction_rate': repro['total_reproduction_rate'], 'tier': repro['tier']
    }

    print(f"  수익률: {bt['total_return']:.2%}, 거래: {bt['trades']}회, 재현율: {repro['total_reproduction_rate']:.2%} ({repro['tier']})")

print(f"\n{'='*60}")
print("연도별 요약:")
for year, res in results_all.items():
    print(f"{year}: {res['return']:>7.2%} (재현율 {res['reproduction_rate']:>6.2%}, {res['tier']})")

# 저장
output = Path(__file__).parent / 'results' / 'all_years_summary.json'
with open(output, 'w') as f:
    json.dump(results_all, f, indent=2, default=float)
print(f"\n✅ 저장: {output}")
