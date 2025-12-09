#!/usr/bin/env python3
"""
하락장 손실 분석
- BEAR 시장 상태에서 발생한 손실 패턴 분석
- 현금 전환 vs 포지션 유지 비교
- 숏 포지션 시뮬레이션 (가상 수익 계산)
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime
import json

sys.path.append('..')
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategies.v34_supreme.market_classifier_v34 import MarketClassifierV34


def analyze_bear_market_losses():
    """BEAR 시장 상태에서 손실 패턴 분석"""

    print("=" * 80)
    print("  하락장 손실 분석 (2020-2024)")
    print("=" * 80)

    # 데이터 로드 (Day 타임프레임)
    with DataLoader('../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2020-01-01', end_date='2024-12-31')

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx', 'atr'])

    # 시장 분류
    classifier = MarketClassifierV34()
    market_states = []

    for i in range(len(df)):
        prev_row = df.iloc[i-1] if i > 0 else None
        current_row = df.iloc[i]
        state = classifier.classify_market_state(current_row, prev_row)
        market_states.append(state)

    df['market_state'] = market_states

    # BEAR 시장 기간 추출
    bear_moderate = df[df['market_state'] == 'BEAR_MODERATE']
    bear_strong = df[df['market_state'] == 'BEAR_STRONG']
    all_bear = df[df['market_state'].isin(['BEAR_MODERATE', 'BEAR_STRONG'])]

    print(f"\n📊 시장 상태 분포 (총 {len(df)}일)")
    print(f"   BEAR_STRONG:   {len(bear_strong):4d}일 ({len(bear_strong)/len(df)*100:5.1f}%)")
    print(f"   BEAR_MODERATE: {len(bear_moderate):4d}일 ({len(bear_moderate)/len(df)*100:5.1f}%)")
    print(f"   전체 BEAR:     {len(all_bear):4d}일 ({len(all_bear)/len(df)*100:5.1f}%)")

    # BEAR 기간별 수익률 계산
    print("\n📉 BEAR 시장 기간별 수익률")
    print("-" * 80)

    bear_periods = []
    in_bear = False
    start_idx = None

    for i in range(len(df)):
        is_bear = df.iloc[i]['market_state'] in ['BEAR_MODERATE', 'BEAR_STRONG']

        if is_bear and not in_bear:
            # BEAR 시작
            in_bear = True
            start_idx = i
        elif not is_bear and in_bear:
            # BEAR 종료
            in_bear = False
            end_idx = i - 1

            start_price = df.iloc[start_idx]['close']
            end_price = df.iloc[end_idx]['close']
            duration = end_idx - start_idx + 1

            bear_periods.append({
                'start_date': df.iloc[start_idx].name,
                'end_date': df.iloc[end_idx].name,
                'duration_days': duration,
                'start_price': start_price,
                'end_price': end_price,
                'return_pct': (end_price / start_price - 1) * 100,
                'start_state': df.iloc[start_idx]['market_state']
            })

    # 마지막 BEAR 기간 처리
    if in_bear:
        end_idx = len(df) - 1
        start_price = df.iloc[start_idx]['close']
        end_price = df.iloc[end_idx]['close']
        duration = end_idx - start_idx + 1

        bear_periods.append({
            'start_date': df.iloc[start_idx].name,
            'end_date': df.iloc[end_idx].name,
            'duration_days': duration,
            'start_price': start_price,
            'end_price': end_price,
            'return_pct': (end_price / start_price - 1) * 100,
            'start_state': df.iloc[start_idx]['market_state']
        })

    # BEAR 기간 통계
    total_bear_days = sum(p['duration_days'] for p in bear_periods)
    avg_duration = np.mean([p['duration_days'] for p in bear_periods])
    avg_return = np.mean([p['return_pct'] for p in bear_periods])
    worst_return = min([p['return_pct'] for p in bear_periods])

    print(f"총 BEAR 기간: {len(bear_periods)}회")
    print(f"평균 지속 일수: {avg_duration:.1f}일")
    print(f"평균 수익률: {avg_return:+.2f}%")
    print(f"최악 수익률: {worst_return:+.2f}%")

    print("\n상위 10개 BEAR 기간:")
    for i, period in enumerate(sorted(bear_periods, key=lambda x: x['return_pct'])[:10], 1):
        start_str = period['start_date'].strftime('%Y-%m-%d') if hasattr(period['start_date'], 'strftime') else str(period['start_date'])[:10]
        end_str = period['end_date'].strftime('%Y-%m-%d') if hasattr(period['end_date'], 'strftime') else str(period['end_date'])[:10]
        print(f"{i:2d}. {start_str} ~ {end_str} "
              f"({period['duration_days']:3d}일): {period['return_pct']:+7.2f}%")

    return df, bear_periods


def compare_cash_vs_hold(df, bear_periods):
    """현금 전환 vs 포지션 유지 비교"""

    print("\n" + "=" * 80)
    print("  전략 비교: 현금 전환 vs 포지션 유지")
    print("=" * 80)

    initial_capital = 10_000_000

    # 전략 1: 포지션 유지 (Buy & Hold)
    buy_hold_return = (df.iloc[-1]['close'] / df.iloc[0]['close'] - 1) * 100
    buy_hold_final = initial_capital * (1 + buy_hold_return / 100)

    # 전략 2: BEAR 시 현금 전환
    capital_cash = initial_capital
    position = 0
    in_position = True
    entry_price = df.iloc[0]['close']
    position = capital_cash / entry_price
    capital_cash = 0

    cash_conversion_trades = []

    for i in range(len(df)):
        current_price = df.iloc[i]['close']
        is_bear = df.iloc[i]['market_state'] in ['BEAR_MODERATE', 'BEAR_STRONG']

        if in_position and is_bear:
            # BEAR 감지 → 현금 전환
            capital_cash = position * current_price * (1 - 0.0005)  # 수수료 0.05%
            position = 0
            in_position = False

            cash_conversion_trades.append({
                'date': df.iloc[i].name,
                'action': 'SELL',
                'price': current_price,
                'reason': 'BEAR_DETECTED',
                'capital': capital_cash
            })

        elif not in_position and not is_bear:
            # BEAR 해제 → 재진입
            position = capital_cash / current_price * (1 - 0.0005)
            capital_cash = 0
            in_position = True

            cash_conversion_trades.append({
                'date': df.iloc[i].name,
                'action': 'BUY',
                'price': current_price,
                'reason': 'BEAR_CLEARED',
                'capital': position * current_price
            })

    # 최종 평가
    if in_position:
        cash_final = position * df.iloc[-1]['close']
    else:
        cash_final = capital_cash

    cash_return = (cash_final / initial_capital - 1) * 100

    print(f"\n전략 1: Buy & Hold (포지션 유지)")
    print(f"   최종 자산: {buy_hold_final:,.0f}원")
    print(f"   수익률: {buy_hold_return:+.2f}%")

    print(f"\n전략 2: BEAR 시 현금 전환")
    print(f"   거래 횟수: {len(cash_conversion_trades)}회")
    print(f"   최종 자산: {cash_final:,.0f}원")
    print(f"   수익률: {cash_return:+.2f}%")
    print(f"   개선: {cash_return - buy_hold_return:+.2f}%p")

    return cash_conversion_trades, cash_return, buy_hold_return


def simulate_short_positions(df, bear_periods):
    """숏 포지션 시뮬레이션"""

    print("\n" + "=" * 80)
    print("  숏 포지션 시뮬레이션 (바이낸스 선물 가정)")
    print("=" * 80)

    initial_capital = 10_000_000
    fee_rate = 0.0004  # 바이낸스 선물 수수료 (0.04%)

    # 전략 3: 업비트 롱 + 바이낸스 숏 헷지
    capital = initial_capital
    upbit_position = 0  # BTC 수량
    binance_position = 0  # 숏 포지션 (양수 = 숏)

    in_upbit = True
    upbit_entry = df.iloc[0]['close']
    upbit_position = capital / upbit_entry

    trades = []

    for i in range(len(df)):
        current_price = df.iloc[i]['close']
        is_bear = df.iloc[i]['market_state'] in ['BEAR_MODERATE', 'BEAR_STRONG']

        if is_bear and binance_position == 0:
            # BEAR 감지 → 바이낸스 숏 오픈
            short_size = upbit_position * current_price * 0.5  # 50% 헷지
            binance_position = short_size / current_price
            short_entry = current_price

            trades.append({
                'date': df.iloc[i].name,
                'action': 'SHORT_OPEN',
                'exchange': 'Binance',
                'price': current_price,
                'size': short_size,
                'reason': 'BEAR_HEDGE'
            })

        elif not is_bear and binance_position > 0:
            # BEAR 해제 → 바이낸스 숏 청산
            short_pnl = (short_entry - current_price) / short_entry * binance_position * short_entry
            short_pnl -= binance_position * current_price * fee_rate * 2  # 진입+청산 수수료

            capital += short_pnl

            trades.append({
                'date': df.iloc[i].name,
                'action': 'SHORT_CLOSE',
                'exchange': 'Binance',
                'price': current_price,
                'pnl': short_pnl,
                'reason': 'BEAR_CLEARED'
            })

            binance_position = 0

    # 최종 평가
    upbit_value = upbit_position * df.iloc[-1]['close']

    if binance_position > 0:
        # 미청산 숏 포지션
        short_pnl = (short_entry - df.iloc[-1]['close']) / short_entry * binance_position * short_entry
        short_pnl -= binance_position * df.iloc[-1]['close'] * fee_rate * 2
        capital += short_pnl

    total_value = upbit_value + capital - initial_capital
    final_return = (total_value / initial_capital - 1) * 100

    # 숏 포지션 통계
    short_trades = [t for t in trades if t['action'] == 'SHORT_CLOSE']
    total_short_pnl = sum(t['pnl'] for t in short_trades)
    avg_short_pnl = np.mean([t['pnl'] for t in short_trades]) if short_trades else 0

    print(f"\n전략 3: 업비트 롱 + 바이낸스 숏 헷지 (50%)")
    print(f"   업비트 가치: {upbit_value:,.0f}원")
    print(f"   바이낸스 숏 수익: {total_short_pnl:+,.0f}원")
    print(f"   최종 자산: {total_value:,.0f}원")
    print(f"   수익률: {final_return:+.2f}%")

    print(f"\n숏 거래 통계:")
    print(f"   거래 횟수: {len(short_trades)}회")
    print(f"   평균 수익: {avg_short_pnl:+,.0f}원")
    print(f"   총 수익: {total_short_pnl:+,.0f}원")

    return trades, final_return, total_short_pnl


def main():
    """메인 함수"""

    # 1. BEAR 시장 손실 패턴 분석
    df, bear_periods = analyze_bear_market_losses()

    # 2. 현금 전환 vs 포지션 유지 비교
    cash_trades, cash_return, hold_return = compare_cash_vs_hold(df, bear_periods)

    # 3. 숏 포지션 시뮬레이션
    short_trades, hedge_return, short_pnl = simulate_short_positions(df, bear_periods)

    # 결과 요약
    print("\n" + "=" * 80)
    print("  최종 결과 요약")
    print("=" * 80)

    strategies = [
        ('Buy & Hold', hold_return),
        ('BEAR 시 현금 전환', cash_return),
        ('업비트 롱 + 바이낸스 숏 헷지', hedge_return)
    ]

    print(f"\n전략별 수익률 비교 (2020-2024, 초기 자본 1,000만원):")
    for name, ret in sorted(strategies, key=lambda x: x[1], reverse=True):
        print(f"   {name:30s}: {ret:+8.2f}%")

    print(f"\n✅ 분석 완료!")
    print(f"   BEAR 기간: {len(bear_periods)}회 발생")
    print(f"   숏 헷지 추가 수익: {short_pnl:+,.0f}원")

    # 결과 저장
    report = {
        'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'period': '2020-2024',
        'bear_periods': bear_periods,
        'strategies': {
            'buy_hold': {
                'return_pct': hold_return,
                'description': '포지션 유지'
            },
            'cash_conversion': {
                'return_pct': cash_return,
                'trades': len(cash_trades),
                'description': 'BEAR 시 현금 전환'
            },
            'hedge_short': {
                'return_pct': hedge_return,
                'short_pnl': short_pnl,
                'trades': len(short_trades),
                'description': '업비트 롱 + 바이낸스 숏 헷지'
            }
        },
        'recommendation': '바이낸스 선물 연동으로 하락장 대응 권장'
    }

    with open('bear_market_analysis_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n보고서 저장: bear_market_analysis_report.json")


if __name__ == '__main__':
    main()
