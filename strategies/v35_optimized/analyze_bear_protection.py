#!/usr/bin/env python3
"""
BEAR 보호 로직 효과 분석
- BEAR_PROTECTION 시그널 발동 횟수
- 포지션 보유율
- BEAR 기간 중 포지션 노출 분석
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V35OptimizedStrategy
from strategies.v34_supreme.market_classifier_v34 import MarketClassifierV34
import pandas as pd
import json


def analyze_bear_protection():
    """BEAR 보호 효과 상세 분석"""

    print("=" * 80)
    print("  BEAR 보호 로직 효과 분석")
    print("=" * 80)

    # Config 로드
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 데이터 로드 (2023-2025)
    years = [2023, 2024, 2025]

    for year in years:
        print(f"\n{'=' * 80}")
        print(f"  {year}년 분석")
        print(f"{'=' * 80}")

        with DataLoader('../../upbit_bitcoin.db') as loader:
            if year == 2025:
                df = loader.load_timeframe('day', start_date=f'{year}-01-01')
            else:
                df = loader.load_timeframe('day', start_date=f'{year}-01-01', end_date=f'{year}-12-31')

        # 지표 추가
        df = MarketAnalyzer.add_indicators(df, indicators=[
            'rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch'
        ])

        # 시장 분류
        classifier = MarketClassifierV34()
        market_states = []
        for i in range(len(df)):
            prev_row = df.iloc[i-1] if i > 0 else None
            current_row = df.iloc[i]
            state = classifier.classify_market_state(current_row, prev_row)
            market_states.append(state)

        df['market_state'] = market_states

        # 전략 실행
        strategy = V35OptimizedStrategy(config)

        signals = []
        position_days = []
        bear_protection_count = 0

        for i in range(30, len(df)):
            signal = strategy.execute(df, i)

            signals.append({
                'date': df.iloc[i].name,
                'action': signal['action'],
                'reason': signal.get('reason', 'UNKNOWN'),
                'market_state': df.iloc[i]['market_state'],
                'in_position': strategy.in_position
            })

            # BEAR_PROTECTION 카운트
            if 'BEAR_PROTECTION' in signal.get('reason', ''):
                bear_protection_count += 1

            # 포지션 보유 일수
            if strategy.in_position:
                position_days.append(df.iloc[i].name)

        # 통계 계산
        total_days = len(df) - 30
        days_in_position = len(position_days)
        position_ratio = days_in_position / total_days * 100

        # BEAR 기간 분석
        bear_days = df[df['market_state'].isin(['BEAR_MODERATE', 'BEAR_STRONG'])].index
        bear_count = len(bear_days)
        bear_ratio = bear_count / len(df) * 100

        # BEAR 중 포지션 보유
        bear_position_overlap = len([d for d in position_days if d in bear_days])

        # 거래 분석
        buy_signals = [s for s in signals if s['action'] == 'buy']
        sell_signals = [s for s in signals if s['action'] == 'sell']
        bear_sells = [s for s in sell_signals if 'BEAR_PROTECTION' in s['reason']]

        print(f"\n📊 포지션 통계")
        print(f"   총 일수: {total_days}일")
        print(f"   포지션 보유: {days_in_position}일 ({position_ratio:.1f}%)")
        print(f"   현금 보유: {total_days - days_in_position}일 ({100 - position_ratio:.1f}%)")

        print(f"\n📉 BEAR 시장 통계")
        print(f"   BEAR 기간: {bear_count}일 ({bear_ratio:.1f}%)")
        print(f"   BEAR 중 포지션 보유: {bear_position_overlap}일")
        print(f"   BEAR 노출율: {bear_position_overlap / bear_count * 100 if bear_count > 0 else 0:.1f}%")

        print(f"\n🛡️ BEAR 보호 효과")
        print(f"   BEAR_PROTECTION 발동: {bear_protection_count}회")
        print(f"   전체 매도: {len(sell_signals)}회")
        print(f"   BEAR 보호 비율: {bear_protection_count / len(sell_signals) * 100 if sell_signals else 0:.1f}%")

        print(f"\n📈 거래 통계")
        print(f"   매수: {len(buy_signals)}회")
        print(f"   매도: {len(sell_signals)}회")
        print(f"   - BEAR 보호: {len(bear_sells)}회")
        print(f"   - 일반 청산: {len(sell_signals) - len(bear_sells)}회")

        # 상세 BEAR 보호 케이스
        if bear_sells:
            print(f"\n🔍 BEAR 보호 발동 케이스:")
            for i, sig in enumerate(bear_sells, 1):
                date_str = sig['date'].strftime('%Y-%m-%d') if hasattr(sig['date'], 'strftime') else str(sig['date'])[:10]
                print(f"   {i}. {date_str} | {sig['market_state']} | {sig['reason']}")

    print(f"\n{'=' * 80}")
    print(f"✅ 분석 완료!")


if __name__ == '__main__':
    analyze_bear_protection()
