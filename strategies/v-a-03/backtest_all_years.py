#!/usr/bin/env python3
"""v-a-03: Dynamic Exit + Market Filter (2020-2025)"""
import sys, json
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import pandas as pd
from datetime import timedelta
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# Dynamic Exit
EXIT_PERIODS = [(1,0.02,-0.01), (3,0.05,-0.02), (5,0.08,-0.03),
                (7,0.12,-0.04), (14,0.20,-0.06), (30,0.40,-0.10)]

def classify_market(row):
    """간단한 3-Level 분류"""
    if row['rsi']>60 and row['mfi']>60: return 'BULL'
    if row['rsi']<40 or row['mfi']<40: return 'BEAR'
    return 'SIDEWAYS'

def generate_signals(df):
    """Entry: RSI 50-65, MFI 50-60 + Market BULL"""
    sigs = []
    for i in range(len(df)):
        r = df.iloc[i]
        market = classify_market(r)
        if 50<=r['rsi']<=65 and 50<=r['mfi']<=60 and 0.9<=r['volume_ratio']<=1.3 and market=='BULL':
            sigs.append({'timestamp':r['timestamp'], 'entry_price':r['close']})
    return pd.DataFrame(sigs)

def backtest_dynamic(sigs, price_data):
    """Dynamic Exit 백테스팅"""
    price_data = price_data.set_index('timestamp') if 'timestamp' in price_data.columns else price_data
    trades = []
    for _, s in sigs.iterrows():
        entry_time, entry_price = s['timestamp'], s['entry_price']

        # 각 기간 체크
        for days, tp, sl in EXIT_PERIODS:
            exit_time = entry_time + timedelta(days=days)
            exit_data = price_data[price_data.index >= exit_time]
            if len(exit_data) == 0: continue

            exit_price = exit_data.iloc[0]['close']
            ret_pct = (exit_price - entry_price) / entry_price

            # 익절/손절 체크
            if ret_pct >= tp or ret_pct <= sl:
                trades.append({'return_pct': ret_pct, 'hold_days': days,
                              'exit_reason': 'TP' if ret_pct>=tp else 'SL'})
                break
        else:
            # 30일까지 도달
            exit_time = entry_time + timedelta(days=30)
            exit_data = price_data[price_data.index >= exit_time]
            if len(exit_data) > 0:
                exit_price = exit_data.iloc[0]['close']
                trades.append({'return_pct': (exit_price-entry_price)/entry_price,
                              'hold_days': 30, 'exit_reason': 'TIMEOUT'})

    if not trades: return {'total_return': 0, 'win_rate': 0, 'trades': 0}
    trades_df = pd.DataFrame(trades)
    return {
        'total_return': trades_df['return_pct'].sum(),
        'win_rate': (trades_df['return_pct'] > 0).sum() / len(trades),
        'trades': len(trades),
        'avg_hold': trades_df['hold_days'].mean()
    }

print("v-a-03: Dynamic Exit + Market Filter")
print("="*60)

db = DataLoader(str(Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'))
results = {}

for year in [2020, 2021, 2022, 2023, 2024, 2025]:
    print(f"\n[{year}]", end=" ")

    # 완벽한 시그널
    try:
        perfect = pd.read_csv(Path(__file__).parent.parent / 'v41_scalping_voting/analysis/perfect_signals' /
                             f'day_{year}_perfect.csv', parse_dates=['timestamp'])
        print(f"Perfect: {len(perfect)}개", end=" ")
    except:
        print("⚠️  No perfect signals")
        continue

    # 시장 데이터
    df = db.load_timeframe('day', f'{year}-01-01', f'{year}-12-31')
    df = MarketAnalyzer.add_indicators(df, ['rsi', 'mfi'])
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
    df = df.dropna()

    # 시그널 & 백테스팅
    sigs = generate_signals(df)
    bt = backtest_dynamic(sigs, df)

    # 재현율
    if len(sigs) > 0:
        matched = sum(1 for s in sigs['timestamp'] if any(abs((s-p).total_seconds())<86400 for p in perfect['timestamp']))
        repro = matched / len(perfect) if len(perfect) > 0 else 0
    else:
        matched, repro = 0, 0

    results[year] = {
        'return': bt['total_return'], 'trades': bt['trades'], 'win_rate': bt['win_rate'],
        'signal_repro': repro, 'signals': len(sigs), 'avg_hold': bt.get('avg_hold', 0)
    }

    print(f"| 수익: {bt['total_return']:>7.2%}, 거래: {bt['trades']}회, 재현율: {repro:>6.2%}, 평균보유: {bt.get('avg_hold',0):.1f}일")

print(f"\n{'='*60}")
print("v-a-01/02/03 비교:")
print("="*60)

# 로드
va01 = json.load(open(Path(__file__).parent.parent / 'v-a-01/results/all_years_summary.json'))
va02 = json.load(open(Path(__file__).parent.parent / 'v-a-02/results/all_years_summary.json'))

for year in [2020, 2021, 2022, 2023, 2024]:
    if year in results:
        v1 = va01[str(year)]
        v2 = va02[str(year)]
        v3 = results[year]
        print(f"{year}: v1 {v1['return']:>7.2%} ({v1['reproduction_rate']:>5.2%}) | "
              f"v2 {v2['return']:>7.2%} ({v2['signal_repro']:>5.2%}) | "
              f"v3 {v3['return']:>7.2%} ({v3['signal_repro']:>5.2%})")

# 저장
out = Path(__file__).parent / 'results/all_years_summary.json'
with open(out, 'w') as f:
    json.dump(results, f, indent=2, default=float)
print(f"\n✅ {out}")
