#!/usr/bin/env python3
"""
2025년 손실 거래 패턴 분석

Phase 1-2: 2025년 성과가 낮은 이유 및 개선 방향 도출
"""

import json
from pathlib import Path
from typing import List, Dict
import pandas as pd

def analyze_2025_losses():
    """2025년 손실 거래 상세 분석"""

    result_file = Path(__file__).parent.parent / 'results' / 'backtest_v37_style.json'

    with open(result_file, 'r') as f:
        data = json.load(f)

    if '2025' not in data['results']:
        print("2025 데이터 없음")
        return

    trades = data['results']['2025']['trades']

    # 손실 거래만 필터
    losing_trades = [t for t in trades if t['profit_pct'] < 0]
    winning_trades = [t for t in trades if t['profit_pct'] > 0]

    print("="*80)
    print("  v-a-11 2025년 손실 거래 패턴 분석")
    print("="*80)

    print(f"\n[기본 통계]")
    print(f"총 거래: {len(trades)}회")
    print(f"승리: {len(winning_trades)}회 ({len(winning_trades)/len(trades)*100:.1f}%)")
    print(f"손실: {len(losing_trades)}회 ({len(losing_trades)/len(trades)*100:.1f}%)")

    print(f"\n승리 거래 평균 수익: {sum(t['profit_pct'] for t in winning_trades)/len(winning_trades):.2f}%")
    print(f"손실 거래 평균 손실: {sum(t['profit_pct'] for t in losing_trades)/len(losing_trades):.2f}%")

    total_profit = sum(t['profit_pct'] for t in winning_trades)
    total_loss = sum(t['profit_pct'] for t in losing_trades)
    print(f"\n총 익절: +{total_profit:.2f}%")
    print(f"총 손절: {total_loss:.2f}%")
    print(f"순 수익: {total_profit + total_loss:.2f}%")

    # 손실 거래 상세 분석
    print("\n" + "="*80)
    print("  손실 거래 상세")
    print("="*80)

    # 전략별
    loss_by_strategy = {}
    for t in losing_trades:
        strategy = t['strategy']
        if strategy not in loss_by_strategy:
            loss_by_strategy[strategy] = []
        loss_by_strategy[strategy].append(t)

    print("\n[전략별 손실]")
    for strategy, trades_list in sorted(loss_by_strategy.items(), key=lambda x: len(x[1]), reverse=True):
        avg_loss = sum(t['profit_pct'] for t in trades_list) / len(trades_list)
        total_loss_pct = sum(t['profit_pct'] for t in trades_list)
        print(f"{strategy}: {len(trades_list)}회, 평균 {avg_loss:.2f}%, 총 {total_loss_pct:.2f}%")

    # 청산 사유별
    loss_by_exit = {}
    for t in losing_trades:
        exit_reason = t['exit_reason']
        if exit_reason not in loss_by_exit:
            loss_by_exit[exit_reason] = []
        loss_by_exit[exit_reason].append(t)

    print("\n[청산 사유별]")
    for reason, trades_list in sorted(loss_by_exit.items(), key=lambda x: len(x[1]), reverse=True):
        avg_loss = sum(t['profit_pct'] for t in trades_list) / len(trades_list)
        print(f"{reason}: {len(trades_list)}회, 평균 {avg_loss:.2f}%")

    # 월별
    loss_by_month = {}
    for t in losing_trades:
        month = t['entry_time'][:7]
        if month not in loss_by_month:
            loss_by_month[month] = []
        loss_by_month[month].append(t)

    print("\n[월별 손실]")
    for month in sorted(loss_by_month.keys()):
        trades_list = loss_by_month[month]
        total_loss_pct = sum(t['profit_pct'] for t in trades_list)
        print(f"{month}: {len(trades_list)}회, 총 {total_loss_pct:.2f}%")

    # 최대 손실 거래 Top 5
    print("\n[최대 손실 거래 Top 5]")
    sorted_losses = sorted(losing_trades, key=lambda x: x['profit_pct'])
    for i, trade in enumerate(sorted_losses[:5], 1):
        print(f"\n{i}. {trade['entry_time']} → {trade['exit_time']}")
        print(f"   전략: {trade['strategy']}")
        print(f"   손실: {trade['profit_pct']:.2f}%")
        print(f"   청산: {trade['exit_reason']}")
        print(f"   보유: {trade['hold_days']}일")

    # 개선 방향 제안
    print("\n" + "="*80)
    print("  개선 방향 제안")
    print("="*80)

    # 1. Stop Loss 분석
    stop_loss_count = sum(1 for t in losing_trades if 'STOP_LOSS' in t['exit_reason'])
    stop_loss_pct = stop_loss_count / len(losing_trades) * 100 if losing_trades else 0

    print(f"\n1. Stop Loss 개선")
    print(f"   - 현재 SL 발생: {stop_loss_count}회 ({stop_loss_pct:.1f}%)")
    if stop_loss_pct > 30:
        print(f"   ⚠️ SL 과다 발생! 완화 필요")
        print(f"   → SIDEWAYS SL: -1.08% → -2.0% 완화")
        print(f"   → ATR 기반 Dynamic SL 도입 (ATR × 3.0)")

    # 2. 전략별 개선
    if 'sideways' in loss_by_strategy:
        sideways_losses = loss_by_strategy['sideways']
        print(f"\n2. SIDEWAYS 전략 개선")
        print(f"   - 손실 거래: {len(sideways_losses)}회")
        print(f"   → RSI < 30 조건 강화 (현재 < 24)")
        print(f"   → Volume > 2.0x 조건 강화 (현재 > 1.68x)")
        print(f"   → Grid Trading 추가 (Support/Resistance)")

    # 3. 월별 패턴
    worst_months = sorted(loss_by_month.items(), key=lambda x: sum(t['profit_pct'] for t in x[1]))[:2]
    if worst_months:
        print(f"\n3. 취약 월 대응")
        for month, trades_list in worst_months:
            total_loss = sum(t['profit_pct'] for t in trades_list)
            print(f"   - {month}: {total_loss:.2f}% 손실")
        print(f"   → 시장 상태 변화 감지 강화")
        print(f"   → Defensive 포지션 축소 (현재 20% → 10%)")

    # 4. 승률 개선
    current_win_rate = len(winning_trades) / len(trades) * 100
    print(f"\n4. 승률 개선")
    print(f"   - 현재 승률: {current_win_rate:.1f}%")
    print(f"   - 목표 승률: 55%+")
    print(f"   → Entry 조건 강화 (ADX, Volume, RSI)")
    print(f"   → Kelly Criterion 포지션 사이징")
    print(f"   → 저신뢰도 시그널 제외")

    print("\n" + "="*80)


if __name__ == '__main__':
    analyze_2025_losses()
