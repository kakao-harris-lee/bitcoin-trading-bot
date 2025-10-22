#!/usr/bin/env python3
"""v-a-02: 데이터 기반 최적화 백테스트 (2020-2025)"""
import sys, json
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import pandas as pd
from datetime import timedelta
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# v-a-02 최적화된 파라미터 (완벽한 시그널 패턴 기반)
def generate_optimized_signals(df):
    """RSI(50-65) + MFI(50-60) + Vol(0.9-1.3)"""
    sigs = []
    for i in range(len(df)):
        r = df.iloc[i]
        if 50 <= r['rsi'] <= 65 and 50 <= r['mfi'] <= 60 and 0.9 <= r['volume_ratio'] <= 1.3:
            sigs.append({'timestamp': r['timestamp'], 'entry_price': r['close']})
    return pd.DataFrame(sigs)

def backtest(sigs, price_data, hold_days=30):
    """백테스팅"""
    price_data = price_data.set_index('timestamp') if 'timestamp' in price_data.columns else price_data
    trades = []
    for _, s in sigs.iterrows():
        exit_time = s['timestamp'] + timedelta(days=hold_days)
        exit_data = price_data[price_data.index >= exit_time]
        if len(exit_data) == 0: continue
        entry_price, exit_price = s['entry_price'], exit_data.iloc[0]['close']
        trades.append({'return_pct': (exit_price - entry_price) / entry_price})

    if not trades: return {'total_return': 0, 'win_rate': 0, 'trades': 0}
    trades_df = pd.DataFrame(trades)
    return {
        'total_return': trades_df['return_pct'].sum(),
        'win_rate': (trades_df['return_pct'] > 0).sum() / len(trades),
        'trades': len(trades)
    }

print("v-a-02 연도별 백테스팅 (최적화)")
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

    # 시장 데이터 & 시그널
    df = db.load_timeframe('day', f'{year}-01-01', f'{year}-12-31')
    df = MarketAnalyzer.add_indicators(df, ['rsi', 'mfi'])
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
    df = df.dropna()

    sigs = generate_optimized_signals(df)
    bt = backtest(sigs, df)

    # 재현율 (간이)
    matched = sum(1 for s in sigs['timestamp'] if any(abs((s-p).total_seconds())<86400 for p in perfect['timestamp']))
    repro = matched / len(perfect) if len(perfect) > 0 else 0

    results[year] = {
        'return': bt['total_return'], 'trades': bt['trades'], 'win_rate': bt['win_rate'],
        'signal_repro': repro, 'signals': len(sigs)
    }

    print(f"| 수익률: {bt['total_return']:>7.2%}, 거래: {bt['trades']}회, 재현율: {repro:>6.2%}")

print(f"\n{'='*60}")
print("v-a-01 vs v-a-02 비교:")
print("="*60)

# v-a-01 결과 로드
va01 = json.load(open(Path(__file__).parent.parent / 'v-a-01/results/all_years_summary.json'))

for year in [2020, 2021, 2022, 2023, 2024]:
    if year in results and year in va01:
        v1_ret, v2_ret = va01[str(year)]['return'], results[year]['return']
        v1_repr, v2_repr = va01[str(year)]['reproduction_rate'], results[year]['signal_repro']
        improvement = ((v2_ret - v1_ret) / abs(v1_ret) * 100) if v1_ret != 0 else 0
        print(f"{year}: v1 {v1_ret:>7.2%} (재현 {v1_repr:>5.2%}) → v2 {v2_ret:>7.2%} (재현 {v2_repr:>5.2%}) | {improvement:+.0f}%")

# 저장
out = Path(__file__).parent / 'results/all_years_summary.json'
out.parent.mkdir(exist_ok=True)
with open(out, 'w') as f:
    json.dump(results, f, indent=2, default=float)
print(f"\n✅ {out}")
