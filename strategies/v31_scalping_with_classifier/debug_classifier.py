#!/usr/bin/env python3
"""시장 분류기 디버그"""

import json
from market_classifier import MarketClassifier
import pandas as pd

with open('config.json') as f:
    config = json.load(f)

DB_PATH = '../../upbit_bitcoin.db'

# Initialize classifier
classifier = MarketClassifier(DB_PATH, config)
classifier.load_day_data("2023-01-01", "2024-12-31")

# Check 2024 classifications
dates_2024 = pd.date_range('2024-01-01', '2024-12-31', freq='D')

bull_days = []
bear_days = []
sideways_days = []

for date in dates_2024:
    state = classifier.classify_market_at_date(date)
    if state == 'BULL':
        bull_days.append(date)
    elif state == 'BEAR':
        bear_days.append(date)
    else:
        sideways_days.append(date)

print(f"2024년 시장 분류 결과:")
print(f"BULL: {len(bull_days)} 일 ({len(bull_days)/365*100:.1f}%)")
print(f"BEAR: {len(bear_days)} 일 ({len(bear_days)/365*100:.1f}%)")
print(f"SIDEWAYS: {len(sideways_days)} 일 ({len(sideways_days)/365*100:.1f}%)")

print(f"\nBULL 기간 샘플 (처음 10개):")
for d in bull_days[:10]:
    indicators = classifier.get_day_indicators(d)
    print(f"{d.date()}: MFI={indicators['mfi']:.1f}, MACD={indicators['macd']:,.0f}, Signal={indicators['macd_signal']:,.0f}, Close={indicators['close']:,.0f}")

print(f"\nBEAR 기간 샘플 (처음 10개):")
for d in bear_days[:10]:
    indicators = classifier.get_day_indicators(d)
    print(f"{d.date()}: MFI={indicators['mfi']:.1f}, MACD={indicators['macd']:,.0f}, Signal={indicators['macd_signal']:,.0f}, Close={indicators['close']:,.0f}")

# Check specific dates
print(f"\n2024년 주요 날짜:")
key_dates = ['2024-01-01', '2024-03-01', '2024-06-01', '2024-09-01', '2024-12-01']
for d in key_dates:
    state = classifier.classify_market_at_date(d)
    indicators = classifier.get_day_indicators(d)
    print(f"{d}: {state:8} | MFI={indicators['mfi']:5.1f}, MACD>{indicators['macd_signal']}: {indicators['macd'] > indicators['macd_signal']}, Close={indicators['close']:,.0f}")
