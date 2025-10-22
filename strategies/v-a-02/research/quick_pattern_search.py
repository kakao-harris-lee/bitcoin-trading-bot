#!/usr/bin/env python3
"""v-a-02: 빠른 패턴 탐색 (2020-2024)"""
import sys, json, itertools
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))
import pandas as pd
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# 패턴 후보
PATTERNS = {
    'rsi': [(30,50), (40,60), (50,65), (55,70)],
    'mfi': [(30,50), (40,60), (50,65), (55,70)],
    'vol': [(0.8,1.2), (0.9,1.3), (1.0,1.5)]
}

def test_pattern(df, perfect, rsi, mfi, vol):
    """패턴 테스트"""
    sigs = df[(df['rsi'].between(*rsi)) & (df['mfi'].between(*mfi)) &
              (df['volume_ratio'].between(*vol))]['timestamp'].tolist()
    if not sigs: return {'params': (rsi,mfi,vol), 'rate': 0, 'count': 0}

    matched = sum(1 for s in sigs if any(abs((s-p).total_seconds())<86400 for p in perfect['timestamp']))
    return {'params': (rsi,mfi,vol), 'rate': matched/len(perfect), 'count': len(sigs), 'matched': matched}

def search_timeframe(tf, years):
    """타임프레임별 탐색"""
    print(f"\n[{tf}]")

    # 완벽한 시그널
    perfect_dir = Path(__file__).parent.parent.parent / 'v41_scalping_voting/analysis/perfect_signals'
    perfects = []
    for y in years:
        try:
            perfects.append(pd.read_csv(perfect_dir / f'{tf}_{y}_perfect.csv', parse_dates=['timestamp']))
        except: pass
    if not perfects: return None
    perfect = pd.concat(perfects)
    print(f"  Perfect: {len(perfect)}개")

    # 시장 데이터
    db = DataLoader(str(Path(__file__).parent.parent.parent.parent / 'upbit_bitcoin.db'))
    dfs = []
    for y in years:
        d = db.load_timeframe(tf, f'{y}-01-01', f'{y}-12-31')
        d = MarketAnalyzer.add_indicators(d, ['rsi','mfi'])
        d['volume_ratio'] = d['volume']/d['volume'].rolling(20).mean()
        dfs.append(d.dropna())
    df = pd.concat(dfs)

    # 조합 테스트
    results = []
    for r, m, v in itertools.product(*PATTERNS.values()):
        results.append(test_pattern(df, perfect, r, m, v))

    results.sort(key=lambda x: x['rate'], reverse=True)
    top = results[0]
    print(f"  Best: {top['rate']:.2%} - RSI{top['params'][0]}, MFI{top['params'][1]}, Vol{top['params'][2]}")
    return {'timeframe': tf, 'total_perfect': len(perfect), 'best': top, 'top5': results[:5]}

# 실행
print("v-a-02 Quick Pattern Search")
configs = {'day':[2020,2021,2022,2023,2024], 'minute60':[2020,2021,2022,2023,2024],
           'minute240':[2020,2021,2022,2023,2024], 'minute15':[2023,2024], 'minute5':[2024]}

all_results = {}
for tf, years in configs.items():
    res = search_timeframe(tf, years)
    if res: all_results[tf] = res

# 저장
out = Path(__file__).parent/'results'/f'quick_search_{pd.Timestamp.now().strftime("%y%m%d-%H%M")}.json'
out.parent.mkdir(exist_ok=True)
with open(out, 'w') as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\n✅ {out}")
